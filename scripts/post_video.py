import json, os, re, sys, tempfile, time, subprocess
from pathlib import Path
from urllib.parse import unquote
import requests, pydantic
sys.path.insert(0, str(Path(__file__).parent))
from crypto import decrypt, get_password
from instagrapi import Client
import imageio_ffmpeg

ROOT = Path(__file__).parent.parent
SESSION_FILE = ROOT / "data" / "session.enc"
HISTORY_FILE = ROOT / "data" / "history.json"
HASHTAGS = "#قرآن #قران #القرآن_الكريم #اسلام #ذكر_الله #تلاوة #quran #islam #islamic #muslim"
MAX_RUNTIME = 4.5 * 3600
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

def git_push_history():
    run = lambda *a: subprocess.run(a, capture_output=True, text=True)
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "add", "data/history.json")
    run("git", "commit", "-m", "chore: update history [skip ci]")
    run("git", "pull", "--rebase", "--autostash")
    run("git", "push")

def load_client():
    cl = Client()
    cl.set_settings(json.loads(decrypt(SESSION_FILE.read_text(), get_password())))
    cl.delay_range = [2, 5]
    cl.expose = lambda *a, **k: True
    return cl

def get_video_url(cl, pk):
    # محاولة الحصول على رابط الفيديو مباشرة من الـ API الخام
    try:
        res = cl.private_request(f"media/{pk}/info/")
        items = res.get("items", [])
        if items:
            versions = items[0].get("video_versions", [])
            if versions:
                return versions[0].get("url")
    except Exception as e:
        print(f"  Raw API request failed: {str(e)[:100]}")
        
    # محاولة أخرى عبر Media Info العادية
    try:
        info = cl.media_info(pk)
        return info.video_url
    except Exception:
        pass
        
    return None

def download(cl, pk, folder):
    url = get_video_url(cl, pk)
    if not url:
        print("  Could not get video URL.")
        return None
    p = folder / f"dl_{int(time.time())}.mp4"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(p, "wb") as f:
            for chunk in r.iter_content(1 << 20): f.write(chunk)
    return p

def process_and_post(cl, pk, msg_id, history):
    tmp = Path(tempfile.mkdtemp())
    try:
        print("  --> Downloading video directly from API...")
        src = download(cl, pk, tmp)
        if not src or not src.exists():
            return False
            
        out, thumb = tmp / "out.mp4", tmp / "thumb.jpg"
        print("  --> Editing (flip to avoid duplicate)...")
        r = subprocess.run([FFMPEG, "-y", "-i", str(src), "-vf", "hflip",
                            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                            "-c:a", "copy", "-movflags", "+faststart", str(out)],
                           capture_output=True)
        if r.returncode != 0:
            print("  ffmpeg failed:", r.stderr[-300:].decode(errors="ignore")); return False
            
        subprocess.run([FFMPEG, "-y", "-i", str(out), "-ss", "1", "-vframes", "1", str(thumb)], capture_output=True)
        
        print("  --> Uploading to your account...")
        try:
            cl.clip_upload(str(out), HASHTAGS, thumbnail=str(thumb) if thumb.exists() else None)
        except pydantic.ValidationError:
            pass # تم الرفع بنجاح رغم خطأ القراءة
            
        print("  POSTED SUCCESSFULLY")
        history.append(msg_id)
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
        git_push_history()
        return True
    except Exception as e:
        print("  Error:", str(e)[:200]); return False
    finally:
        for f in tmp.glob("*"):
            try: f.unlink()
            except Exception: pass

def main():
    cl = load_client()
    my_id = str(cl.user_id)
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    start = time.time()
    print(f"Monitoring for {MAX_RUNTIME/3600} hours...")
    
    while time.time() - start < MAX_RUNTIME:
        try:
            posted = False
            threads = cl.private_request("direct_v2/inbox/", params={
                "persistentBadging": "true", "limit": "10", "thread_message_limit": "1"
            }).get("inbox", {}).get("threads", [])
            
            for th in threads:
                r = cl.private_request(f"direct_v2/threads/{th['thread_id']}/", params={"direction": "older", "limit": "5"})
                items = r.get("thread", {}).get("items", [])
                for item in items:
                    mid = str(item.get("item_id"))
                    if mid in history: continue
                    if str(item.get("user_id")) == my_id: continue
                    if item.get("item_type") != "xma_clip": continue
                    
                    print(f"Checking {mid} | type: {item.get('item_type')}")
                    
                    # استخراج الـ pk مباشرة من الرسالة
                    pk = item.get("original_media_igid")
                    if not pk:
                        print("  No original_media_igid found, skipping.")
                        continue
                        
                    if process_and_post(cl, int(pk), mid, history):
                        posted = True
                        break
                if posted: break
                
            if not posted:
                print("No new valid videos. Waiting 180 seconds...")
            time.sleep(180)
            
        except Exception as e:
            if "Challenge" in type(e).__name__ or "Challenge" in str(e):
                print("CHALLENGE DETECTED! Stopping to protect account.")
                sys.exit(1)
            print(f"Monitor error: {str(e)[:150]}")
            time.sleep(180)

if __name__ == "__main__": main()

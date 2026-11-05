import json, os, sys, tempfile, time, subprocess, re
from pathlib import Path
import requests, pydantic
sys.path.insert(0, str(Path(__file__).parent))
from crypto import decrypt, get_password
from instagrapi import Client
import imageio_ffmpeg

SESSION_FILE = Path(__file__).parent.parent / "data" / "session.enc"
HISTORY_FILE = Path(__file__).parent.parent / "data" / "history.json"
HASHTAGS = "#قرآن #قران #القرآن_الكريم #اسلام #ذكر_الله #تلاوة #quran #islam #islamic #muslim"

def git_push_history():
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"])
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    subprocess.run(["git", "add", "data/history.json"])
    subprocess.run(["git", "commit", "-m", "chore: update history [skip ci]"])
    subprocess.run(["git", "push"])

def load_client():
    session = json.loads(decrypt(SESSION_FILE.read_text(), get_password()))
    cl = Client()
    cl.set_settings(session)
    cl.delay_range = [2, 5]
    cl.expose = lambda *args, **kwargs: True
    return cl

def process_video(cl, media_pk, msg_id, history):
    print(f"Processing media PK: {media_pk}")
    ti, to, thumb = Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".jpg"))
    try:
        media = cl.media_info(media_pk)
        if not media.video_url:
            print("Not a video, skipping.")
            return False
            
        print("Downloading high quality video...")
        with requests.get(media.video_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with ti.open("wb") as f:
                for chunk in r.iter_content(65536): f.write(chunk)
                
        print("Editing (flip to avoid duplicate)...")
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        r1 = subprocess.run([ffmpeg_exe, "-y", "-i", str(ti), "-vf", "hflip", "-c:v", "libx264", "-crf", "18", "-c:a", "copy", str(to)], capture_output=True)
        if r1.returncode != 0:
            print("ffmpeg edit failed")
            return False
            
        r2 = subprocess.run([ffmpeg_exe, "-y", "-i", str(to), "-ss", "00:00:01.000", "-vframes", "1", str(thumb)], capture_output=True)
        
        print("Uploading to your account...")
        caption = media.caption_text or ""
        try:
            cl.clip_upload(str(to), caption + "\n\n" + HASHTAGS, thumbnail=str(thumb))
        except pydantic.ValidationError:
            pass
            
        print("POSTED SUCCESSFULLY")
        history.append(msg_id)
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
        git_push_history()
        return True
    except Exception as e:
        print(f"Error processing video: {e}")
        return False
    finally:
        for f in (ti, to, thumb):
            if f.exists(): f.unlink()

def extract_pk(msg):
    # 1. البحث في xma_share
    if getattr(msg, 'xma_share', None):
        if getattr(msg.xma_share, 'video', None) and getattr(msg.xma_share.video, 'pk', None):
            return msg.xma_share.video.pk
        if getattr(msg.xma_share, 'media', None) and getattr(msg.xma_share.media, 'pk', None):
            return msg.xma_share.media.pk

    # 2. البحث في clip أو media
    if getattr(msg, 'clip', None) and getattr(msg.clip, 'pk', None):
        return msg.clip.pk
    if getattr(msg, 'media', None) and getattr(msg.media, 'pk', None):
        return msg.media.pk
        
    # 3. خطة الطوارئ: قراءة الـ JSON الخام واستخراج الـ pk
    try:
        raw_json = msg.model_dump_json()
        # البحث عن أي pk يبدأ بـ 20 رقم أو أكثر (عادة أرقام الفيديوهات طويلة)
        match = re.search(r'"pk":\s*"?(\d{15,})"?', raw_json)
        if match:
            return int(match.group(1))
    except:
        pass
        
    return None

def main():
    cl = load_client()
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    start_time = time.time()
    MAX_RUNTIME = 4.5 * 3600 
    
    print(f"Starting DM monitor for {MAX_RUNTIME/3600} hours...")
    
    while time.time() - start_time < MAX_RUNTIME:
        try:
            threads = cl.direct_threads(amount=5)
            found = False
            for thread in threads:
                messages = cl.direct_messages(thread.id, amount=5)
                for msg in messages:
                    if msg.id in history: continue
                    
                    text = getattr(msg, "text", "") or ""
                    print(f"Checking msg {msg.id} | type: {msg.item_type}")
                    
                    pk = extract_pk(msg)
                    
                    # إذا لم نجد PK، نجرب الروابط النصية
                    if not pk and text:
                        match = re.search(r'https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/([a-zA-Z0-9_-]+)', text)
                        if match:
                            try:
                                pk = cl.media_pk_from_code(match.group(1))
                            except:
                                pass

                    if pk:
                        print(f"Extracted PK: {pk}")
                        if process_video(cl, pk, msg.id, history):
                            found = True
                            break
                if found: break
            
            if not found:
                print("No new valid videos. Waiting 30 seconds...")
                time.sleep(30)
                
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(30)

    print("Time limit reached. Exiting gracefully.")

if __name__ == "__main__": main()

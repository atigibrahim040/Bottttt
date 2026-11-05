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

def process_video(cl, target_url, msg_id, history):
    print(f"Found new link: {target_url}")
    ti = Path(tempfile.mktemp(suffix=".mp4"))
    to = Path(tempfile.mktemp(suffix=".mp4"))
    thumb = Path(tempfile.mktemp(suffix=".jpg"))
    
    try:
        print("Downloading high quality video...")
        media_pk = cl.media_pk_from_url(target_url)
        media = cl.media_info(media_pk)
        if not media.video_url:
            print("Not a video link.")
            return False
            
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
        
        print("Uploading...")
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

def main():
    cl = load_client()
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    start_time = time.time()
    MAX_RUNTIME = 4.5 * 3600 
    
    print(f"Starting DM monitor for {MAX_RUNTIME/3600} hours...")
    
    while time.time() - start_time < MAX_RUNTIME:
        try:
            threads = cl.direct_threads(amount=10)
            found = False
            for thread in threads:
                for msg in thread.messages:
                    text = getattr(msg, "text", "") or ""
                    link_obj = getattr(msg, "link", None)
                    if link_obj and hasattr(link_obj, "text"):
                        text += " " + (link_obj.text or "")
                    if text:
                        match = re.search(r'https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[a-zA-Z0-9_-]+', text)
                        if match and msg.id not in history:
                            target_url = match.group(0)
                            if process_video(cl, target_url, msg.id, history):
                                found = True
                                break
                if found: break
            
            if not found:
                print("No new links. Waiting 60 seconds...")
                time.sleep(60)
                
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(60)

    print("Time limit reached. Exiting gracefully for next run.")

if __name__ == "__main__": main()

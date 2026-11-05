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

def load_client():
    session = json.loads(decrypt(SESSION_FILE.read_text(), get_password()))
    cl = Client()
    cl.set_settings(session)
    cl.delay_range = [2, 5]
    cl.expose = lambda *args, **kwargs: True
    return cl

def main():
    cl = load_client()
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    print("Checking DMs for new links...")
    
    threads = cl.direct_threads(amount=10)
    target_url = None
    msg_id = None
    
    for thread in threads:
        # نبحث في الرسائل عن روابط إنستقرام
        for msg in thread.messages:
            if msg.item_type == "text" and msg.text:
                # نبحث عن رابط ريلز أو بوست
                match = re.search(r'https?://(?:www\.)?instagram\.com/(?:reel|p)/[a-zA-Z0-9_-]+', msg.text)
                if match and msg.id not in history:
                    target_url = match.group(0)
                    msg_id = msg.id
                    break
        if target_url: break

    if not target_url:
        sys.exit("No new video links found in DMs.")

    print(f"Found link: {target_url}")
    
    ti, to, thumb = Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".jpg"))
    try:
        print("Downloading video in high quality...")
        media_pk = cl.media_pk_from_url(target_url)
        media = cl.media_info(media_pk)
        
        if not media.video_url:
            sys.exit("The link does not contain a video.")
            
        with requests.get(media.video_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with ti.open("wb") as f:
                for chunk in r.iter_content(65536): f.write(chunk)
                
        print("Editing video (flip to avoid duplicate detection)...")
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        # نعكس الفيديو فقط ونحافظ على الصوت الأصلي
        r1 = subprocess.run([ffmpeg_exe, "-y", "-i", str(ti), "-vf", "hflip", "-c:v", "libx264", "-crf", "18", "-c:a", "copy", str(to)], capture_output=True)
        if r1.returncode != 0: sys.exit("ffmpeg edit failed: " + r1.stderr.decode()[:300])
        
        print("Generating thumbnail...")
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
    finally:
        for f in (ti, to, thumb):
            if f.exists(): f.unlink()

if __name__ == "__main__": main()

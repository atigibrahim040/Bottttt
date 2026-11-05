import json, os, random, sys, tempfile, time, subprocess
import imageio_ffmpeg
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from crypto import decrypt, get_password
from instagrapi import Client

SESSION_FILE = Path(__file__).parent.parent / "data" / "session.enc"
SOURCES_FILE = Path(__file__).parent.parent / "data" / "sources.json"
HISTORY_FILE = Path(__file__).parent.parent / "data" / "history.json"
HASHTAGS = "#قرآن #قران #القرآن_الكريم #اسلام #ذكر_الله #تلاوة #quran #islam #islamic #muslim"

def load_client():
    if not SESSION_FILE.exists(): sys.exit("No session file.")
    session = json.loads(decrypt(SESSION_FILE.read_text(), get_password()))
    cl = Client()
    cl.set_settings(session)
    cl.delay_range = [2, 5]
    return cl

def main():
    cl = load_client()
    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8")) if SOURCES_FILE.exists() else ["quran"]
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    random.shuffle(sources)
    selected = None
    print("Searching for a new Quran clip...")
    for source in sources:
        try:
            uid = cl.user_id_from_username(source)
            time.sleep(3)
            for c in cl.user_clips(uid, amount=5):
                if c.pk not in history and getattr(c, 'video_url', None):
                    selected = c
                    break
            if selected: break
        except Exception as e:
            print(f"Error {source}: {e}")
            time.sleep(5)
    if not selected: sys.exit("No new clips found.")
    print(f"Selected: {selected.pk} from @{selected.user.username}")
    ti, to, thumb = Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".jpg"))
    try:
        print("Downloading...")
        with requests.get(selected.video_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with ti.open("wb") as f:
                for chunk in r.iter_content(65536): f.write(chunk)
        print("Editing with ffmpeg (flip + speed)...")
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        r1 = subprocess.run([ffmpeg_exe,"-y","-i",str(ti),"-vf","hflip,setpts=0.95*PTS","-af","atempo=1.05","-c:v","libx264","-c:a","aac",str(to)], capture_output=True)
        if r1.returncode != 0: sys.exit("ffmpeg edit failed: " + r1.stderr.decode()[:300])
        print("Generating thumbnail with ffmpeg...")
        r2 = subprocess.run([ffmpeg_exe,"-y","-i",str(to),"-ss","00:00:01.000","-vframes","1",str(thumb)], capture_output=True)
        if r2.returncode != 0: sys.exit("ffmpeg thumb failed: " + r2.stderr.decode()[:300])
        print("Uploading (with pre-generated thumbnail)...")
        caption = getattr(selected, 'caption_text', '') or ""
        cl.clip_upload(str(to), caption + "\n\n" + HASHTAGS, thumbnail=str(thumb))
        print("POSTED SUCCESSFULLY")
        history.append(selected.pk)
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
    finally:
        for f in (ti, to, thumb):
            if f.exists(): f.unlink()

if __name__ == "__main__": main()

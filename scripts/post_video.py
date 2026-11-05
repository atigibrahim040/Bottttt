import json, os, random, sys, tempfile
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from crypto import decrypt, get_password
from instagrapi import Client
from moviepy.editor import VideoFileClip, vfx

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
            for c in cl.user_clips(uid, amount=5):
                if c.pk not in history and c.video_url:
                    selected = c
                    break
            if selected: break
        except Exception as e:
            print(f"Error {source}: {e}")
    if not selected: sys.exit("No new clips found.")
    print(f"Selected: {selected.pk} from @{selected.user.username}")
    ti, to = Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".mp4"))
    try:
        print("Downloading...")
        with requests.get(selected.video_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with ti.open("wb") as f:
                for chunk in r.iter_content(65536): f.write(chunk)
        print("Editing to avoid duplicate detection (flip + speed)...")
        clip = VideoFileClip(str(ti))
        if clip.duration > 2: clip = clip.subclip(0.5, clip.duration - 0.5)
        clip = clip.fx(vfx.mirror_x).fx(vfx.speedx, 1.05)
        clip.write_videofile(str(to), codec="libx264", audio_codec="aac", logger=None)
        clip.close()
        print("Uploading...")
        cl.clip_upload(str(to), (selected.caption or "") + "\n\n" + HASHTAGS)
        print("POSTED SUCCESSFULLY")
        history.append(selected.pk)
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
    finally:
        if ti.exists(): ti.unlink()
        if to.exists(): to.unlink()

if __name__ == "__main__": main()

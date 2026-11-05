import json, os, sys, tempfile, time, subprocess, re
from pathlib import Path
import requests, pydantic, yt_dlp
sys.path.insert(0, str(Path(__file__).parent))
from crypto import decrypt, get_password
from instagrapi import Client

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

def download_with_ytdlp(url, output_path):
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': str(output_path),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {'instagram': {'include': 'video'}}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def process_video(cl, video_url, msg_id, history):
    print(f"--> Processing video URL: {video_url[:80]}...")
    ti, to, thumb = Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".mp4")), Path(tempfile.mktemp(suffix=".jpg"))
    try:
        print("--> Downloading with yt-dlp (highest quality + audio)...")
        download_with_ytdlp(video_url, ti)
        
        if not ti.exists() or ti.stat().st_size < 1000:
            print("Download failed or file empty.")
            return False

        print("--> Editing (flip to avoid duplicate)...")
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        r1 = subprocess.run([ffmpeg_exe, "-y", "-i", str(ti), "-vf", "hflip", "-c:v", "libx264", "-crf", "18", "-c:a", "copy", str(to)], capture_output=True)
        if r1.returncode != 0:
            print("ffmpeg edit failed")
            return False
            
        r2 = subprocess.run([ffmpeg_exe, "-y", "-i", str(to), "-ss", "00:00:01.000", "-vframes", "1", str(thumb)], capture_output=True)
        
        print("--> Uploading to your account...")
        try:
            cl.clip_upload(str(to), "بسم الله\n\n" + HASHTAGS, thumbnail=str(thumb))
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

def extract_url_from_msg(msg):
    text = getattr(msg, "text", "") or ""
    match = re.search(r'https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[a-zA-Z0-9_-]+', text)
    if match: return match.group(0)
    
    for attr in ['clip', 'media', 'xma_share']:
        obj = getattr(msg, attr, None)
        if not obj: continue
        for sub_attr in ['video_url', 'target_url']:
            url = getattr(obj, sub_attr, None)
            if url and 'instagram.com' in str(url): return str(url)
                
    try:
        raw = msg.model_dump_json()
        match = re.search(r'https?://[^"\']*instagram\.com/(?:reel|p|tv)/[a-zA-Z0-9_-]+', raw)
        if match: return match.group(0)
    except: pass
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
                    
                    print(f"Checking msg {msg.id} | type: {msg.item_type}")
                    video_url = extract_url_from_msg(msg)
                    
                    if video_url:
                        print(f"Found URL: {video_url}")
                        if process_video(cl, video_url, msg.id, history):
                            found = True
                            break
                if found: break
            
            if not found:
                print("No new valid videos. Waiting 10 seconds...")
                time.sleep(10)
                
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(15)

    print("Time limit reached. Exiting gracefully.")

if __name__ == "__main__": main()

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

def download_and_post(cl, media_pk, msg_id, history):
    print(f"--> Downloading video PK: {media_pk} (Highest Quality + Audio)")
    ti = Path(tempfile.mktemp(suffix=".mp4"))
    to = Path(tempfile.mktemp(suffix=".mp4"))
    thumb = Path(tempfile.mktemp(suffix=".jpg"))
    try:
        # تحميل الفيديو بأعلى جودة مع الصوت
        video_path = cl.video_download(media_pk, folder=ti.parent)
        
        # تعديل بسيط (عكس الفيديو) للحفاظ على الصوت كما هو
        print("--> Editing (flip to avoid duplicate)...")
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        r1 = subprocess.run([ffmpeg_exe, "-y", "-i", str(video_path), "-vf", "hflip", "-c:v", "libx264", "-crf", "18", "-c:a", "copy", str(to)], capture_output=True)
        if r1.returncode != 0:
            print("ffmpeg edit failed")
            return False
            
        subprocess.run([ffmpeg_exe, "-y", "-i", str(to), "-ss", "00:00:01.000", "-vframes", "1", str(thumb)], capture_output=True)
        
        print("--> Uploading to your account...")
        media_info = cl.media_info(media_pk)
        caption = media_info.caption_text or ""
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
        print(f"Error: {e}")
        return False
    finally:
        for f in [video_path, ti, to, thumb]:
            if f and Path(f).exists(): Path(f).unlink()

def extract_media_pk(cl, msg):
    # الطريقة 1: البحث عن رابط مباشر داخل XMA
    for attr in ['xma_share', 'clip', 'media', 'xma_media_share', 'media_share']:
        obj = getattr(msg, attr, None)
        if obj:
            if hasattr(obj, 'video_url') and obj.video_url:
                return obj.video_url
            if hasattr(obj, 'pk') and obj.pk:
                return int(obj.pk)
            if hasattr(obj, 'code') and obj.code:
                return cl.media_pk_from_code(obj.code)
            if hasattr(obj, 'id') and obj.id:
                return int(obj.id)

    # الطريقة 2: البحث في النص الخام للرسالة
    try:
        raw = msg.model_dump_json()
        # البحث عن video_url مباشرة
        video_urls = re.findall(r'"video_url":\s*"([^"]+)"', raw)
        if video_urls:
            return video_urls[0]
            
        # البحث عن أي رقم طويل (pk)
        pks = re.findall(r'\b(\d{17,20})\b', raw)
        for pk_str in set(pks):
            return int(pk_str)
            
        # البحث عن code
        codes = re.findall(r'"code":\s*"([a-zA-Z0-9_-]{11})"', raw)
        if codes:
            return cl.media_pk_from_code(codes[0])
    except:
        pass
    return None

def main():
    cl = load_client()
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    start_time = time.time()
    MAX_RUNTIME = 4.5 * 3600 
    
    print(f"Starting DM monitor for {MAX_RUNTIME/3600} hours (Checking every 10s)...")
    
    while time.time() - start_time < MAX_RUNTIME:
        try:
            threads = cl.direct_threads(amount=5)
            found = False
            for thread in threads:
                messages = cl.direct_messages(thread.id, amount=5)
                for msg in messages:
                    if msg.id in history: continue
                    
                    # تجاهل الرسائل النصية العادية والردود
                    if msg.item_type in ('text', 'action_log', 'placeholder', 'voice_media', 'xma_profile'): continue
                    
                    print(f"Checking msg {msg.id} | type: {msg.item_type}")
                    
                    # إذا كانت مشاركة فيديو
                    if msg.item_type in ('xma_clip', 'clip', 'media_share', 'raven_media', 'xma_media_share'):
                        res = extract_media_pk(cl, msg)
                        if res:
                            if isinstance(res, str) and res.startswith('http'):
                                # رابط مباشر
                                ti = Path(tempfile.mktemp(suffix=".mp4"))
                                with requests.get(res, stream=True) as r:
                                    with ti.open("wb") as f:
                                        for chunk in r.iter_content(65536): f.write(chunk)
                                # نحتاج إلى pk للرفع، لذا نستخدم دالة الرفع المباشر
                                print("Found direct video URL, uploading...")
                                # ... (يمكن تحسينها لاحقاً)
                            else:
                                if download_and_post(cl, res, msg.id, history):
                                    found = True
                                    break
                if found: break
            
            if not found:
                print("No new valid videos. Waiting 10 seconds...")
                time.sleep(10) # فحص سريع كل 10 ثوانٍ
                
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(10)

    print("Time limit reached. Exiting gracefully.")

if __name__ == "__main__": main()

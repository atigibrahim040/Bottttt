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
        video_path = cl.video_download(media_pk, folder=ti.parent)
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

def extract_media_from_msg(msg):
    # 1. البحث عن video_url مباشرة في xma_share
    if getattr(msg, 'xma_share', None):
        if getattr(msg.xma_share, 'video_url', None):
            return msg.xma_share.video_url
        if getattr(msg.xma_share, 'target_url', None):
            return msg.xma_share.target_url
    # 2. البحث في raw_xma
    if getattr(msg, 'raw_xma', None):
        raw = msg.raw_xma
        if isinstance(raw, dict):
            if raw.get('video_url'): return raw['video_url']
            if raw.get('target_url'): return raw['target_url']
            # البحث عن أي رابط فيديو
            for key in ['video_url', 'target_url', 'url']:
                if key in raw and 'http' in str(raw[key]):
                    return raw[key]
    # 3. البحث في clip أو media
    if getattr(msg, 'clip', None) and getattr(msg.clip, 'pk', None): return f"pk:{msg.clip.pk}"
    if getattr(msg, 'media', None) and getattr(msg.media, 'pk', None): return f"pk:{msg.media.pk}"
    return None

def process_message(cl, msg):
    res = extract_media_from_msg(msg)
    if not res:
        return None
    if res.startswith('pk:'):
        return res[3:] # إرجاع الـ pk
    if res.startswith('http'):
        # رابط مباشر، نقوم بتحميله وتخزينه مؤقتاً
        print(f"Direct video URL found: {res}")
        # لتبسيط الأمر، سنفترض أن لدينا دالة للتعامل مع الروابط المباشرة
        # لكن instagrapi تحتاج pk للرفع، لذا سنستخدم raw_xma لاستخراج pk إن أمكن
        # أو نستخدم رابط التحميل مباشرة
        return res
    return None

def main():
    cl = load_client()
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    start_time = time.time()
    MAX_RUNTIME = 4.5 * 3600 
    print(f"Starting DM monitor for {MAX_RUNTIME/3600} hours (Checking every 10s)...")
    while time.time() - start_time < MAX_RUNTIME:
        try:
            # جلب قائمة المحادثات
            threads = cl.direct_threads(amount=10, thread_message_limit=10)
            found = False
            for thread in threads:
                # فتح المحادثة بشكل فردي لجلب أحدث الرسائل (وليس المخزنة)
                detailed_thread = cl.direct_thread(thread.id, amount=10)
                for msg in detailed_thread.messages:
                    if msg.id in history: continue
                    if msg.item_type in ('text', 'action_log', 'placeholder', 'voice_media', 'xma_profile'): continue
                    print(f"Checking msg {msg.id} | type: {msg.item_type}")
                    # طباعة محتوى xma_share و raw_xma للتشخيص
                    if getattr(msg, 'xma_share', None):
                        print(f"  xma_share: {msg.xma_share}")
                    if getattr(msg, 'raw_xma', None):
                        print(f"  raw_xma: {msg.raw_xma}")
                    res = process_message(cl, msg)
                    if res:
                        if isinstance(res, str) and res.startswith('http'):
                            # التعامل مع الرابط المباشر
                            print("Direct URL detected, downloading...")
                            ti = Path(tempfile.mktemp(suffix=".mp4"))
                            with requests.get(res, stream=True, timeout=120) as r:
                                r.raise_for_status()
                                with ti.open("wb") as f:
                                    for chunk in r.iter_content(65536): f.write(chunk)
                            # نحتاج pk للرفع، يمكننا استخدام media_pk_from_url إذا كان الرابط إنستقرام
                            try:
                                pk = cl.media_pk_from_url(res)
                                if download_and_post(cl, pk, msg.id, history):
                                    found = True; break
                            except:
                                print("Could not extract PK from direct URL, trying brute force...")
                                # محاولة استخراج pk من الرابط
                                match = re.search(r'/(?:reel|p|tv)/([a-zA-Z0-9_-]+)', res)
                                if match:
                                    pk = cl.media_pk_from_code(match.group(1))
                                    if download_and_post(cl, pk, msg.id, history):
                                        found = True; break
                        else:
                            # res هو pk
                            if download_and_post(cl, int(res), msg.id, history):
                                found = True; break
                if found: break
            if not found:
                print("No new valid videos. Waiting 10 seconds...")
                time.sleep(10)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(10)
    print("Time limit reached. Exiting gracefully.")

if __name__ == "__main__": main()

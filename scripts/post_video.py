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
MAX_AGE_HOURS = 48
CODE_RE = re.compile(r'instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]{5,})')
PK_RE = re.compile(r'^(\d{15,20})(?:_\d+)?$')
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
skipped = set()

def git_push_history():
    run = lambda *a: subprocess.run(a, capture_output=True, text=True)
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "add", "data/history.json")
    run("git", "commit", "-m", "chore: update history [skip ci]")
    run("git", "pull", "--rebase", "--autostash")
    print("push:", run("git", "push").returncode)

def load_client():
    cl = Client()
    cl.set_settings(json.loads(decrypt(SESSION_FILE.read_text(), get_password())))
    cl.delay_range = [2, 5]
    cl.expose = lambda *a, **k: True
    return cl

def raw_items(cl, thread_id, limit=15):
    r = cl.private_request(f"direct_v2/threads/{thread_id}/",
                           params={"visual_message_return_type": "unseen",
                                   "direction": "older", "limit": str(limit)})
    return r.get("thread", {}).get("items", [])

def walk(o, key=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, k)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, key)
    else:
        yield key, o

def shorten(o, n=120):
    if isinstance(o, dict): return {k: shorten(v) for k, v in o.items()}
    if isinstance(o, list): return [shorten(v) for v in o[:3]]
    s = str(o)
    return s if len(s) <= n else s[:n] + "…"

def candidates(item):
    codes, pks, vids = [], [], []
    for k, v in walk(item):
        if isinstance(v, str):
            s = unquote(v)
            m = CODE_RE.search(s)
            if m and m.group(1) not in codes: codes.append(m.group(1))
            if k in ("video_url", "playable_url", "playable_url_hd", "url") and \
               re.search(r'\.mp4|video', s) and s.startswith("http") and s not in vids:
                vids.append(s)
            if k == "code" and re.fullmatch(r'[A-Za-z0-9_-]{8,14}', v) and v not in codes:
                codes.append(v)
        kl = k.lower()
        if kl in ("media_id", "pk", "target_id", "clip_id", "reel_id") or "media" in kl:
            m = PK_RE.match(str(v))
            if m and int(m.group(1)) not in pks: pks.append(int(m.group(1)))
    return codes, pks, vids

def resolve_pk(cl, item):
    codes, pks, vids = candidates(item)
    pk_list = []
    for c in codes:
        try: pk_list.append(cl.media_pk_from_code(c))
        except Exception: pass
    pk_list += pks
    for pk in pk_list:
        try:
            info = cl.media_info(pk)
            if info.media_type == 2 or info.product_type == "clips":
                return pk, info, None
        except Exception as e:
            print(f"  pk {pk} invalid: {str(e)[:80]}")
    if vids:
        return None, None, vids[0]
    return None, None, None

def download(cl, pk, direct_url, folder):
    if pk:
        try: return Path(cl.clip_download(pk, folder=folder))
        except Exception as e:
            print("clip_download failed:", str(e)[:100])
            try: return Path(cl.video_download(pk, folder=folder))
            except Exception as e2: print("video_download failed:", str(e2)[:100])
    url = direct_url or (str(cl.media_info(pk).video_url) if pk else None)
    if not url: return None
    p = folder / f"dl_{int(time.time())}.mp4"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(p, "wb") as f:
            for chunk in r.iter_content(1 << 20): f.write(chunk)
    return p

def download_and_post(cl, pk, info, direct_url, msg_id, history):
    tmp = Path(tempfile.mkdtemp())
    src = out = thumb = None
    try:
        src = download(cl, pk, direct_url, tmp)
        if not src or not src.exists():
            print("download failed"); return False
        out, thumb = tmp / "out.mp4", tmp / "thumb.jpg"
        r = subprocess.run([FFMPEG, "-y", "-i", str(src), "-vf", "hflip",
                            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                            "-c:a", "copy", "-movflags", "+faststart", str(out)],
                           capture_output=True)
        if r.returncode != 0:
            print("ffmpeg failed:", r.stderr[-300:].decode(errors="ignore")); return False
        subprocess.run([FFMPEG, "-y", "-i", str(out), "-ss", "1", "-vframes", "1", str(thumb)],
                       capture_output=True)
        caption = (getattr(info, "caption_text", "") or "") if info else ""
        try:
            cl.clip_upload(str(out), caption + "\n\n" + HASHTAGS,
                           thumbnail=str(thumb) if thumb.exists() else None)
        except pydantic.ValidationError:
            pass
        print("POSTED SUCCESSFULLY")
        history.append(msg_id)
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
        git_push_history()
        return True
    except Exception as e:
        print("Error:", e); return False
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
                for item in raw_items(cl, th["thread_id"]):
                    mid = str(item.get("item_id"))
                    if mid in history or mid in skipped: continue
                    if str(item.get("user_id")) == my_id: continue
                    ts = int(item.get("timestamp", 0)) / 1e6
                    if ts and time.time() - ts > MAX_AGE_HOURS * 3600:
                        skipped.add(mid); continue
                    t = item.get("item_type")
                    if t in ("text", "action_log", "placeholder", "voice_media", "like"): continue
                    print(f"Checking {mid} | type: {t}")
                    print("  RAW:", json.dumps(shorten(item), ensure_ascii=False)[:2500])
                    pk, info, direct = resolve_pk(cl, item)
                    if not pk and not direct:
                        print("  could not extract video; skipping"); skipped.add(mid); continue
                    if download_and_post(cl, pk, info, direct, mid, history):
                        posted = True; break
                    skipped.add(mid)
                if posted: break
            if not posted:
                print("No new valid videos. Waiting 10 seconds...")
            time.sleep(10)
        except Exception as e:
            if "Challenge" in type(e).__name__ or "Challenge" in str(e):
                print("CHALLENGE DETECTED! Stopping to protect account.")
                print(str(e)[:300])
                sys.exit(1)
            print(f"Monitor error: {e}")
            time.sleep(30)
    print("Time limit reached.")

if __name__ == "__main__":
    main()

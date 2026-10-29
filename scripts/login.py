import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto import encrypt, get_password

DEVICE = {
    "app_version": "340.0.0.35.110",
    "android_version": 34, "android_release": "14",
    "dpi": "420dpi", "resolution": "1080x2340",
    "manufacturer": "samsung", "device": "dm3q",
    "model": "SM-S918B", "cpu": "qcom", "version_code": "658745893",
}
UA = "Instagram 340.0.0.35.110 Android (34/14; 420dpi; 1080x2340; samsung; SM-S918B; dm3q; qcom; en_US; 658745893)"

def log(m): print(f"[LOGIN] {m}", flush=True)

def main():
    u = os.getenv("IG_USERNAME","").strip(); p = os.getenv("IG_PASSWORD","").strip()
    if not u or not p: log("ERROR: missing credentials"); sys.exit(1)
    log(f"User: {u} | PwdLen: {len(p)}")
    from instagrapi import Client
    from instagrapi.exceptions import BadPassword, ChallengeRequired, TwoFactorRequired
    for attempt in range(1, 7):
        log(f"=== Attempt {attempt}/6 ===")
        cl = Client()
        cl.delay_range = [1, 3]
        cl.set_device(DEVICE)
        cl.set_user_agent(UA)
        try: cl.request_timeout = 20
        except Exception: pass
        log("Calling cl.login()...")
        try:
            cl.login(u, p)
            log(f"SUCCESS @{cl.username}")
            enc = encrypt(json.dumps(cl.get_settings()), get_password())
            sf = Path(__file__).parent.parent / "data" / "session.enc"
            sf.parent.mkdir(parents=True, exist_ok=True)
            sf.write_text(enc)
            log(f"Saved: {sf} ({len(enc)} chars)")
            return
        except TwoFactorRequired: log("2FA required"); sys.exit(1)
        except BadPassword: log("BAD PASSWORD"); sys.exit(1)
        except ChallengeRequired:
            log("CHALLENGE - open Instagram app, tap 'It was me'")
            if attempt < 6: time.sleep(90)
        except Exception as e:
            log(f"Error: {type(e).__name__}: {e}")
            if attempt < 6: time.sleep(60)
    log("ALL ATTEMPTS FAILED"); sys.exit(1)

if __name__ == "__main__": main()

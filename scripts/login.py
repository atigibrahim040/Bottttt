"""Login to Instagram with retry-on-challenge, save encrypted session."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from crypto import encrypt, get_password
from instagrapi import Client
from instagrapi.exceptions import BadPassword, ChallengeRequired, TwoFactorRequired

SESSION_FILE = Path(__file__).parent.parent / "data" / "session.enc"
MAX_ATTEMPTS = 6
WAIT_SECONDS = 90
PREP_DELAY = 15


def get_credentials():
    user = os.getenv("IG_USERNAME", "").strip()
    pwd = os.getenv("IG_PASSWORD", "").strip()
    if not user or not pwd:
        sys.exit("ERROR: IG_USERNAME and IG_PASSWORD secrets are required")
    return user, pwd


def try_login(user, pwd, device_settings, user_agent):
    cl = Client()
    cl.delay_range = [2, 5]
    if device_settings:
        s = cl.get_settings()
        s["device_settings"] = device_settings
        s["user_agent"] = user_agent
        cl.set_settings(s)
    cl.login(user, pwd)
    return cl


def main():
    user, pwd = get_credentials()

    probe = Client()
    base = probe.get_settings()
    device_settings = base.get("device_settings", {})
    user_agent = base.get("user_agent", "")

    print("=" * 60)
    print(f"  Login for @{user}")
    print("=" * 60)
    print("  IMPORTANT: Open the Instagram app on your phone NOW")
    print(f"  Preparing in {PREP_DELAY} seconds...")
    time.sleep(PREP_DELAY)

    cl = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n=== Attempt {attempt}/{MAX_ATTEMPTS} ===")
        try:
            cl = try_login(user, pwd, device_settings, user_agent)
            print(f"LOGIN SUCCESS: @{cl.username} (id={cl.user_id})")
            break
        except TwoFactorRequired:
            code = os.getenv("IG_2FA_CODE", "").strip()
            if not code:
                sys.exit("2FA required but IG_2FA_CODE secret not set")
            cl = Client()
            cl.login(user, pwd, verification_code=code)
            print(f"LOGIN SUCCESS (2FA): @{cl.username}")
            break
        except BadPassword:
            sys.exit("BAD PASSWORD: check IG_USERNAME / IG_PASSWORD")
        except ChallengeRequired:
            print("!" * 60)
            print("  CHALLENGE REQUIRED")
            print("  -> Open Instagram app on your phone")
            print("  -> Tap 'This was me' / 'It was me'")
            print(f"  -> Waiting {WAIT_SECONDS} seconds...")
            print("!" * 60)
            if attempt == MAX_ATTEMPTS:
                sys.exit("Still challenged after all attempts")
            time.sleep(WAIT_SECONDS)
        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(WAIT_SECONDS)

    if cl is None:
        sys.exit("LOGIN FAILED")

    try:
        cl.get_timeline_feed()
        print("Session verified")
    except Exception as e:
        print(f"Warning: could not verify session: {e}")

    session_json = json.dumps(cl.get_settings())
    encrypted = encrypt(session_json, get_password())
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(encrypted, encoding="ascii")
    print(f"\nSaved encrypted session: {SESSION_FILE} ({len(encrypted)} chars)")


if __name__ == "__main__":
    main()

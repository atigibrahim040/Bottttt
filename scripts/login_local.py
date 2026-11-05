import json, sys, getpass
from pathlib import Path
from instagrapi import Client
from instagrapi.exceptions import BadPassword, ChallengeRequired, TwoFactorRequired

def main():
    u = input("Username: ").strip()
    p = getpass.getpass("Password: ")
    cl = Client(override_app_version=True)
    cl.delay_range = [3, 8]
    print("Logging in...", flush=True)
    try:
        cl.login(u, p)
    except TwoFactorRequired:
        code = input("2FA code: ").strip()
        cl.login(u, p, verification_code=code)
    except BadPassword:
        sys.exit("BAD PASSWORD")
    except ChallengeRequired:
        sys.exit("CHALLENGE - open app, tap 'It was me', wait 5 min, retry")
    except Exception as e:
        sys.exit(f"ERROR: {type(e).__name__}: {e}")
    print(f"SUCCESS @{cl.username}", flush=True)
    Path("session.json").write_text(json.dumps(cl.get_settings()))
    print("Saved session.json", flush=True)

if __name__ == "__main__": main()

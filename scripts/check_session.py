"""Verify current encrypted session still works (run in Termux)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from crypto import decrypt, get_password
from instagrapi import Client

SESSION_FILE = Path(__file__).parent.parent / "data" / "session.enc"

if not SESSION_FILE.exists():
    sys.exit(f"{SESSION_FILE} not found")

session = json.loads(decrypt(SESSION_FILE.read_text(), get_password()))
cl = Client()
cl.set_settings(session)
cl.get_timeline_feed()
print(f"Session valid for @{cl.username}")

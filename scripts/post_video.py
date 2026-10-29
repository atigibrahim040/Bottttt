"""Post next queued video to Instagram (used by GitHub Actions)."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from crypto import decrypt, get_password
from instagrapi import Client

SESSION_FILE = Path(__file__).parent.parent / "data" / "session.enc"
QUEUE_FILE = Path(__file__).parent.parent / "data" / "queue.json"

HASHTAGS = (
    "#قرآن #قران #القرآن_الكريم #اسلام #ذكر_الله #تلاوة "
    "#quran #islam #islamic #muslim #allahuakbar #dua"
)


def load_client():
    if not SESSION_FILE.exists():
        sys.exit("No session file. Run login workflow first.")
    session = json.loads(decrypt(SESSION_FILE.read_text(), get_password()))
    cl = Client()
    cl.set_settings(session)
    cl.delay_range = [2, 5]
    return cl


def download(url, path):
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)


def main():
    cl = load_client()
    if not QUEUE_FILE.exists():
        sys.exit(f"{QUEUE_FILE} not found")
    queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    pending = [i for i, x in enumerate(queue) if not x.get("posted")]
    if not pending:
        print("Queue empty, nothing to post")
        return
    idx = pending[0]
    item = queue[idx]
    caption = (item.get("caption", "") + "\n\n" + HASHTAGS).strip()
    print(f"Posting #{idx}: {caption[:80]}")

    tmp = Path(tempfile.mktemp(suffix=".mp4"))
    try:
        print("Downloading video...")
        download(item["url"], tmp)
        if tmp.stat().st_size < 1000:
            raise RuntimeError("Downloaded file too small")
        print(f"Uploading ({tmp.stat().st_size // 1024} KB)...")
        cl.clip_upload(str(tmp), caption)
        item["posted"] = True
        item["posted_at"] = datetime.now(timezone.utc).isoformat()
        print("POSTED SUCCESSFULLY")
    finally:
        if tmp.exists():
            tmp.unlink()
        QUEUE_FILE.write_text(
            json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()

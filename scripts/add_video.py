"""Add video URL to queue. Usage: python scripts/add_video.py <url> [caption]"""
import json
import sys
from pathlib import Path

QUEUE = Path(__file__).parent.parent / "data" / "queue.json"


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/add_video.py <video_url> [caption]")
    url = sys.argv[1].strip()
    caption = sys.argv[2] if len(sys.argv) > 2 else ""
    q = json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []
    q.append({"url": url, "caption": caption, "posted": False})
    QUEUE.write_text(json.dumps(q, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Added. Queue size: {len(q)}")


if __name__ == "__main__":
    main()

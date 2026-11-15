# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import random
import re
import sys
import time
from collections import defaultdict, deque
from urllib.parse import parse_qs, urlparse

from telethon import TelegramClient, events
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    FloodWaitError,
    SessionRevokedError,
    UserAlreadyParticipantError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

# ───────────────────────── Logging ─────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("telethon").setLevel(logging.WARNING)
log = logging.getLogger("listener")

# ───────────────────────── Config ─────────────────────────
def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        log.critical("Missing environment variable: %s", name)
        sys.exit(1)
    return value


try:
    API_ID = int(env("TELEGRAM_API_ID"))
except ValueError:
    log.critical("TELEGRAM_API_ID must be an integer")
    sys.exit(1)
API_HASH = env("TELEGRAM_API_HASH")
SESSION = env("TELEGRAM_SESSION")

RUN_MINUTES = int(os.environ.get("RUN_MINUTES", "350"))
FAABOT_USERNAME = "FAABOT"
CODE_PROMPT_TIMEOUT = 120          # seconds to wait for the "send the code" prompt
MAX_START_RETRIES = 2              # re-send /start after joining channels
JOIN_PER_MESSAGE_LIMIT = 5

BUTTON_KEYWORDS = ("تحقق", "التحقق", "استخدام كود", "استلام")
JOIN_KEYWORDS = ("اشترك", "اشتراك", "مشترك", "قناة", "القناة")

BIDI_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\u061c]")
URL_RE = re.compile(
    r"(?<![A-Za-z0-9_.@])(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/[^\s<>\"'()\[\]]+",
    re.I,
)
MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]{3,31})")
CODE_PROMPT_RE = re.compile(r"[اأإ]رسل\s+(?:ال)?كود")
USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")
PAYLOAD_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")
TME_HOSTS = {"t.me", "www.t.me", "telegram.me", "telegram.dog"}
RESERVED_PATHS = {
    "joinchat", "addstickers", "addemoji", "addtheme", "addlist", "share", "proxy",
    "socks", "c", "s", "iv", "setlanguage", "login", "confirmphone", "invoice",
    "giftcode", "m", "boost", "contact",
}

CODE_PATTERNS = [
    re.compile(r"كود\s*[:：]\s*([A-Za-z0-9]{2,20})(?![A-Za-z0-9])"),
    re.compile(r"الكود\s+([A-Za-z0-9]{2,20})(?![A-Za-z0-9])"),
    re.compile(r"[:：]\s*([A-Za-z0-9]{3,20})(?![A-Za-z0-9])"),
]

# ───────────────────────── State ─────────────────────────
client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH,
    connection_retries=10,
    retry_delay=5,
    auto_reconnect=True,
    request_retries=5,
)

action_lock = asyncio.Lock()      # one action at a time, 7-10s apart
faabot_lock = asyncio.Lock()      # one FAABOT flow at a time
code_prompt = asyncio.Event()     # set when FAABOT asks for the code

seen_codes = set()
seen_links = set()
attempted_joins = set()
clicked_buttons = set()
last_start = {}                   # bot username(lower) -> last /start text
retry_counts = defaultdict(int)
click_times = defaultdict(deque)
background = set()


# ───────────────────────── Helpers ─────────────────────────
def clean(text) -> str:
    return BIDI_RE.sub("", text or "")


async def human_delay():
    await asyncio.sleep(random.uniform(7.0, 10.0))


def spawn(coro):
    task = asyncio.create_task(coro)
    background.add(task)
    task.add_done_callback(background.discard)
    return task


async def safe(name, coro):
    try:
        await coro
    except Exception:
        log.exception("Unhandled error in task '%s'", name)


def rate_ok(key, limit=8, window=600):
    now = time.monotonic()
    dq = click_times[key]
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


async def step(label, func, *args, **kwargs):
    """Run one action with a human delay before it. Never raises."""
    async with action_lock:
        await human_delay()
        try:
            log.info("▶ %s", label)
            return True, await func(*args, **kwargs)
        except FloodWaitError as e:
            wait = min(e.seconds + 2, 900)
            log.warning("FloodWait %ss on '%s'", e.seconds, label)
            await asyncio.sleep(wait)
        except Exception as e:
            log.error("✖ '%s' failed: %s: %s", label, type(e).__name__, e)
        return False, None


async def send_to_bot(username: str, text: str) -> bool:
    username = username.lstrip("@")
    ok, _ = await step(f"send {text!r} -> @{username}", client.send_message, username, text)
    return ok


async def join_target(kind: str, value: str):
    try:
        if kind == "invite":
            await client(ImportChatInviteRequest(value))
        else:
            await client(JoinChannelRequest(value))
    except UserAlreadyParticipantError:
        log.info("Already a member: %s", value)


def extract_code(text: str):
    for pat in CODE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def iter_buttons(msg):
    try:
        rows = msg.buttons or []
    except Exception:
        return
    for x, row in enumerate(rows):
        for y, btn in enumerate(row):
            yield x, y, btn


def collect_urls(msg):
    urls = []
    try:
        text = clean(msg.raw_text or "")
        urls += [u.rstrip(".,;:!?،؛") for u in URL_RE.findall(text)]
        for ent in msg.entities or []:
            u = getattr(ent, "url", None)
            if u:
                urls.append(u)
        for _, _, btn in iter_buttons(msg):
            u = getattr(btn, "url", None)
            if u:
                urls.append(u)
    except Exception:
        log.exception("collect_urls failed")
    return list(dict.fromkeys(urls))


def parse_tme(url: str):
    """Returns (kind, a, b): ('start', bot, payload) | ('invite', hash, None) | ('public', username, None)."""
    try:
        url = url.strip().rstrip(".,;:!?،؛)")
        if not re.match(r"https?://", url, re.I):
            url = "https://" + url
        u = urlparse(url)
        if (u.hostname or "").lower() not in TME_HOSTS:
            return None
        parts = [p for p in u.path.split("/") if p]
        if not parts:
            return None
        first = parts[0]
        query = parse_qs(u.query)

        if "start" in query:
            if len(parts) == 1 and USERNAME_RE.fullmatch(first):
                payload = query["start"][0]
                if PAYLOAD_RE.fullmatch(payload):
                    return ("start", first, payload)
            return None

        if first.startswith("+") and len(first) > 1:
            return ("invite", first[1:], None)
        if first.lower() == "joinchat" and len(parts) > 1:
            return ("invite", parts[1], None)
        if (
            USERNAME_RE.fullmatch(first)
            and first.lower() not in RESERVED_PATHS
            and not first.lower().endswith("bot")
        ):
            return ("public", first, None)
    except Exception:
        log.exception("parse_tme failed for %r", url)
    return None


# ───────────────────────── Flows ─────────────────────────
async def run_faabot_flow(code: str):
    async with faabot_lock:
        last_start[FAABOT_USERNAME.lower()] = "/start"
        retry_counts[FAABOT_USERNAME.lower()] = 0
        code_prompt.clear()
        if not await send_to_bot(FAABOT_USERNAME, "/start"):
            return
        try:
            await asyncio.wait_for(code_prompt.wait(), CODE_PROMPT_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning("No code prompt from FAABOT, sending code anyway")
        await send_to_bot(FAABOT_USERNAME, code)
        log.info("FAABOT code sent: %s", code)


async def run_referral_flow(bot: str, payload: str):
    text = f"/start {payload}"
    last_start[bot.lower()] = text
    retry_counts[bot.lower()] = 0
    await send_to_bot(bot, text)


async def process_public(event):
    msg = event.message
    text = clean(event.raw_text)

    if "faabot" in text.lower():
        code = extract_code(text)
        if code:
            if code.upper() in seen_codes:
                log.info("Code %s already handled, skipping", code)
            else:
                seen_codes.add(code.upper())
                log.info("FAABOT code found: %s", code)
                spawn(safe("faabot", run_faabot_flow(code)))
        else:
            log.info("FAABOT mentioned but no code found")

    for url in collect_urls(msg):
        info = parse_tme(url)
        if not info or info[0] != "start":
            continue
        _, bot, payload = info
        key = (bot.lower(), payload)
        if key in seen_links:
            continue
        seen_links.add(key)
        log.info("Referral link found: @%s ?start=%s", bot, payload)
        spawn(safe("referral", run_referral_flow(bot, payload)))


async def process_private(event):
    sender = await event.get_sender()
    if sender is None or not getattr(sender, "bot", False):
        return

    msg = event.message
    bot_key = (getattr(sender, "username", None) or str(sender.id)).lower()
    text = clean(event.raw_text)

    if bot_key == FAABOT_USERNAME.lower() and CODE_PROMPT_RE.search(text):
        code_prompt.set()

    labels = [clean(btn.text or "") for _, _, btn in iter_buttons(msg)]
    haystack = text + " " + " ".join(labels)
    wants_join = any(k in haystack for k in JOIN_KEYWORDS)

    # ── 1) forced subscription ──
    targets = []
    for url in collect_urls(msg):
        info = parse_tme(url)
        if info and info[0] in ("invite", "public"):
            targets.append((info[0], info[1]))
    if wants_join:
        for name in MENTION_RE.findall(text):
            if not name.lower().endswith("bot"):
                targets.append(("public", name))
    targets = list(dict.fromkeys(targets))[:JOIN_PER_MESSAGE_LIMIT]

    joined_any = False
    for kind, value in targets:
        key = f"{kind}:{value}".lower()
        if key in attempted_joins:
            continue
        attempted_joins.add(key)
        ok, _ = await step(f"join {kind} {value}", join_target, kind, value)
        joined_any = joined_any or ok

    # ── 2) inline buttons ──
    clicked = False
    for x, y, btn in iter_buttons(msg):
        label = clean(btn.text or "")
        if not any(k in label for k in BUTTON_KEYWORDS):
            continue
        if getattr(btn, "url", None) or getattr(btn, "data", None) is None:
            continue  # URL buttons / non-callback buttons can't be "clicked"
        mkey = (bot_key, msg.id, x, y)
        if mkey in clicked_buttons:
            continue
        clicked_buttons.add(mkey)
        if not rate_ok(f"click:{bot_key}"):
            log.warning("Click rate limit reached for @%s", bot_key)
            continue
        ok, _ = await step(f"click '{label}' @{bot_key}", msg.buttons[x][y].click)
        clicked = clicked or ok

    # ── 3) after joining, retry /start (bounded) ──
    if joined_any and not clicked:
        last = last_start.get(bot_key)
        if last and retry_counts[bot_key] < MAX_START_RETRIES:
            retry_counts[bot_key] += 1
            await send_to_bot(bot_key, last)


# ───────────────────────── Handlers ─────────────────────────
@client.on(events.NewMessage(incoming=True, func=lambda e: not e.is_private))
async def on_public(event):
    try:
        if event.out:
            return
        spawn(safe("public", process_public(event)))
    except Exception:
        log.exception("on_public failed")


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def on_private(event):
    try:
        if event.out:
            return
        spawn(safe("private", process_private(event)))
    except Exception:
        log.exception("on_private failed")


# ───────────────────────── Main ─────────────────────────
async def main() -> int:
    deadline = time.monotonic() + RUN_MINUTES * 60
    authorized = False

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log.info("Time limit reached (%d min)", RUN_MINUTES)
            break
        try:
            await client.connect()
            if not authorized:
                if not await client.is_user_authorized():
                    log.critical("Session is not authorized. Regenerate TELEGRAM_SESSION.")
                    return 1
                me = await client.get_me()
                log.info("Logged in as %s (id=%s). Listening for %d min...",
                         getattr(me, "first_name", "?"), me.id, RUN_MINUTES)
                authorized = True
            await asyncio.wait_for(client.run_until_disconnected(), timeout=remaining)
            log.warning("Disconnected, reconnecting...")
            await asyncio.sleep(5)
        except asyncio.TimeoutError:
            if time.monotonic() >= deadline - 1:
                log.info("Time limit reached (%d min)", RUN_MINUTES)
                break
            log.warning("Timeout, retrying...")
            await asyncio.sleep(5)
        except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, SessionRevokedError) as e:
            log.critical("Session invalid (%s). Regenerate TELEGRAM_SESSION.", type(e).__name__)
            return 1
        except Exception:
            log.exception("Main loop error, retrying in 10s")
            await asyncio.sleep(10)

    for task in list(background):
        task.cancel()
    try:
        await client.disconnect()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass

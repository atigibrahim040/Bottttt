import asyncio
import logging
import os
import random
import re
import sys
import time
from collections import defaultdict, deque
from functools import partial

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, UserAlreadyParticipantError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

# ───────────────────────── الإعدادات ─────────────────────────
RUN_MINUTES = 350                 # مدة التشغيل القصوى
DELAY_MIN, DELAY_MAX = 7.0, 10.0  # التأخير البشري (ثواني)
FAABOT_USERNAME = "FAABOT"
QUEUE_MAX = 200                   # أقصى عدد مهام منتظرة
MAX_JOINS_PER_MESSAGE = 5         # أقصى قنوات تنضم لها من رسالة واحدة
MAX_ACTIONS_PER_BOT = 8           # أقصى إجراءات (انضمام/ضغط) لكل بوت
ACTIONS_WINDOW = 600              # ... خلال هذه المدة (ثواني) - لمنع اللوب
CODE_DEDUP_TTL = 1800             # تجاهل نفس الكود إذا تكرر خلال 30 دقيقة

BUTTON_KEYWORDS = ("تحقق", "التحقق", "استخدام كود", "استلام")
SUBSCRIBE_WORDS = ("اشترك", "اشتراك", "قناة", "قنوات")
RESERVED_LINKS = {
    "joinchat", "addstickers", "addemoji", "addtheme", "addlist", "share", "proxy",
    "socks", "setlanguage", "boost", "iv", "login", "contact", "giftcode",
    "invoice", "bg", "confirmphone", "c", "s",
}

# ───────────────────────── Regex ─────────────────────────
# إزالة الرموز المخفية + التشكيل + التطويل عشان الاستخراج يكون أدق
INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u0640\u064b-\u065f]")

TME = r"(?<![A-Za-z0-9.\-])(?:t\.me|telegram\.me|telegram\.dog)/"

FAABOT_RE = re.compile(r"(?<![A-Za-z0-9_])(?:@FAABOT|FAABOT@)(?![A-Za-z0-9_])", re.IGNORECASE)

# الكود : LJYS  |  الكود: 7DD  |  الكود :JOTL  |  الكود : `LJYS`
CODE_RE = re.compile(
    r"(?:ال)?كود\s*[:：\-–=]?\s*[\"'`“”‘’«»\[\(\*_~|<>]*\s*([A-Za-z0-9]{2,20})(?![A-Za-z0-9])"
)
# احتياطي: أي كود كبير (حروف/أرقام) بعد نقطتين
CODE_FALLBACK_RE = re.compile(
    r"[:：]\s*[\"'`“”‘’«»\[\(\*_~|<>]*\s*(?=[A-Z0-9]*[A-Z])([A-Z0-9]{3,12})(?![A-Za-z0-9])"
)

REFERRAL_RE = re.compile(
    TME + r"([A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9])/?\?start=([A-Za-z0-9_\-]{1,64})",
    re.IGNORECASE,
)
INVITE_RE = re.compile(TME + r"(?:\+|joinchat/)([A-Za-z0-9_\-]{10,})", re.IGNORECASE)
PUBLIC_RE = re.compile(
    TME + r"([A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9])(?![A-Za-z0-9_])(?!/?\?start)",
    re.IGNORECASE,
)
MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9])(?![A-Za-z0-9_])")

# ───────────────────────── Logging ─────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
logging.getLogger("telethon").setLevel(logging.WARNING)
log = logging.getLogger("listener")

# ───────────────────────── الحالة العامة ─────────────────────────
client: TelegramClient | None = None
queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
SEEN_CODES: dict = {}
SEEN_REFERRALS: dict = {}
JOINED: set = set()
BOT_ACTIONS: dict = defaultdict(deque)


# ───────────────────────── أدوات مساعدة ─────────────────────────
async def human_delay():
    await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def clean(text) -> str:
    return INVISIBLE_RE.sub("", text or "")


def seen_recently(store: dict, key, ttl: float) -> bool:
    ts = store.get(key)
    return ts is not None and (time.monotonic() - ts) <= ttl


def enqueue(label: str, factory) -> bool:
    try:
        queue.put_nowait((label, factory))
        return True
    except asyncio.QueueFull:
        log.warning("Queue full, dropped: %s", label)
        return False


def allow_action(sender_id) -> bool:
    now = time.monotonic()
    dq = BOT_ACTIONS[sender_id]
    while dq and now - dq[0] > ACTIONS_WINDOW:
        dq.popleft()
    if len(dq) >= MAX_ACTIONS_PER_BOT:
        return False
    dq.append(now)
    return True


def extract_code(text: str):
    m = CODE_RE.search(text) or CODE_FALLBACK_RE.search(text)
    return m.group(1) if m else None


def extract_referrals(haystack: str):
    out, seen = [], set()
    for m in REFERRAL_RE.finditer(haystack):
        bot, payload = m.group(1), m.group(2)
        if not bot.lower().endswith("bot"):  # يوزر البوتات دائماً ينتهي بـ bot
            continue
        key = (bot.lower(), payload)
        if key not in seen:
            seen.add(key)
            out.append((bot, payload))
    return out


async def collect_haystack(message, text: str) -> str:
    """النص + روابط الـ entities المخفية + روابط الأزرار."""
    parts = [text]
    try:
        for ent in message.entities or []:
            url = getattr(ent, "url", None)
            if url:
                parts.append(url)
    except Exception:
        log.exception("entities parse error")
    try:
        rows = await message.get_buttons()
        for row in rows or []:
            for btn in row:
                if btn.url:
                    parts.append(btn.url)
    except Exception:
        log.exception("buttons parse error")
    return "\n".join(parts)


def extract_join_targets(text: str, haystack: str):
    targets, seen = [], set()

    def add(kind, value):
        key = (kind, value if kind == "invite" else value.lower())
        if key not in seen:
            seen.add(key)
            targets.append((kind, value))

    for m in INVITE_RE.finditer(haystack):
        add("invite", m.group(1))
    for m in PUBLIC_RE.finditer(haystack):
        name = m.group(1)
        if name.lower() in RESERVED_LINKS or name.lower().endswith("bot"):
            continue
        add("public", name)
    if any(w in text for w in SUBSCRIBE_WORDS):
        for m in MENTION_RE.finditer(text):
            name = m.group(1)
            if not name.lower().endswith("bot"):
                add("public", name)
    return targets[:MAX_JOINS_PER_MESSAGE]


async def find_button(message):
    """يرجع (صف, عمود) لأول زر inline يحتوي كلمة مطلوبة."""
    try:
        rows = await message.get_buttons()
        for i, row in enumerate(rows or []):
            for j, btn in enumerate(row):
                if btn.data is None:  # أزرار callback فقط
                    continue
                label = clean(btn.text)
                if any(k in label for k in BUTTON_KEYWORDS):
                    return i, j
    except Exception:
        log.exception("find_button error")
    return None


# ───────────────────────── المهام (تنفذ بالتسلسل) ─────────────────────────
async def faabot_job(code: str):
    try:
        await human_delay()
        await client.send_message(FAABOT_USERNAME, "/start", parse_mode=None)
        log.info("→ @FAABOT: /start")
        await human_delay()
        await client.send_message(FAABOT_USERNAME, code, parse_mode=None)
        log.info("→ @FAABOT: %s", code)
    except Exception:
        SEEN_CODES.pop(code, None)
        raise


async def referral_job(bot: str, payload: str):
    try:
        await human_delay()
        await client.send_message(bot, f"/start {payload}", parse_mode=None)
        log.info("→ @%s: /start %s", bot, payload)
    except Exception:
        SEEN_REFERRALS.pop((bot.lower(), payload), None)
        raise


async def private_job(message, targets, btn_pos):
    for kind, value in targets:
        key = (kind, value if kind == "invite" else value.lower())
        if key in JOINED:
            continue
        await human_delay()
        try:
            if kind == "invite":
                await client(ImportChatInviteRequest(value))
            else:
                await client(JoinChannelRequest(value))
            JOINED.add(key)
            log.info("Joined %s: %s", kind, value)
        except UserAlreadyParticipantError:
            JOINED.add(key)
        except FloodWaitError:
            raise
        except Exception as e:
            log.warning("Join failed (%s %s): %r", kind, value, e)

    if btn_pos:
        i, j = btn_pos
        await human_delay()
        try:
            rows = await message.get_buttons()
            await rows[i][j].click()
            log.info("Clicked button [%d][%d]", i, j)
        except FloodWaitError:
            raise
        except Exception as e:
            log.warning("Button click failed: %r", e)


async def worker():
    while True:
        label, factory = await queue.get()
        try:
            log.info("Job: %s", label)
            await factory()
        except FloodWaitError as e:
            log.warning("FloodWait %ss on job: %s", e.seconds, label)
            await asyncio.sleep(e.seconds + 3)
        except Exception:
            log.exception("Job failed: %s", label)
        finally:
            queue.task_done()


# ───────────────────────── الـ Handlers ─────────────────────────
def _not_private(e) -> bool:
    return not e.is_private


def _is_private(e) -> bool:
    return bool(e.is_private)


async def on_group_message(event):
    """رسائل القنوات والمجموعات: كود FAABOT + روابط ?start="""
    try:
        if event.out:
            return
        text = clean(event.raw_text)
        message = event.message
        if not text and not message.reply_markup:
            return
        haystack = await collect_haystack(message, text)

        if FAABOT_RE.search(text):
            code = extract_code(text)
            if not code:
                log.info("FAABOT mentioned but no code found")
            elif not seen_recently(SEEN_CODES, code, CODE_DEDUP_TTL):
                if enqueue(f"FAABOT code {code}", partial(faabot_job, code)):
                    SEEN_CODES[code] = time.monotonic()

        for bot, payload in extract_referrals(haystack):
            key = (bot.lower(), payload)
            if seen_recently(SEEN_REFERRALS, key, float("inf")):
                continue
            if enqueue(f"referral {bot}?start={payload}", partial(referral_job, bot, payload)):
                SEEN_REFERRALS[key] = time.monotonic()
    except Exception:
        log.exception("group handler error")


async def on_private_message(event):
    """رسائل البوتات الخاصة: اشتراك إجباري + ضغط أزرار"""
    try:
        if event.out:
            return
        sender = await event.get_sender()
        if sender is None or not getattr(sender, "bot", False):
            return

        message = event.message
        text = clean(event.raw_text)
        haystack = await collect_haystack(message, text)

        targets = extract_join_targets(text, haystack)
        targets = [t for t in targets
                   if (t[0], t[1] if t[0] == "invite" else t[1].lower()) not in JOINED]
        btn_pos = await find_button(message)

        if not targets and not btn_pos:
            return
        if not allow_action(event.sender_id):
            log.warning("Action limit reached for bot %s, skipping", event.sender_id)
            return

        enqueue(
            f"private reply from {event.sender_id}",
            partial(private_job, message, targets, btn_pos),
        )
    except Exception:
        log.exception("private handler error")


# ───────────────────────── التشغيل ─────────────────────────
async def main() -> int:
    global client

    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session = os.environ.get("TELEGRAM_SESSION", "").strip()
    if not (api_id and api_hash and session):
        log.critical("Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_SESSION")
        return 1
    try:
        api_id_int = int(api_id)
    except ValueError:
        log.critical("TELEGRAM_API_ID must be a number")
        return 1

    client = TelegramClient(
        StringSession(session),
        api_id_int,
        api_hash,
        connection_retries=-1,
        retry_delay=5,
        auto_reconnect=True,
    )

    await client.connect()
    if not await client.is_user_authorized():
        log.critical("Session is not authorized (invalid/expired TELEGRAM_SESSION)")
        await client.disconnect()
        return 1

    me = await client.get_me()
    log.info("Logged in as %s (id=%s)", getattr(me, "first_name", "?"), me.id)

    client.add_event_handler(on_group_message, events.NewMessage(incoming=True, func=_not_private))
    client.add_event_handler(on_private_message, events.NewMessage(incoming=True, func=_is_private))

    worker_task = asyncio.create_task(worker())
    deadline = time.monotonic() + RUN_MINUTES * 60
    log.info("Listening for up to %d minutes...", RUN_MINUTES)

    try:
        while time.monotonic() < deadline:
            try:
                if not client.is_connected():
                    await client.connect()
                await asyncio.wait_for(
                    client.run_until_disconnected(),
                    timeout=max(1.0, deadline - time.monotonic()),
                )
            except asyncio.TimeoutError:
                pass
            except Exception:
                log.exception("Listener error, will reconnect")
            if time.monotonic() < deadline:
                await asyncio.sleep(5)
    finally:
        worker_task.cancel()
        try:
            await client.disconnect()
        except Exception:
            pass

    log.info("Time limit reached, shutting down.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)

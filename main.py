# -*- coding: utf-8 -*-
"""
Telegram Auto-Listener for GitHub Actions
- Listens to channels/groups for @FAABOT codes and referral links
- Handles private bot replies (join channels / click inline buttons)
- Human-like delays (7-10s), never crashes, max runtime 350 minutes
"""

import os
import re
import random
import asyncio
import logging

from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("telegram-automation")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.environ["TELEGRAM_SESSION"]

MAX_RUNTIME_SECONDS = 350 * 60  # 350 minutes hard limit

FAABOT_USERNAME = "FAABOT"

# Keywords for clicking inline buttons in private bot replies
BUTTON_KEYWORDS = ["تحقق", "التحقق", "استخدام كود", "استلام"]

# Keywords that indicate a mandatory channel subscription request
SUBSCRIBE_KEYWORDS = ["اشترك", "قناة"]

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------
# Matches: "الكود : LJYS" / "الكود: JOTL" / "الكود 7DD"
CODE_REGEX = re.compile(r"الكود\s*[:：]?\s*([A-Za-z0-9]+)")

# Matches: https://t.me/BOTNAME?start=PAYLOAD
REFERRAL_REGEX = re.compile(
    r"https?://t\.me/([A-Za-z0-9_]{3,64})\?start=([A-Za-z0-9_\-]+)"
)

# Matches any t.me link that is NOT a bot (possible channel/group link)
CHANNEL_LINK_REGEX = re.compile(r"https?://t\.me/([A-Za-z0-9_]{3,64})")

# A very rough heuristic: bot usernames often end with 'bot'
BOT_SUFFIX_REGEX = re.compile(r"bot$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def human_delay() -> float:
    """Human-like delay between 7 and 10 seconds."""
    return random.uniform(7.0, 10.0)


async def smart_delay():
    try:
        await asyncio.sleep(human_delay())
    except Exception as e:
        log.warning("Delay interrupted: %s", e)


async def safe_send(client: TelegramClient, target, text: str, what: str = "message"):
    """Send a message safely, resolving username inline without crashing."""
    try:
        await client.send_message(target, text)
        log.info("[SEND %s] -> %s : %r", what, target, text)
        return True
    except Exception as e:
        log.error("[SEND FAIL %s] target=%r text=%r error=%s", what, target, text, e)
        return False


# ---------------------------------------------------------------------------
# Handler 1: Channels / Groups — FAABOT codes + referral links
# ---------------------------------------------------------------------------
async def handle_public_message(event, client: TelegramClient):
    try:
        text = event.raw_text or ""
        if not text:
            return

        # --- 1) FAABOT code flow ---
        if ("FAABOT@" in text) or ("@FAABOT" in text):
            code_match = CODE_REGEX.search(text)
            if code_match:
                code = code_match.group(1)
                log.info("[FAABOT] Found code: %s", code)

                # Step 1: /start
                await smart_delay()
                ok = await safe_send(client, FAABOT_USERNAME, "/start", "faabot-start")
                if not ok:
                    return

                # Step 2: the extracted code
                await smart_delay()
                await safe_send(client, FAABOT_USERNAME, code, "faabot-code")
            else:
                log.info("[FAABOT] Mentioned but no code found in message.")

        # --- 2) Referral links (?start=) ---
        for username, payload in REFERRAL_REGEX.findall(text):
            log.info("[REFERRAL] bot=%s payload=%s", username, payload)
            await smart_delay()
            await safe_send(client, username, f"/start {payload}", "referral")

    except Exception as e:
        log.error("[PUBLIC HANDLER ERROR] %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Handler 2: Private messages from bots — join channels + click buttons
# ---------------------------------------------------------------------------
async def handle_private_message(event, client: TelegramClient):
    try:
        sender = await event.get_sender()
        # Only react to bots in private chats
        if not getattr(sender, "bot", False):
            return

        text = event.raw_text or ""

        # --- 1) Mandatory subscription: join channels mentioned in text ---
        needs_join = any(kw in text for kw in SUBSCRIBE_KEYWORDS)
        if needs_join:
            for username in CHANNEL_LINK_REGEX.findall(text):
                # Skip obvious bot links (bots can't be joined as channels anyway)
                if BOT_SUFFIX_REGEX.search(username):
                    continue
                try:
                    log.info("[JOIN] Attempting to join @%s", username)
                    await smart_delay()
                    await client(functions.channels.JoinChannelRequest(channel=username))
                    log.info("[JOIN] Successfully joined @%s", username)
                except Exception as e:
                    log.error("[JOIN FAIL] @%s error=%s", username, e)

        # --- 2) Click inline buttons with target keywords ---
        try:
            button_rows = event.message.buttons
        except Exception:
            button_rows = None

        if button_rows:
            for row in button_rows:
                if not row:
                    continue
                for button in row:
                    try:
                        btn_text = (button.text or "")
                    except Exception:
                        btn_text = ""
                    if any(kw in btn_text for kw in BUTTON_KEYWORDS):
                        try:
                            log.info("[BUTTON] Clicking: %r", btn_text)
                            await smart_delay()
                            await button.click()
                            log.info("[BUTTON] Clicked: %r", btn_text)
                        except Exception as e:
                            log.error("[BUTTON FAIL] %r error=%s", btn_text, e)

    except Exception as e:
        log.error("[PRIVATE HANDLER ERROR] %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    log.info("Starting Telegram automation client...")

    client = TelegramClient(
        StringSession(SESSION),
        API_ID,
        API_HASH,
        # Connection tuning for CI environments
        connection_retries=None,
        retry_delay=2,
        auto_reconnect=True,
        request_retries=10,
    )

    await client.start()
    me = await client.get_me()
    log.info("Logged in as: %s (id=%s)", getattr(me, "username", None), me.id)

    # --- Event: new messages everywhere (incoming only) ---
    @client.on(events.NewMessage(incoming=True))
    async def _on_message(event):
        try:
            # Ignore messages sent by the account itself (safety vs loops)
            if event.out:
                return

            if event.is_private:
                await handle_private_message(event, client)
            else:
                await handle_public_message(event, client)
        except Exception as e:
            log.error("[EVENT LOOP ERROR] %s", e, exc_info=True)

    log.info("Client is listening (max runtime: %d minutes)...",
             MAX_RUNTIME_SECONDS // 60)

    try:
        await asyncio.wait_for(
            client.run_until_disconnected(),
            timeout=MAX_RUNTIME_SECONDS,
        )
    except asyncio.TimeoutError:
        log.info("Maximum runtime (%d minutes) reached. Shutting down gracefully.",
                 MAX_RUNTIME_SECONDS // 60)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    log.info("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Interrupted by user/system.")
    except Exception as e:
        log.error("FATAL (unexpected): %s", e, exc_info=True)
        # Exit cleanly so the workflow can restart/logs stay readable
        raise SystemExit(1)

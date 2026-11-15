import os
import re
import sys
import asyncio
import random
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

env_api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
env_api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
env_session = os.environ.get("TELEGRAM_SESSION", "").strip()

if not env_api_id or not env_api_hash or not env_session:
    logging.error("CRITICAL ERROR: Missing environment variables.")
    sys.exit(1)

API_ID = int(env_api_id)
API_HASH = env_api_hash
SESSION = env_session

TALABATI_BOT = '@FAABOT'
FUNDING_BOT = '@yynnurybot'

async def human_delay():
    delay = random.uniform(7.0, 10.0)
    logging.info(f"Waiting for {delay:.2f} seconds (Human behavior)...")
    await asyncio.sleep(delay)

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

@client.on(events.NewMessage(incoming=True))
async def global_listener(event):
    text = event.message.text or ""
    if not text:
        return

    # 1. بوت طلباتي @FAABOT (الكود ديناميكي يتغير دائماً)
    if '@FAABOT' in text or 'FAABOT@' in text:
        code = None
        # البحث عن الكود بعد كلمة "الكود" أو "كود" (يدعم 7DD, YERY, 514, 784...)
        match_ar = re.search(r'(?:الكود|كود)\s*[:|]?\s*([a-zA-Z0-9]+)', text)
        if match_ar:
            code = match_ar.group(1)
        else:
            # البحث عن الكود بعد @FAABOT مباشرة
            match_en = re.search(r'(?:FAABOT@|@FAABOT)\s*([a-zA-Z0-9]+)', text)
            if match_en:
                code = match_en.group(1)

        if code:
            try:
                logging.info(f"Found dynamic FAABOT code: {code}. Sending /start...")
                await client.send_message(TALABATI_BOT, '/start')
                await human_delay()
                
                logging.info(f"Sending dynamic code: {code} to {TALABATI_BOT}")
                await client.send_message(TALABATI_BOT, code)
                await human_delay()
            except Exception as e:
                logging.error(f"Error sending FAABOT code: {e}")

    # 2. صيد روابط تمويل yynnurybot
    referral_links = re.findall(r'https://t\.me/yynnurybot\?start=([a-zA-Z0-9_\-]+)', text)
    for payload in referral_links:
        try:
            logging.info(f"Found yynnurybot referral payload: {payload}. Sending /start...")
            await client.send_message(FUNDING_BOT, f'/start {payload}')
            await human_delay()
        except Exception as e:
            logging.error(f"Error sending funding payload: {e}")

@client.on(events.NewMessage(from_users=[TALABATI_BOT, FUNDING_BOT]))
async def bot_listener(event):
    text = event.message.text or ""
    logging.info(f"Received reply from bot: {text[:80]}...")

    # 1. الاشتراك الإجباري
    if "اشترك" in text or "عليك الاشتراك" in text:
        links = re.findall(r'https://t\.me/[a-zA-Z0-9_]+', text)
        if links:
            try:
                logging.info(f"Joining required channel: {links[0]}")
                await client(JoinChannelRequest(links[0]))
                await human_delay()
            except Exception as e:
                logging.error(f"Error joining channel: {e}")

    # 2. الضغط على الأزرار (استخدام كود، تحقق)
    if event.message.buttons:
        for row in event.message.buttons:
            for btn in row:
                btn_text = btn.text
                if any(keyword in btn_text for keyword in ["تحقق", "التحقق", "استخدام كود"]):
                    try:
                        logging.info(f"Clicking button: {btn_text}")
                        await btn.click()
                        await human_delay()
                    except Exception as e:
                        logging.error(f"Error clicking button: {e}")

async def main():
    logging.info("Starting Advanced Telegram Automation Script...")
    await client.start()
    logging.info("Client started successfully. Listening for DYNAMIC codes...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())

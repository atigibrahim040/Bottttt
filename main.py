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

async def human_delay():
    delay = random.uniform(7.0, 10.0)
    logging.info(f"Waiting for {delay:.2f} seconds...")
    await asyncio.sleep(delay)

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

@client.on(events.NewMessage(incoming=True))
async def global_listener(event):
    # تجاهل الرسائل الخاصة لتجنب التداخل مع ردود البوتات
    if event.is_private:
        return

    text = event.message.text or ""
    if not text:
        return

    # 1. صيد أكواد @FAABOT (مثل LJYS, JOTL, 7DD)
    if '@FAABOT' in text or 'FAABOT@' in text:
        # استخراج الكود بعد كلمة "الكود :" أو "كود"
        match = re.search(r'الكود\s*[:|]?\s*([a-zA-Z0-9]+)', text)
        if not match:
            # محاولة أخرى إذا كانت الصيغة مختلفة
            match = re.search(r'FAABOT@\s*([a-zA-Z0-9]+)', text)
            
        if match:
            code = match.group(1)
            logging.info(f"Found TALABATI code: {code}")
            try:
                await client.send_message(TALABATI_BOT, '/start')
                await human_delay()
                
                # إرسال الكود
                logging.info(f"Sending code {code} to TALABATI_BOT")
                await client.send_message(TALABATI_BOT, code)
                await human_delay()
            except Exception as e:
                logging.error(f"Error sending FAABOT code: {e}")

    # 2. صيد أي رابط بوت يحتوي على start (مثل iraqi_isbot, yynnurybot)
    # السكربت يبحث عن أي رابط بهذا الشكل: https://t.me/BOT_NAME?start=PAYLOAD
    links = re.findall(r'https://t\.me/([a-zA-Z0-9_]+bot)\?start=([a-zA-Z0-9_\-]+)', text)
    for bot_name, payload in links:
        try:
            logging.info(f"Found bot link: @{bot_name} with payload {payload}")
            # إرسال الأمر /start مع الكود للبوت (وهذا يعادل الضغط على الرابط)
            await client.send_message(f'@{bot_name}', f'/start {payload}')
            await human_delay()
        except Exception as e:
            logging.error(f"Error sending start payload to @{bot_name}: {e}")

@client.on(events.NewMessage(incoming=True))
async def bot_reply_listener(event):
    # الاستماع فقط للرسائل الخاصة (ردود البوتات)
    if not event.is_private:
        return

    text = event.message.text or ""
    if not text:
        return
        
    logging.info(f"Received reply from bot: {text[:50]}...")

    # 1. التعامل مع الاشتراك الإجباري
    if "اشترك" in text or "قناة" in text or "انضم" in text:
        links = re.findall(r'https://t\.me/[a-zA-Z0-9_]+', text)
        for link in links:
            if '?start=' not in link: # التأكد من أنه رابط قناة وليس بوت
                try:
                    logging.info(f"Joining required channel: {link}")
                    await client(JoinChannelRequest(link))
                    await human_delay()
                except Exception as e:
                    logging.error(f"Error joining channel {link}: {e}")

    # 2. الضغط على الأزرار (تحقق، استخدام كود)
    if event.message.buttons:
        for row in event.message.buttons:
            for btn in row:
                btn_text = btn.text
                if any(keyword in btn_text for keyword in ["تحقق", "التحقق", "استخدام كود", "استلام", "شحن"]):
                    try:
                        logging.info(f"Clicking button: {btn_text}")
                        await btn.click()
                        await human_delay()
                    except Exception as e:
                        logging.error(f"Error clicking button {btn_text}: {e}")

async def main():
    logging.info("Starting Advanced Telegram Automation Script...")
    await client.start()
    logging.info("Client started successfully. Listening for any bot links and FAABOT codes...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())

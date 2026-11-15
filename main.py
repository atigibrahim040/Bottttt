import os
import re
import asyncio
import random
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.environ["TELEGRAM_SESSION"]

# أسماء القنوات التي تنشر الأكواد والروابط
SOURCE_CHANNELS = ['@TALABATKOM_Channel', '@AsiacellFunding_Channel'] # يرجى تعديلها بأسماء القنوات الحقيقية
# البوتات المستهدفة
TARGET_BOTS = ['@FAABOT', '@yynnurybot']

async def human_delay():
    delay = random.uniform(7.0, 10.0)
    logging.info(f"Waiting for {delay:.2f} seconds (Human behavior)...")
    await asyncio.sleep(delay)

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def channel_listener(event):
    text = event.message.text
    if not text:
        return
    
    logging.info(f"New message detected: {text[:80]}...")

    # 1. صيد صيغة FAABOT@ 7DD (كما في الصورة 7)
    faabot_codes = re.findall(r'FAABOT@\s*([a-zA-Z0-9]{3,10})', text)
    for code in faabot_codes:
        try:
            logging.info(f"Found FAABOT code: {code}. Sending to @FAABOT...")
            await client.send_message('@FAABOT', '/start')
            await human_delay()
            await client.send_message('@FAABOT', code)
            await human_delay()
        except Exception as e:
            logging.error(f"Error sending FAABOT code: {e}")

    # 2. صيد روابط yynnurybot (كما في الصور 3 و 4)
    referral_links = re.findall(r'https://t\.me/yynnurybot\?start=([a-zA-Z0-9_\-]+)', text)
    for payload in referral_links:
        try:
            logging.info(f"Found yynnurybot referral payload: {payload}. Sending /start...")
            await client.send_message('@yynnurybot', f'/start {payload}')
            await human_delay()
        except Exception as e:
            logging.error(f"Error sending yynnurybot payload: {e}")

    # 3. صيد الأكواد العادية (مثل LIDNU)
    plain_codes = re.findall(r'^(?:الكود\s*[:|]?\s*)([A-Z0-9]{3,10})$', text, re.MULTILINE)
    for p_code in plain_codes:
        try:
            logging.info(f"Found plain code: {p_code}. Sending to @FAABOT...")
            await client.send_message('@FAABOT', p_code)
            await human_delay()
        except Exception as e:
            logging.error(f"Error sending plain code: {e}")


@client.on(events.NewMessage(from_users=TARGET_BOTS))
async def bot_listener(event):
    text = event.message.text or ""
    logging.info(f"Received reply from bot: {text[:80]}...")

    # 1. التعامل مع الاشتراك الإجباري (صورة 2)
    if "اشترك" in text or "عليك الاشتراك" in text:
        links = re.findall(r'https://t\.me/[a-zA-Z0-9_]+', text)
        if links:
            try:
                logging.info(f"Joining required channel: {links[0]}")
                await client(JoinChannelRequest(links[0]))
                await human_delay()
            except Exception as e:
                logging.error(f"Error joining channel: {e}")

    # 2. الضغط التلقائي على الأزرار (استخدام كود، تحقق من الاشتراك، رجوع)
    if event.message.buttons:
        for row in event.message.buttons:
            for btn in row:
                btn_text = btn.text
                if any(keyword in btn_text for keyword in ["تحقق", "التحقق", "استخدام كود", "تجميع نقاط"]):
                    try:
                        logging.info(f"Clicking button: {btn_text}")
                        await btn.click()
                        await human_delay()
                    except Exception as e:
                        logging.error(f"Error clicking button: {e}")

async def main():
    logging.info("Starting Advanced Telegram Automation Script...")
    await client.start()
    logging.info("Client started successfully. Listening for target formats...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())

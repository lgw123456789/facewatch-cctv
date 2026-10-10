import json
import sys
from pathlib import Path

import requests

config = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
token = str(config.get("telegram_bot_token", "")).strip()
if not token or "PASTE" in token:
    sys.exit("Put your bot token from @BotFather into config.json first.")

try:
    reply = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
except requests.RequestException as e:
    sys.exit(f"Could not reach Telegram ({type(e).__name__}) - check the internet connection.")
if not reply.get("ok"):
    sys.exit(f"Telegram said: {reply.get('description')} - is the bot token correct?")

chats = {}
for update in reply["result"]:
    message = update.get("message") or update.get("channel_post") or {}
    chat = message.get("chat")
    if chat:
        chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name") or ""

if not chats:
    sys.exit("No messages found. Send any message to your bot in Telegram, then run this again.")
for chat_id, who in chats.items():
    print(f'"telegram_chat_id": "{chat_id}"     <- {who}')

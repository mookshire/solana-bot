from __future__ import annotations
import os, json, requests

def _post_json(url: str, payload: dict):
    try:
        r = requests.post(url, json=payload, timeout=6)
        r.raise_for_status()
        print(f"[notify] POST ok → {url.split('//',1)[-1][:40]}…")
    except Exception as e:
        print(f"[notify] POST error: {e}")

def send_text(msg: str) -> None:
    wh = os.environ.get("WEBHOOK_URL")
    if wh:
        # Slack/Discord-compatible: simple {"text": "..."}
        _post_json(wh, {"text": msg})

    bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if bot and chat:
        url = f"https://api.telegram.org/bot{bot}/sendMessage"
        try:
            r = requests.post(url, data={"chat_id": chat, "text": msg}, timeout=6)
            r.raise_for_status()
            print("[notify] Telegram ok")
        except Exception as e:
            print(f"[notify] Telegram error: {e}")

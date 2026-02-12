import requests

def telegram_send_message(bot_token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # 🔒 Por si acaso: límite seguro de longitud
    if len(text) > 4000:
        text = text[:4000] + "\n…"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }

    r = requests.post(url, json=payload, timeout=25)

    if not r.ok:
        # 👇 Esto es lo que nos dirá exactamente por qué Telegram se queja
        print("❌ Telegram error:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()



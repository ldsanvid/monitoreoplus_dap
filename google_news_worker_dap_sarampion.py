import os
import time
import feedparser
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


# Si ya tienes telegram_utils en tu proyecto (como en el worker de Fajardo), úsalo:
from telegram_utils import telegram_send_message
MX_TZ = ZoneInfo("America/Mexico_City")


START_TIME = datetime.now(ZoneInfo("America/Mexico_City")).astimezone(timezone.utc)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_DAP")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID_DAP_SALUD")  # o el nombre que prefieras

CHECK_INTERVAL = int(os.environ.get("GOOGLE_NEWS_CHECK_INTERVAL", "120"))  # 2 min default

# RSS del tema
RSS_URL = os.environ.get("GOOGLE_NEWS_RSS_SARAMPION_MX")

SEEN_FILE = "google_news_seen_dap_sarampion.txt"
seen_ids = set()


def cargar_vistos():
    global seen_ids
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen_ids = set(l.strip() for l in f if l.strip())
    print(f"📁 IDs ya vistos (DAP sarampión): {len(seen_ids)}")


def guardar_visto(entry_id: str):
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        f.write(entry_id + "\n")


def formatear_alerta(entry) -> str:
    titulo_raw = getattr(entry, "title", "(sin título)").strip()
    link = getattr(entry, "link", "").strip()

    # En Google News muchas veces viene: "Titular - Medio"
    titulo = titulo_raw
    medio_desde_titulo = ""
    if " - " in titulo_raw:
        parte_titulo, parte_medio = titulo_raw.rsplit(" - ", 1)
        titulo = parte_titulo.strip()
        medio_desde_titulo = parte_medio.strip()

    medio_rss = ""
    if hasattr(entry, "source") and getattr(entry.source, "title", None):
        medio_rss = str(entry.source.title).strip()

    medio = medio_rss or medio_desde_titulo

    # Fecha
    fecha_txt = ""
    pub_parsed = getattr(entry, "published_parsed", None)

    if pub_parsed is not None:
        try:
            ts = time.mktime(pub_parsed)

            # Primero creamos en UTC
            fecha_utc = datetime.fromtimestamp(ts, tz=timezone.utc)

            # Convertimos a hora CDMX
            fecha_dt = fecha_utc.astimezone(ZoneInfo("America/Mexico_City"))

            meses = ["enero","febrero","marzo","abril","mayo","junio",
                    "julio","agosto","septiembre","octubre","noviembre","diciembre"]

            fecha_txt = f"{fecha_dt.day} de {meses[fecha_dt.month-1]} de {fecha_dt.year}"

        except Exception:
            fecha_txt = ""

    # Dominio (por si no hay medio)
    dominio = ""
    if link:
        try:
            dominio = (urlparse(link).netloc or "").replace("www.", "").strip()
        except Exception:
            dominio = ""

    partes = []
    partes.append("🚨 *ALERTA DAP | Sarampión*")
    partes.append(f"📰 {titulo}")
    if medio:
        partes.append(f"🗞 {medio}")
    elif dominio:
        partes.append(f"🗞 {dominio}")
    if fecha_txt:
        partes.append(f"📅 {fecha_txt}")
    if link:
        partes.append(f"🔗 {link}")

    texto = "\n".join(partes).strip()
    if len(texto) > 3500:
        texto = texto[:3500] + "\n…"
    return texto


def procesar_feed():
    if not RSS_URL:
        print("⚠️ Falta GOOGLE_NEWS_RSS_SARAMPION_MX. No hago nada.")
        return
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Falta TELEGRAM_BOT_TOKEN_DAP o TELEGRAM_CHAT_ID_DAP_SALUD.")
        return

    print("🔎 Revisando RSS Google News: sarampión (edición MX)…")
    feed = feedparser.parse(RSS_URL)

    if not getattr(feed, "entries", None):
        print("⚠️ El feed no trae entries.")
        return

    print(f"📚 Entradas en el feed: {len(feed.entries)}")

    hoy_cdmx = datetime.now(ZoneInfo("America/Mexico_City")).date()
    nuevas = 0

    for entry in reversed(feed.entries):
        raw_id = getattr(entry, "id", None) or getattr(entry, "link", None)
        if not raw_id:
            continue

        entry_id = f"sarampion_mx|{raw_id}"

        # Filtrar por fecha/hora para no mandar backlog
        pub_parsed = getattr(entry, "published_parsed", None)
        if pub_parsed is None:
            continue

        try:
            ts = time.mktime(pub_parsed)

            # Crear en UTC
            fecha_utc = datetime.fromtimestamp(ts, tz=timezone.utc)

            # Convertir a CDMX
            fecha_cdmx = fecha_utc.astimezone(ZoneInfo("America/Mexico_City"))

            entry_date = fecha_cdmx.date()


            from datetime import timedelta

            limite = datetime.now(MX_TZ) - timedelta(hours=6)
            if fecha_cdmx < limite:
                continue

        except Exception as e:
            print(f"⚠️ No se pudo interpretar fecha: {e}")
            continue

        if entry_id in seen_ids:
            continue

        # Enviar Telegram
        try:
            texto = formatear_alerta(entry)
            print(f"✉️ Enviando alerta nueva a Telegram: {entry_id}")
            telegram_send_message(BOT_TOKEN, CHAT_ID, texto)
        except Exception as e:
            print(f"❌ Error enviando a Telegram: {e}")
            continue

        seen_ids.add(entry_id)
        guardar_visto(entry_id)
        nuevas += 1

    if nuevas == 0:
        print("ℹ️ No hubo noticias nuevas en esta revisión.")
    else:
        print(f"✅ {nuevas} alertas nuevas enviadas.")


if __name__ == "__main__":
    print("🚀 Worker DAP: Google News → Telegram (sarampión México)")
    cargar_vistos()
    print(f"⏱ Intervalo: {CHECK_INTERVAL} segundos")
    while True:
        try:
            procesar_feed()
        except Exception as e:
            print(f"⚠️ Error en ciclo principal: {e}")
        time.sleep(CHECK_INTERVAL)


import requests
from pathlib import Path
from datetime import datetime

# === CONFIGURACIÓN ===

BASE_URL = "https://editoraveracruz.gob.mx/sigav2/front/views/cargar_pdf.php?id=GAC-{id_num}"
ESTADO_ARCHIVO = "veracruz_last_id.txt"
CARPETA_SALIDA = "gacetas_veracruz"

# Rango diario muy razonable: es difícil que haya más de 10 gacetas nuevas en un día
MAX_INTENTOS_POR_DIA = 5


def leer_ultimo_id():
    """
    Lee el último ID numérico guardado en veracruz_last_id.txt.
    Si no existe, usa un valor inicial (ajústalo SOLO la primera vez).
    """
    path = Path(ESTADO_ARCHIVO)
    if path.exists():
        try:
            valor = int(path.read_text().strip())
            print(f"[INFO] Último ID leído desde {ESTADO_ARCHIVO}: {valor}")
            return valor
        except ValueError:
            print("[ADVERTENCIA] El archivo de estado existe pero está corrupto. Usando valor inicial.")

    # Si llegas aquí es porque es la PRIMERA VEZ o el archivo está dañado.
    # OJO: ajústalo solamente una vez y luego deja que el script lo maneje solo.
    valor_inicial = 3110
    print(f"[INFO] No existe {ESTADO_ARCHIVO}. Usando ID inicial {valor_inicial}")
    return valor_inicial


def guardar_ultimo_id(id_num):
    Path(ESTADO_ARCHIVO).write_text(str(id_num), encoding="utf-8")
    print(f"[INFO] Último ID actualizado en {ESTADO_ARCHIVO}: {id_num}")


def es_respuesta_pdf(resp: requests.Response) -> bool:
    content_type = resp.headers.get("Content-Type", "").lower()
    if "pdf" in content_type:
        return True
    if len(resp.content) > 10_000 and resp.content.startswith(b"%PDF"):
        return True
    return False


def descargar_nuevas_gacetas():
    ultimo_id = leer_ultimo_id()
    carpeta = Path(CARPETA_SALIDA)
    carpeta.mkdir(parents=True, exist_ok=True)

    hoy = datetime.now().date()
    encontrados_hoy = 0
    id_actual = ultimo_id + 1

    for _ in range(MAX_INTENTOS_POR_DIA):
        url = BASE_URL.format(id_num=id_actual)
        print(f"[INFO] Probando ID {id_actual}: {url}")

        try:
            resp = requests.get(url, timeout=60)
        except requests.RequestException as e:
            print(f"[ERROR] Error de conexión con {url}: {e}")
            break

        if resp.status_code != 200:
            print(f"[INFO] Status {resp.status_code} para {url}. Asumimos que ya no hay más gacetas nuevas.")
            break

        if not es_respuesta_pdf(resp):
            print(f"[INFO] La respuesta de {url} no parece PDF. Cortamos búsqueda.")
            break

        nombre_archivo = f"GACETA_VERACRUZ_{hoy:%Y%m%d}_GAC-{id_actual}.pdf"
        ruta = carpeta / nombre_archivo
        with open(ruta, "wb") as f:
            f.write(resp.content)

        print(f"[OK] Gaceta descargada: {ruta}")
        encontrados_hoy += 1
        ultimo_id = id_actual
        id_actual += 1

    if encontrados_hoy == 0:
        print("[INFO] No se encontraron gacetas nuevas (o ya estabas al día).")
    else:
        guardar_ultimo_id(ultimo_id)
        print(f"[INFO] Total de nuevas gacetas encontradas: {encontrados_hoy}")


if __name__ == "__main__":
    descargar_nuevas_gacetas()

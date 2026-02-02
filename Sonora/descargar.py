import asyncio
from datetime import datetime
from pathlib import Path

import requests
from playwright.async_api import async_playwright

URL_SONORA = "https://congresoson.gob.mx/gacetas"


async def descargar_gaceta_sonora_ultima(carpeta_salida="gacetas_sonora"):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"[INFO] Abriendo {URL_SONORA} …")
        await page.goto(URL_SONORA, wait_until="networkidle")

        # Variable compartida para guardar la primera URL .pdf que aparezca
        pdf_url_holder = {"url": None}

        def on_request(request):
            url = request.url
            lower = url.lower()
            # Nos quedamos con la PRIMERA .pdf que veamos
            if ".pdf" in lower and pdf_url_holder["url"] is None:
                pdf_url_holder["url"] = url
                print(f"[DEBUG] Request PDF detectada: {url}")

        # Escuchamos todas las requests del contexto (todas las pestañas)
        context.on("request", on_request)

        # Selector del icono de la sesión (no el Aviso Integral)
        icono = page.locator("img[src*='IconoPdf'][alt*='Sesión']").first
        print("[INFO] Buscando icono de PDF de la sesión…")
        await icono.wait_for(state="visible", timeout=15000)

        print("[INFO] Haciendo clic en el icono de la sesión…")
        await icono.click()

        # Esperamos hasta 10 segundos a que aparezca alguna URL .pdf
        print("[INFO] Esperando a que aparezca la request del PDF…")
        for _ in range(20):  # 20 x 0.5s = 10 segundos
            if pdf_url_holder["url"] is not None:
                break
            await page.wait_for_timeout(500)

        pdf_url = pdf_url_holder["url"]
        if not pdf_url:
            raise RuntimeError("No se detectó ninguna request a un PDF después del clic.")

        print(f"[INFO] URL de la gaceta detectada: {pdf_url}")

        # Descargamos el PDF con requests
        print(f"[INFO] Descargando PDF desde: {pdf_url}")
        try:
            resp = requests.get(pdf_url, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"No se pudo descargar el PDF desde {pdf_url}: {e}")

        content_type = resp.headers.get("Content-Type", "").lower()
        print(f"[INFO] Content-Type devuelto: {content_type}")
        if "pdf" not in content_type:
            print("[ADVERTENCIA] La respuesta no parece PDF, se guardará igual para revisar.")

        carpeta = Path(carpeta_salida)
        carpeta.mkdir(parents=True, exist_ok=True)

        hoy = datetime.now().date()
        nombre_archivo = f"GACETA_SONORA_{hoy:%Y%m%d}.pdf"
        ruta = carpeta / nombre_archivo

        with open(ruta, "wb") as f:
            f.write(resp.content)

        print(f"[OK] Gaceta descargada en: {ruta}")

        await browser.close()
        return ruta


if __name__ == "__main__":
    asyncio.run(descargar_gaceta_sonora_ultima())

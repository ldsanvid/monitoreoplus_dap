import os
from datetime import datetime
import asyncio
from playwright.async_api import async_playwright

URL_GACETA = "https://data.consejeria.cdmx.gob.mx/BusquedaGaceta/"
CARPETA_SALIDA = "gaceta"
os.makedirs(CARPETA_SALIDA, exist_ok=True)

async def descargar_gaceta_cdmx():
    fecha_hoy = datetime.now().strftime("%Y%m%d")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"📄 Abriendo página: {URL_GACETA}")
        # Cargamos la página; con 'load' basta, ZK sigue jalando cosas por XHR
        await page.goto(URL_GACETA, wait_until="load", timeout=120_000)

        # Esperar a que aparezca la imagen de la Gaceta:
        # cualquier <img> con clase z-image y src que contenga 'GACETITA'
        selector = "img.z-image[src*='GACETITA']"
        print(f"🔍 Esperando selector: {selector}")
        await page.wait_for_selector(selector, timeout=120_000)

        # Hacer click y esperar la descarga
        async with page.expect_download() as download_info:
            print("🖱️ Haciendo click en la imagen de la Gaceta...")
            await page.click(selector)

        download = await download_info.value

        nombre_archivo = f"GACETA_CDMX_{fecha_hoy}.pdf"
        ruta_archivo = os.path.join(CARPETA_SALIDA, nombre_archivo)

        await download.save_as(ruta_archivo)

        print(f"✅ Gaceta descargada en: {ruta_archivo}")

        await browser.close()
        return ruta_archivo


if __name__ == "__main__":
    asyncio.run(descargar_gaceta_cdmx())
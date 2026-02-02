import os
import pandas as pd
from datetime import datetime
from pathlib import Path

from openai import OpenAI
import PyPDF2

# ------------------------------
# 🔧 Configuración
# ------------------------------

DO_INDEX_CSV = os.getenv("DO_INDEX_CSV", "do_index.csv")

# Directorios base donde guardaremos textos y resúmenes
TEXT_BASE_DIR = os.getenv("DO_TEXT_DIR", "do_textos")
SUMMARY_BASE_DIR = os.getenv("DO_SUMMARY_DIR", "do_resumenes")

OPENAI_API_KEY = "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"
if not OPENAI_API_KEY:
    raise RuntimeError("Falta la variable de entorno OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# Aseguramos que existan los directorios base
Path(TEXT_BASE_DIR).mkdir(parents=True, exist_ok=True)
Path(SUMMARY_BASE_DIR).mkdir(parents=True, exist_ok=True)


# ------------------------------
# 🧾 Funciones auxiliares
# ------------------------------

def extraer_texto_pdf(ruta_pdf: str) -> str:
    """
    Extrae texto de un PDF usando PyPDF2.
    Devuelve un string con el texto concatenado de todas las páginas.
    """
    ruta_pdf = os.path.normpath(ruta_pdf)

    if not os.path.exists(ruta_pdf):
        raise FileNotFoundError(f"No se encontró el PDF: {ruta_pdf}")

    texto_paginas = []

    with open(ruta_pdf, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        num_pages = len(reader.pages)
        for i in range(num_pages):
            try:
                page = reader.pages[i]
                txt = page.extract_text() or ""
                texto_paginas.append(txt)
            except Exception as e:
                print(f"⚠️ Error al extraer texto de la página {i} de {ruta_pdf}: {e}")

    texto_completo = "\n\n".join(texto_paginas)
    return texto_completo


def resumir_texto_normativo(texto: str, jurisdiccion: str, fecha: str, doc_id: str) -> str:
    """
    Genera un resumen normativo en bullets, factual, sin interpretación,
    a partir del texto completo del documento.
    """
    # Para no mandar textos absurdamente grandes, recortamos a cierto tamaño de caracteres
    # (ajusta si hace falta)
    max_chars = int(os.getenv("DO_MAX_CHARS", "20000"))
    texto_recortado = texto[:max_chars]

    system_msg = """
Eres un analista normativo que elabora resúmenes técnicos de diarios oficiales
y gacetas parlamentarias para un despacho de asuntos públicos.

INSTRUCCIONES
- Responde SIEMPRE en español.
- No inventes información ni añadas contexto externo.
- No expliques por qué algo es importante ni uses frases como:
  "lo que indica", "lo que podría implicar", "esto muestra que",
  "lo que refuerza", "esto evidencia", "esto sugiere", etc.
- Describe únicamente el contenido normativo del documento:
  decretos, acuerdos, reformas, lineamientos, nombramientos, etc.

FORMATO DEL RESUMEN
- Escribe de 3 a 8 bullets.
- Cada bullet:
  - Debe comenzar con "- " (guion + espacio).
  - Debe ser UNA sola oración, clara y factual.
  - Debe describir una medida, decisión, reforma o disposición concreta.
- No incluyas links ni nombres de medios.
- No cierres con conclusiones ni valoraciones.
"""

    user_msg = f"""
Elabora un resumen normativo en bullets del siguiente documento.

Metadatos:
- Jurisdicción: {jurisdiccion}
- Fecha oficial de publicación: {fecha}
- ID del documento: {doc_id}

Texto del documento (recortado si es muy largo):
\"\"\"{texto_recortado}\"\"\"
"""

    completion = client.chat.completions.create(
        model=os.getenv("DO_RESUMEN_MODEL", "gpt-4o-mini"),
        temperature=0,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    )

    resumen = completion.choices[0].message.content.strip()
    return resumen


def asegurar_directorio_para_archivo(base_dir: str, jurisdiccion: str) -> Path:
    """
    Crea (si no existe) el subdirectorio por jurisdicción dentro de base_dir
    y devuelve el Path.
    """
    dir_jur = Path(base_dir) / jurisdiccion
    dir_jur.mkdir(parents=True, exist_ok=True)
    return dir_jur


# ------------------------------
# 🧠 Proceso principal
# ------------------------------

def procesar_diarios():
    if not os.path.exists(DO_INDEX_CSV):
        raise FileNotFoundError(f"No se encontró {DO_INDEX_CSV}")

    df = pd.read_csv(DO_INDEX_CSV)

    columnas_esperadas = [
        "id", "fecha", "jurisdiccion", "pdf_path",
        "text_path", "summary_path", "status", "created_at"
    ]
    for col in columnas_esperadas:
        if col not in df.columns:
            raise ValueError(
                f"El do_index.csv debe tener la columna '{col}'. "
                f"Columnas actuales: {list(df.columns)}"
            )

    # Iteramos solo sobre filas que aún estén en estado 'raw' o sin summary_path
    for idx, row in df.iterrows():
        status = str(row.get("status", "")).strip().lower()
        text_path = row.get("text_path")
        summary_path = row.get("summary_path")

        # Ya procesado (tiene summary_path y status = summary_ready)
        if status == "summary_ready" and isinstance(summary_path, str) and summary_path.strip():
            continue

        doc_id = str(row["id"])
        fecha_str = str(row["fecha"])
        jurisdiccion = str(row["jurisdiccion"])
        pdf_dir = str(row["pdf_path"])

        print(f"\n📄 Procesando documento {doc_id} ({jurisdiccion}, {fecha_str})")

        # Ruta real del PDF: pdf_path + id
        ruta_pdf = os.path.join(pdf_dir, doc_id)
        ruta_pdf = os.path.normpath(ruta_pdf)

        try:
            texto = extraer_texto_pdf(ruta_pdf)
            if not texto.strip():
                print(f"⚠️ Texto vacío extraído de {ruta_pdf}, se omite resumen.")
                continue
        except Exception as e:
            print(f"❌ Error al extraer texto de {ruta_pdf}: {e}")
            continue

        # Guardar texto completo
        dir_textos = asegurar_directorio_para_archivo(TEXT_BASE_DIR, jurisdiccion)
        base_name = os.path.splitext(doc_id)[0]  # sin .pdf
        archivo_texto = dir_textos / f"{base_name}.txt"

        try:
            with open(archivo_texto, "w", encoding="utf-8") as f:
                f.write(texto)
        except Exception as e:
            print(f"❌ Error al guardar texto en {archivo_texto}: {e}")
            continue

        # Generar resumen normativo
        try:
            resumen = resumir_texto_normativo(texto, jurisdiccion, fecha_str, doc_id)
        except Exception as e:
            print(f"❌ Error al generar resumen para {doc_id}: {e}")
            continue

        # Guardar resumen
        dir_resumenes = asegurar_directorio_para_archivo(SUMMARY_BASE_DIR, jurisdiccion)
        archivo_resumen = dir_resumenes / f"{base_name}_resumen.txt"

        try:
            with open(archivo_resumen, "w", encoding="utf-8") as f:
                f.write(resumen)
        except Exception as e:
            print(f"❌ Error al guardar resumen en {archivo_resumen}: {e}")
            continue

        # Actualizar dataframe
        df.at[idx, "text_path"] = str(archivo_texto)
        df.at[idx, "summary_path"] = str(archivo_resumen)
        df.at[idx, "status"] = "summary_ready"

        print(f"✅ Documento procesado: {doc_id}")
        print(f"   Texto:    {archivo_texto}")
        print(f"   Resumen:  {archivo_resumen}")

    # Guardamos el índice actualizado
    df.to_csv(DO_INDEX_CSV, index=False)
    print(f"\n💾 Índice actualizado guardado en {DO_INDEX_CSV}")


if __name__ == "__main__":
    procesar_diarios()

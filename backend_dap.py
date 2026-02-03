from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS   # 👈 NUEVA LÍNEA
import os
from datetime import datetime
import pandas as pd
from openai import OpenAI


# ------------------------------
# 🚀 Configuración base
# ------------------------------

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app, resources={r"/*": {"origins": "*"}})  # 👈 Habilita CORS para todo

# Cliente OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Falta la variable de entorno OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# Orden en el que queremos mostrar las jurisdicciones
ORDEN_JURISDICCIONES = ["DOF", "SONORA", "VERACRUZ", "CDMX"]
DO_INDEX_CSV = os.getenv("DO_INDEX_CSV", "do_index.csv")

# Directorio base del proyecto (usado para armar rutas absolutas)
BASE_DIR = os.path.dirname(os.path.abspath(DO_INDEX_CSV))

# Ruta al CSV de noticias DAP
NOTICIAS_DAP_CSV = os.getenv("NOTICIAS_DAP_CSV", "noticias_dap.csv")

# Orden sugerido de temas (para que el resumen salga en un orden lógico)
ORDEN_TEMATICO = [
    "industria_alimentaria",
    "cemento",
    "gas",
    "impuesto",
    "casinos",
    "movilidad",
    "seguridad",
    "agenda nacional",
]


# ------------------------------
# 🔧 Helpers
# ------------------------------

def cargar_noticias_dap_por_fecha(fecha_str: str) -> pd.DataFrame:
    """
    Carga noticias desde noticias_dap.csv y devuelve solo las de la fecha indicada.
    - fecha_str debe venir en formato 'YYYY-MM-DD'.
    """
    if not os.path.exists(NOTICIAS_DAP_CSV):
        raise FileNotFoundError(f"No se encontró el archivo {NOTICIAS_DAP_CSV}")

    df = pd.read_csv(NOTICIAS_DAP_CSV)

    columnas_esperadas = ["fecha", "titular", "termino", "enlace", "medio"]
    for col in columnas_esperadas:
        if col not in df.columns:
            raise ValueError(
                f"El CSV de noticias DAP debe tener la columna '{col}', "
                f"pero las columnas actuales son: {list(df.columns)}"
            )

    # Normalizar fechas del CSV a date
    df["fecha_parsed"] = pd.to_datetime(
        df["fecha"], errors="coerce", dayfirst=False
    ).dt.date

    try:
        fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha debe ir en formato YYYY-MM-DD")

    noticias_dia = df[df["fecha_parsed"] == fecha_obj].copy()
    return noticias_dia


def construir_contexto_por_tema(noticias_dia: pd.DataFrame) -> str:
    """
    Construye un contexto textual donde cada línea es:
    'tema :: titular'
    agrupado por tema (termino).
    """
    if noticias_dia.empty:
        return ""

    # Aseguramos tipos correctos
    noticias_dia["termino"] = noticias_dia["termino"].astype(str)
    noticias_dia["titular"] = noticias_dia["titular"].astype(str)

    temas_presentes = list(noticias_dia["termino"].unique())

    # Reordenamos según ORDEN_TEMATICO, y luego agregamos cualquier tema extra al final
    temas_ordenados = []
    ya_agregados = set()

    for t in ORDEN_TEMATICO:
        if t in temas_presentes and t not in ya_agregados:
            temas_ordenados.append(t)
            ya_agregados.add(t)

    for t in temas_presentes:
        if t not in ya_agregados:
            temas_ordenados.append(t)
            ya_agregados.add(t)

    lineas = []
    max_contexto_por_tema = 10  # cuántos titulares máximo enviamos al modelo por tema

    for tema in temas_ordenados:
        subset = noticias_dia[noticias_dia["termino"] == tema].head(max_contexto_por_tema)
        tema_norm = tema.replace(" ", "_").lower()
        for _, row in subset.iterrows():
            titulo = row["titular"].strip()
            if titulo:
                lineas.append(f"{tema_norm} :: {titulo}")

    contexto = "\n".join(lineas)
    return contexto


def generar_resumen_noticias_dap(fecha_str: str) -> dict:
    """
    Genera el resumen en bullets por tema (sin links) para las noticias de DAP en una fecha.
    Devuelve un dict listo para jsonify.
    """
    noticias_dia = cargar_noticias_dap_por_fecha(fecha_str)

    if noticias_dia.empty:
        return {
            "fecha": fecha_str,
            "resumen": "",
            "titulares_por_tema": {},
            "error": "No hay noticias para esa fecha",
        }

    contexto = construir_contexto_por_tema(noticias_dia)

    system_msg = """
Eres un redactor técnico que elabora un resumen factual de noticias
para un despacho de asuntos públicos.

INSTRUCCIONES GENERALES
- Responde SIEMPRE en español.
- No inventes información ni añadas contexto externo.
- No expliques por qué algo es importante.
- NO uses frases como: "lo que indica", "lo que podría implicar",
  "esto muestra que", "lo que refuerza", "lo que evidencia",
  "esto sugiere que", ni variantes.
- Describe únicamente los hechos reportados en los titulares.

FORMATO OBLIGATORIO
- Escribe el resumen en bloques por tema.
- Para cada tema que tenga noticias, usa este formato:

NOMBRE_DEL_TEMA_EN_MAYÚSCULAS (sin viñeta)
- Bullet 1 describiendo un hecho concreto basado en un titular.
- Bullet 2 describiendo otro hecho concreto.
- (Máximo 4 bullets por tema)

- Cada bullet:
  - Debe comenzar con "- " (guion + espacio).
  - Debe ser una sola oración, clara y factual.
  - NO debe incluir links, ni nombres de medios, ni fechas explícitas.
  - NO debe contener juicios, interpretaciones o conclusiones.

- Respeta exactamente este formato:
NOMBRE_TEMA
- ...
- ...

SIN texto introductorio antes del primer tema.
SIN conclusiones ni frases de cierre después del último bullet.
"""

    user_msg = f"""
Genera el resumen en bullets por tema para la fecha {fecha_str}.

Cada línea del contexto tiene el formato:
tema :: titular

Contexto (titulares del día):
{contexto}
"""

    completion = client.chat.completions.create(
        model=os.getenv("DAP_RESUMEN_MODEL", "gpt-4o-mini"),
        temperature=0,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    )

    resumen_texto = completion.choices[0].message.content.strip()

    # También devolvemos las noticias crudas agrupadas por tema
    titulares_por_tema = {}
    for tema, group in noticias_dia.groupby("termino"):
        tema_norm = tema.replace(" ", "_").lower()
        titulares_por_tema[tema_norm] = []
        for _, row in group.iterrows():
            titulares_por_tema[tema_norm].append(
                {
                    "titular": str(row["titular"]).strip(),
                    "medio": str(row["medio"]).strip(),
                    "enlace": str(row["enlace"]).strip(),
                }
            )

    return {
        "fecha": fecha_str,
        "resumen": resumen_texto,
    }


# ------------------------------
# 🌐 Endpoints
# ------------------------------

@app.route("/")
def serve_frontend():
    # Sirve el archivo index.html que está en el mismo directorio que backend_dap.py
    return send_from_directory(".", "index.html")


@app.route("/health")
def health():
    # Ruta de salud para pruebas / monitoreo
    return jsonify({"status": "ok", "message": "Backend DAP MVP activo"})



@app.route("/resumen_noticias", methods=["GET"])
def resumen_noticias():
    """
    Endpoint:
      GET /resumen_noticias?fecha=YYYY-MM-DD
    """
    fecha_str = request.args.get("fecha")
    if not fecha_str:
        return jsonify({"error": "Debe especificar una fecha en formato YYYY-MM-DD"}), 400

    try:
        resultado = generar_resumen_noticias_dap(fecha_str)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # log para debug
        print("❌ Error en /resumen_noticias:", repr(e))
        return jsonify({"error": "Error interno al generar el resumen"}), 500

    # Si no hay noticias, devolvemos 404 lógico, pero con cuerpo útil
    if resultado.get("error") == "No hay noticias para esa fecha":
        return jsonify(resultado), 404

    return jsonify(resultado), 200

def cargar_diarios_por_fecha(fecha_str: str) -> pd.DataFrame:
    """
    Carga el índice normativo (do_index.csv) y devuelve solo los registros
    de la fecha indicada que ya tienen resumen generado.
    - fecha_str debe ir en formato 'YYYY-MM-DD'.
    - Filtra filas con summary_path no vacío y status = 'summary_ready' (si existe).
    """
    if not os.path.exists(DO_INDEX_CSV):
        raise FileNotFoundError(f"No se encontró el archivo {DO_INDEX_CSV}")

    df = pd.read_csv(DO_INDEX_CSV)

    columnas_esperadas = [
        "id",
        "fecha",
        "jurisdiccion",
        "pdf_path",
        "text_path",
        "summary_path",
        "status",
        "created_at",
    ]
    for col in columnas_esperadas:
        if col not in df.columns:
            raise ValueError(
                f"El do_index.csv debe tener la columna '{col}'. "
                f"Columnas actuales: {list(df.columns)}"
            )

    # Normalizar fecha
    df["fecha_parsed"] = pd.to_datetime(
        df["fecha"], errors="coerce", dayfirst=False
    ).dt.date

    try:
        fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha debe ir en formato YYYY-MM-DD")

    df_dia = df[df["fecha_parsed"] == fecha_obj].copy()

    # Nos quedamos solo con documentos que ya tienen resumen
    def tiene_resumen(row):
        status = str(row.get("status", "")).strip().lower()
        summary_path = str(row.get("summary_path", "")).strip()
        return bool(summary_path) and (status == "summary_ready" or status == "")

    if not df_dia.empty:
        df_dia = df_dia[df_dia.apply(tiene_resumen, axis=1)]

    return df_dia


def construir_contexto_diarios_por_jurisdiccion(df_dia: pd.DataFrame) -> dict:
    """
    A partir de las filas del índice de un día,
    construye un dict {jurisdiccion: texto_concatenado_de_resumenes}.
    """
    contexto_por_jurisdiccion = {}
    if df_dia.empty:
        return contexto_por_jurisdiccion

    # Aseguramos tipos
    df_dia["jurisdiccion"] = df_dia["jurisdiccion"].astype(str)
    df_dia["summary_path"] = df_dia["summary_path"].astype(str)

    # Límite de caracteres por jurisdicción para no mandar textos absurdamente grandes
    max_chars_por_jurisdiccion = int(os.getenv("DO_MAX_CHARS_RESUMENES", "24000"))

    for jurisdiccion, group in df_dia.groupby("jurisdiccion"):
        textos = []
        for _, row in group.iterrows():
            ruta_rel = str(row.get("summary_path", "")).strip()
            if not ruta_rel:
                continue

            # Normalizamos la ruta tal como viene del CSV
            ruta_resumen = os.path.normpath(ruta_rel)

            # Si es relativa, la colgamos del directorio base del proyecto
            if not os.path.isabs(ruta_resumen):
                ruta_resumen = os.path.join(BASE_DIR, ruta_resumen)

            if not os.path.exists(ruta_resumen):
                print(f"⚠️ No se encontró resumen: {ruta_resumen}")
                continue
            try:
                with open(ruta_resumen, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                if txt:
                    textos.append(txt)
            except Exception as e:
                print(f"⚠️ Error al leer resumen {ruta_resumen}: {e}")


        if not textos:
            continue

        texto_concatenado = "\n\n".join(textos)
        # Recorte por seguridad
        texto_concatenado = texto_concatenado[:max_chars_por_jurisdiccion]
        contexto_por_jurisdiccion[jurisdiccion] = texto_concatenado

    return contexto_por_jurisdiccion


def generar_resumen_diarios(fecha_str: str, jurisdiccion_filtro: str | None = None) -> dict:
    """
    Genera un resumen diario normativo por fecha.

    Si jurisdiccion_filtro es None:
        - Consolida todas las jurisdicciones (DOF, SONORA, VERACRUZ, CDMX, etc.)
    Si jurisdiccion_filtro tiene valor (ej. "VERACRUZ"):
        - Solo genera resumen para esa jurisdicción.

    Devuelve un dict listo para jsonify:
      {
        "fecha": "YYYY-MM-DD",
        "resumen": "DOF\n- ...\nSONORA\n- ...\n...",
        "error": "..." (opcional)
      }
    """
    df_dia = cargar_diarios_por_fecha(fecha_str)

    if df_dia.empty:
        return {
            "fecha": fecha_str,
            "resumen": "",
            "error": "No hay diarios oficiales para esa fecha",
        }

    contexto_por_jur = construir_contexto_diarios_por_jurisdiccion(df_dia)

    if not contexto_por_jur:
        return {
            "fecha": fecha_str,
            "resumen": "",
            "error": "No hay resúmenes normativos disponibles para esa fecha",
        }

    # Normalizamos filtro de jurisdicción (si viene)
    jurisdiccion_filtro_norm = None
    if jurisdiccion_filtro:
        jurisdiccion_filtro_norm = jurisdiccion_filtro.strip().upper()

    system_msg = """
Eres un analista normativo que elabora resúmenes diarios
de diarios oficiales y gacetas parlamentarias para un
despacho de asuntos públicos.

INSTRUCCIONES GENERALES
- Responde SIEMPRE en español.
- No inventes información ni añadas contexto externo.
- No interpretes ni evalúes impactos.
- NO uses frases como:
  "lo que indica", "lo que podría implicar",
  "esto muestra que", "esto sugiere que",
  "esto evidencia", ni variantes.

CRITERIOS EDITORIALES
- Prioriza ÚNICAMENTE disposiciones normativas de fondo:
  decretos, reformas, acuerdos con efectos generales,
  impuestos, tarifas, subsidios, expropiaciones,
  programas, lineamientos regulatorios y nombramientos relevantes.
- Ignora o resume en un solo bullet, sin detalle:
  - Procedimientos internos del Congreso
  - Convocatorias, instalación o clausura de sesiones
  - Turno o recepción de oficios
  - Edictos de cualquier tipo
  - Avisos o actos notariales
  - Publicaciones sin efectos regulatorios generales
- Si un día solo contiene contenidos procedimentales,
  edictos o actos notariales, indícalo en UNO solo bullet.

FORMATO OBLIGATORIO
- Escribe el resumen en bullets.
- Máximo 5 bullets.
- Cada bullet:
  - Debe comenzar con "- "
  - Debe ser UNA sola oración.
  - Debe describir un hecho normativo concreto.
- No incluyas links, números de tomo ni horarios
  (matutino/vespertino).

SIN introducción.
SIN conclusiones.
"""

    resumen_final_lineas = []

    # Determinar qué jurisdicciones procesar
    if jurisdiccion_filtro_norm:
        # Solo una jurisdicción
        if jurisdiccion_filtro_norm not in contexto_por_jur:
            return {
                "fecha": fecha_str,
                "resumen": "",
                "error": f"No hay diarios para la jurisdicción '{jurisdiccion_filtro_norm}' en esa fecha",
            }
        jurisdicciones_a_procesar = [jurisdiccion_filtro_norm]
    else:
        # Todas las jurisdicciones en orden fijo, luego las extra
        jurisdicciones_a_procesar = []
        ya_agregadas = set()

        for j in ORDEN_JURISDICCIONES:
            if j in contexto_por_jur and j not in ya_agregadas:
                jurisdicciones_a_procesar.append(j)
                ya_agregadas.add(j)

        for j in contexto_por_jur.keys():
            j_up = j.upper()
            if j_up not in ya_agregadas:
                jurisdicciones_a_procesar.append(j_up)
                ya_agregadas.add(j_up)

    for jurisdiccion in jurisdicciones_a_procesar:
        contexto = contexto_por_jur.get(jurisdiccion)
        if not contexto:
            continue

        user_msg = f"""
Elabora el resumen diario normativo de lo publicado en {jurisdiccion}
en la fecha {fecha_str}.

A continuación tienes la compilación de resúmenes por tomo o edición de ese día.
Reescríbelos siguiendo estrictamente las instrucciones editoriales:

\"\"\"{contexto}\"\"\"
"""

        completion = client.chat.completions.create(
            model=os.getenv("DO_RESUMEN_MODEL", "gpt-4o-mini"),
            temperature=0,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )

        resumen_jur = completion.choices[0].message.content.strip()
        if not resumen_jur:
            continue

        # Añadimos bloque con encabezado de jurisdicción
        resumen_final_lineas.append(jurisdiccion.upper())
        resumen_final_lineas.append(resumen_jur)
        resumen_final_lineas.append("")  # línea en blanco

    resumen_texto = "\n".join(resumen_final_lineas).strip()

    if not resumen_texto:
        return {
            "fecha": fecha_str,
            "resumen": "",
            "error": "No se generó contenido normativo relevante para esa fecha",
        }

    return {
        "fecha": fecha_str,
        "resumen": resumen_texto,
    }

# -----------------------------------------
# 🧠 Helpers para /pregunta
# -----------------------------------------

def detectar_intencion_pregunta(pregunta: str) -> dict:
    """
    Analiza la pregunta y devuelve un dict con:
      {
        "tipo": "noticias" | "normativo",
        "jurisdiccion": "DOF"/"SONORA"/"VERACRUZ"/"CDMX" o None,
        "termino": uno de ORDEN_TEMATICO o None
      }
    """
    p = (pregunta or "").lower()

    # Detectar jurisdicción (normativo)
    jurisdiccion = None
    if "dof" in p or "diario oficial de la federación" in p:
        jurisdiccion = "DOF"
    elif "sonora" in p:
        jurisdiccion = "SONORA"
    elif "veracruz" in p:
        jurisdiccion = "VERACRUZ"
    elif "cdmx" in p or "ciudad de méxico" in p:
        jurisdiccion = "CDMX"

    # ¿Es normativo?
    palabras_normativo = [
        "dof",
        "diario oficial",
        "gaceta",
        "congreso",
        "parlamentaria",
        "ley",
        "reforma",
    ]
    es_normativo = any(w in p for w in palabras_normativo) or jurisdiccion is not None

    # Detectar tema de noticias (termino)
    termino = None
    patrones_temas = {
        "industria_alimentaria": ["industria alimentaria", "alimentos", "alimentaria"],
        "cemento": ["cemento"],
        "gas": ["gas"],
        "impuesto": ["impuesto", "impuestos", "tributario", "fiscal"],
        "casinos": ["casino", "casinos", "juegos de azar"],
        "movilidad": ["movilidad", "transporte público", "tráfico", "transito", "tránsito"],
        "seguridad": ["seguridad", "violencia", "delincuencia"],
        "agenda nacional": ["agenda nacional", "noticias nacionales"],
    }

    for t, patrones in patrones_temas.items():
        if any(pat in p for pat in patrones):
            termino = t
            break

    tipo = "normativo" if es_normativo else "noticias"

    return {
        "tipo": tipo,
        "jurisdiccion": jurisdiccion,
        "termino": termino,
    }


def obtener_ultima_fecha_noticias() -> str | None:
    """
    Devuelve la fecha más reciente disponible en noticias_dap.csv en formato YYYY-MM-DD.
    """
    if not os.path.exists(NOTICIAS_DAP_CSV):
        return None

    df = pd.read_csv(NOTICIAS_DAP_CSV)
    if "fecha" not in df.columns:
        return None

    df["fecha_parsed"] = pd.to_datetime(
        df["fecha"], errors="coerce", dayfirst=False
    ).dt.date

    fechas = df["fecha_parsed"].dropna().unique().tolist()
    if not fechas:
        return None

    ultima = max(fechas)
    return ultima.strftime("%Y-%m-%d")


def obtener_ultima_fecha_diarios() -> str | None:
    """
    Devuelve la fecha más reciente disponible en do_index.csv (con resumen listo)
    en formato YYYY-MM-DD.
    """
    if not os.path.exists(DO_INDEX_CSV):
        return None

    df = pd.read_csv(DO_INDEX_CSV)
    if "fecha" not in df.columns:
        return None

    df["fecha_parsed"] = pd.to_datetime(
        df["fecha"], errors="coerce", dayfirst=False
    ).dt.date

    # Filtrar solo los que tienen resumen
    def tiene_resumen(row):
        status = str(row.get("status", "")).strip().lower()
        summary_path = str(row.get("summary_path", "")).strip()
        return bool(summary_path) and (status == "summary_ready" or status == "")

    df = df[df.apply(tiene_resumen, axis=1)]

    fechas = df["fecha_parsed"].dropna().unique().tolist()
    if not fechas:
        return None

    ultima = max(fechas)
    return ultima.strftime("%Y-%m-%d")

def preparar_contexto_y_fuentes_noticias(fecha_str: str, termino_filtro: str | None = None):
    """
    Carga las noticias de una fecha (y opcionalmente de un tema) y construye:
      - contexto textual para LLM
      - lista de fuentes (titular, medio, enlace, termino)
    """
    try:
        noticias_dia = cargar_noticias_dap_por_fecha(fecha_str)
    except Exception as e:
        print("⚠️ Error al cargar noticias para /pregunta:", repr(e))
        return "", []

    if termino_filtro:
        noticias_dia = noticias_dia[noticias_dia["termino"] == termino_filtro]

    if noticias_dia.empty:
        return "", []

    lineas = []
    fuentes = []

    # Limitamos número de filas para no pasarle todo al modelo
    max_noticias = int(os.getenv("MAX_NOTICIAS_PREGUNTA", "40"))
    noticias_trunc = noticias_dia.head(max_noticias)

    for _, row in noticias_trunc.iterrows():
        tema = str(row["termino"])
        titular = str(row["titular"])
        medio = str(row.get("medio", ""))
        enlace = str(row.get("enlace", ""))

        lineas.append(f"[{tema}] {titular} (medio: {medio})")

        fuentes.append({
            "tipo": "noticia",
            "fecha": fecha_str,
            "termino": tema,
            "titular": titular,
            "medio": medio,
            "enlace": enlace,
        })

    contexto = "\n".join(lineas)
    return contexto, fuentes

def preparar_contexto_y_fuentes_diarios(fecha_str: str, jurisdiccion: str | None = None):
    """
    Carga los resúmenes normativos de una fecha (y opcionalmente de una jurisdicción)
    y arma:
      - contexto textual para LLM (a partir de los resúmenes por tomo)
      - lista de fuentes (jurisdiccion, id, pdf_path)
    """
    try:
        df_dia = cargar_diarios_por_fecha(fecha_str)
    except Exception as e:
        print("⚠️ Error al cargar diarios para /pregunta:", repr(e))
        return "", []

    if df_dia.empty:
        return "", []

    if jurisdiccion:
        df_dia = df_dia[df_dia["jurisdiccion"].astype(str).str.upper() == jurisdiccion.upper()]

    if df_dia.empty:
        return "", []

    contexto_por_jur = construir_contexto_diarios_por_jurisdiccion(df_dia)

    textos = []
    fuentes = []

    if jurisdiccion and jurisdiccion in contexto_por_jur:
        textos.append(f"{jurisdiccion}:\n{contexto_por_jur[jurisdiccion]}")
        group = df_dia[df_dia["jurisdiccion"].astype(str).str.upper() == jurisdiccion.upper()]
        df_relevante = group
    else:
        # concatenar todo
        for jur, txt in contexto_por_jur.items():
            textos.append(f"{jur}:\n{txt}")
        df_relevante = df_dia

    # Fuentes: lista de documentos (no todos)
    max_docs = int(os.getenv("MAX_DIARIOS_PREGUNTA", "10"))
    for _, row in df_relevante.head(max_docs).iterrows():
        fuentes.append({
            "tipo": "diario",
            "fecha": str(row.get("fecha", fecha_str)),
            "jurisdiccion": str(row.get("jurisdiccion", "")),
            "id": str(row.get("id", "")),
            "pdf_path": str(row.get("pdf_path", "")),
        })

    contexto = "\n\n".join(textos)
    return contexto, fuentes


@app.route("/fechas_noticias", methods=["GET"])
def fechas_noticias():
    """
    Endpoint:
      GET /fechas_noticias

    Devuelve:
      {
        "fechas": ["YYYY-MM-DD", ...]
      }

    Fechas disponibles en noticias_dap.csv
    """
    CSV_NOTICIAS = os.getenv("NOTICIAS_DAP_CSV", "noticias_dap.csv")

    if not os.path.exists(CSV_NOTICIAS):
        return jsonify({"error": f"No se encontró el archivo {CSV_NOTICIAS}"}), 500

    try:
        df = pd.read_csv(CSV_NOTICIAS)
    except Exception as e:
        print("❌ Error al leer noticias_dap.csv:", repr(e))
        return jsonify({"error": "Error al leer el CSV de noticias"}), 500

    if "fecha" not in df.columns:
        return jsonify({"error": "El CSV de noticias no tiene columna 'fecha'"}), 500

    # Normalizar fechas
    df["fecha_parsed"] = pd.to_datetime(
        df["fecha"], errors="coerce", dayfirst=True
    ).dt.date

    fechas_unicas = df["fecha_parsed"].dropna().unique().tolist()

    if not fechas_unicas:
        return jsonify({"fechas": []}), 200

    fechas_ordenadas = sorted(fechas_unicas, reverse=True)
    fechas_str = [f.strftime("%Y-%m-%d") for f in fechas_ordenadas]

    return jsonify({"fechas": fechas_str}), 200

@app.route("/do_fechas", methods=["GET"])
def do_fechas():
    """
    Endpoint:
      GET /do_fechas

    Devuelve:
      {
        "fechas": ["2026-01-30", "2026-01-29", ...]
      }

    Lista de fechas para las que ya hay al menos un resumen normativo.
    """
    if not os.path.exists(DO_INDEX_CSV):
        return jsonify({"error": f"No se encontró el archivo {DO_INDEX_CSV}"}), 500

    try:
        df = pd.read_csv(DO_INDEX_CSV)
    except Exception as e:
        print("❌ Error al leer do_index.csv:", repr(e))
        return jsonify({"error": "Error al leer el índice normativo"}), 500

    # Normalizar fechas
    if "fecha" not in df.columns:
        return jsonify({"error": "El índice normativo no tiene columna 'fecha'"}), 500

    df["fecha_parsed"] = pd.to_datetime(
        df["fecha"], errors="coerce", dayfirst=False
    ).dt.date

    # Filtrar filas que ya tienen resumen
    def tiene_resumen(row):
        status = str(row.get("status", "")).strip().lower()
        summary_path = str(row.get("summary_path", "")).strip()
        return bool(summary_path) and (status == "summary_ready" or status == "")

    df = df[df.apply(tiene_resumen, axis=1)]

    if df.empty:
        return jsonify({"fechas": []}), 200

    fechas_unicas = df["fecha_parsed"].dropna().unique().tolist()
    fechas_ordenadas = sorted(fechas_unicas, reverse=True)
    fechas_str = [f.strftime("%Y-%m-%d") for f in fechas_ordenadas]

    return jsonify({"fechas": fechas_str}), 200

@app.route("/do_jurisdicciones", methods=["GET"])
def do_jurisdicciones():
    """
    Endpoint:
      GET /do_jurisdicciones
      GET /do_jurisdicciones?fecha=YYYY-MM-DD  (opcional)

    Si se pasa 'fecha':
      - Se devuelven solo jurisdicciones con resumen en esa fecha.
    Si no:
      - Se devuelven todas las jurisdicciones presentes en el índice.

    Respuesta:
      {
        "fecha": "YYYY-MM-DD" (o null),
        "jurisdicciones": ["DOF", "SONORA", "VERACRUZ", ...]
      }
    """
    fecha_str = request.args.get("fecha")

    if not os.path.exists(DO_INDEX_CSV):
        return jsonify({"error": f"No se encontró el archivo {DO_INDEX_CSV}"}), 500

    try:
        df = pd.read_csv(DO_INDEX_CSV)
    except Exception as e:
        print("❌ Error al leer do_index.csv:", repr(e))
        return jsonify({"error": "Error al leer el índice normativo"}), 500

    # Normalizar fechas
    if "fecha" not in df.columns or "jurisdiccion" not in df.columns:
        return jsonify({"error": "El índice normativo no tiene columnas necesarias"}), 500

    df["fecha_parsed"] = pd.to_datetime(
        df["fecha"], errors="coerce", dayfirst=False
    ).dt.date

    # Filtrar filas que ya tienen resumen
    def tiene_resumen(row):
        status = str(row.get("status", "")).strip().lower()
        summary_path = str(row.get("summary_path", "")).strip()
        return bool(summary_path) and (status == "summary_ready" or status == "")

    df = df[df.apply(tiene_resumen, axis=1)]

    if fecha_str:
        try:
            fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "La fecha debe ir en formato YYYY-MM-DD"}), 400

        df = df[df["fecha_parsed"] == fecha_obj]

    if df.empty:
        return jsonify({
            "fecha": fecha_str,
            "jurisdicciones": []
        }), 200

    jurisdicciones = (
        df["jurisdiccion"]
        .astype(str)
        .str.upper()
        .unique()
        .tolist()
    )
    jurisdicciones.sort()

    return jsonify({
        "fecha": fecha_str,
        "jurisdicciones": jurisdicciones
    }), 200


# -----------------------------------------
# 🌐 Endpoint: /resumen_diarios
# -----------------------------------------

@app.route("/resumen_diarios", methods=["GET"])
def resumen_diarios():
    """
    Endpoint:
      GET /resumen_diarios?fecha=YYYY-MM-DD&jurisdiccion=DOF

    Parámetros:
      - fecha: obligatorio (YYYY-MM-DD)
      - jurisdiccion: opcional (DOF, SONORA, VERACRUZ, CDMX, etc.)

    Si no se pasa 'jurisdiccion', devuelve todas las jurisdicciones disponibles.
    Si se pasa, devuelve solo esa.
    """
    fecha_str = request.args.get("fecha")
    if not fecha_str:
        return jsonify({"error": "Debe especificar una fecha en formato YYYY-MM-DD"}), 400

    jurisdiccion = request.args.get("jurisdiccion")
    if jurisdiccion:
        jurisdiccion = jurisdiccion.strip().upper()

    try:
        resultado = generar_resumen_diarios(fecha_str, jurisdiccion_filtro=jurisdiccion)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print("❌ Error en /resumen_diarios:", repr(e))
        return jsonify({"error": "Error interno al generar el resumen normativo"}), 500

    if resultado.get("error"):
        return jsonify({
            "fecha": resultado.get("fecha", fecha_str),
            "resumen": resultado.get("resumen", ""),
            "error": resultado["error"],
        }), 404

    # Solo fecha + resumen (como en /resumen_noticias)
    return jsonify({
        "fecha": resultado.get("fecha"),
        "resumen": resultado.get("resumen", ""),
    }), 200

@app.route("/jurisdicciones_disponibles", methods=["GET"])
def jurisdicciones_disponibles():
    """
    Endpoint:
      GET /jurisdicciones_disponibles?fecha=YYYY-MM-DD

    Devuelve:
      {
        "fecha": "YYYY-MM-DD",
        "jurisdicciones": ["DOF", "SONORA", "VERACRUZ"]
      }
    """
    fecha_str = request.args.get("fecha")
    if not fecha_str:
        return jsonify({"error": "Debe especificar una fecha en formato YYYY-MM-DD"}), 400

    try:
        df_dia = cargar_diarios_por_fecha(fecha_str)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print("❌ Error en /jurisdicciones_disponibles:", repr(e))
        return jsonify({"error": "Error interno al consultar jurisdicciones"}), 500

    if df_dia.empty:
        return jsonify({
            "fecha": fecha_str,
            "jurisdicciones": []
        }), 404

    jurisdicciones = sorted(df_dia["jurisdiccion"].astype(str).str.upper().unique().tolist())

    return jsonify({
        "fecha": fecha_str,
        "jurisdicciones": jurisdicciones
    }), 200

@app.route("/do_pdfs", methods=["GET"])
def do_pdfs():
    """
    Endpoint:
      GET /do_pdfs?fecha=YYYY-MM-DD&jurisdiccion=DOF

    Devuelve la lista de PDFs disponibles para esa fecha y jurisdicción,
    con una URL para descargarlos desde el servidor.
    """
    fecha_str = request.args.get("fecha")
    jurisdiccion = request.args.get("jurisdiccion")

    if not fecha_str:
        return jsonify({"error": "Debe especificar una fecha en formato YYYY-MM-DD"}), 400
    if not jurisdiccion:
        return jsonify({"error": "Debe especificar una jurisdiccion"}), 400

    jurisdiccion = str(jurisdiccion).strip().upper()

    try:
        df_dia = cargar_diarios_por_fecha(fecha_str)
    except FileNotFoundError as e:
        return jsonify({"error": str(e), "documentos": []}), 500
    except ValueError as e:
        return jsonify({"error": str(e), "documentos": []}), 400
    except Exception as e:
        print("❌ Error en do_pdfs/cargar_diarios_por_fecha:", repr(e))
        return jsonify({"error": "Error interno al leer el índice normativo", "documentos": []}), 500

    if df_dia.empty:
        return jsonify({
            "fecha": fecha_str,
            "jurisdiccion": jurisdiccion,
            "documentos": []
        }), 200

    # Filtrar por jurisdicción
    df_dia["jurisdiccion"] = df_dia["jurisdiccion"].astype(str).str.upper()
    df_jur = df_dia[df_dia["jurisdiccion"] == jurisdiccion].copy()

    if df_jur.empty:
        return jsonify({
            "fecha": fecha_str,
            "jurisdiccion": jurisdiccion,
            "documentos": []
        }), 200

    docs = []
    for _, row in df_jur.iterrows():
        doc_id = str(row.get("id", "")).strip()
        if not doc_id:
            continue

        docs.append({
            "id": doc_id,
            "nombre": doc_id,
            "jurisdiccion": jurisdiccion,
            "url": f"/descargar_pdf?id={doc_id}"
        })

    return jsonify({
        "fecha": fecha_str,
        "jurisdiccion": jurisdiccion,
        "documentos": docs
    }), 200


@app.route("/descargar_pdf", methods=["GET"])
def descargar_pdf():
    """
    Endpoint:
      GET /descargar_pdf?id=ID_DEL_DOCUMENTO

    Busca en do_index.csv el registro con ese id, arma la ruta real
    al PDF (pdf_path + id) y lo envía como archivo descargable.
    """
    doc_id = request.args.get("id")
    if not doc_id:
        return jsonify({"error": "Debe especificar el parámetro 'id'"}), 400

    if not os.path.exists(DO_INDEX_CSV):
        return jsonify({"error": f"No se encontró el archivo {DO_INDEX_CSV}"}), 500

    try:
        df = pd.read_csv(DO_INDEX_CSV)
    except Exception as e:
        print("❌ Error al leer do_index.csv en /descargar_pdf:", repr(e))
        return jsonify({"error": "Error al leer el índice normativo"}), 500

    df_id = df[df["id"].astype(str) == str(doc_id)]
    if df_id.empty:
        return jsonify({"error": f"No se encontró un registro con id={doc_id}"}), 404

    row = df_id.iloc[0]
    pdf_dir = str(row.get("pdf_path", "")).strip()
    if not pdf_dir:
        return jsonify({"error": "El índice no tiene pdf_path para este documento"}), 500

    ruta_pdf = os.path.join(pdf_dir, doc_id)
    ruta_pdf = os.path.normpath(ruta_pdf)

    if not os.path.exists(ruta_pdf):
        return jsonify({"error": f"No se encontró el PDF en {ruta_pdf}"}), 404

    try:
        return send_file(
            ruta_pdf,
            as_attachment=True,
            download_name=doc_id
        )
    except Exception as e:
        print("❌ Error al enviar PDF en /descargar_pdf:", repr(e))
        return jsonify({"error": "Error interno al enviar el PDF"}), 500


@app.route("/resumen_do", methods=["POST"])
def resumen_do():
    """
    Endpoint:
      POST /resumen_do

    Body (JSON):
      {
        "fecha": "YYYY-MM-DD",
        "jurisdiccion": "DOF" | "SONORA" | "VERACRUZ" | "CDMX" | ...
      }

    Devuelve:
      {
        "fecha": "YYYY-MM-DD",
        "jurisdiccion": "VERACRUZ",
        "resumen": "VERACRUZ\n- ...",
        "error": "..." (opcional)
      }
    """
    data = request.get_json(silent=True) or {}

    fecha_str = data.get("fecha")
    jurisdiccion = data.get("jurisdiccion")

    if not fecha_str:
        return jsonify({"error": "Debe especificar 'fecha' en el cuerpo JSON"}), 400
    if not jurisdiccion:
        return jsonify({"error": "Debe especificar 'jurisdiccion' en el cuerpo JSON"}), 400

    jurisdiccion = str(jurisdiccion).strip().upper()

    try:
        resultado = generar_resumen_diarios(fecha_str, jurisdiccion_filtro=jurisdiccion)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print("❌ Error en /resumen_do:", repr(e))
        return jsonify({"error": "Error interno al generar el resumen normativo"}), 500

    if resultado.get("error"):
        return jsonify({
            "fecha": resultado.get("fecha", fecha_str),
            "jurisdiccion": jurisdiccion,
            "resumen": resultado.get("resumen", ""),
            "error": resultado["error"],
        }), 404

    return jsonify({
        "fecha": resultado.get("fecha", fecha_str),
        "jurisdiccion": jurisdiccion,
        "resumen": resultado.get("resumen", ""),
    }), 200

@app.route("/reporte_semanal", methods=["GET"])
def reporte_semanal():
    """
    Endpoint stub para el MVP de DAP.
    Devuelve una lista (posiblemente vacía) de reportes semanales.
    Más adelante podemos hacerlo que lea PDFs de una carpeta o de S3.
    """
    # Por ahora, devolver lista vacía para que el frontend muestre
    # "No hay reportes semanales disponibles todavía."
    return jsonify([]), 200

@app.route("/pregunta", methods=["POST"])
def pregunta():
    """
    Endpoint de chatbot:

      POST /pregunta
      Body JSON:
        {
          "pregunta": "...",
          "fecha": "YYYY-MM-DD"  (opcional)
        }

    Lógica:
      - Detecta si la pregunta es sobre noticias o normativo.
      - Si no viene fecha, usa la más reciente disponible para ese tipo.
      - Construye contexto a partir de titulares o resúmenes normativos.
      - Llama a OpenAI para responder de forma estrictamente factual.
    """
    data = request.get_json(silent=True) or {}

    texto_pregunta = data.get("pregunta", "")
    fecha_str = data.get("fecha")

    if not texto_pregunta or not isinstance(texto_pregunta, str):
        return jsonify({"error": "Debe especificar el campo 'pregunta' en el cuerpo JSON"}), 400

    # Detectar intención
    intent = detectar_intencion_pregunta(texto_pregunta)
    tipo = intent["tipo"]           # "noticias" | "normativo"
    jurisdiccion = intent["jurisdiccion"]
    termino = intent["termino"]

    # Resolver fecha si no viene
    if not fecha_str:
        if tipo == "noticias":
            fecha_str = obtener_ultima_fecha_noticias()
        else:
            fecha_str = obtener_ultima_fecha_diarios()

    if not fecha_str:
        return jsonify({"error": "No se pudo determinar una fecha válida para responder la pregunta"}), 400

    # Construir contexto y fuentes según el tipo
    if tipo == "noticias":
        contexto, fuentes = preparar_contexto_y_fuentes_noticias(fecha_str, termino_filtro=termino)
        if not contexto:
            return jsonify({
                "respuesta": f"No encontré noticias relevantes para esa pregunta en la fecha {fecha_str}.",
                "fuentes": [],
                "tipo": tipo,
                "fecha": fecha_str,
            }), 200

        system_msg = """
Eres un analista que responde preguntas sobre noticias para un despacho de asuntos públicos.

INSTRUCCIONES:
- Responde SIEMPRE en español.
- Usa EXCLUSIVAMENTE la información de los titulares que se te proporcionan.
- No inventes contexto externo ni antecedentes.
- No uses frases como:
  "lo que indica", "lo que implica", "esto sugiere", "esto muestra que",
  ni saques conclusiones políticas o estratégicas.
- Puedes responder en 2 a 5 bullets si la pregunta pide un recuento.
- Sé concreto y factual.
"""

        user_msg = f"""
Pregunta del usuario:
\"\"\"{texto_pregunta}\"\"\"

Fecha de referencia: {fecha_str}

A continuación tienes titulares de noticias del día, uno por línea:
\"\"\"{contexto}\"\"\"

Responde a la pregunta usando ÚNICAMENTE lo que aparece en esos titulares.
"""

    else:  # tipo == "normativo"
        contexto, fuentes = preparar_contexto_y_fuentes_diarios(fecha_str, jurisdiccion=jurisdiccion)
        if not contexto:
            desc_jur = f" para {jurisdiccion}" if jurisdiccion else ""
            return jsonify({
                "respuesta": f"No encontré contenido normativo relevante{desc_jur} en la fecha {fecha_str}.",
                "fuentes": [],
                "tipo": tipo,
                "fecha": fecha_str,
                "jurisdiccion": jurisdiccion,
            }), 200

        system_msg = """
Eres un analista normativo que responde preguntas sobre diarios oficiales
y gacetas parlamentarias para un despacho de asuntos públicos.

INSTRUCCIONES:
- Responde SIEMPRE en español.
- Usa EXCLUSIVAMENTE la información del contexto normativo que se te proporciona.
- No inventes artículos, leyes, fechas ni antecedentes externos.
- No uses frases como:
  "lo que indica", "lo que implica", "esto sugiere", "esto muestra que".
- Describe de forma factual qué se publicó o qué medidas se adoptaron.
- Puedes responder en 2 a 5 bullets si la pregunta pide un recuento.
"""

        user_msg = f"""
Pregunta del usuario:
\"\"\"{texto_pregunta}\"\"\"

Fecha de referencia: {fecha_str}
Jurisdicción: {jurisdiccion or "todas las disponibles"}

A continuación tienes resúmenes normativos de diarios oficiales y gacetas:
\"\"\"{contexto}\"\"\"

Responde a la pregunta usando ÚNICAMENTE lo que aparece en este contexto.
"""

    # Llamada a OpenAI
    try:
        completion = client.chat.completions.create(
            model=os.getenv("PREGUNTA_MODEL", "gpt-4o-mini"),
            temperature=0,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        respuesta = completion.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Error en /pregunta al llamar a OpenAI:", repr(e))
        return jsonify({"error": "Error interno al generar la respuesta de la pregunta"}), 500

    return jsonify({
        "respuesta": respuesta,
        "fuentes": fuentes,
        "tipo": tipo,
        "fecha": fecha_str,
        "jurisdiccion": jurisdiccion,
        "termino": termino,
    }), 200


# ------------------------------
# ▶️ Main (para correr local)
# ------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)


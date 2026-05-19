"""
=============================================================================
  CONVERSOR DE EXTRACTOS BANCARIOS A EXCEL — Interfaz Gráfica
  Bancos soportados: Macro | Galicia | Santander | Bancor
=============================================================================

INSTALACIÓN (una sola vez):
  1. Instalar Python 3.10+: https://www.python.org/downloads/
     ⚠️  En la instalación, TILDAR "Add Python to PATH"
  2. Abrir una terminal (cmd) y ejecutar:
       pip install streamlit openpyxl
  3. Instalar Poppler:
       Descargar desde: https://github.com/oschwartz10612/poppler-windows/releases
       Descomprimir en C:\\poppler
       Agregar C:\\poppler\\Library\\bin al PATH del sistema
       (o C:\\poppler\\bin según la versión descargada)

USO:
  1. Abrir una terminal (cmd) en la carpeta donde está este archivo
  2. Ejecutar:  streamlit run app.py
  3. Se abre el navegador automáticamente
  4. Seleccionar banco, subir PDFs, descargar el Excel
=============================================================================
"""

import streamlit as st
import re
import os
import io
import subprocess
import tempfile
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES COMUNES
# ─────────────────────────────────────────────────────────────────────────────

def pdf_to_text(pdf_path: str, layout: bool = True) -> str:
    """Convierte un PDF a texto usando pdftotext (requiere Poppler)."""
    args = ["pdftotext"]
    if layout:
        args.append("-layout")
    args += [pdf_path, "-"]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pdftotext falló para '{pdf_path}'.\n"
            "Verificá que Poppler esté instalado y en el PATH.\n"
            f"Error: {result.stderr}"
        )
    return result.stdout or ""


def parse_num(s: str):
    """Convierte número argentino (1.234,56 o -1.234,56 o 1.234,56-) a float."""
    if not s:
        return None
    s = s.strip().replace("$", "").strip()
    trailing_neg = s.endswith("-")
    if trailing_neg:
        s = s[:-1].strip()
    negative = s.startswith("-") or trailing_neg
    s = s.lstrip("-").strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def mes_from_fecha(fecha_str: str) -> int:
    partes = fecha_str.split("/")
    return int(partes[1])


def normalizar_fecha(fecha_str: str) -> str:
    partes = fecha_str.split("/")
    if len(partes[2]) == 2:
        partes[2] = "20" + partes[2]
    return "/".join(partes)


# ─────────────────────────────────────────────────────────────────────────────
#  REGISTRO DE PARSERS
# ─────────────────────────────────────────────────────────────────────────────

PARSERS = {}


def registrar_parser(nombre_banco: str):
    def decorator(func):
        PARSERS[nombre_banco.lower()] = func
        return func
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO MACRO
# ─────────────────────────────────────────────────────────────────────────────

@registrar_parser("macro")
def parser_macro(pdf_path: str) -> list:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")
    movimientos = []
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    for line in lines:
        date_m = re.match(r"^    (\d{2}/\d{2}/\d{2})\s", line)
        if not date_m:
            continue
        fecha = normalizar_fecha(date_m.group(1))
        mes = mes_from_fecha(fecha)
        descripcion = " ".join(line[13:84].split())
        matches = [(m.start(), m.group()) for m in re_num.finditer(line)]
        if not matches:
            continue
        saldo_pos, saldo_str = matches[-1]
        if saldo_pos > 0 and line[saldo_pos - 1] == "-":
            saldo_str = "-" + saldo_str
        saldo = parse_num(saldo_str)
        debito = credito = None
        if len(matches) >= 2:
            pos2, str2 = matches[-2]
            val2 = parse_num(str2)
            if pos2 < 140:
                debito = val2
            else:
                credito = val2
            if len(matches) >= 3:
                pos3, str3 = matches[-3]
                val3 = parse_num(str3)
                if pos3 < 140 <= pos2:
                    debito = val3
                    credito = val2
        movimientos.append({
            "mes": mes, "fecha": fecha, "descripcion": descripcion,
            "debito": debito, "credito": credito, "saldo": saldo,
        })
    return movimientos


# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO GALICIA
# ─────────────────────────────────────────────────────────────────────────────

@registrar_parser("galicia")
def parser_galicia(pdf_path: str) -> list:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")

    re_fecha = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(.+)")
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}-?")

    skip_contains = [
        "Resumen de Cuenta", "Página", "Descripción", "Origen",
        "Crédito", "Débito", "Saldo", "Total", "Consolidado",
        "PERIODO COMPRENDIDO", "TOTAL ", "Importe",
    ]

    movimientos = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re_fecha.match(line)
        if not m:
            i += 1
            continue
        fecha_str = m.group(1)
        partes = fecha_str.split("/")
        fecha = f"{partes[0]}/{partes[1]}/20{partes[2]}"
        mes = int(partes[1])
        nums = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]
        if nums:
            desc_end = nums[0][0]
        else:
            desc_end = len(line)
        desc_raw = line[len(fecha_str):desc_end]
        desc_raw = re.sub(r"\b[0-9A-Z]{4}\b", "", desc_raw)
        descripcion = " ".join(desc_raw.split())
        j = i + 1
        while j < len(lines):
            next_line = lines[j]
            if not next_line.strip():
                j += 1
                continue
            if re_fecha.match(next_line):
                break
            if any(x in next_line for x in skip_contains):
                j += 1
                continue
            if re.match(r"^\s*\d{10,}", next_line.strip()):
                j += 1
                continue
            if not re_num.findall(next_line):
                descripcion += " " + " ".join(next_line.split())
            j += 1
        i = j
        if not nums:
            continue
        saldo = parse_num(nums[-1][1])
        debito = credito = None
        if len(nums) >= 2:
            val = parse_num(nums[-2][1])
            if val is not None:
                if val < 0:
                    debito = abs(val)
                else:
                    credito = val
        movimientos.append({
            "mes": mes, "fecha": fecha, "descripcion": descripcion.strip(),
            "debito": debito, "credito": credito, "saldo": saldo,
        })
    return movimientos


# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO SANTANDER
# ─────────────────────────────────────────────────────────────────────────────

@registrar_parser("santander")
def parser_santander(pdf_path: str) -> list:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")
    movimientos = []
    re_fecha_line = re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s")
    re_monto = re.compile(r"-?\$\s*[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    # ── Detectar umbrales de columna por página ──
    # Cada header "Comprobante...Débito...Crédito" define el umbral.
    # umbral = posición donde termina el header "Débito" + 2
    # (los números right-align al header, así que cualquier número que
    # empiece DESPUÉS del fin de Débito pertenece a la columna Crédito)
    page_thresholds = []  # [(line_number, umbral), ...]
    for idx, line in enumerate(lines):
        if "Comprobante" in line and "Movimiento" in line:
            pos_debito_end = line.find("bito")
            if pos_debito_end >= 0:
                pos_debito_end += 4  # end of "bito"
                umbral = pos_debito_end + 2  # pequeño margen
                page_thresholds.append((idx, umbral))

    def get_umbral(line_idx):
        """Devuelve el umbral vigente para una línea dada."""
        umbral = 105  # fallback
        for hdr_line, hdr_umbral in page_thresholds:
            if hdr_line <= line_idx:
                umbral = hdr_umbral
            else:
                break
        return umbral

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if any(x in stripped for x in [
            "Cuenta Corriente", "CBU:", "Comprobante",
            "Saldo total", "Detalle impositivo", "Tipo de impuesto",
            "Total retencion", "Importe susceptible", "Totales de",
            "Por retencion", "Por devolucion", "Legales", "Intercambio",
            "Ponemos en tu", "Garantía", "Los depósitos", "Acuerdo de giro",
            "CFTEA", "Impuestos al", "Cheques", "Depósito de cheques",
            "Aviso Importante", "Solicitud de cheques", "ECHEQs",
            "Otros", "Fondos Comunes", "Las inversiones",
            "Unidad de Información", "Tenés alguna", "Llamanos",
            "Recordá que", "No te dejes", "Banco Santander Argentina",
            "Total Retención", "Regimen de Recaudación", "en el período",
        ]):
            i += 1
            continue
        if re.match(r"^\s*\d+\s*-\s*\d+\s*$", stripped):
            i += 1
            continue
        if re.match(r"^\s*\* Salvo", stripped):
            i += 1
            continue
        m = re_fecha_line.match(line)
        if not m:
            i += 1
            continue
        fecha = normalizar_fecha(m.group(1))
        mes = mes_from_fecha(fecha)
        montos = [(mt.start(), mt.group()) for mt in re_monto.finditer(line)]
        first_dollar = line.find("$")
        if first_dollar > 0:
            desc_raw = line[len(m.group(0)):first_dollar]
        else:
            desc_raw = line[len(m.group(0)):]
        desc_raw = re.sub(r"^\s*\d+\s+", "", desc_raw, count=1)
        descripcion = " ".join(desc_raw.split())
        j = i + 1
        if j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()
            if (next_stripped
                and not re_fecha_line.match(next_line)
                and not re.match(r"^\s*\d+\s*-\s*\d+\s*$", next_stripped)
                and "Cuenta Corriente" not in next_stripped
                and "CBU:" not in next_stripped
                and "Comprobante" not in next_stripped):
                extra_montos = re_monto.findall(next_line)
                if not extra_montos:
                    descripcion += " " + " ".join(next_stripped.split())
                    j += 1
        current_line = i
        i = j
        def limpiar_monto(s):
            return s.replace("$", "").replace(" ", "").strip()
        if not montos:
            continue
        saldo = parse_num(limpiar_monto(montos[-1][1]))
        debito = credito = None
        if len(montos) >= 2:
            pos_val = montos[-2][0]
            val = parse_num(limpiar_monto(montos[-2][1]))
            umbral = get_umbral(current_line)
            if val is not None:
                if pos_val < umbral:
                    debito = abs(val)
                else:
                    credito = abs(val)
        movimientos.append({
            "mes": mes, "fecha": fecha, "descripcion": descripcion,
            "debito": debito, "credito": credito, "saldo": saldo,
        })
    return movimientos


# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCOR
# ─────────────────────────────────────────────────────────────────────────────

@registrar_parser("bancor")
def parser_bancor(pdf_path: str) -> list:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")
    anio = None
    for line in lines[:50]:
        m = re.search(r"(\d{2}/\d{2}/(\d{4}))\s+\d{2}/\d{2}/\d{4}", line)
        if m:
            anio = m.group(2)
            break
    if not anio:
        anio = "2025"
    movimientos = []
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")
    re_fecha_line = re.compile(r"^\s+(\d{2}/\d{2})\s+(.+)")
    UMBRAL_DEB_CRED = 140

    for line in lines:
        if "SALDO RES. ANTERIOR" in line:
            continue
        m = re_fecha_line.match(line)
        if not m:
            continue
        fecha_corta = m.group(1)
        fecha = f"{fecha_corta}/{anio}"
        mes = int(fecha_corta.split("/")[1])
        matches = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]
        if not matches:
            continue
        desc_match = re.match(r"^\s+\d{2}/\d{2}\s+(\d+\s+)?(.+?)\s{2,}", line)
        if desc_match:
            descripcion = desc_match.group(2).strip()
            descripcion = re.sub(r"\s+\d{4,}\s*$", "", descripcion).strip()
        else:
            first_num = re_num.search(line)
            raw = line[:first_num.start()] if first_num else line
            descripcion = re.sub(r"^\s+\d{2}/\d{2}\s+", "", raw).strip()
            descripcion = " ".join(descripcion.split())
        saldo = parse_num(matches[-1][1])
        debito = credito = None
        if len(matches) >= 2:
            pos2 = matches[-2][0]
            val2 = parse_num(matches[-2][1])
            if val2 is not None:
                if pos2 < UMBRAL_DEB_CRED:
                    debito = abs(val2)
                else:
                    credito = abs(val2)
        movimientos.append({
            "mes": mes, "fecha": fecha, "descripcion": descripcion,
            "debito": debito, "credito": credito, "saldo": saldo,
        })
    return movimientos


# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BBVA (Banco BBVA Argentina)
# ─────────────────────────────────────────────────────────────────────────────

@registrar_parser("bbva")
def parser_bbva(pdf_path: str) -> list:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")

    re_fecha = re.compile(r"^\s*(\d{2}/\d{2})\s+(.+)")
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    # ── Detectar año(s) del extracto ──
    # Buscar líneas "correspondiente al mes de: MESNAME YYYY" para mapear meses a años
    meses_nombres = {
        "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
        "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
        "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
    }
    mes_a_anio = {}
    for line in lines:
        m = re.search(r"correspondiente al mes de:\s+(\w+)\s+(\d{4})", line)
        if m:
            nombre_mes = m.group(1).upper()
            anio = int(m.group(2))
            if nombre_mes in meses_nombres:
                mes_a_anio[meses_nombres[nombre_mes]] = anio

    # Fallback: extraer del código del header (ej: 110030247202507011DIGITAL → 2025)
    anio_fallback = None
    for line in lines[:20]:
        m = re.search(r"1\d{7}(\d{4})\d{4}DIGITAL", line)
        if m:
            anio_fallback = int(m.group(1))
            break
    if not anio_fallback:
        anio_fallback = 2025

    def obtener_anio(mes_num):
        if mes_num in mes_a_anio:
            return mes_a_anio[mes_num]
        # Si no hay info, deducir del contexto: si hay meses con año conocido,
        # un mes mayor que el máximo mes conocido probablemente es del año anterior
        if mes_a_anio:
            max_mes = max(mes_a_anio.keys())
            max_anio = mes_a_anio[max_mes]
            if mes_num > max_mes:
                return max_anio - 1
            return max_anio
        return anio_fallback

    movimientos = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detener al llegar a SALDO AL o TOTAL MOVIMIENTOS
        if "SALDO AL" in stripped or "TOTAL MOVIMIENTOS" in stripped:
            break

        # Saltar headers, legales, etc.
        if not stripped:
            i += 1
            continue
        if any(x in stripped for x in [
            "FECHA", "ORIGEN", "CONCEPTO", "DÉBITO", "CRÉDITO", "SALDO",
            "SALDO ANTERIOR", "Sobre (", "Página", "Banco BBVA",
            "Resumen", "Pymes y Negocios", "Cuentas y paquetes",
            "OCASA", "TIERRA", "PRES HIPOLITO", "DIGITAL", "OCRCU",
            "Cuenta Pyme", "CONSOLIDADO", "MANTENIMIENTO", "MOVIMIENTOS",
            "BONIFICACIONES", "CUENTA DÉBITO", "Cta.Cte.Bancaria",
            "Intervinientes", "CBU ", "Sucursal gestora", "DETALLE",
            "Movimientos en cuentas", "Saldo Consolidado",
        ]):
            i += 1
            continue

        m = re_fecha.match(line)
        if not m:
            i += 1
            continue

        fecha_corta = m.group(1)  # DD/MM
        mes_num = int(fecha_corta.split("/")[1])
        anio = obtener_anio(mes_num)
        fecha = f"{fecha_corta}/{anio}"

        # Extraer números
        nums = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]

        # Descripción: texto entre ORIGEN y primer número
        if nums:
            desc_end = nums[0][0]
        else:
            desc_end = len(line)
        # Saltar fecha y origen (D 733, 474, D 500, etc.)
        resto = m.group(2)
        origen_match = re.match(r"^(D\s+)?\d{3}\s+", resto)
        if origen_match:
            desc_start = line.find(resto) + origen_match.end()
        else:
            # Sin código de origen (ej: líneas con solo "D" o vacío)
            desc_start = line.find(resto)
            # Skip leading "D " if present
            temp = line[desc_start:].lstrip()
            if temp.startswith("D "):
                desc_start = line.find(temp) + 2

        descripcion = " ".join(line[desc_start:desc_end].split())

        i += 1

        if not nums:
            continue

        # Saldo = último número
        saldo = parse_num(nums[-1][1])

        debito = credito = None
        if len(nums) >= 2:
            val = parse_num(nums[-2][1])
            if val is not None:
                if val < 0:
                    debito = abs(val)
                else:
                    credito = val

        movimientos.append({
            "mes": mes_num, "fecha": fecha, "descripcion": descripcion.strip(),
            "debito": debito, "credito": credito, "saldo": saldo,
        })

    return movimientos


# ─────────────────────────────────────────────────────────────────────────────
#  GENERADOR DE EXCEL
# ─────────────────────────────────────────────────────────────────────────────

def generar_excel(hojas: dict) -> bytes:
    """
    Recibe dict { nombre_hoja: [movimientos] }
    Devuelve el archivo Excel como bytes (para descarga).
    """
    wb = openpyxl.Workbook()
    if wb.sheetnames == ["Sheet"]:
        del wb["Sheet"]

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    data_font   = Font(name="Arial", size=9)
    alt_fill    = PatternFill("solid", fgColor="EBF3FB")
    white_fill  = PatternFill("solid", fgColor="FFFFFF")
    thin        = Side(style="thin", color="CCCCCC")
    border      = Border(left=thin, right=thin, top=thin, bottom=thin)
    num_fmt     = "#,##0.00"
    headers     = ["Nro de Mes", "Fecha", "Descripcion", "" , "Debito", "Credito", "Saldo"]
    col_widths  = [12, 14, 60, 18, 18, 20]

    for sheet_name, txs in hojas.items():
        ws = wb.create_sheet(title=sheet_name[:31])
        for col, (hdr, w) in enumerate(zip(headers, col_widths), 1):
            cell = ws.cell(row=1, column=col, value=hdr)
            cell.font      = header_font
            cell.fill      = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border    = border
            ws.column_dimensions[cell.column_letter].width = w
        ws.row_dimensions[1].height = 20
        for row_idx, tx in enumerate(txs, 2):
            fill = alt_fill if row_idx % 2 == 0 else white_fill
            valores = [
                tx["mes"], tx["fecha"], tx["descripcion"], None,
                tx["debito"], tx["credito"], tx["saldo"],
            ]
            for col, val in enumerate(valores, 1):
                cell = ws.cell(row=row_idx, column=col, value=val)
                cell.font   = data_font
                cell.fill   = fill
                cell.border = border
                if col <= 2:
                    cell.alignment = Alignment(horizontal="center")
                elif col == 3:
                    cell.alignment = Alignment(horizontal="left")
                elif col == 4:
                    pass  # columna vacía, no hacer nada
                else:
                    cell.alignment = Alignment(horizontal="right")
                    if val is not None:
                        cell.number_format = num_fmt
        ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
#  VERIFICAR QUE POPPLER ESTÁ INSTALADO
# ─────────────────────────────────────────────────────────────────────────────

def poppler_disponible() -> bool:
    try:
        result = subprocess.run(
            ["pdftotext", "-v"],
            capture_output=True, text=True,
        )
        return True
    except FileNotFoundError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  INTERFAZ GRÁFICA (Streamlit)
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Conversor de Extractos Bancarios",
        page_icon="🏦",
        layout="centered",
    )

    # ── Estilos ──
    st.markdown("""
    <style>
        .stApp { max-width: 800px; margin: 0 auto; }
        div[data-testid="stFileUploader"] {
            border: 2px dashed #1F4E79;
            border-radius: 10px;
            padding: 10px;
        }
        .success-box {
            background: rgba(76, 175, 80, 0.15);
            border-left: 4px solid #4caf50;
            color: inherit;;
            padding: 12px 16px;
            border-radius: 4px;
            margin: 8px 0;
        }
        .info-box {
            background: rgba(31, 78, 121, 0.15);
            border-left: 4px solid #1F4E79;
            color: inherit;
            padding: 12px 16px;
            border-radius: 4px;
            margin: 8px 0;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("sg.jpg", width=150)
    with col2:
        st.title("Conversor de Extractos Bancarios")
        st.caption("Convertí extractos bancarios en PDF a Excel — Macro, Galicia, Santander, Bancor")

    # ── Verificar Poppler ──
    if not poppler_disponible():
        st.error(
            "⚠️ **Poppler no está instalado o no está en el PATH.**\n\n"
            "Este programa necesita `pdftotext` (parte de Poppler) para leer PDFs.\n\n"
            "**Instalación en Windows:**\n"
            "1. Descargar desde: [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases)\n"
            "2. Descomprimir en `C:\\poppler`\n"
            "3. Agregar `C:\\poppler\\Library\\bin` al PATH del sistema\n"
            "4. Reiniciar esta terminal y volver a ejecutar"
        )
        st.stop()

    # ── Estado de sesión para acumular hojas ──
    if "hojas" not in st.session_state:
        st.session_state.hojas = {}

    st.divider()

    # ── Formulario para agregar una hoja ──
    st.subheader("📄 Agregar extracto")

    col1, col2 = st.columns(2)
    with col1:
        banco = st.selectbox(
            "Banco",
            options=list(PARSERS.keys()),
            format_func=lambda x: "BBVA" if x.lower() == "bbva" else x.capitalize(),
        )
    with col2:
        nombre_hoja = st.text_input(
            "Nombre de la hoja",
            max_chars=31,
        )

    archivos = st.file_uploader(
        "Subí los PDFs del extracto",
        type=["pdf"],
        accept_multiple_files=True,
        help="Podés subir varios PDFs del mismo banco/cuenta. Se acumulan en la misma hoja.",
    )

    if st.button("➕ Agregar hoja", type="primary", use_container_width=True):
        if not nombre_hoja.strip():
            st.warning("Ingresá un nombre para la hoja.")
        elif not archivos:
            st.warning("Subí al menos un PDF.")
        else:
            parser = PARSERS[banco]
            todos_movs = []
            errores = []

            progress = st.progress(0, text="Procesando PDFs...")
            for idx, archivo in enumerate(archivos):
                try:
                    # Guardar PDF temporalmente para que pdftotext lo lea
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(archivo.read())
                        tmp_path = tmp.name

                    movs = parser(tmp_path)
                    todos_movs.extend(movs)
                    os.unlink(tmp_path)

                except Exception as e:
                    errores.append(f"{archivo.name}: {e}")
                finally:
                    progress.progress(
                        (idx + 1) / len(archivos),
                        text=f"Procesando {archivo.name}..."
                    )

            progress.empty()

            if errores:
                for err in errores:
                    st.error(f"❌ {err}")

            if todos_movs:
                # Ordenar cronológicamente (stable sort preserva orden interno de cada PDF)
                def fecha_sort_key(m):
                    partes = m["fecha"].split("/")
                    return (int(partes[2]), int(partes[1]), int(partes[0]))
                todos_movs.sort(key=fecha_sort_key)

                sheet_name = nombre_hoja.strip()[:31]
                st.session_state.hojas[sheet_name] = todos_movs
                st.markdown(
                    f'<div class="success-box">✅ <strong>{sheet_name}</strong>: '
                    f'{len(todos_movs):,} movimientos de {len(archivos)} PDF(s)</div>',
                    unsafe_allow_html=True,
                )
            elif not errores:
                st.warning("No se encontraron movimientos en los PDFs subidos.")

    # ── Hojas acumuladas ──
    if st.session_state.hojas:
        st.divider()
        st.subheader("📊 Hojas en el Excel")

        for nombre, movs in st.session_state.hojas.items():
            debitos = sum(1 for m in movs if m["debito"] is not None)
            creditos = sum(1 for m in movs if m["credito"] is not None)
            saldo_final = movs[-1]["saldo"] if movs else 0

            col_info, col_del = st.columns([5, 1])
            with col_info:
                st.markdown(
                    f'<div class="info-box">'
                    f'<strong>{nombre}</strong><br>'
                    f'{len(movs):,} movimientos &nbsp;·&nbsp; '
                    f'{debitos:,} débitos &nbsp;·&nbsp; '
                    f'{creditos:,} créditos &nbsp;·&nbsp; '
                    f'Saldo final: {saldo_final:,.2f}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_del:
                st.write("")  # Espaciado
                if st.button("🗑️", key=f"del_{nombre}", help=f"Quitar {nombre}"):
                    del st.session_state.hojas[nombre]
                    st.rerun()

        # ── Botón de descarga ──
        st.divider()

        nombre_archivo = st.text_input(
            "Nombre del archivo Excel",
            value="extractos_bancarios.xlsx",
        )
        if not nombre_archivo.endswith(".xlsx"):
            nombre_archivo += ".xlsx"

        col_dl, col_clear = st.columns([3, 1])
        with col_dl:
            excel_bytes = generar_excel(st.session_state.hojas)
            st.download_button(
                label=f"⬇️ Descargar Excel ({len(st.session_state.hojas)} hojas)",
                data=excel_bytes,
                file_name=nombre_archivo,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )
        with col_clear:
            if st.button("🔄 Limpiar", use_container_width=True, help="Borrar todas las hojas"):
                st.session_state.hojas = {}
                st.rerun()

    # ── Footer ──
    st.divider()
    st.caption(
        "Bancos soportados: Macro · Galicia · Santander · Bancor &nbsp;|&nbsp; "
        "Requiere Poppler instalado"
    )


if __name__ == "__main__":
    main()
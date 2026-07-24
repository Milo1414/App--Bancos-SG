# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES COMUNES
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import stat
import sys
import subprocess
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
#  RESOLUCIÓN DE LOS EJECUTABLES pdftotext
#
#  La app usa DOS motores distintos, y no son intercambiables:
#
#   · `-table`  → sólo existe en **Xpdf**. Es el que alinea bien las columnas
#                 Débito/Crédito/Saldo de Galicia, Santander, Bancor, BBVA,
#                 Nación y MacroV2. En Linux se usa el binario incluido en el
#                 repo (bin/pdftotext), porque el pdftotext de Poppler que
#                 traen los servidores no soporta `-table`.
#
#   · `-layout` → se usa **Poppler**. El `-layout` de Xpdf, sobre los extractos
#                 de MacroV1, directamente PIERDE la columna de importes en
#                 buena parte de las filas (se queda sólo con el saldo), así
#                 que Macro no reconcilia. El de Poppler los conserva.
#
#  Por eso cada modo resuelve su propio ejecutable en vez de compartir uno.
# ─────────────────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))

# Candidatos para el binario Xpdf (el que soporta -table).
_XPDF_CANDIDATOS = [
    os.path.join(_HERE, "bin", "pdftotext"),          # bundle Linux (Streamlit Cloud)
    os.path.join(_HERE, "bin", "pdftotext.exe"),      # bundle Windows (opcional)
    r"C:\Program Files\Git\mingw64\bin\pdftotext.exe",
    r"C:\xpdf\bin64\pdftotext.exe",
    r"C:\xpdf\bin32\pdftotext.exe",
]

_cache_cmd = {}


def _soporta_table(exe: str) -> bool:
    """True si `exe` entiende la opción -table (o sea, si es Xpdf)."""
    try:
        salida = subprocess.run(
            [exe, "-h"], capture_output=True, text=True, errors="replace"
        )
    except OSError:
        return False
    # `-h` imprime el listado de opciones: sólo el de Xpdf incluye '-table'.
    return "-table" in (salida.stdout + salida.stderr)


def _asegurar_ejecutable(ruta: str) -> None:
    """git no siempre preserva el bit +x del binario incluido en el repo."""
    try:
        modo = os.stat(ruta).st_mode
        os.chmod(ruta, modo | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _cmd_table() -> str:
    """Ejecutable Xpdf (soporta -table). Lanza RuntimeError si no hay ninguno."""
    if "table" in _cache_cmd:
        return _cache_cmd["table"]

    for ruta in _XPDF_CANDIDATOS:
        if os.path.exists(ruta):
            if not sys.platform.startswith("win"):
                _asegurar_ejecutable(ruta)
            if _soporta_table(ruta):
                _cache_cmd["table"] = ruta
                return ruta

    # Último recurso: el pdftotext del PATH, si resultara ser Xpdf.
    if _soporta_table("pdftotext"):
        _cache_cmd["table"] = "pdftotext"
        return "pdftotext"

    raise RuntimeError(
        "No se encontró un pdftotext de Xpdf (el único que soporta '-table').\n"
        "El pdftotext de Poppler NO sirve para este modo.\n"
        "Descargalo de https://www.xpdfreader.com/download.html y dejá el "
        "ejecutable en la carpeta 'bin/' de esta aplicación."
    )


def _cmd_layout() -> str:
    """Ejecutable Poppler (para -layout). Se toma el pdftotext del PATH."""
    return _cache_cmd.setdefault("layout", "pdftotext")


def _pdftotext_cmd(table: bool = False) -> str:
    """Devuelve la ruta al ejecutable pdftotext que corresponde al modo pedido."""
    return _cmd_table() if table else _cmd_layout()


def pdf_to_text(pdf_path: str, layout: bool = True, table: bool = False) -> str:
    """Convierte un PDF a texto usando pdftotext.

    modo:
      - table=True   → 'pdftotext -table' con Xpdf (Galicia, Santander, Bancor,
                       BBVA, Nación, MacroV2).
      - layout=True  → 'pdftotext -layout' con Poppler (MacroV1).
    """
    args = [_pdftotext_cmd(table=table)]
    if table:
        args.append("-table")
    elif layout:
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
        motor = "Xpdf (bin/pdftotext)" if table else "Poppler (pdftotext del PATH)"
        raise RuntimeError(
            f"pdftotext falló para '{os.path.basename(pdf_path)}' usando {motor}.\n"
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


_RE_SALDO_INICIAL = re.compile(r"saldo\s+(?:res\.?\s+)?(?:anterior|inicial)", re.IGNORECASE)
_RE_MONTO_SALDO   = re.compile(r"-?\$?\s*\d{1,3}(?:\.\d{3})*,\d{2}-?")


def extraer_saldo_inicial(lines):
    """
    Busca la línea de 'Saldo Anterior' / 'Saldo Inicial' del extracto y devuelve
    el último importe de esa línea (que es el saldo), o None si no la encuentra.
    Es el saldo inicial que informa el banco; se usa como semilla para la fila
    'SALDO INICIAL' del Excel. (Galicia no la rotula → devuelve None.)
    """
    for line in lines:
        if _RE_SALDO_INICIAL.search(line):
            nums = _RE_MONTO_SALDO.findall(line)
            if nums:
                return parse_num(nums[-1])
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
#  DIAGNÓSTICO POR PARSER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Diagnostico:
    total_lineas: int = 0
    lineas_con_fecha: int = 0
    movimientos_parseados: int = 0
    lineas_descartadas: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
#  VERIFICAR QUE ESTÁN LOS DOS MOTORES DE pdftotext
# ─────────────────────────────────────────────────────────────────────────────

def motores_faltantes() -> list:
    """Devuelve los motores de pdftotext que faltan: 'poppler' y/o 'xpdf'."""
    faltan = []
    try:
        subprocess.run([_cmd_layout(), "-v"], capture_output=True, text=True)
    except OSError:
        faltan.append("poppler")
    try:
        _cmd_table()
    except RuntimeError:
        faltan.append("xpdf")
    return faltan


def poppler_disponible() -> bool:
    return "poppler" not in motores_faltantes()

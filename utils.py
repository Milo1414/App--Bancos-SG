# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES COMUNES
# ─────────────────────────────────────────────────────────────────────────────

import re
import subprocess
from dataclasses import dataclass, field


def pdf_to_text(pdf_path: str, layout: bool = True, table: bool = False) -> str:
    """Convierte un PDF a texto usando pdftotext (Xpdf/Poppler).

    modo:
      - table=True   → 'pdftotext -table' (optimizado para tablas: alinea bien
                       las columnas Débito/Crédito/Saldo de los extractos que
                       -layout desalinea, ej. Bancor, Nación, Santander).
      - layout=True  → 'pdftotext -layout' (por defecto; el resto de los bancos).
    """
    args = ["pdftotext"]
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

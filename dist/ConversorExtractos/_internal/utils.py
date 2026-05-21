# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES COMUNES
# ─────────────────────────────────────────────────────────────────────────────

import os
import subprocess
import sys
from dataclasses import dataclass, field


def get_pdftotext_path() -> str:
    """
    Resuelve la ruta absoluta del binario pdftotext.

    Orden de búsqueda:
      1. Carpeta del ejecutable/script + poppler/ (bundleado con PyInstaller)
      2. poppler_bin/ relativa al script (desarrollo local sin PATH)
      3. PATH del sistema (fallback, para compatibilidad actual)
    """
    # Base dir: en bundleado PyInstaller está en sys._MEIPASS; en desarrollo, la carpeta de este archivo
    if hasattr(sys, '_MEIPASS'):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    bin_name = "pdftotext.exe" if sys.platform == "win32" else "pdftotext"

    # 1. Bundleado (PyInstaller onedir / onefile)
    bundled = os.path.join(base_dir, "poppler", bin_name)
    if os.path.isfile(bundled):
        return bundled

    # 2. Desarrollo local (carpeta poppler_bin junto al proyecto)
    local = os.path.join(base_dir, "poppler_bin", bin_name)
    if os.path.isfile(local):
        return local

    # 3. Fallback: asumir que está en el PATH del sistema
    return "pdftotext"


def pdf_to_text(pdf_path: str, layout: bool = True) -> str:
    """Convierte un PDF a texto usando pdftotext (requiere Poppler)."""
    args = [get_pdftotext_path()]
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
        subprocess.run(
            [get_pdftotext_path(), "-v"],
            capture_output=True, text=True,
        )
        return True
    except FileNotFoundError:
        return False

# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO GALICIA
# ─────────────────────────────────────────────────────────────────────────────
#
#  Se usa `pdftotext -table` (no -layout): con -layout Galicia desalinea las
#  columnas y arrastra texto legal como si fuera movimiento. Con -table cada
#  movimiento queda en UNA línea: FECHA  DESCRIPCION  IMPORTE  SALDO, y todo
#  reconcilia. Galicia imprime el Débito con signo negativo y el Crédito
#  positivo, así que se clasifica por el signo del propio importe.

import re
from utils import pdf_to_text, parse_num
from parsers import registrar_parser


# Importe del bloque "Saldos" del encabezado (con $ y posible '-' final).
_RE_MONTO_HEADER = re.compile(r"\$\s*-?\d{1,3}(?:\.\d{3})*,\d{2}-?")


def _extraer_saldo_inicial(lines):
    """El saldo de apertura de Galicia no se rotula 'Saldo Anterior': aparece en
    el bloque 'Saldos' del encabezado como el PRIMER importe $X.XXX,XX- antes de
    la sección 'Movimientos' (ej. $20.205,41-)."""
    for line in lines:
        if line.strip() == "Movimientos":
            break
        m = _RE_MONTO_HEADER.search(line)
        if m:
            return parse_num(m.group())
    return None


@registrar_parser("galicia")
def parser_galicia(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, table=True)
    lines = text.split("\n")

    re_fecha = re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s")
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}-?")
    # Ruido a no adjuntar como descripción: códigos (R5321U...), CUIT, números largos.
    re_codigo = re.compile(r"^[A-Z0-9]{6,}$")

    skip_contains = [
        "Resumen de Cuenta", "Página", "P�gina", "Descripci", "Origen",
        "Crédito", "Cr�dito", "Débito", "D�bito", "Saldo",
        "Fecha", "CBU", "Número de cuenta", "N�mero de cuenta",
    ]

    movimientos = []
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))

    saldo_inicial = _extraer_saldo_inicial(lines)

    en_movimientos = False
    fin = False
    for line in lines:
        if fin:
            break
        s = line.strip()
        if s == "Movimientos":
            en_movimientos = True
            continue
        if not en_movimientos:
            continue
        # Fin de la sección de movimientos → evita arrastrar totales / texto legal.
        if s.startswith("Total") or "Consolidado" in s:
            fin = True
            break

        m = re_fecha.match(line)
        if not m:
            # Línea de continuación → adjuntar a la descripción del último mov.
            if (movimientos and s
                    and not re_num.search(line)
                    and not any(x in line for x in skip_contains)
                    and not re_codigo.match(s)):
                movimientos[-1]["descripcion"] = (
                    movimientos[-1]["descripcion"] + " " + " ".join(s.split())
                ).strip()
            continue

        diagnostico.lineas_con_fecha += 1
        partes = m.group(1).split("/")
        fecha = f"{partes[0]}/{partes[1]}/20{partes[2]}"
        mes = int(partes[1])

        nums = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]
        if len(nums) < 2:
            diagnostico.lineas_descartadas.append({
                "linea_idx": 0,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue

        # Descripción: texto entre la fecha y el primer número.
        desc = line[m.end(1):nums[0][0]]
        descripcion = " ".join(desc.split())

        saldo = parse_num(nums[-1][1])
        val = parse_num(nums[-2][1])
        debito = credito = None
        if val is not None:
            if val < 0:
                debito = abs(val)
            else:
                credito = val

        movimientos.append({
            "mes": mes, "fecha": fecha, "descripcion": descripcion,
            "debito": debito, "credito": credito, "saldo": saldo,
        })
        diagnostico.movimientos_parseados += 1

    if saldo_inicial is not None:
        for mv in movimientos:
            mv["saldo_inicial"] = saldo_inicial

    return movimientos, diagnostico

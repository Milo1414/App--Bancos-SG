# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO MACRO — FORMATO V2 ("Últimos Movimientos")
# ─────────────────────────────────────────────────────────────────────────────
#
#  Formato distinto al de MacroV1: una tabla con columnas
#     Fecha | Nro. de Referencia | Causal | Concepto | Importe | Saldo
#  El "Importe" es un único monto CON signo: el débito viene negativo y el
#  crédito positivo, así que se clasifica por el signo del propio importe
#  (igual que Galicia/BBVA). Se usa `pdftotext -table`: cada movimiento queda
#  en UNA sola línea y las columnas quedan alineadas (con -layout se corren la
#  Referencia y el Importe a la fila de al lado). Verificado Diferencia=0 en
#  los 164 movimientos del extracto de ejemplo (4 páginas).
#
#  Notas:
#   - La fecha usa año de 4 dígitos (31/03/2026).
#   - Referencia y Causal son siempre numéricas y son los dos primeros tokens
#     tras la fecha; el Concepto es el texto entre la Causal y el primer '$'
#     (puede ser puramente numérico, ej. un CBU/identificador).
#   - El extracto lista los movimientos de MÁS NUEVO a más viejo (31/03 arriba,
#     02/03 abajo). Se devuelven invertidos (cronológico, más viejo primero)
#     para que el saldo arrastrado del Excel reconcilie también DENTRO de cada
#     día (el orden del banco solo se conserva estable por fecha en la app).
#   - No hay fila "Saldo Anterior": el saldo inicial lo deriva el Excel del
#     primer movimiento (el más antiguo).

import re
from utils import pdf_to_text, parse_num, mes_from_fecha, normalizar_fecha, Diagnostico
from parsers import registrar_parser


@registrar_parser("macrov2")
def parser_macrov2(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, table=True)
    lines = text.split("\n")
    movimientos = []
    diagnostico = Diagnostico(total_lineas=len(lines))

    re_fecha = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s")
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    for line_idx, line in enumerate(lines):
        m = re_fecha.match(line)
        if not m:
            continue

        diagnostico.lineas_con_fecha += 1
        fecha = normalizar_fecha(m.group(1))
        mes = mes_from_fecha(fecha)

        nums = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]
        if len(nums) < 2:
            diagnostico.lineas_descartadas.append({
                "linea_idx": line_idx,
                "contenido": line[:120],
                "motivo": "sin importe/saldo",
            })
            continue

        # Descripción = Concepto: se descartan los dos primeros tokens tras la
        # fecha (Referencia y Causal) y se toma el texto hasta el primer importe.
        rest = line[m.end():nums[0][0]]
        toks = rest.split()
        descripcion = " ".join(toks[2:]) if len(toks) > 2 else " ".join(toks)

        # Importe (anteúltimo monto) con signo → débito(-) / crédito(+).
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

    # El extracto viene de más nuevo a más viejo → invertir a cronológico.
    movimientos.reverse()
    return movimientos, diagnostico

# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCOR
# ─────────────────────────────────────────────────────────────────────────────
#
#  Se usa `pdftotext -table` (no -layout): en Bancor -layout desplaza el importe
#  a la línea del movimiento anterior. Con -table cada movimiento queda en UNA
#  línea: FECHA  DESCRIPCION  IMPORTE  SALDO, y los saldos reconcilian.
#
#  Débito vs Crédito: Bancor NO imprime encabezado de columnas y, además, las
#  columnas se corren entre páginas, así que clasificar por posición x no es
#  confiable (rompe en extractos con créditos). El importe SIEMPRE se lee tal
#  cual del PDF; para decidir en qué columna va se usa el signo del cambio de
#  saldo respecto de la fila anterior: si el saldo sube es Crédito, si baja es
#  Débito (definición contable). La columna "Diferencia" del Excel sigue siendo
#  el verificador: usa el importe leído (no el delta), así que si el importe
#  impreso no coincide con el movimiento del saldo, la diferencia lo delata.

import re
from utils import pdf_to_text, parse_num, extraer_saldo_inicial
from parsers import registrar_parser


@registrar_parser("bancor")
def parser_bancor(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, table=True)
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
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")
    re_fecha_line = re.compile(r"^\s+(\d{2}/\d{2})\s+(.+)")

    # Saldo inicial informado (SALDO RES. ANTERIOR): semilla para clasificar el
    # primer movimiento por el signo del cambio de saldo.
    saldo_ini = extraer_saldo_inicial(lines)
    saldo_prev = saldo_ini

    for line_idx, line in enumerate(lines):
        if "SALDO RES. ANTERIOR" in line:
            continue
        m = re_fecha_line.match(line)
        if not m:
            continue
        diagnostico.lineas_con_fecha += 1
        fecha_corta = m.group(1)
        fecha = f"{fecha_corta}/{anio}"
        mes = int(fecha_corta.split("/")[1])
        matches = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]
        if not matches:
            diagnostico.lineas_descartadas.append({
                "linea_idx": line_idx,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue
        # Descripción: texto entre la fecha y el primer número.
        first_num_pos = matches[0][0]
        descripcion = re.sub(r"^\s*\d{2}/\d{2}\s+", "", line[:first_num_pos]).strip()
        descripcion = " ".join(descripcion.split())

        saldo = parse_num(matches[-1][1])
        debito = credito = None
        if len(matches) >= 2:
            val2 = parse_num(matches[-2][1])
            if val2 is not None:
                importe = abs(val2)
                # Clasificar por el signo del cambio de saldo (Crédito sube,
                # Débito baja). Si no hay saldo previo, se asume Débito.
                if saldo_prev is not None and saldo is not None and saldo >= saldo_prev:
                    credito = importe
                else:
                    debito = importe
        if saldo is not None:
            saldo_prev = saldo
        movimientos.append({
            "mes": mes, "fecha": fecha, "descripcion": descripcion,
            "debito": debito, "credito": credito, "saldo": saldo,
        })
        diagnostico.movimientos_parseados += 1

    if saldo_ini is not None:
        for m in movimientos:
            m["saldo_inicial"] = saldo_ini

    return movimientos, diagnostico

# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO MACRO
# ─────────────────────────────────────────────────────────────────────────────

import re
from utils import pdf_to_text, parse_num, mes_from_fecha, normalizar_fecha, extraer_saldo_inicial
from parsers import registrar_parser


@registrar_parser("macro")
def parser_macro(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")
    movimientos = []
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    for line_idx, line in enumerate(lines):
        date_m = re.match(r"^    (\d{2}/\d{2}/\d{2})\s", line)
        if not date_m:
            continue
        diagnostico.lineas_con_fecha += 1
        fecha = normalizar_fecha(date_m.group(1))
        mes = mes_from_fecha(fecha)
        descripcion = " ".join(line[13:84].split())
        matches = [(m.start(), m.group()) for m in re_num.finditer(line)]
        if not matches:
            diagnostico.lineas_descartadas.append({
                "linea_idx": line_idx,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
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
        diagnostico.movimientos_parseados += 1
    saldo_ini = extraer_saldo_inicial(lines)
    if saldo_ini is not None:
        for m in movimientos:
            m["saldo_inicial"] = saldo_ini

    return movimientos, diagnostico

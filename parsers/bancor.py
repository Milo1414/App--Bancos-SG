# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCOR
# ─────────────────────────────────────────────────────────────────────────────

import re
from utils import pdf_to_text, parse_num
from parsers import registrar_parser


@registrar_parser("bancor")
def parser_bancor(pdf_path: str) -> tuple:
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
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")
    re_fecha_line = re.compile(r"^\s+(\d{2}/\d{2})\s+(.+)")
    UMBRAL_DEB_CRED = 140

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
        diagnostico.movimientos_parseados += 1
    return movimientos, diagnostico

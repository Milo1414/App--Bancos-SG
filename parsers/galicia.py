# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO GALICIA
# ─────────────────────────────────────────────────────────────────────────────

import re
from utils import pdf_to_text, parse_num
from parsers import registrar_parser


@registrar_parser("galicia")
def parser_galicia(pdf_path: str) -> tuple:
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
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re_fecha.match(line)
        if not m:
            i += 1
            continue
        diagnostico.lineas_con_fecha += 1
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
        linea_fecha_idx = i
        i = j
        if not nums:
            diagnostico.lineas_descartadas.append({
                "linea_idx": linea_fecha_idx,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
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
        diagnostico.movimientos_parseados += 1
    return movimientos, diagnostico

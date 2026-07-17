# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO SANTANDER
# ─────────────────────────────────────────────────────────────────────────────
#
#  Se usa `pdftotext -table` (no -layout): con -layout Santander desplaza el
#  importe a la línea anterior (por eso el crédito real de $5.300.000 caía sobre
#  la fila "Saldo Inicial"). Con -table cada movimiento queda en UNA línea:
#  FECHA [COMPROB] DESCRIPCION  DEBITO|CREDITO  SALDO, y todo reconcilia.

import re
from utils import pdf_to_text, parse_num, mes_from_fecha, normalizar_fecha, extraer_saldo_inicial
from parsers import registrar_parser


@registrar_parser("santander")
def parser_santander(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, table=True)
    lines = text.split("\n")
    movimientos = []
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))
    re_fecha_line = re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s")
    re_monto = re.compile(r"-?\$\s*[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    # ── Umbral de columna Débito|Crédito por página ──
    # El header "... Débito ... Crédito ... Saldo" define la frontera: cualquier
    # importe que empiece después del fin de "Débito" pertenece a Crédito.
    page_thresholds = []
    for idx, line in enumerate(lines):
        if "bito" in line and "dito" in line and "Saldo" in line:
            pos_debito_end = line.find("bito")
            if pos_debito_end >= 0:
                umbral = pos_debito_end + 4 + 2  # fin de "Débito" + margen
                page_thresholds.append((idx, umbral))

    def get_umbral(line_idx):
        umbral = 96  # fallback (calibrado sobre los PDF de ejemplo)
        for hdr_line, hdr_umbral in page_thresholds:
            if hdr_line <= line_idx:
                umbral = hdr_umbral
            else:
                break
        return umbral

    def limpiar_monto(s):
        return s.replace("$", "").replace(" ", "").strip()

    # Palabras que marcan líneas que no son movimientos (cabeceras/secciones).
    SKIP = [
        "Cuenta Corriente", "CBU:", "Comprobante", "Movimiento",
        "Total en pesos", "Total en", "Salvo error", "Resumen de",
    ]

    fin = False
    for i, line in enumerate(lines):
        if fin:
            break
        stripped = line.strip()
        if not stripped:
            continue

        # Fin de la sección de movimientos.
        if "Detalle impositivo" in stripped or "Tasas de Acuerdos" in stripped:
            fin = True
            break

        m = re_fecha_line.match(line)
        if not m:
            # Línea de continuación → se adjunta a la descripción del último
            # movimiento (datos de comprobante / contraparte). Nunca lleva $.
            if (movimientos
                    and "$" not in stripped
                    and not any(x in stripped for x in SKIP)):
                movimientos[-1]["descripcion"] = (
                    movimientos[-1]["descripcion"] + " " + " ".join(stripped.split())
                ).strip()
            continue

        # Línea con fecha al inicio.
        # La fila "Saldo Inicial" NO es un movimiento (es el saldo semilla).
        if "Saldo Inicial" in line:
            continue

        diagnostico.lineas_con_fecha += 1
        fecha = normalizar_fecha(m.group(1))
        mes = mes_from_fecha(fecha)

        montos = [(mt.start(), mt.group()) for mt in re_monto.finditer(line)]
        first_dollar = line.find("$")
        if first_dollar > 0:
            desc_raw = line[len(m.group(0)):first_dollar]
        else:
            desc_raw = line[len(m.group(0)):]
        desc_raw = re.sub(r"^\s*\d+\s+", "", desc_raw, count=1)  # quita comprobante
        descripcion = " ".join(desc_raw.split())

        if not montos:
            diagnostico.lineas_descartadas.append({
                "linea_idx": i,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue

        saldo = parse_num(limpiar_monto(montos[-1][1]))
        debito = credito = None
        if len(montos) >= 2:
            pos_val = montos[-2][0]
            val = parse_num(limpiar_monto(montos[-2][1]))
            umbral = get_umbral(i)
            if val is not None:
                if pos_val < umbral:
                    debito = abs(val)
                else:
                    credito = abs(val)
        movimientos.append({
            "mes": mes, "fecha": fecha, "descripcion": descripcion,
            "debito": debito, "credito": credito, "saldo": saldo,
        })
        diagnostico.movimientos_parseados += 1

    saldo_ini = extraer_saldo_inicial(lines)
    if saldo_ini is not None:
        for mv in movimientos:
            mv["saldo_inicial"] = saldo_ini

    return movimientos, diagnostico

# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO SANTANDER
# ─────────────────────────────────────────────────────────────────────────────

import re
from utils import pdf_to_text, parse_num, mes_from_fecha, normalizar_fecha
from parsers import registrar_parser


@registrar_parser("santander")
def parser_santander(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")
    movimientos = []
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))
    re_fecha_line = re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s")
    re_monto = re.compile(r"-?\$\s*[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    # ── Detectar umbrales de columna por página ──
    # Cada header "Comprobante...Débito...Crédito" define el umbral.
    # umbral = posición donde termina el header "Débito" + 2
    # (los números right-align al header, así que cualquier número que
    # empiece DESPUÉS del fin de Débito pertenece a la columna Crédito)
    page_thresholds = []  # [(line_number, umbral), ...]
    for idx, line in enumerate(lines):
        if "Comprobante" in line and "Movimiento" in line:
            pos_debito_end = line.find("bito")
            if pos_debito_end >= 0:
                pos_debito_end += 4  # end of "bito"
                umbral = pos_debito_end + 2  # pequeño margen
                page_thresholds.append((idx, umbral))

    def get_umbral(line_idx):
        """Devuelve el umbral vigente para una línea dada."""
        umbral = 105  # fallback
        for hdr_line, hdr_umbral in page_thresholds:
            if hdr_line <= line_idx:
                umbral = hdr_umbral
            else:
                break
        return umbral

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if any(x in stripped for x in [
            "Cuenta Corriente", "CBU:", "Comprobante",
            "Saldo total", "Detalle impositivo", "Tipo de impuesto",
            "Total retencion", "Importe susceptible", "Totales de",
            "Por retencion", "Por devolucion", "Legales", "Intercambio",
            "Ponemos en tu", "Garantía", "Los depósitos", "Acuerdo de giro",
            "CFTEA", "Impuestos al", "Cheques", "Depósito de cheques",
            "Aviso Importante", "Solicitud de cheques", "ECHEQs",
            "Otros", "Fondos Comunes", "Las inversiones",
            "Unidad de Información", "Tenés alguna", "Llamanos",
            "Recordá que", "No te dejes", "Banco Santander Argentina",
            "Total Retención", "Regimen de Recaudación", "en el período",
        ]):
            i += 1
            continue
        if re.match(r"^\s*\d+\s*-\s*\d+\s*$", stripped):
            i += 1
            continue
        if re.match(r"^\s*\* Salvo", stripped):
            i += 1
            continue
        m = re_fecha_line.match(line)
        if not m:
            i += 1
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
        desc_raw = re.sub(r"^\s*\d+\s+", "", desc_raw, count=1)
        descripcion = " ".join(desc_raw.split())
        j = i + 1
        if j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()
            if (next_stripped
                and not re_fecha_line.match(next_line)
                and not re.match(r"^\s*\d+\s*-\s*\d+\s*$", next_stripped)
                and "Cuenta Corriente" not in next_stripped
                and "CBU:" not in next_stripped
                and "Comprobante" not in next_stripped):
                extra_montos = re_monto.findall(next_line)
                if not extra_montos:
                    descripcion += " " + " ".join(next_stripped.split())
                    j += 1
        current_line = i
        i = j
        def limpiar_monto(s):
            return s.replace("$", "").replace(" ", "").strip()
        if not montos:
            diagnostico.lineas_descartadas.append({
                "linea_idx": current_line,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue
        saldo = parse_num(limpiar_monto(montos[-1][1]))
        debito = credito = None
        if len(montos) >= 2:
            pos_val = montos[-2][0]
            val = parse_num(limpiar_monto(montos[-2][1]))
            umbral = get_umbral(current_line)
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
    return movimientos, diagnostico

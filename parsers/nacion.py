# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO NACION
# ─────────────────────────────────────────────────────────────────────────────

import re
from utils import pdf_to_text, parse_num, normalizar_fecha, mes_from_fecha, Diagnostico, extraer_saldo_inicial
from parsers import registrar_parser


@registrar_parser("nacion")
def parser_nacion(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, table=True)
    lines = text.split("\n")

    # Detect year from PERIODO line
    anio = None
    for line in lines[:50]:
        m = re.search(r"PERIODO:\s+\d{2}/\d{2}/(\d{4})\s+AL", line)
        if m:
            anio = m.group(1)
            break
    if not anio:
        anio = "2025"

    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}-?")
    # Nota: -table a veces antepone '____' en el margen izquierdo (sin correr
    # las columnas), por eso el regex acepta [\s_]* al inicio.
    re_fecha_line = re.compile(r"^[\s_]*(\d{2}/\d{2}/\d{2})\s+(.+)")

    # Dynamic threshold detection from header lines
    page_thresholds = []
    for idx, line in enumerate(lines):
        if "DEBITOS" in line and "CREDITOS" in line:
            pos_deb_end = line.find("DEBITOS") + len("DEBITOS")
            pos_cred_start = line.find("CREDITOS")
            umbral = (pos_deb_end + pos_cred_start) // 2
            page_thresholds.append((idx, umbral))

    def get_umbral(line_idx):
        umbral = 85
        for start_idx, u in page_thresholds:
            if line_idx >= start_idx:
                umbral = u
        return umbral

    movimientos = []
    diagnostico = Diagnostico(total_lineas=len(lines))

    # El umbral de columnas que informa el encabezado no siempre alcanza: Nación
    # imprime los créditos empezando unos caracteres a la IZQUIERDA de donde
    # arranca el título "CREDITOS", así que los créditos grandes caen del lado
    # del débito y se clasifican mal. El criterio confiable es el propio saldo:
    # es un saldo acumulado, así que el signo de (saldo − saldo_anterior) dice
    # si el movimiento sumó o restó. La posición queda sólo como respaldo para
    # cuando no hay saldo previo o el delta no coincide con el importe.
    saldo_previo = extraer_saldo_inicial(lines)

    for line_idx, line in enumerate(lines):
        m = re_fecha_line.match(line)
        if not m:
            continue

        if "SALDO ANTERIOR" in line or "SALDO FINAL" in line:
            continue

        diagnostico.lineas_con_fecha += 1
        fecha_corta = m.group(1)
        fecha = normalizar_fecha(fecha_corta)
        mes = mes_from_fecha(fecha)

        matches = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]
        if not matches:
            diagnostico.lineas_descartadas.append({
                "linea_idx": line_idx,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue

        # Description: text between date and first amount, strip trailing comprobante
        desc_start = m.start(2)
        first_amt_pos = matches[0][0]
        raw_desc = line[desc_start:first_amt_pos]
        raw_desc = re.sub(r"\s+\d+\s*$", "", raw_desc).strip()
        descripcion = " ".join(raw_desc.split())

        saldo = parse_num(matches[-1][1])
        debito = credito = None
        if len(matches) >= 2:
            pos2 = matches[-2][0]
            val2 = parse_num(matches[-2][1])
            if val2 is not None:
                importe = abs(val2)
                es_credito = None

                # 1º criterio: variación del saldo acumulado.
                if saldo_previo is not None and saldo is not None:
                    delta = round(saldo - saldo_previo, 2)
                    if abs(abs(delta) - importe) <= 0.01:
                        es_credito = delta > 0

                # 2º criterio (respaldo): posición respecto de las columnas.
                if es_credito is None:
                    es_credito = pos2 >= get_umbral(line_idx)

                if es_credito:
                    credito = importe
                else:
                    debito = importe

        if saldo is not None:
            saldo_previo = saldo

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

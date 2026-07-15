# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BBVA (Banco BBVA Argentina)
# ─────────────────────────────────────────────────────────────────────────────

import re
from utils import pdf_to_text, parse_num
from parsers import registrar_parser


@registrar_parser("bbva")
def parser_bbva(pdf_path: str) -> tuple:
    text = pdf_to_text(pdf_path, layout=True)
    lines = text.split("\n")

    re_fecha = re.compile(r"^\s*(\d{2}/\d{2})\s+(.+)")
    re_num   = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    # Detecta inicio de sección de cuenta:
    # "CC $ 267-015530/5 (Cta.Cte.Bancaria) - Iva-Responsable Inscripto"
    # "CC U$S 267-401531/5 (Cta.Cte.Bancaria) - Iva-Responsable Inscripto"
    re_cuenta = re.compile(
        r"CC\s+[\$U\$S]+\s+([\d\-]+/\d+)\s+\(Cta\.Cte\.Bancaria\)\s+-\s+Iva",
        re.IGNORECASE,
    )

    # ── Detectar año(s) del extracto ──
    meses_nombres = {
        "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
        "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
        "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
    }
    mes_a_anio = {}
    for line in lines:
        m = re.search(r"correspondiente al mes de:\s+(\w+)\s+(\d{4})", line)
        if m:
            nombre_mes = m.group(1).upper()
            anio = int(m.group(2))
            if nombre_mes in meses_nombres:
                mes_a_anio[meses_nombres[nombre_mes]] = anio

    # Fallback: extraer del código del header (ej: 110046746202510011DIGITAL → 2025)
    anio_fallback = None
    for line in lines[:20]:
        m = re.search(r"1\d{7}(\d{4})\d{4}DIGITAL", line)
        if m:
            anio_fallback = int(m.group(1))
            break
    if not anio_fallback:
        anio_fallback = 2025

    def obtener_anio(mes_num):
        if mes_num in mes_a_anio:
            return mes_a_anio[mes_num]
        if mes_a_anio:
            max_mes  = max(mes_a_anio.keys())
            max_anio = mes_a_anio[max_mes]
            if mes_num > max_mes:
                return max_anio - 1
            return max_anio
        return anio_fallback

    # ── Extraer descripción de una línea de movimiento ──
    def extraer_descripcion(line, resto, desc_end):
        """
        Formato: DD/MM   [D [NNN]]   CONCEPTO...   [-DEBITO]   [CREDITO]   SALDO
        ORIGEN puede ser: vacío, 'D', 'D NNN' (NNN = 3 dígitos: 100, 500, etc.)
        """
        origen_re = re.match(r"^(D(?:\s+\d{3})?\s+)", resto)
        if origen_re:
            desc_start = line.find(resto) + origen_re.end()
        else:
            desc_start = line.find(resto)
        return " ".join(line[desc_start:desc_end].split())

    movimientos = []
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))

    cuenta_activa = None  # número de cuenta actual (ej: "267-015530/5")
    fin_extracto  = False
    saldo_ini_por_cuenta = {}  # cuenta → saldo anterior (saldo inicial) informado

    SKIP = [
        "FECHA", "ORIGEN", "CONCEPTO", "DÉBITO", "CRÉDITO",
        "SALDO ANTERIOR", "SALDO AL", "TOTAL MOVIMIENTOS",
        "Sobre (", "Página", "Banco BBVA",
        "Resumen", "Pymes y Negocios", "Cuentas y paquetes",
        "OCASA", "TIERRA", "PRES HIPOLITO", "DIGITAL", "OCRCU",
        "Cuenta Pyme", "CONSOLIDADO", "MANTENIMIENTO", "MOVIMIENTOS",
        "BONIFICACIONES", "CUENTA DÉBITO", "Cta.Cte.Bancaria",
        "Intervinientes", "CBU ", "Sucursal gestora", "DETALLE",
        "Movimientos en cuentas", "Saldo Consolidado",
        "Impuesto a los", "TOTAL COBRADO", "TOTAL DEV", "IMP. NETO",
        "RETENIDO", "El credito de impuesto", "REGIMEN SISTEMA",
        "Ver Legales",
    ]

    for i, line in enumerate(lines):
        if fin_extracto:
            break

        stripped = line.strip()

        # ── Marcadores de fin de sección de movimientos ──
        # "Transferencias" y "Legales y avisos" aparecen siempre después de
        # todos los movimientos reales; todo lo que sigue son datos auxiliares.
        if stripped in ("Transferencias", "Legales y avisos"):
            fin_extracto = True
            break

        # ── Detectar cambio de sección de cuenta ──
        mc = re_cuenta.search(stripped)
        if mc:
            cuenta_activa = mc.group(1)
            continue

        # Saltear líneas sin cuenta activa (cabecera del PDF)
        if cuenta_activa is None:
            continue

        # Saltear cuenta en dólares (no la procesamos)
        if cuenta_activa.startswith("401"):
            continue

        # Saltear vacías
        if not stripped:
            continue

        # Capturar el saldo anterior (saldo inicial) informado por cada cuenta,
        # antes de que el filtro SKIP descarte la línea.
        if "SALDO ANTERIOR" in stripped and cuenta_activa not in saldo_ini_por_cuenta:
            nums_sa = re_num.findall(line)
            if nums_sa:
                saldo_ini_por_cuenta[cuenta_activa] = parse_num(nums_sa[-1])

        # Saltear headers, legales, totales y otras líneas no-movimiento
        if any(x in stripped for x in SKIP):
            continue

        m = re_fecha.match(line)
        if not m:
            continue

        fecha_corta = m.group(1)

        # Saltar la fila especial "00/00 SIN MOVIMIENTOS"
        if fecha_corta == "00/00":
            continue

        diagnostico.lineas_con_fecha += 1

        mes_num = int(fecha_corta.split("/")[1])
        anio    = obtener_anio(mes_num)
        fecha   = f"{fecha_corta}/{anio}"
        resto   = m.group(2)

        nums = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]

        if not nums:
            diagnostico.lineas_descartadas.append({
                "linea_idx": i,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue

        descripcion = extraer_descripcion(line, resto, nums[0][0])

        # Regla: el ÚLTIMO número es SALDO.
        # De los anteriores: negativo → DÉBITO, positivo → CRÉDITO.
        saldo   = parse_num(nums[-1][1])
        debito  = None
        credito = None
        for _, raw in nums[:-1]:
            val = parse_num(raw)
            if val is None:
                continue
            if val < 0:
                debito  = abs(val)
            else:
                credito = val

        movimientos.append({
            "mes":         mes_num,
            "fecha":       fecha,
            "descripcion": descripcion,
            "debito":      debito,
            "credito":     credito,
            "saldo":       saldo,
            "cuenta":      cuenta_activa,
        })
        diagnostico.movimientos_parseados += 1

    # Etiquetar cada movimiento con el saldo inicial informado de SU cuenta
    # (cada cuenta se exporta como una hoja aparte).
    for m in movimientos:
        si = saldo_ini_por_cuenta.get(m["cuenta"])
        if si is not None:
            m["saldo_inicial"] = si

    return movimientos, diagnostico
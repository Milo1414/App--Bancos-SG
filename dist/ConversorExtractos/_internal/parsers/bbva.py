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
    re_num = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})*,\d{2}")

    # ── Detectar año(s) del extracto ──
    # Buscar líneas "correspondiente al mes de: MESNAME YYYY" para mapear meses a años
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

    # Fallback: extraer del código del header (ej: 110030247202507011DIGITAL → 2025)
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
        # Si no hay info, deducir del contexto: si hay meses con año conocido,
        # un mes mayor que el máximo mes conocido probablemente es del año anterior
        if mes_a_anio:
            max_mes = max(mes_a_anio.keys())
            max_anio = mes_a_anio[max_mes]
            if mes_num > max_mes:
                return max_anio - 1
            return max_anio
        return anio_fallback

    movimientos = []
    from utils import Diagnostico
    diagnostico = Diagnostico(total_lineas=len(lines))
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detener al llegar a SALDO AL o TOTAL MOVIMIENTOS
        if "SALDO AL" in stripped or "TOTAL MOVIMIENTOS" in stripped:
            break

        # Saltar headers, legales, etc.
        if not stripped:
            i += 1
            continue
        if any(x in stripped for x in [
            "FECHA", "ORIGEN", "CONCEPTO", "DÉBITO", "CRÉDITO", "SALDO",
            "SALDO ANTERIOR", "Sobre (", "Página", "Banco BBVA",
            "Resumen", "Pymes y Negocios", "Cuentas y paquetes",
            "OCASA", "TIERRA", "PRES HIPOLITO", "DIGITAL", "OCRCU",
            "Cuenta Pyme", "CONSOLIDADO", "MANTENIMIENTO", "MOVIMIENTOS",
            "BONIFICACIONES", "CUENTA DÉBITO", "Cta.Cte.Bancaria",
            "Intervinientes", "CBU ", "Sucursal gestora", "DETALLE",
            "Movimientos en cuentas", "Saldo Consolidado",
        ]):
            i += 1
            continue

        m = re_fecha.match(line)
        if not m:
            i += 1
            continue

        diagnostico.lineas_con_fecha += 1
        fecha_corta = m.group(1)  # DD/MM
        mes_num = int(fecha_corta.split("/")[1])
        anio = obtener_anio(mes_num)
        fecha = f"{fecha_corta}/{anio}"

        # Extraer números
        nums = [(mt.start(), mt.group()) for mt in re_num.finditer(line)]

        # Descripción: texto entre ORIGEN y primer número
        if nums:
            desc_end = nums[0][0]
        else:
            desc_end = len(line)
        # Saltar fecha y origen (D 733, 474, D 500, etc.)
        resto = m.group(2)
        origen_match = re.match(r"^(D\s+)?\d{3}\s+", resto)
        if origen_match:
            desc_start = line.find(resto) + origen_match.end()
        else:
            # Sin código de origen (ej: líneas con solo "D" o vacío)
            desc_start = line.find(resto)
            # Skip leading "D " if present
            temp = line[desc_start:].lstrip()
            if temp.startswith("D "):
                desc_start = line.find(temp) + 2

        descripcion = " ".join(line[desc_start:desc_end].split())

        i += 1

        if not nums:
            diagnostico.lineas_descartadas.append({
                "linea_idx": i - 1,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue

        # Saldo = último número
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
            "mes": mes_num, "fecha": fecha, "descripcion": descripcion.strip(),
            "debito": debito, "credito": credito, "saldo": saldo,
        })
        diagnostico.movimientos_parseados += 1

    return movimientos, diagnostico

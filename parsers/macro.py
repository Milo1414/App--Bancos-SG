# ─────────────────────────────────────────────────────────────────────────────
#  PARSER: BANCO MACRO — FORMATO V1 ("Resumen General" / DETALLE DE MOVIMIENTO)
# ─────────────────────────────────────────────────────────────────────────────
#
#  Formato de tabla:
#     FECHA | DESCRIPCION | REFERENCIA | DEBITOS | CREDITOS | SALDO
#
#  Motor: primero `pdftotext -table` de Xpdf. En los extractos de 2026, el
#  `-layout` (de Xpdf o de Poppler) sale desarmado: los importes quedan en
#  líneas aparte y corridos respecto de su fila. Con `-table` cada fila trae
#  completa su fecha, su descripción, su importe y su saldo.
#  Respaldo: extractos anteriores reconciliaban con el `-layout` de Poppler.
#  Si con `-table` quedan líneas descartadas o el saldo no encadena, se prueba
#  Poppler y se queda el resultado con menos problemas.
#
#  Dirección (débito o crédito): `-table` no respeta la columna de cada fila
#  (un mismo importe puede quedar más a la izquierda o más a la derecha según
#  la página), así que la dirección se decide por el SALDO: si el saldo de la
#  fila es el anterior más el importe es un crédito; si es el anterior menos
#  el importe, un débito. Sólo cuando esa cuenta no cierra (falta el saldo
#  anterior o el banco imprimió el día en otro orden) se usa la posición del
#  importe respecto del encabezado "FECHA ... DEBITOS ... CREDITOS ... SALDO".
#
#  Un mismo PDF trae VARIAS cuentas (ej. "CUENTA CORRIENTE ESPECIAL EN PESOS",
#  "CUENTA CORRIENTE BANCARIA" y la de DOLARES). Cada movimiento se etiqueta
#  con su cuenta para que la app arme una hoja por cuenta: si se mezclaran,
#  el saldo arrastrado saltaría al cambiar de cuenta y "Diferencia" no cerraría.
#  La cuenta en DOLARES se descarta (misma criterio que BBVA).

import re
from utils import pdf_to_text, parse_num, mes_from_fecha, normalizar_fecha, Diagnostico
from parsers import registrar_parser


# "CUENTA CORRIENTE ESPECIAL EN PESOS NRO.: 4-399-0950295930-2"
# "CAJA DE AHORRO EN PESOS NRO.: 4-399-0000000001-1"
_RE_CUENTA = re.compile(r"^\s*((?:CUENTA|CAJA\s+DE\s+AHORROS?)\s+.*?)\s+NRO\.:\s+(\S+)",
                        re.IGNORECASE)
_TOLERANCIA = 0.011  # centavos de redondeo al comparar saldos
_RE_SALDO_ULT = re.compile(r"SALDO\s+ULTIMO\s+EXTRACTO\s+AL\s+\d{2}/\d{2}/\d{4}", re.IGNORECASE)
_RE_FECHA = re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s")
_RE_NUM = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}")


def _columnas(line: str):
    """Bordes derechos de DEBITOS / CREDITOS / SALDO en la línea de encabezado."""
    fin_deb = line.find("DEBITOS")
    fin_cred = line.find("CREDITOS")
    fin_saldo = line.find("SALDO")
    if fin_deb < 0 or fin_cred < 0 or fin_saldo < 0:
        return None
    return (
        fin_deb + len("DEBITOS"),
        fin_cred + len("CREDITOS"),
        fin_saldo + len("SALDO"),
    )


@registrar_parser("macro")
def parser_macro(pdf_path: str) -> tuple:
    resultado = _parsear_texto(pdf_to_text(pdf_path, table=True))
    problemas = _problemas(*resultado)
    if problemas:
        try:
            respaldo = _parsear_texto(pdf_to_text(pdf_path, layout=True))
        except (OSError, RuntimeError):
            return resultado  # sin Poppler: queda el resultado de Xpdf
        if _problemas(*respaldo) < problemas:
            return respaldo
    return resultado


def _problemas(movimientos, diagnostico) -> int:
    """Líneas descartadas + filas cuyo saldo no encadena con la anterior de su cuenta."""
    saltos = 0
    anterior = {}
    for m in movimientos:
        base = anterior.get(m["cuenta"], m.get("saldo_inicial"))
        if base is not None and m["saldo"] is not None and abs(
                base + (m["credito"] or 0) - (m["debito"] or 0) - m["saldo"]) > _TOLERANCIA:
            saltos += 1
        anterior[m["cuenta"]] = m["saldo"]
    return len(diagnostico.lineas_descartadas) + saltos


def _parsear_texto(text: str) -> tuple:
    lines = text.split("\n")
    movimientos = []
    diagnostico = Diagnostico(total_lineas=len(lines))

    cols = None            # (fin_debitos, fin_creditos, fin_saldo)
    cuenta_activa = None
    cuenta_es_usd = False
    saldo_ini_por_cuenta = {}
    ultimo_saldo = {}      # cuenta → último saldo visto (para filas sin saldo)

    for line_idx, line in enumerate(lines):
        # ── Encabezado de columnas: fija/actualiza las posiciones ──
        if "DEBITOS" in line and "CREDITOS" in line and "SALDO" in line:
            nuevas = _columnas(line)
            if nuevas:
                cols = nuevas
            continue

        # ── Cambio de cuenta ──
        mc = _RE_CUENTA.match(line)
        if mc:
            cuenta_activa = mc.group(2)
            cuenta_es_usd = "DOLAR" in mc.group(1).upper()
            continue

        # ── Saldo inicial que informa el banco para la cuenta activa ──
        if _RE_SALDO_ULT.search(line):
            if cuenta_activa and cuenta_activa not in saldo_ini_por_cuenta:
                nums = _RE_NUM.findall(line)
                if nums:
                    saldo_ini_por_cuenta[cuenta_activa] = parse_num(nums[-1])
            continue

        m = _RE_FECHA.match(line)
        if not m:
            continue

        if cuenta_es_usd:
            continue  # la cuenta en dólares no se procesa (no entra al diagnóstico)

        diagnostico.lineas_con_fecha += 1

        if cols is None:
            diagnostico.lineas_descartadas.append({
                "linea_idx": line_idx,
                "contenido": line[:120],
                "motivo": "sin encabezado de columnas",
            })
            continue

        fin_deb, fin_cred, fin_saldo = cols
        corte_deb_cred = (fin_deb + fin_cred) / 2
        corte_cred_saldo = (fin_cred + fin_saldo) / 2

        montos = [(mt.end(), mt.group()) for mt in _RE_NUM.finditer(line)]
        if not montos:
            diagnostico.lineas_descartadas.append({
                "linea_idx": line_idx,
                "contenido": line[:120],
                "motivo": "sin montos",
            })
            continue

        debito = credito = saldo = None
        anterior = ultimo_saldo.get(cuenta_activa, saldo_ini_por_cuenta.get(cuenta_activa))
        valores = [parse_num(raw) for _, raw in montos]
        if len(valores) >= 2 and None not in valores[-2:] and anterior is not None:
            # Importe + saldo: el saldo dice la dirección.
            importe, saldo = abs(valores[-2]), valores[-1]
            delta = saldo - anterior
            if abs(delta - importe) <= _TOLERANCIA:
                credito = importe
            elif abs(delta + importe) <= _TOLERANCIA:
                debito = importe
            else:
                saldo = None  # no cierra: se decide por posición

        if debito is None and credito is None:
            # Respaldo: cada monto cae en la columna cuyo borde derecho tiene más cerca.
            saldo = None
            for fin, raw in montos:
                val = parse_num(raw)
                if val is None:
                    continue
                if fin > corte_cred_saldo:
                    saldo = val
                elif fin > corte_deb_cred:
                    credito = abs(val)
                else:
                    debito = abs(val)

        if debito is None and credito is None:
            diagnostico.lineas_descartadas.append({
                "linea_idx": line_idx,
                "contenido": line[:120],
                "motivo": "sin débito ni crédito",
            })
            continue

        fecha = normalizar_fecha(m.group(1))

        # Descripción: texto entre la fecha y el primer importe, sin el token
        # final de REFERENCIA (siempre numérico: "737280595", "0", …).
        primer_monto = min(mt.start() for mt in _RE_NUM.finditer(line))
        tokens = line[m.end():primer_monto].split()
        if len(tokens) > 1 and tokens[-1].isdigit():
            tokens = tokens[:-1]
        descripcion = " ".join(tokens)

        # Macro no imprime el saldo en todas las filas: se arrastra el anterior.
        if saldo is None:
            base = ultimo_saldo.get(cuenta_activa)
            if base is None:
                base = saldo_ini_por_cuenta.get(cuenta_activa)
            if base is not None:
                saldo = round(base + (credito or 0) - (debito or 0), 2)
        if saldo is not None:
            ultimo_saldo[cuenta_activa] = saldo

        movimientos.append({
            "mes": mes_from_fecha(fecha), "fecha": fecha, "descripcion": descripcion,
            "debito": debito, "credito": credito, "saldo": saldo,
            "cuenta": cuenta_activa,
        })
        diagnostico.movimientos_parseados += 1

    for mv in movimientos:
        si = saldo_ini_por_cuenta.get(mv["cuenta"])
        if si is not None:
            mv["saldo_inicial"] = si

    movimientos = _ordenar_por_saldo(movimientos, saldo_ini_por_cuenta)
    return movimientos, diagnostico


def _ordenar_por_saldo(movimientos, saldo_ini_por_cuenta):
    """Reordena los movimientos de un mismo día para que el saldo encadene.

    Cuando dos movimientos de la misma fecha caen en páginas distintas, Macro
    a veces los imprime en un orden que no es el del saldo (el saldo de la
    segunda fila es el que da pie al de la primera). Los importes y los saldos
    son correctos; sólo está invertido el orden. Se reordena cada grupo de
    misma fecha eligiendo, paso a paso, la fila cuyo saldo encadena con el
    saldo acumulado. Si un grupo no encadena, se deja tal como vino.
    """
    resultado = []
    i = 0
    saldo_actual = {}
    while i < len(movimientos):
        cuenta = movimientos[i]["cuenta"]
        fecha = movimientos[i]["fecha"]
        j = i
        while (j < len(movimientos)
               and movimientos[j]["cuenta"] == cuenta
               and movimientos[j]["fecha"] == fecha):
            j += 1
        grupo = movimientos[i:j]

        base = saldo_actual.get(cuenta, saldo_ini_por_cuenta.get(cuenta))
        if base is not None and len(grupo) > 1:
            pendientes = list(grupo)
            ordenado = []
            corriente = base
            while pendientes:
                siguiente = next(
                    (m for m in pendientes
                     if m["saldo"] is not None
                     and abs(round(corriente + (m["credito"] or 0)
                                   - (m["debito"] or 0), 2) - m["saldo"]) <= 0.011),
                    None,
                )
                if siguiente is None:
                    ordenado = None
                    break
                pendientes.remove(siguiente)
                ordenado.append(siguiente)
                corriente = siguiente["saldo"]
            if ordenado:
                grupo = ordenado

        resultado.extend(grupo)
        if grupo and grupo[-1]["saldo"] is not None:
            saldo_actual[cuenta] = grupo[-1]["saldo"]
        i = j
    return resultado

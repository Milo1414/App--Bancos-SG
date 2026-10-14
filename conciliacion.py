# ─────────────────────────────────────────────────────────────────────────────
#  CATEGORIZACIÓN DETERMINISTA DE MOVIMIENTOS (columna "Detalle")
# ─────────────────────────────────────────────────────────────────────────────
#
#  Etapa entre la extracción (parsers/) y la exportación (excel.py). Asigna a
#  cada movimiento UNA de las 13 categorías permitidas o el texto literal
#  "#N/D", con reglas de banco + descripción + dirección y, cuando hace falta,
#  datos del perfil del cliente (razón social, CUIT, cuentas, exclusiones).
#
#  · Sin Streamlit, sin red, sin modelos: se puede importar y probar solo.
#  · Las reglas viven en un único catálogo de producción:
#        assets/reglas_bancarias.json
#    Es el de public/conciliaciones_bancarias/ sin los ejemplos de evidencia
#    (citan clientes reales; public/ no se versiona). Una prueba verifica que
#    las reglas de ambas copias sean idénticas.
#    La semántica replica public/conciliaciones_bancarias/motor_referencia.py,
#    que se conserva intacto como oráculo independiente.
#  · Los datos del cliente NUNCA se escriben en el catálogo: viajan aparte, en
#    el perfil de cada hoja.
#
#  Contrato del clasificador (un movimiento):
#      banco, descripcion, descripcion_secundaria, debito/credito (magnitudes
#      positivas, la inactiva en None/0) o importe con signo (+ crédito,
#      − débito), tipo_movimiento opcional, contraparte_nombre/_cuit/_cuenta y
#      contraparte_tercero_verificado cuando el parser los obtuvo del propio
#      movimiento.
#  El adaptador `adaptar_movimiento` convierte una fila de los parsers a ese
#  contrato con una lista blanca de campos: Cuenta, Detalle previo, notas,
#  fila o nombre de archivo nunca llegan al clasificador.

import copy
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent
RUTA_CATALOGO = _RAIZ / "assets" / "reglas_bancarias.json"

# Salida cerrada: exactamente estos nombres (sin espacios finales) o "#N/D".
CATEGORIAS = (
    "Deudores por venta",
    "Proveedores",
    "Retencion IIBB",
    "imp 25.413",
    "Gastos y comisiones Bancarias",
    "Iva Credito",
    "Iva Percepcion",
    "Sueldos a Pagar",
    "Fondo comun de Inversion",
    "Plazo Fijo",
    "Pago Arca",
    "Transferencia entre cuentas",
    "Caja",
)
PENDIENTE = "#N/D"

DIRECCIONES = ("Debito", "Credito")
PREDICADOS = ("excluded_counterparty", "own_counterparty",
              "unresolved_counterparty", "residual_credit")

# Clave del parser (o nombre del banco) → banco del catálogo.
# Macro tiene parsers (MacroV1 y MacroV2) pero el catálogo no trae reglas
# validadas para ese banco: se reconoce para dar un motivo claro, no se
# "renombra" como otro banco.
MACRO = "Macro"
_BANCOS = {
    "GALICIA": "Galicia", "BANCO GALICIA": "Galicia",
    "BBVA": "BBVA", "BANCO BBVA": "BBVA",
    "SANTANDER": "Santander", "BANCO SANTANDER": "Santander",
    "NACION": "Nacion", "BANCO NACION": "Nacion", "BNA": "Nacion",
    "BANCOR": "Bancor", "BANCO DE CORDOBA": "Bancor",
    "MACRO": MACRO, "MACROV1": MACRO, "MACROV2": MACRO, "BANCO MACRO": MACRO,
}

# Familia de transferencia (mismo patrón que la referencia). Sólo dentro de
# esta familia se busca la identidad del titular o de una contraparte.
_CODIGO = r"(?:(?:[DC]\s+)?(?:\d+\s+)?)"
_FAMILIA_TRANSFERENCIA = re.compile(
    rf"^{_CODIGO}(?:TRF\b|TRANSF\w*\b|TR NE\d+\b|CREDITO TRANSF\w*\b|"
    r"DEBITO TRANSF\w*\b|MOVIM(?:IENTO)? ENTRE CUENTAS\b|DEB TRAN INTERB\b|"
    r"BCA E TR O BCO\b|TRANS CR\b|SERVICIO A PROVEEDORES\b|ANULACION DE TRANSFERENCIA O BCO\b)"
)
_FILA_NO_MOVIMIENTO = re.compile(r"^(?:SALDO\b|SIN MOVIMIENTOS\b|CONTROL\b|TOTAL\b)")
_RE_IVA = re.compile(r"\bI\s*\.?\s*V\s*\.?\s*A\b")
_RE_25413 = re.compile(r"(?<!\d)25[.\s]*413(?!\d)")
_RE_PUNTUACION = re.compile(r"[^A-Z0-9]+")
_RE_ESPACIOS = re.compile(r"\s+")
_ROTULOS_TITULAR = ("CUIT DEL RESPONSABLE IMPOSITIVO", "CUIT RESPONSABLE IMPOSITIVO")


# ─────────────────────────────────────────────────────────────────────────────
#  NORMALIZACIÓN (siempre sobre una copia; la descripción original no cambia)
# ─────────────────────────────────────────────────────────────────────────────

def normalizar(texto) -> str:
    """Mayúsculas, sin acentos, I.V.A.→IVA, 25.413→25413, puntuación→espacio.

    Conserva los dígitos: pueden ser un CUIT o una cuenta propia.
    """
    if texto is None:
        return ""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(texto).upper())
                if not unicodedata.combining(c))
    t = _RE_IVA.sub("IVA", t)
    t = _RE_25413.sub("25413", t)  # antes de separar la puntuación
    return _RE_ESPACIOS.sub(" ", _RE_PUNTUACION.sub(" ", t)).strip()


def _solo_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def limpiar_descripcion(texto, alias_titular, marcadores_pie):
    """Normaliza y corta el pie de página pegado a la descripción.

    Devuelve (texto_limpio, traza). Si el pie empieza con el rótulo
    "CUIT del Responsable Impositivo", el alias del titular que lo precede
    también pertenece al encabezado/pie y se retira: no es una contraparte.
    """
    t = normalizar(texto)
    traza = {}
    cortes = [(t.find(m), m) for m in marcadores_pie if m in t]
    if cortes:
        pos, marcador = min(cortes)
        prefijo = t[:pos].strip()
        traza["pie_cortado"] = marcador
        if t[pos:].startswith(_ROTULOS_TITULAR):
            for alias in sorted(alias_titular, key=len, reverse=True):
                if prefijo == alias or prefijo.endswith(" " + alias):
                    prefijo = prefijo[:-len(alias)].strip()
                    traza["titular_de_pie_retirado"] = alias
                    break
        t = prefijo
    return t, traza


# ─────────────────────────────────────────────────────────────────────────────
#  CATÁLOGO
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Regla:
    id: str
    banco: str
    prioridad: int
    detalle: str
    direcciones: tuple
    activa: bool
    estado: str
    patrones: tuple            # regex compiladas sobre la descripción operativa
    patrones_secundarios: tuple  # regex sobre la segunda línea bancaria
    predicado: str | None
    nota: str


@dataclass(frozen=True)
class Catalogo:
    bancos: tuple
    categorias: tuple
    fallback: str
    marcadores_pie: tuple
    reglas: tuple              # sólo activas, ordenadas por (prioridad, id)
    reglas_inactivas: tuple
    origen: str


def _error(msg):
    raise ValueError(f"Catálogo inválido: {msg}")


def compilar_catalogo(datos: dict, origen: str = "<dict>") -> Catalogo:
    """Valida el JSON del catálogo y precompila sus expresiones.

    No modifica `datos`. Rechaza IDs duplicados, regex inválidas, categorías
    fuera de la lista cerrada, predicados/bancos/direcciones desconocidos y
    reglas sin ninguna condición.
    """
    if not isinstance(datos, dict):
        _error("se esperaba un objeto JSON")
    for clave in ("allowed_details", "fallback", "banks", "rules", "normalization"):
        if clave not in datos:
            _error(f"falta la clave '{clave}'")
    if tuple(datos["allowed_details"]) != CATEGORIAS:
        _error("allowed_details no coincide con las 13 categorías permitidas")
    if datos["fallback"] != PENDIENTE:
        _error(f"fallback debe ser '{PENDIENTE}'")
    bancos = tuple(datos["banks"])
    marcadores = tuple(datos["normalization"].get("footer_markers", []))
    if any(m != normalizar(m) for m in marcadores):
        _error("los footer_markers deben estar normalizados")

    vistos = set()
    activas, inactivas = [], []
    for i, r in enumerate(datos["rules"]):
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            _error(f"regla #{i} sin id")
        if rid in vistos:
            _error(f"id duplicado {rid}")
        vistos.add(rid)
        if r.get("bank") != "*" and r.get("bank") not in bancos:
            _error(f"{rid}: banco desconocido {r.get('bank')!r}")
        prioridad = r.get("priority")
        if not isinstance(prioridad, int) or isinstance(prioridad, bool):
            _error(f"{rid}: prioridad no entera")
        if r.get("detalle") not in CATEGORIAS + (PENDIENTE,):
            _error(f"{rid}: detalle fuera del catálogo {r.get('detalle')!r}")
        direcciones = tuple(r.get("directions") or ())
        if not direcciones or any(d not in DIRECCIONES for d in direcciones):
            _error(f"{rid}: direcciones inválidas {direcciones}")
        if not isinstance(r.get("enabled"), bool):
            _error(f"{rid}: 'enabled' debe ser booleano")
        predicado = r.get("predicate")
        if predicado is not None and predicado not in PREDICADOS:
            _error(f"{rid}: predicado no soportado {predicado!r}")
        try:
            pats = tuple(re.compile(p) for p in r.get("description_patterns", []))
            secs = tuple(re.compile(p) for p in r.get("secondary_patterns", []))
        except (re.error, TypeError) as e:
            _error(f"{rid}: expresión inválida ({e})")
        if not pats and not secs and predicado is None:
            _error(f"{rid}: regla sin condiciones")
        regla = Regla(rid, r["bank"], prioridad, r["detalle"], direcciones,
                      r["enabled"], r.get("status", ""), pats, secs, predicado,
                      r.get("note") or "")
        (activas if regla.activa else inactivas).append(regla)

    activas.sort(key=lambda x: (x.prioridad, x.id))
    return Catalogo(bancos, CATEGORIAS, PENDIENTE, marcadores,
                    tuple(activas), tuple(inactivas), origen)


@lru_cache(maxsize=8)
def _cargar(ruta: str, mtime: float) -> Catalogo:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return compilar_catalogo(datos, origen=ruta)


def cargar_catalogo(path=None) -> Catalogo:
    """Lee y valida el catálogo (una vez: queda en caché mientras no cambie)."""
    ruta = Path(path) if path else RUTA_CATALOGO
    ruta = ruta.resolve()
    return _cargar(str(ruta), ruta.stat().st_mtime)


def _como_catalogo(catalogo) -> Catalogo:
    if catalogo is None:
        return cargar_catalogo()
    if isinstance(catalogo, Catalogo):
        return catalogo
    return compilar_catalogo(catalogo)


# ─────────────────────────────────────────────────────────────────────────────
#  PERFIL DEL CLIENTE
# ─────────────────────────────────────────────────────────────────────────────

def perfil_vacio() -> dict:
    """Perfil sin identidad configurada (listas vacías = dato desconocido)."""
    return {
        "cliente_id": "",
        "razon_social": "",
        "alias_titular": [],
        "cuits_propios": [],
        "cuentas_propias": [],
        "contrapartes_excluidas": [],
        "contrapartes_verificadas": [],
        "reglas_negocio": {"creditos_residuales_ventas": True},
    }


# Claves conocidas: una clave mal escrita ("cuit_propios") se rechaza en vez
# de ignorarse en silencio (el perfil parecería configurado y no lo estaría).
_CLAVES_PERFIL = {"cliente_id", "razon_social", "alias_titular", "cuits_propios", "cuentas_propias",
                  "contrapartes_excluidas", "contrapartes_verificadas", "reglas_negocio",
                  "instrucciones"}
_CLAVES_ITEM = {
    "cuentas_propias": {"banco", "moneda", "referencias_extracto", "nota"},
    "contrapartes_excluidas": {"alias", "cuits", "directions", "motivo"},
    "contrapartes_verificadas": {"alias", "cuits", "motivo"},
}
_CLAVES_REGLAS = {"creditos_residuales_ventas", "depositos_explicitos_efectivo",
                  "gestion_sueldos_bbva", "activar_plazo_fijo"}
# Un alias hecho sólo de la forma societaria coincide con cualquier "… SA".
_FORMAS_SOCIETARIAS = {"SA", "S A", "SRL", "S R L", "SAS", "S A S", "SAU", "S A U", "SACI",
                       "SAIC", "SH", "S H", "SC", "S C", "SCS", "SOCIEDAD ANONIMA"}


def validar_perfil(perfil) -> tuple:
    """Comprueba la estructura de un perfil (la de config_cliente_ejemplo.json).

    Devuelve (perfil_copiado, avisos). Lanza ValueError con la lista de
    problemas si la estructura no sirve. No completa datos faltantes con los
    de otra empresa.
    """
    errores, avisos = [], []
    if not isinstance(perfil, dict):
        raise ValueError("El perfil debe ser un objeto JSON {...}.")
    p = copy.deepcopy(perfil)

    def _lista_de_textos(valor, donde):
        if not isinstance(valor, list) or not all(isinstance(x, str) for x in valor):
            errores.append(f"{donde} debe ser una lista de textos.")
            return False
        return True

    def _revisar_alias(valor, donde):
        a = normalizar(valor)
        if not a:
            return
        if a in _FORMAS_SOCIETARIAS or len(a) < 3:
            errores.append(f"{donde}: el alias {valor!r} es demasiado genérico "
                           "(coincidiría con muchas contrapartes).")
        elif len(a) < 5:
            avisos.append(f"{donde}: el alias {valor!r} es corto; revisá que no coincida "
                          "con otras contrapartes.")

    desconocidas = sorted(set(p) - _CLAVES_PERFIL)
    if desconocidas:
        errores.append(f"Claves desconocidas: {', '.join(desconocidas)}.")
    for clave in ("cliente_id", "razon_social"):
        if clave in p and not isinstance(p[clave], str):
            errores.append(f"'{clave}' debe ser texto.")
    if isinstance(p.get("razon_social"), str):
        _revisar_alias(p["razon_social"], "'razon_social'")
    if _lista_de_textos(p.get("alias_titular", []), "'alias_titular'"):
        for a in p.get("alias_titular", []):
            _revisar_alias(a, "'alias_titular'")
    if _lista_de_textos(p.get("cuits_propios", []), "'cuits_propios'"):
        for c in p.get("cuits_propios", []):
            if len(_solo_digitos(c)) != 11:
                errores.append(f"CUIT propio {c!r} no tiene 11 dígitos.")

    for clave, campos in (("cuentas_propias", ("referencias_extracto",)),
                          ("contrapartes_excluidas", ("alias", "cuits")),
                          ("contrapartes_verificadas", ("alias", "cuits"))):
        items = p.get(clave, [])
        if not isinstance(items, list):
            errores.append(f"'{clave}' debe ser una lista de objetos.")
            continue
        for n, item in enumerate(items, 1):
            if not isinstance(item, dict):
                errores.append(f"'{clave}' #{n} debe ser un objeto.")
                continue
            extra = sorted(set(item) - _CLAVES_ITEM[clave])
            if extra:
                errores.append(f"'{clave}' #{n}: claves desconocidas {', '.join(extra)}.")
            for campo in campos:
                if _lista_de_textos(item.get(campo, []), f"'{clave}' #{n}.{campo}"):
                    if campo == "alias":
                        for a in item.get("alias", []):
                            _revisar_alias(a, f"'{clave}' #{n}")
                    if campo == "cuits":
                        for c in item.get("cuits", []):
                            if len(_solo_digitos(c)) != 11:
                                errores.append(f"'{clave}' #{n}: CUIT {c!r} no tiene 11 dígitos.")
            if clave == "contrapartes_excluidas":
                dirs = item.get("directions", list(DIRECCIONES))
                if not isinstance(dirs, list) or any(d not in DIRECCIONES for d in dirs):
                    errores.append(f"'{clave}' #{n}.directions admite sólo Debito/Credito.")
                if not item.get("alias") and not item.get("cuits"):
                    errores.append(f"'{clave}' #{n} necesita alias o cuits.")
            if clave == "cuentas_propias" and any(
                    len(normalizar(ref)) < 6 for ref in item.get("referencias_extracto", [])
                    if isinstance(ref, str)):
                avisos.append(f"'cuentas_propias' #{n}: una referencia muy corta parece un "
                              "sufijo; se compara como frase completa.")

    reglas = p.get("reglas_negocio", {})
    if not isinstance(reglas, dict):
        errores.append("'reglas_negocio' debe ser un objeto.")
    else:
        extra = sorted(set(reglas) - _CLAVES_REGLAS)
        if extra:
            errores.append(f"'reglas_negocio': claves desconocidas {', '.join(extra)}.")
        if not isinstance(reglas.get("creditos_residuales_ventas", True), bool):
            errores.append("'reglas_negocio.creditos_residuales_ventas' debe ser true/false.")
        if reglas.get("activar_plazo_fijo"):
            avisos.append("activar_plazo_fijo se ignora: la regla de Plazo Fijo sigue "
                          "desactivada en el catálogo hasta validarla con muestras reales.")
    if errores:
        raise ValueError("\n".join(errores))
    return p, avisos


def nombre_perfil(perfil) -> str:
    perfil = perfil or {}
    nombre = (perfil.get("razon_social") or perfil.get("cliente_id") or "").strip()
    return nombre or "Sin perfil (identidad no configurada)"


@dataclass(frozen=True)
class _Perfil:
    alias: tuple
    cuits: tuple
    cuentas: tuple
    excluidas: tuple   # (direcciones, alias normalizados, cuits)
    verificadas: tuple  # (alias normalizados, cuits)
    residual_ventas: bool


def _preparar_perfil(config) -> _Perfil:
    config = config or {}
    # `or` en cada lectura: un null en el JSON equivale a "no configurado".
    alias = tuple(a for a in (normalizar(x) for x in
                              [config.get("razon_social") or ""] + list(config.get("alias_titular") or []))
                  if a)

    def _identidad(item):
        return (tuple(a for a in (normalizar(x) for x in item.get("alias") or []) if a),
                tuple(item.get("cuits") or []))

    return _Perfil(
        alias=alias,
        cuits=tuple(config.get("cuits_propios") or []),
        cuentas=tuple(a for item in config.get("cuentas_propias") or []
                      for a in (normalizar(r) for r in item.get("referencias_extracto") or []) if a),
        excluidas=tuple((tuple(item.get("directions") or DIRECCIONES),) + _identidad(item)
                        for item in config.get("contrapartes_excluidas") or []),
        verificadas=tuple(_identidad(item) for item in config.get("contrapartes_verificadas") or []),
        residual_ventas=bool((config.get("reglas_negocio") or {}).get("creditos_residuales_ventas", True)),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  DIRECCIÓN E IDENTIDAD
# ─────────────────────────────────────────────────────────────────────────────

def _decimal(valor) -> Decimal:
    if valor is None or valor == "":
        return Decimal(0)
    if isinstance(valor, bool):
        raise ValueError("Importe booleano")
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, ValueError) as e:
        raise ValueError("Importe no numérico; normalizar en el adaptador") from e
    if not d.is_finite():
        raise ValueError("Importe no finito")
    return d


def _direccion(m) -> str:
    """Dirección a partir de los importes, nunca de palabras de la descripción."""
    db, cr = _decimal(m.get("debito")), _decimal(m.get("credito"))
    if db < 0 or cr < 0:
        raise ValueError("DB/CR negativos; revisar convención del adaptador")
    if db and cr:
        raise ValueError("Débito y crédito simultáneos")
    direccion = "Debito" if db else "Credito" if cr else None
    if direccion is None and "importe" in m:
        signo = _decimal(m["importe"])
        direccion = "Credito" if signo > 0 else "Debito" if signo < 0 else None
    if direccion is None:
        raise ValueError("Sin movimiento no nulo")
    declarado = normalizar(m.get("tipo_movimiento", ""))
    canonico = {"DEBITO": "Debito", "DB": "Debito", "CREDITO": "Credito", "CR": "Credito"}
    if declarado and canonico.get(declarado) != direccion:
        raise ValueError("Tipo de movimiento inconsistente con los importes")
    return direccion


def _frase(texto, alias_normalizado) -> bool:
    a = alias_normalizado
    return bool(a and re.search(r"(?:^| )" + re.escape(a) + r"(?: |$)", texto))


def _cuit_en(texto, cuit) -> bool:
    c = _solo_digitos(cuit)
    if len(c) != 11:
        return False
    patron = re.escape(c[:2]) + r"\s*" + re.escape(c[2:10]) + r"\s*" + re.escape(c[10:])
    return bool(re.search(r"(?<![A-Z0-9])" + patron + r"(?![A-Z0-9])", texto))


def _identidad_en(texto, alias, cuits) -> bool:
    return any(_frase(texto, a) for a in alias) or any(_cuit_en(texto, c) for c in cuits)


def _rasgos(m, perfil: _Perfil, catalogo: Catalogo, direccion):
    principal, traza1 = limpiar_descripcion(m.get("descripcion"), perfil.alias, catalogo.marcadores_pie)
    secundaria, traza2 = limpiar_descripcion(m.get("descripcion_secundaria"), perfil.alias,
                                             catalogo.marcadores_pie)
    # Contraparte: sólo campos que el parser obtuvo del propio movimiento.
    nombre = normalizar(m.get("contraparte_nombre", ""))
    cuit = _solo_digitos(m.get("contraparte_cuit", ""))
    cuenta = normalizar(m.get("contraparte_cuenta", ""))
    textos = " ".join(x for x in (principal, secundaria, nombre, cuit, cuenta) if x)

    familia = bool(_FAMILIA_TRANSFERENCIA.search(principal))
    propia = familia and (
        any(_frase(textos, a) for a in perfil.alias)
        or any(_cuit_en(textos, c) for c in perfil.cuits)
        or any(_frase(textos, ref) for ref in perfil.cuentas)
    )
    excluida = familia and any(
        direccion in dirs and _identidad_en(textos, alias, cuits)
        for dirs, alias, cuits in perfil.excluidas
    )
    verificada = bool(m.get("contraparte_tercero_verificado", False)) or any(
        _identidad_en(textos, alias, cuits) for alias, cuits in perfil.verificadas
    )
    propios = [_solo_digitos(x) for x in perfil.cuits]
    if len(cuit) == 11 and propios and cuit not in propios:
        verificada = True
    traza = {}
    if traza1:
        traza["descripcion"] = traza1
    if traza2:
        traza["descripcion_secundaria"] = traza2
    return {
        "principal": principal, "secundaria": secundaria, "familia_transferencia": familia,
        "propia": propia, "excluida": excluida, "tercero_verificado": verificada,
        "traza": traza,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  CLASIFICACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def _pendiente(motivo, **extra):
    return {"detalle": PENDIENTE, "regla_id": None, "motivo": motivo, **extra}


def banco_catalogo(valor):
    """Clave de parser o nombre de banco → nombre del catálogo (o None)."""
    return _BANCOS.get(normalizar(valor))


def categorizar_movimiento(movimiento, config_cliente=None, catalogo=None) -> dict:
    """Decide el Detalle de UN movimiento (contrato del clasificador).

    Devuelve un dict con al menos `detalle`, `regla_id` y `motivo`, más la
    traza (`descripcion_normalizada`, `tipo_movimiento`, coincidencias…).
    """
    cat = _como_catalogo(catalogo)
    perfil = config_cliente if isinstance(config_cliente, _Perfil) else _preparar_perfil(config_cliente)
    return _categorizar(movimiento, perfil, cat)


def _categorizar(m, perfil: _Perfil, cat: Catalogo) -> dict:
    if not m.get("banco"):
        return _pendiente("Banco de origen ausente")
    banco = banco_catalogo(m.get("banco"))
    if banco == MACRO:
        return _pendiente("Banco sin reglas validadas (Macro): falta un corpus etiquetado",
                          banco=banco)
    if banco not in cat.bancos:
        return _pendiente("Banco no soportado")
    if not isinstance(m.get("descripcion"), str) or not m["descripcion"].strip():
        return _pendiente("Descripción ausente o inválida", banco=banco)
    try:
        direccion = _direccion(m)
    except ValueError as e:
        return _pendiente(str(e), banco=banco)

    f = _rasgos(m, perfil, cat, direccion)
    base = {"banco": banco, "tipo_movimiento": direccion,
            "descripcion_normalizada": f["principal"]}
    if f["secundaria"]:
        base["descripcion_secundaria_normalizada"] = f["secundaria"]
    if f["traza"]:
        base["normalizacion"] = f["traza"]
    if not f["principal"]:
        return _pendiente("Descripción operativa vacía", **base)
    if _FILA_NO_MOVIMIENTO.match(f["principal"]):
        return _pendiente("Fila de saldo, control o resumen", **base)

    predicados = {
        "excluded_counterparty": f["excluida"],
        "own_counterparty": f["propia"],
        "unresolved_counterparty": not f["propia"] and not f["tercero_verificado"],
        "residual_credit": direccion == "Credito" and perfil.residual_ventas,
    }
    coincidencias = []
    for r in cat.reglas:  # ya ordenadas por prioridad
        if coincidencias and r.prioridad > coincidencias[0].prioridad:
            break  # sólo interesa la prioridad ganadora
        if r.banco not in ("*", banco) or direccion not in r.direcciones:
            continue
        if r.patrones and not any(p.search(f["principal"]) for p in r.patrones):
            continue
        if r.patrones_secundarios and not any(p.search(f["secundaria"]) for p in r.patrones_secundarios):
            continue
        if r.predicado is not None and not predicados[r.predicado]:
            continue
        coincidencias.append(r)

    if not coincidencias:
        return _pendiente("Sin coincidencia", **base)
    ganadoras = coincidencias  # todas comparten la menor prioridad
    if len({r.detalle for r in ganadoras}) > 1:
        return _pendiente("Conflicto de reglas de igual prioridad",
                          reglas_en_conflicto=[r.id for r in ganadoras], **base)
    ganadora = ganadoras[0]
    return {"detalle": ganadora.detalle, "regla_id": ganadora.id,
            "motivo": ganadora.nota or "Patrón del catálogo",
            "prioridad": ganadora.prioridad,
            "coincidencias": [r.id for r in ganadoras], **base}


# ─────────────────────────────────────────────────────────────────────────────
#  ADAPTADOR (fila de los parsers → contrato del clasificador) Y LOTES
# ─────────────────────────────────────────────────────────────────────────────

# Campos del contrato que una fila extraída puede aportar tal cual.
_CAMPOS_OPERATIVOS = ("descripcion_secundaria", "moneda", "fecha", "importe", "tipo_movimiento",
                      "contraparte_nombre", "contraparte_cuit", "contraparte_cuenta",
                      "contraparte_tercero_verificado", "id")


def adaptar_movimiento(mov: dict) -> dict:
    """Fila de un parser → movimiento del clasificador.

    · debito/credito ya son magnitudes positivas (o None): se pasan sin
      reconvertir ni cambiar signos.
    · Si el parser separó la primera línea (`descripcion_operativa`, hoy
      Santander), esa es la descripción a clasificar; `descripcion` sigue
      siendo el texto que se exporta.
    · `cuenta` (cuenta bancaria de ORIGEN) no se mapea a contraparte_cuenta.
    """
    entrada = {
        "banco": mov.get("banco"),
        "descripcion": (mov["descripcion_operativa"] if "descripcion_operativa" in mov
                        else mov.get("descripcion")),
        "debito": mov.get("debito"),
        "credito": mov.get("credito"),
    }
    for campo in _CAMPOS_OPERATIVOS:
        if mov.get(campo) is not None:
            entrada[campo] = mov[campo]
    return entrada


def clasificar_hojas(hojas: dict, metadatos_hojas: dict | None = None, catalogo=None):
    """Clasifica todas las hojas acumuladas.

    hojas:            {nombre_hoja: [movimientos de los parsers]}
    metadatos_hojas:  {nombre_hoja: {"perfil": {...}}} — el perfil con el que
                      se cargó cada hoja. Sin metadatos → perfil vacío.
    Devuelve (hojas_con_detalle, reporte). Las filas devueltas son COPIAS con
    la clave `detalle`; las originales no se tocan. El reporte trae una
    decisión por fila (hoja, fila de Excel, regla, motivo).
    """
    cat = _como_catalogo(catalogo)
    metadatos_hojas = metadatos_hojas or {}
    salida, reporte = {}, []
    for nombre, movs in hojas.items():
        perfil = _preparar_perfil((metadatos_hojas.get(nombre) or {}).get("perfil"))
        filas = []
        for i, mov in enumerate(movs):
            decision = _categorizar(adaptar_movimiento(mov), perfil, cat)
            filas.append(dict(mov, detalle=decision["detalle"]))
            reporte.append({
                "hoja": nombre, "fila_excel": i + 3, "fecha": mov.get("fecha"),
                "descripcion": mov.get("descripcion"), "banco": mov.get("banco"),
                "debito": mov.get("debito"), "credito": mov.get("credito"),
                **decision,
            })
        salida[nombre] = filas
    return salida, reporte


def pendientes_por_hoja(reporte) -> dict:
    """{hoja: cantidad de filas con #N/D}."""
    conteo = {}
    for d in reporte:
        conteo.setdefault(d["hoja"], 0)
        if d["detalle"] == PENDIENTE:
            conteo[d["hoja"]] += 1
    return conteo


_COLUMNAS_REPORTE = ("hoja", "fila_excel", "fecha", "banco", "descripcion", "debito", "credito",
                     "detalle", "regla_id", "motivo", "reglas_en_conflicto",
                     "descripcion_normalizada", "descripcion_secundaria_normalizada")


def _celda_csv(valor) -> str:
    """Valor de celda para un CSV que se abre con Excel en español.

    · Importes con coma decimal ("599,89"): con "." Excel los lee como texto o
      como separador de miles.
    · Textos que Excel tomaría como fórmula (=, +, -, @) van con un apóstrofo
      adelante (inyección de fórmulas en CSV).
    """
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, (int, float, Decimal)):
        return f"{Decimal(str(valor)):.2f}".replace(".", ",") if not isinstance(valor, int) else str(valor)
    texto = str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def reporte_pendientes_csv(reporte) -> str:
    """CSV (separador ;) con las filas #N/D y conflictos, para revisión técnica.

    Va aparte del Excel: el libro final sólo lleva la columna Detalle.
    """
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(_COLUMNAS_REPORTE)
    for d in reporte:
        if d["detalle"] != PENDIENTE:
            continue
        fila = dict(d)
        if fila.get("reglas_en_conflicto"):
            fila["reglas_en_conflicto"] = ",".join(fila["reglas_en_conflicto"])
        w.writerow([_celda_csv(fila.get(c)) for c in _COLUMNAS_REPORTE])
    return buf.getvalue()

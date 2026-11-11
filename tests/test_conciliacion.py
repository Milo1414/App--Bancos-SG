"""Regresiones de la categorización (columna Detalle).

Ejecutar desde la raíz del proyecto:   python -m unittest discover -s tests -v
(sólo biblioteca estándar + openpyxl; no importa Streamlit).

public/ no se versiona (tiene extractos y conciliaciones reales). Las pruebas
que usan el paquete de reglas completo o los PDF se saltean si public/ no está,
o si falta alguno de los dos motores de pdftotext. Los PDF se reconocen por su
hash, no por el nombre: así el repositorio no guarda nombres de clientes.
"""
import copy
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
PAQUETE = RAIZ / "public" / "conciliaciones_bancarias"
sys.path.insert(0, str(RAIZ))

import openpyxl  # noqa: E402

import conciliacion as C  # noqa: E402
from excel import generar_excel  # noqa: E402

CATALOGO = C.cargar_catalogo()
HAY_PAQUETE = (PAQUETE / "casos_prueba.json").exists()
CASOS = (json.loads((PAQUETE / "casos_prueba.json").read_text(encoding="utf-8"))
         if HAY_PAQUETE else [])
JSON_CATALOGO = json.loads(C.RUTA_CATALOGO.read_text(encoding="utf-8"))
sin_paquete = unittest.skipUnless(HAY_PAQUETE, "public/conciliaciones_bancarias no está (sólo local)")


def detalle(mov, perfil=None, catalogo=CATALOGO):
    return C.categorizar_movimiento(mov, perfil, catalogo)["detalle"]


def mov(banco, descripcion, debito=None, credito=None, **extra):
    return {"banco": banco, "descripcion": descripcion, "debito": debito, "credito": credito, **extra}


# ─────────────────────────────────────────────────────────────────────────────
class CasosDelPaquete(unittest.TestCase):

    def test_modulo_no_importa_streamlit(self):
        salida = subprocess.run(
            [sys.executable, "-c", "import sys, conciliacion; print('streamlit' in sys.modules)"],
            cwd=RAIZ, capture_output=True, text=True, check=True)
        self.assertEqual(salida.stdout.strip(), "False")

    @sin_paquete
    def test_108_casos(self):
        self.assertEqual(len(CASOS), 108)
        fallos = [(c["id"], c["detalle_esperado"], detalle(c["movimiento"], c["config_cliente"]))
                  for c in CASOS
                  if detalle(c["movimiento"], c["config_cliente"]) != c["detalle_esperado"]]
        self.assertEqual(fallos, [])

    @sin_paquete
    def test_misma_decision_que_la_referencia(self):
        """motor_referencia.py es el oráculo: misma regla y motivo en los 108."""
        sys.path.insert(0, str(PAQUETE))
        import motor_referencia as R
        ref = R.cargar_catalogo(PAQUETE / "reglas_bancarias.json")
        for c in CASOS:
            a = C.categorizar_movimiento(c["movimiento"], c["config_cliente"], CATALOGO)
            b = R.categorizar_movimiento(c["movimiento"], c["config_cliente"], ref)
            self.assertEqual((a["detalle"], a["regla_id"], a["motivo"]),
                             (b["detalle"], b["regla_id"], b["motivo"]), c["id"])

    def test_decision_trae_regla_y_motivo(self):
        d = C.categorizar_movimiento(mov("Galicia", "IMP. CRE. LEY 25413", debito=10), None, CATALOGO)
        self.assertEqual((d["detalle"], d["regla_id"]), ("imp 25.413", "GAL_TAX_25413"))
        self.assertTrue(d["motivo"])
        self.assertEqual(d["descripcion_normalizada"], "IMP CRE LEY 25413")


# ─────────────────────────────────────────────────────────────────────────────
class Catalogo(unittest.TestCase):

    def _con(self, **cambios):
        datos = copy.deepcopy(JSON_CATALOGO)
        regla = copy.deepcopy(datos["rules"][1])
        regla.update(cambios)
        datos["rules"].append(regla)
        return datos

    def test_validaciones(self):
        casos = {
            "id duplicado": self._con(),
            "expresión inválida": self._con(id="X1", description_patterns=["(sin cerrar"]),
            "detalle fuera": self._con(id="X2", detalle="Cuenta contable nueva"),
            "detalle con espacio": self._con(id="X3", detalle="Proveedores "),
            "predicado": self._con(id="X4", predicate="adivinar_por_importe"),
            "banco": self._con(id="X5", bank="Banco Inexistente"),
            "direccion": self._con(id="X6", directions=["Entrada"]),
            "sin condiciones": self._con(id="X7", description_patterns=[]),
        }
        for nombre, datos in casos.items():
            with self.subTest(nombre), self.assertRaises(ValueError):
                C.compilar_catalogo(datos)

    def test_categorias_exactas(self):
        self.assertEqual(len(C.CATEGORIAS), 13)
        self.assertEqual(list(C.CATEGORIAS), JSON_CATALOGO["allowed_details"])
        self.assertTrue(all(c == c.strip() for c in C.CATEGORIAS))

    def test_plazo_fijo_sigue_desactivado(self):
        ids_activas = {r.id for r in CATALOGO.reglas}
        self.assertNotIn("COMMON_PLAZO_FIJO", ids_activas)
        self.assertIn("COMMON_PLAZO_FIJO_REVIEW", ids_activas)
        perfil = {"reglas_negocio": {"activar_plazo_fijo": True}}
        self.assertEqual(detalle(mov("BBVA", "VENCIMIENTO PLAZO FIJO", credito=100), perfil), "#N/D")

    def test_conflicto_igual_prioridad(self):
        datos = copy.deepcopy(JSON_CATALOGO)
        datos["rules"].append({
            "id": "TEST_CONFLICTO", "bank": "Galicia", "priority": 10, "detalle": "Proveedores",
            "directions": ["Debito"], "enabled": True, "status": "test",
            "description_patterns": [r"^IMP DEB LEY 25413\b"], "predicate": None, "note": ""})
        d = C.categorizar_movimiento(mov("Galicia", "IMP. DEB. LEY 25413", debito=5), None,
                                     C.compilar_catalogo(datos))
        self.assertEqual(d["detalle"], "#N/D")
        self.assertEqual(d["motivo"], "Conflicto de reglas de igual prioridad")
        self.assertEqual(sorted(d["reglas_en_conflicto"]), ["GAL_TAX_25413", "TEST_CONFLICTO"])

    def test_clasificar_no_modifica_catalogo_ni_perfil(self):
        antes = copy.deepcopy(JSON_CATALOGO)
        perfil = {"razon_social": "EMPRESA NUEVA SA", "cuits_propios": ["30123456789"]}
        perfil_antes = copy.deepcopy(perfil)
        C.compilar_catalogo(JSON_CATALOGO)
        C.categorizar_movimiento(mov("BBVA", "D 500 TRANSFERENCIA 30123456789", debito=1), perfil,
                                 JSON_CATALOGO)
        self.assertEqual(JSON_CATALOGO, antes)
        self.assertEqual(perfil, perfil_antes)

    @sin_paquete
    def test_reglas_sin_datos_de_clientes(self):
        """Ningún patrón fija nombres, CUIT o contrapartes de los perfiles de la muestra."""
        texto = C.normalizar(json.dumps([r["description_patterns"] + r.get("secondary_patterns", [])
                                         for r in JSON_CATALOGO["rules"]]))
        identidades = set()
        for caso in CASOS:
            cfg = caso["config_cliente"]
            identidades.update([cfg.get("razon_social", "")] + cfg.get("alias_titular", [])
                               + cfg.get("cuits_propios", []))
            for item in cfg.get("contrapartes_excluidas", []):
                identidades.update(item.get("alias", []) + item.get("cuits", []))
        identidades = {C.normalizar(x) for x in identidades if x}
        self.assertTrue(identidades)
        for ident in identidades:  # palabra completa: un alias corto no debe coincidir dentro de otra palabra
            self.assertNotIn(f" {ident} ", f" {texto} ")

    def test_catalogo_de_produccion_sin_evidencia(self):
        """assets/ no lleva ejemplos de evidencia (citan clientes reales)."""
        self.assertTrue(all("evidence" not in r for r in JSON_CATALOGO["rules"]))

    @sin_paquete
    def test_mismas_reglas_que_el_paquete(self):
        """La copia de producción tiene exactamente las reglas del paquete completo."""
        completo = json.loads((PAQUETE / "reglas_bancarias.json").read_text(encoding="utf-8"))
        sin_evidencia = [{k: v for k, v in r.items() if k != "evidence"} for r in completo["rules"]]
        self.assertEqual(sin_evidencia, JSON_CATALOGO["rules"])
        for clave in ("allowed_details", "fallback", "banks", "normalization", "resolution"):
            self.assertEqual(completo[clave], JSON_CATALOGO[clave], clave)


# ─────────────────────────────────────────────────────────────────────────────
class Normalizacion(unittest.TestCase):

    def test_formas(self):
        self.assertEqual(C.normalizar("I.V.A. Básico"), "IVA BASICO")
        self.assertEqual(C.normalizar("Ley 25.413"), "LEY 25413")
        self.assertEqual(C.normalizar("Ley 25 413"), "LEY 25413")
        self.assertEqual(C.normalizar("CUIT 30-71049542-0"), "CUIT 30 71049542 0")
        self.assertEqual(C.normalizar(None), "")

    def test_pie_y_titular_del_encabezado(self):
        texto = ("TRF INMED PROVEED TERCERO VARIOS BANCO DESTINO EMPRESA NUEVA SA "
                 "CUIT del Responsable Impositivo : 30-12345678-9 IVA Responsable inscripto")
        limpio, traza = C.limpiar_descripcion(texto, ("EMPRESA NUEVA SA",), CATALOGO.marcadores_pie)
        self.assertEqual(limpio, "TRF INMED PROVEED TERCERO VARIOS BANCO DESTINO")
        self.assertEqual(traza["titular_de_pie_retirado"], "EMPRESA NUEVA SA")
        perfil = {"razon_social": "EMPRESA NUEVA SA", "cuits_propios": ["30123456789"]}
        d = C.categorizar_movimiento(mov("Galicia", texto, debito=100), perfil, CATALOGO)
        self.assertEqual(d["detalle"], "Proveedores")  # no es propia por el pie
        self.assertIn("normalizacion", d)

    def test_pie_con_impuestos_no_genera_falso_positivo(self):
        texto = ("TRANSFERENCIA DE TERCEROS EMPRESA DISTINTA Los depósitos en pesos y en moneda "
                 "extranjera. Retención Impuesto Ley 25.413 I.V.A.")
        self.assertEqual(detalle(mov("Galicia", texto, credito=100)), "Deudores por venta")


# ─────────────────────────────────────────────────────────────────────────────
class EntradaYDireccion(unittest.TestCase):

    def test_entradas_invalidas(self):
        casos = {
            "nan": mov("Galicia", "IVA", debito=float("nan")),
            "inf": mov("Galicia", "IVA", debito=math.inf),
            "texto": mov("Galicia", "IVA", debito="1.234,56"),
            "bool": mov("Galicia", "IVA", debito=True),
            "cero": mov("Galicia", "IVA", debito=0, credito=0),
            "ausente": mov("Galicia", "IVA"),
            "ambos": mov("Galicia", "IVA", debito=10, credito=10),
            "negativo": mov("Galicia", "IVA", debito=-10),
            "inconsistente": mov("Galicia", "IVA", debito=10, tipo_movimiento="Credito"),
            "banco desconocido": mov("Banco Inventado", "IVA", debito=10),
            "sin banco": mov(None, "IVA", debito=10),
            "sin descripcion": mov("Galicia", "  ", debito=10),
        }
        for nombre, m in casos.items():
            with self.subTest(nombre):
                d = C.categorizar_movimiento(m, None, CATALOGO)
                self.assertEqual(d["detalle"], "#N/D")
                self.assertIsNone(d["regla_id"])
                self.assertTrue(d["motivo"])

    def test_importe_con_signo(self):
        self.assertEqual(detalle(mov("BBVA", "D 500 PAGOS AFIP", importe=Decimal("-10.00"))), "Pago Arca")
        self.assertEqual(detalle(mov("Galicia", "CREDITO TRANSFERENCIA COELSA X", importe="25")),
                         "Deudores por venta")

    def test_prefijo_d_c_no_es_la_direccion(self):
        self.assertEqual(detalle(mov("BBVA", "D 733 TRANSFERENCIA 20987654321", credito=100)),
                         "Deudores por venta")
        self.assertEqual(detalle(mov("BBVA", "C 995 CHEQUE 48HS. DEVUELTO CAP F 1", debito=100)),
                         "Deudores por venta")

    def test_palabras_iva_credito_no_son_la_direccion(self):
        self.assertEqual(detalle(mov("BBVA", "IVA TASA GENERAL", debito=100)), "Iva Credito")
        self.assertEqual(detalle(mov("BBVA", "LEY NRO 25.413 SOBRE CREDIT", debito=100)), "imp 25.413")

    def test_macrov1_y_macrov2_comparten_reglas(self):
        for clave in ("macro", "macrov2", "Macro"):
            d = C.categorizar_movimiento(mov(clave, "DEPOSITO EN EFECTIVO", credito=100), None, CATALOGO)
            self.assertEqual((d["detalle"], d["banco"]), ("Caja", "Macro"))
            d = C.categorizar_movimiento(mov(clave, "DBCR 25413 S/DB TASA GRAL", debito=1), None, CATALOGO)
            self.assertEqual((d["detalle"], d["regla_id"]), ("imp 25.413", "MAC_TAX_25413"))

    def test_importe_no_decide_la_categoria(self):
        for descripcion, banco, esperado in (("TRF INMED PROVEED ALGUIEN", "Galicia", "Proveedores"),
                                             ("DEBITO POR PAGO DE HABERES OL", "BBVA", "Sueldos a Pagar"),
                                             ("TRANSF.HB.EXENTO", "Bancor", "#N/D")):
            for importe in (0.01, 1, 999.99, 1e6, 987654321.12):
                with self.subTest(descripcion=descripcion, importe=importe):
                    self.assertEqual(detalle(mov(banco, descripcion, debito=importe)), esperado)

    def test_etiquetas_historicas_no_cambian_la_prediccion(self):
        base = mov("Galicia", "TRANSF.", debito=100)
        con_ruido = dict(base, detalle="Proveedores", Detalle="Proveedores", cuenta_contable="2.1.1",
                         nota="pagado a proveedor", fila=70, archivo="PT - Banco.xlsx",
                         descripcion_manual="Proveedor X")
        self.assertEqual(C.adaptar_movimiento(con_ruido), C.adaptar_movimiento(base))
        self.assertEqual(C.clasificar_hojas({"h": [con_ruido]})[0]["h"][0]["detalle"], "#N/D")


# ─────────────────────────────────────────────────────────────────────────────
class PrioridadesYPerfiles(unittest.TestCase):

    def test_prioridades_antes_del_credito_residual(self):
        casos = [
            (mov("Galicia", "RESCATE FIMA PREMIUM", credito=1), "Fondo comun de Inversion"),
            (mov("Galicia", "DEPOSITO EN EFECTIVO", credito=1), "Caja"),
            (mov("Galicia", "TRANSF. PROPIAS X", credito=1), "Transferencia entre cuentas"),
            (mov("Galicia", "DEV. IMP. DEB. LEY 25.413", credito=1), "imp 25.413"),
            (mov("Galicia", "DEVOLUCION COMISIONES X", credito=1), "Gastos y comisiones Bancarias"),
            (mov("Galicia", "REINTEGRO IVA", credito=1), "Iva Credito"),
            (mov("Bancor", "REINTEGRO COMISION EXTRAORDINARIA", credito=1), "#N/D"),
            (mov("Galicia", "DEP..AUTOSERVICIO TICKET 1", credito=1), "Deudores por venta"),
        ]
        for m, esperado in casos:
            with self.subTest(m["descripcion"]):
                self.assertEqual(detalle(m), esperado)

    def test_percepcion_antes_que_iva(self):
        self.assertEqual(detalle(mov("Galicia", "IVA PERCEPCIONES", debito=1)), "Iva Percepcion")
        self.assertEqual(detalle(mov("Bancor", "IVA PERCEPC.RG", debito=1)), "Iva Percepcion")

    def test_echeq_nacion_gasto_distinto_del_pago(self):
        self.assertEqual(detalle(mov("Nacion", "ECHEQ.EMI.NRO 1234 1234", debito=1)),
                         "Gastos y comisiones Bancarias")
        self.assertEqual(detalle(mov("Nacion", "48HS. BANCOS 159", debito=1)), "Proveedores")

    def test_empresa_nueva_solo_con_su_perfil(self):
        m = mov("BBVA", "D 500 TRANSFERENCIA 30111111118", debito=100)
        self.assertEqual(detalle(m, {"razon_social": "OTRA EMPRESA SRL",
                                     "cuits_propios": ["30111111118"]}), "Transferencia entre cuentas")
        self.assertEqual(detalle(m), "Proveedores")
        self.assertEqual(detalle(m, {"razon_social": "TERCERA EMPRESA SA", "cuits_propios": ["30333333335"]}),
                         "Proveedores")

    def test_exclusion_debito_no_bloquea_credito(self):
        perfil = {"contrapartes_excluidas": [{"alias": ["SOCIO PARTICULAR"], "directions": ["Debito"],
                                              "motivo": "cuenta particular"}]}
        self.assertEqual(detalle(mov("Galicia", "TRF INMED PROVEED SOCIO PARTICULAR", debito=1), perfil),
                         "#N/D")
        self.assertEqual(detalle(mov("Galicia", "TRANSFERENCIAS PROVEEDORES SOCIO PARTICULAR", credito=1),
                                 perfil), "Deudores por venta")
        # Santander: la contraparte viene en la segunda línea bancaria.
        socio = {"contrapartes_excluidas": [{"cuits": ["20111111112"], "motivo": "socio"}]}
        m = mov("Santander", "Transferencia ctas mobile banking", credito=1,
                descripcion_secundaria="De persona ejemplo / varios - var / 20111111112")
        self.assertEqual(detalle(m, socio), "#N/D")
        self.assertEqual(detalle(m), "Deudores por venta")

    def test_familia_ambigua_con_y_sin_identidad(self):
        m = mov("Nacion", "BCA.E.TR.O/BCO -SUC 0001 12345", credito=100)
        self.assertEqual(detalle(m), "#N/D")
        perfil = {"razon_social": "EMPRESA NUEVA SA", "cuits_propios": ["30123456789"]}
        self.assertEqual(detalle(dict(m, contraparte_cuit="30123456789"), perfil),
                         "Transferencia entre cuentas")
        self.assertEqual(detalle(dict(m, contraparte_cuit="20999999993"), perfil), "Deudores por venta")
        bancor = mov("Bancor", "TRANSF.HB.EXENTO", debito=100)
        self.assertEqual(detalle(bancor), "#N/D")
        verificado = {"contrapartes_verificadas": [{"alias": ["PROVEEDOR CONOCIDO SA"]}]}
        self.assertEqual(detalle(dict(bancor, contraparte_nombre="Proveedor Conocido SA"), verificado),
                         "Proveedores")

    def test_cuenta_de_origen_no_es_contraparte(self):
        perfil = {"cuentas_propias": [{"banco": "BBVA", "moneda": "ARS",
                                       "referencias_extracto": ["267-015530/5"]}]}
        fila = mov("bbva", "D 500 TRANSFERENCIA 123", debito=100, cuenta="267-015530/5", saldo=0)
        self.assertNotIn("contraparte_cuenta", C.adaptar_movimiento(fila))
        hojas, _ = C.clasificar_hojas({"h": [fila]}, {"h": {"perfil": perfil}})
        self.assertEqual(hojas["h"][0]["detalle"], "Proveedores")

    @sin_paquete
    def test_validar_perfil(self):
        perfil, avisos = C.validar_perfil(
            json.loads((PAQUETE / "config_cliente_ejemplo.json").read_text(encoding="utf-8")))
        self.assertEqual(perfil["cuits_propios"], [])
        self.assertEqual(avisos, [])
        for malo in ([], {"cuits_propios": "30123456789"}, {"cuits_propios": ["123"]},
                     {"contrapartes_excluidas": [{"directions": ["Debito"]}]},
                     {"contrapartes_excluidas": [{"alias": ["X"], "directions": ["Salida"]}]},
                     {"reglas_negocio": {"creditos_residuales_ventas": "si"}},
                     {"cuit_propios": ["30111111118"]},              # clave mal escrita
                     {"alias_titular": ["SA"]},                      # alias genérico
                     {"alias_titular": ["S.R.L."]},
                     {"contrapartes_excluidas": [{"alias": ["X CORP"], "cuit": ["1"]}]},
                     {"contrapartes_verificadas": [{"cuits": ["123"]}]},
                     {"reglas_negocio": {"credito_residual": False}}):
            with self.subTest(malo=malo), self.assertRaises(ValueError):
                C.validar_perfil(malo)
        for caso in CASOS:  # los perfiles del paquete siguen siendo válidos
            C.validar_perfil(caso["config_cliente"])
        self.assertEqual(C.perfil_vacio()["razon_social"], "")
        # Un null en el JSON equivale a "no configurado" (no rompe la API).
        self.assertEqual(detalle(mov("Galicia", "TRANSF. X", debito=1),
                                 {"alias_titular": None, "reglas_negocio": None}), "#N/D")
        self.assertEqual(C.nombre_perfil(None), "Sin perfil (identidad no configurada)")


# ─────────────────────────────────────────────────────────────────────────────
TEXTO_SANTANDER = """Resumen de cuenta
EMPRESA PRUEBA SRL
CUIT: 30-11111111-8
Cuenta Corriente N° 268-003639/1 CBU: 0720268320000000363918
          Fecha  Comprobante       Movimiento                                           Débito        Crédito          Saldo en cuenta
31/01/26                           Saldo Inicial                                                                       $ 10.000,00
02/02/26         1234              Pago de servicios                                    $ 599,89                       $ 9.400,11
                                   IMP.AFIP: 30707802851164
02/02/26         1235              Pago de servicios                                    $ 100,00                       $ 9.300,11
02/02/26         1236              Pago de servicios                                    $ 50,00                        $ 9.250,11
                                   EPEC: 0001234
                                                                                                                        2 - 6
03/02/26                           Impuesto ley 25.413 debito 0,6%                      $ 4,50                         $ 9.245,61
"""


class ParserSantander(unittest.TestCase):

    def setUp(self):
        from parsers import santander
        with mock.patch.object(santander, "pdf_to_text", return_value=TEXTO_SANTANDER):
            self.movs, self.diag = santander.parser_santander("sintetico.pdf")

    def test_segunda_linea_separada(self):
        self.assertEqual(len(self.movs), 4)
        afip, solo, epec, imp = self.movs
        self.assertEqual(afip["descripcion"], "Pago de servicios IMP.AFIP: 30707802851164")
        self.assertEqual(afip["descripcion_operativa"], "Pago de servicios")
        self.assertEqual(afip["descripcion_secundaria"], "IMP.AFIP: 30707802851164")
        self.assertIsNone(solo["descripcion_secundaria"])
        # El número de página sigue en descripcion (como antes) pero no es 2ª línea.
        self.assertEqual(epec["descripcion"], "Pago de servicios EPEC: 0001234 2 - 6")
        self.assertEqual(epec["descripcion_secundaria"], "EPEC: 0001234")
        self.assertIsNone(imp["descripcion_secundaria"])
        # El titular/CUIT del encabezado nunca se adjunta a un movimiento.
        self.assertFalse(any("30-11111111-8" in (m["descripcion_secundaria"] or "") for m in self.movs))

    def test_clasificacion_tras_el_adaptador(self):
        hojas, rep = C.clasificar_hojas({"S": [dict(m, banco="santander") for m in self.movs]})
        self.assertEqual([m["detalle"] for m in hojas["S"]],
                         ["Pago Arca", "#N/D", "#N/D", "imp 25.413"])
        self.assertEqual(rep[0]["regla_id"], "SAN_ARCA")
        # Con la descripción unificada (comportamiento anterior) no alcanzaba.
        self.assertEqual(detalle(mov("Santander", self.movs[0]["descripcion"], debito=599.89)), "#N/D")


# ─────────────────────────────────────────────────────────────────────────────
def _fila_macro(inicio, desc="", ref="", deb="", cred="", saldo=""):
    return f"{inicio:<9}{desc:<45}{ref:>12}{deb:>20}{cred:>20}{saldo:>20}"


_ENCABEZADO_MACRO = f"{'FECHA':<9}{'DESCRIPCION':<45}{'REFERENCIA':>12}{'DEBITOS':>20}{'CREDITOS':>20}{'SALDO':>20}"
# Importes corridos de columna (como en el `-table` de Xpdf): el crédito de 500
# cae bajo DEBITOS y el débito de 200 bajo CREDITOS. El saldo decide la dirección.
TEXTO_MACROV1 = "\n".join([
    "CAJA DE AHORRO EN PESOS NRO.: 4-399-0000000001-1",
    "DETALLE DE MOVIMIENTO",
    _ENCABEZADO_MACRO,
    _fila_macro("", "SALDO ULTIMO EXTRACTO AL 30/04/2026", saldo="1.000,00"),
    _fila_macro("04/05/26", "ING TRANSF:CLIENTE EJEMPLO-20111111112", "691391", deb="500,00", saldo="1.500,00"),
    _fila_macro("04/05/26", "N/D DBCR 25413 S/DB TASA GRAL", "0", cred="200,00", saldo="1.300,00"),
    "CUENTA CORRIENTE EN PESOS NRO.: 3-399-0000000002-2",
    "DETALLE DE MOVIMIENTO",
    _ENCABEZADO_MACRO,
    _fila_macro("", "SALDO ULTIMO EXTRACTO AL 30/04/2026", saldo="100,00"),
    _fila_macro("05/05/26", "COMISION TRANSFERE", "82401514", deb="50,00", saldo="50,00"),
    # El saldo no cierra con el anterior: se decide por la posición del importe.
    _fila_macro("05/05/26", "PAGO12345678-LIQ COMER PRISMA", "195774", cred="10,00", saldo="999,99"),
    _fila_macro("", "SALDO FINAL AL DIA 29/05/2026", saldo="999,99"),
])


class ParserMacroV1(unittest.TestCase):

    def setUp(self):
        from parsers import macro
        self.macro = macro
        with mock.patch.object(macro, "pdf_to_text", return_value=TEXTO_MACROV1) as pdf:
            self.movs, self.diag = macro.parser_macro("sintetico.pdf")
        self.llamadas = pdf.call_args_list

    def _parsear(self, textos):
        """textos: {"table": ..., "layout": ...} → (movimientos, llamadas)."""
        def falso(ruta, layout=True, table=False):
            return textos["table" if table else "layout"]
        with mock.patch.object(self.macro, "pdf_to_text", side_effect=falso) as pdf:
            movs, _ = self.macro.parser_macro("sintetico.pdf")
        return movs, pdf.call_args_list

    def test_poppler_primero_y_xpdf_si_no_mejora_no_se_usa(self):
        # El texto sintético tiene una fila que no encadena: se prueba Xpdf,
        # que da lo mismo, y queda el resultado de Poppler.
        self.assertEqual(self.llamadas, [mock.call("sintetico.pdf", layout=True),
                                         mock.call("sintetico.pdf", table=True)])

    def test_texto_limpio_no_consulta_xpdf(self):
        limpio = "\n".join(l for l in TEXTO_MACROV1.split("\n") if "LIQ COMER" not in l)
        movs, llamadas = self._parsear({"layout": limpio, "table": ""})
        self.assertEqual(llamadas, [mock.call("sintetico.pdf", layout=True)])
        self.assertEqual(len(movs), 3)

    def test_xpdf_gana_si_tiene_menos_problemas(self):
        limpio = "\n".join(l for l in TEXTO_MACROV1.split("\n") if "LIQ COMER" not in l)
        movs, _ = self._parsear({"layout": TEXTO_MACROV1, "table": limpio})
        self.assertEqual(len(movs), 3)

    def test_poppler_sin_movimientos_prueba_xpdf(self):
        movs, llamadas = self._parsear({"layout": "", "table": TEXTO_MACROV1})
        self.assertEqual(len(llamadas), 2)
        self.assertEqual(len(movs), 4)

    def test_respaldo_vacio_no_reemplaza_movimientos(self):
        # Poppler con un salto de saldo y Xpdf sin movimientos ("0 problemas"):
        # se quedan las filas de Poppler.
        movs, _ = self._parsear({"layout": TEXTO_MACROV1, "table": ""})
        self.assertEqual(len(movs), 4)

    def test_diagnostico_dice_que_motor_se_uso(self):
        from parsers import macro
        limpio = "\n".join(l for l in TEXTO_MACROV1.split("\n") if "LIQ COMER" not in l)
        casos = [({"layout": limpio, "table": ""}, "Poppler -layout"),
                 ({"layout": "", "table": limpio}, "Xpdf -table (Poppler no encontró movimientos)"),
                 ({"layout": TEXTO_MACROV1, "table": limpio}, "Xpdf -table (menos problemas que Poppler)"),
                 ({"layout": TEXTO_MACROV1, "table": TEXTO_MACROV1},
                  "Poppler -layout (Xpdf no mejoró el resultado)")]
        for textos, esperado in casos:
            with self.subTest(esperado), mock.patch.object(
                    macro, "pdf_to_text",
                    side_effect=lambda r, layout=True, table=False, t=textos: t["table" if table else "layout"]):
                _, diag = macro.parser_macro("sintetico.pdf")
                self.assertEqual(diag.motor, esperado)

    def test_si_xpdf_falla_queda_poppler(self):
        def falso(ruta, layout=True, table=False):
            if table:
                raise RuntimeError("pdftotext falló")
            return TEXTO_MACROV1  # con un salto de saldo: dispara el respaldo
        with mock.patch.object(self.macro, "pdf_to_text", side_effect=falso):
            movs, _ = self.macro.parser_macro("sintetico.pdf")
        self.assertEqual(len(movs), 4)
        with mock.patch.object(self.macro, "pdf_to_text",
                               side_effect=lambda r, layout=True, table=False: "" if not table
                               else (_ for _ in ()).throw(RuntimeError("falló"))):
            with self.assertRaises(RuntimeError):  # sin nada de Poppler, el error se ve
                self.macro.parser_macro("sintetico.pdf")

    def test_sin_poppler_usa_xpdf(self):
        for error in (FileNotFoundError("pdftotext"), RuntimeError("No se encontró Poppler")):
            def falso(ruta, layout=True, table=False, error=error):
                if table:
                    return TEXTO_MACROV1
                raise error
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(self.macro, "pdf_to_text", side_effect=falso):
                movs, _ = self.macro.parser_macro("sintetico.pdf")
                self.assertEqual(len(movs), 4)

    def test_direccion_por_saldo_y_cuentas(self):
        self.assertEqual(len(self.diag.lineas_descartadas), 0)
        filas = [(m["cuenta"], m["descripcion"], m["debito"], m["credito"], m["saldo"]) for m in self.movs]
        self.assertEqual(filas, [
            ("4-399-0000000001-1", "ING TRANSF:CLIENTE EJEMPLO-20111111112", None, 500.0, 1500.0),
            ("4-399-0000000001-1", "N/D DBCR 25413 S/DB TASA GRAL", 200.0, None, 1300.0),
            ("3-399-0000000002-2", "COMISION TRANSFERE", 50.0, None, 50.0),
            ("3-399-0000000002-2", "PAGO12345678-LIQ COMER PRISMA", None, 10.0, 999.99),
        ])
        self.assertEqual([m["saldo_inicial"] for m in self.movs], [1000.0, 1000.0, 100.0, 100.0])

    def test_clasificacion_tras_el_adaptador(self):
        hojas, _ = C.clasificar_hojas({"M": [dict(m, banco="macro") for m in self.movs]})
        self.assertEqual([m["detalle"] for m in hojas["M"]],
                         ["Deudores por venta", "imp 25.413", "Gastos y comisiones Bancarias",
                          "Deudores por venta"])


# ─────────────────────────────────────────────────────────────────────────────
class MotoresPdftotext(unittest.TestCase):
    """Cada modo usa su motor, y el texto llega en UTF-8 (sin "�")."""

    def setUp(self):
        import utils
        self.utils = utils
        self.cache = dict(utils._cache_cmd)
        utils._cache_cmd.clear()

    def tearDown(self):
        self.utils._cache_cmd.clear()
        self.utils._cache_cmd.update(self.cache)

    def _con_binarios(self, en_path, poppler):
        u = self.utils
        return (mock.patch.object(u, "_pdftotext_en_path", return_value=en_path),
                mock.patch.object(u, "_POPPLER_CANDIDATOS", []),
                mock.patch.object(u.os.path, "exists", return_value=True),
                mock.patch.object(u, "_es_poppler", side_effect=lambda r: r in poppler))

    def test_poppler_aunque_xpdf_este_primero_en_el_path(self):
        a, b, c, d = self._con_binarios(["/git/pdftotext", "/poppler/pdftotext"], {"/poppler/pdftotext"})
        with a, b, c, d:
            self.assertEqual(self.utils._cmd_layout(), "/poppler/pdftotext")

    def test_solo_xpdf_en_el_path_falta_poppler(self):
        a, b, c, d = self._con_binarios(["/git/pdftotext"], set())
        with a, b, c, d, mock.patch.object(self.utils, "_cmd_table", return_value="/git/pdftotext"):
            with self.assertRaises(RuntimeError):
                self.utils._cmd_layout()
            self.assertEqual(self.utils.motores_faltantes(), ["poppler"])

    def test_path_relativo_no_se_ejecuta(self):
        u = self.utils
        absoluta = str(RAIZ / "bin")
        path = os.pathsep.join(["bin", ".", "", absoluta])
        with mock.patch.dict(u.os.environ, {"PATH": path}), \
                mock.patch.object(u.os.path, "isfile", return_value=True):
            rutas = u._pdftotext_en_path()
        self.assertEqual([os.path.dirname(r) for r in rutas], [absoluta])

    def test_falta_de_poppler_se_recuerda(self):
        a, b, c, d = self._con_binarios(["/git/pdftotext"], set())
        with a as en_path, b, c, d:
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    self.utils._cmd_layout()
            self.assertEqual(en_path.call_count, 1)

    def test_sonda_de_poppler_con_tiempo_maximo(self):
        u = self.utils
        with mock.patch.object(u.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["x", "-v"], 15)) as run:
            self.assertFalse(u._es_poppler("x"))
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_filtros_de_parsers_sin_palabras_con_tilde(self):
        """Con UTF-8, una palabra con tilde en un filtro empezaría a coincidir y podría
        descartar movimientos. Sólo Galicia las tiene, y siempre con su par «�»."""
        import ast

        def comparados(arbol):
            """Textos que se usan para comparar: listas/tuplas/conjuntos de filtros,
            `"x" in línea` y argumentos de startswith/endswith/find/index/count."""
            for n in ast.walk(arbol):
                if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
                    yield from n.elts
                elif isinstance(n, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops):
                    yield n.left
                elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr in ("startswith", "endswith", "find", "index", "count")):
                    yield from n.args

        encontrados = {}
        for ruta in sorted((RAIZ / "parsers").glob("*.py")):
            for n in comparados(ast.parse(ruta.read_text(encoding="utf-8"))):
                if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and any(ord(ch) > 127 for ch in n.value)):
                    encontrados.setdefault(ruta.name, set()).add(n.value)
        galicia = encontrados.pop("galicia.py")
        self.assertEqual(encontrados, {})
        for texto in galicia - {t for t in galicia if "�" in t}:
            par = "".join("�" if ord(ch) > 127 else ch for ch in texto)
            self.assertIn(par, galicia, texto)

    def test_xpdf_escribe_utf8(self):
        u = self.utils
        hecho = subprocess.CompletedProcess([], 0, stdout="Energía de Córdoba", stderr="")
        with mock.patch.object(u, "_cmd_table", return_value="xpdf"), \
                mock.patch.object(u.subprocess, "run", return_value=hecho) as run:
            self.assertEqual(u.pdf_to_text("x.pdf", table=True), "Energía de Córdoba")
        self.assertEqual(run.call_args.args[0], ["xpdf", "-table", "-enc", "UTF-8", "x.pdf", "-"])
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_bbva_no_pierde_movimientos_con_tilde(self):
        from parsers import bbva
        texto = "\n".join([
            "CC $ 267-000000/1 (Cta.Cte.Bancaria) - Iva-Responsable Inscripto",
            "FECHA   ORIGEN   CONCEPTO                         DÉBITO      CRÉDITO      SALDO",
            "        SALDO ANTERIOR                                                   1.000,00",
            "02/01   D 500    PAGO TARJETA DE CRÉDITO          -100,00                  900,00",
            "03/01            DÉBITO AUTOMÁTICO SEGURO           -50,00                  850,00",
            "Transferencias",
        ])
        with mock.patch.object(bbva, "pdf_to_text", return_value=texto):
            movs, _ = bbva.parser_bbva("sintetico.pdf")
        self.assertEqual([(m["descripcion"], m["debito"], m["saldo"]) for m in movs],
                         [("PAGO TARJETA DE CRÉDITO", 100.0, 900.0),
                          ("DÉBITO AUTOMÁTICO SEGURO", 50.0, 850.0)])


# ─────────────────────────────────────────────────────────────────────────────
class Lotes(unittest.TestCase):

    def test_cada_hoja_con_su_banco_y_su_perfil(self):
        """Galicia (empresa A) y BBVA (empresa B) acumuladas en el mismo libro."""
        perfil_a = {"cliente_id": "a", "razon_social": "ALFA SA", "cuits_propios": ["30111111118"]}
        perfil_b = {"cliente_id": "b", "razon_social": "BETA SRL", "cuits_propios": ["30222222226"]}
        hojas = {
            # El nombre de la hoja dice BBVA, pero las filas son de Galicia.
            "BBVA": [mov("galicia", "TRANSF INMED CP ALFA SA VARIOS BANCO X", debito=10),
                     mov("galicia", "IMP. DEB. LEY 25413", debito=1)],
            "Galicia": [mov("bbva", "D 500 TRANSFERENCIA 30111111118", debito=10),
                        mov("bbva", "D 500 TRANSFERENCIA 30222222226", debito=10),
                        mov("bbva", "IMP.LEY 25413 31/03/25 00009", debito=1)],
        }
        originales = copy.deepcopy(hojas)
        meta = {"BBVA": {"perfil": perfil_a}, "Galicia": {"perfil": perfil_b}}
        salida, rep = C.clasificar_hojas(hojas, meta, CATALOGO)
        self.assertEqual([m["detalle"] for m in salida["BBVA"]],
                         ["Transferencia entre cuentas", "imp 25.413"])
        self.assertEqual([m["detalle"] for m in salida["Galicia"]],
                         ["Proveedores", "Transferencia entre cuentas", "imp 25.413"])
        self.assertEqual([d["regla_id"] for d in rep if d["hoja"] == "BBVA"][1], "GAL_TAX_25413")
        self.assertEqual(hojas, originales)  # no se mutan las filas extraídas
        self.assertEqual(C.pendientes_por_hoja(rep), {"BBVA": 0, "Galicia": 0})

    def test_reporte_csv_solo_pendientes(self):
        _, rep = C.clasificar_hojas({"h": [mov("bancor", "TRANSF.HB.EXENTO", debito=1),
                                           mov("bancor", "RECAUDACION SIRCREB", debito=1)]})
        lineas = C.reporte_pendientes_csv(rep).strip().splitlines()
        self.assertEqual(len(lineas), 2)
        self.assertIn("BCR_AMBIGUOUS_TRANSFER", lineas[1])

    def test_reporte_csv_para_excel_en_espanol(self):
        _, rep = C.clasificar_hojas({"h": [mov("bancor", "=TRANSF.HB.EXENTO", debito=5300000.0),
                                           mov("bancor", "TRANSF.HB.EXENTO", debito=599.89)]})
        filas = [l.split(";") for l in C.reporte_pendientes_csv(rep).strip().splitlines()[1:]]
        self.assertEqual((filas[0][4], filas[0][5]), ("'=TRANSF.HB.EXENTO", "5300000,00"))
        self.assertEqual(filas[1][5], "599,89")


# ─────────────────────────────────────────────────────────────────────────────
def _fila(desc, debito=None, credito=None, saldo=0.0, **extra):
    return {"mes": 2, "fecha": "02/02/2026", "descripcion": desc, "debito": debito,
            "credito": credito, "saldo": saldo, **extra}


class Excel(unittest.TestCase):

    def test_detalle_en_j_o_k(self):
        sin_cuenta = [dict(_fila("IVA", debito=10.0, saldo=90.0), detalle="Iva Credito", saldo_inicial=100.0),
                      dict(_fila("RARO", credito=5.0, saldo=95.0), detalle="#N/D")]
        con_cuenta = [dict(_fila("X", debito=1.0, saldo=9.0), cuenta="267-015530/5", detalle="Proveedores")]
        wb = openpyxl.load_workbook(io.BytesIO(generar_excel({"Sin": sin_cuenta, "Con": con_cuenta})))
        s, c = wb["Sin"], wb["Con"]
        self.assertEqual([x.value for x in s[1]],
                         ["Nro de Mes", "Fecha", "Descripcion", None, "Debito", "Credito", "Saldo",
                          "Saldo calculado", "Diferencia", "Detalle"])
        self.assertEqual(c["J1"].value, "Cuenta")
        self.assertEqual(c["K1"].value, "Detalle")
        self.assertEqual(c["J3"].value, "267-015530/5")
        self.assertEqual(c["K3"].value, "Proveedores")
        self.assertEqual((s["J3"].value, s["J4"].value), ("Iva Credito", "#N/D"))
        self.assertEqual(s["J4"].data_type, "s")
        self.assertIsNone(s["J2"].value)  # SALDO INICIAL sin Detalle
        self.assertIsNone(c["K2"].value)
        self.assertIsNone(s["D3"].value)
        self.assertEqual((s["H3"].value, s["I3"].value), ("=G2+F3-E3", "=H3-G3"))
        self.assertEqual((s["H4"].value, s["I4"].value), ("=H3+F4-E4", "=H4-G4"))
        self.assertEqual((s["E3"].value, s["F4"].value, s["G2"].value), (10.0, 5.0, 100.0))
        self.assertEqual(s.freeze_panes, "A3")
        self.assertEqual(s.column_dimensions["C"].width, 60)
        self.assertEqual(s.column_dimensions["J"].width, 30)
        self.assertEqual(c.column_dimensions["J"].width, 18)
        self.assertEqual(c.column_dimensions["K"].width, 30)
        self.assertEqual(s.max_column, 10)
        self.assertEqual(c.max_column, 11)

    def test_detalle_invalido_no_se_exporta(self):
        with self.assertRaises(ValueError):
            generar_excel({"h": [dict(_fila("X", debito=1.0), detalle="Cuenta 2.1.1")]})

    def test_fila_sin_clasificar_queda_pendiente(self):
        wb = openpyxl.load_workbook(io.BytesIO(generar_excel({"h": [_fila("X", debito=1.0)]})))
        self.assertEqual(wb["h"]["J3"].value, "#N/D")


# ─────────────────────────────────────────────────────────────────────────────
# PDF → parser → clasificación → generar_excel → lectura del XLSX
# PDF de ejemplo (sólo locales, en public/), identificados por los primeros
# 16 caracteres de su SHA-256 → (parser, movimientos esperados).
PDFS = {
    "9a50b4f494a18336": ("bbva", 10),
    "50b6eb148e6fe7ae": ("bancor", 77),
    "1243de3bbabb39cb": ("bancor", 12),
    "7ed43fa2df32fd05": ("nacion", 44),
    "d86663f54fee2f89": ("nacion", 34),
    "b3f911d4f8fe2fa3": ("galicia", 14),
    "0c57d3f1379d796e": ("macrov2", 164),
    "23d7606f3d03935f": ("santander", 34),
    "0190cb4e17db0320": ("santander", 288),
    "9c777e07542770b3": ("macro", 256),
    "6f04f66864e4dee9": ("macro", 6386),  # dos cuentas: caja de ahorro y cuenta corriente
}


def pdfs_de_ejemplo():
    """{hash: ruta} de los PDF de ejemplo presentes en public/."""
    encontrados = {}
    for ruta in (RAIZ / "public").rglob("*.pdf"):
        h = hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]
        if h in PDFS:
            encontrados[h] = ruta
    return encontrados


def _motores_disponibles():
    try:
        from utils import motores_faltantes
        return not motores_faltantes()
    except Exception:
        return False


def _excel_original():
    """generar_excel de la versión anterior a la integración (tests/excel_original.py)."""
    fuente = Path(__file__).with_name("excel_original.py").read_text(encoding="utf-8", newline=chr(10))
    espacio = {}
    exec(compile(fuente, "excel_original.py", "exec"), espacio)
    return espacio["generar_excel"]


@unittest.skipUnless(_motores_disponibles(), "faltan los motores de pdftotext")
@unittest.skipUnless(len(pdfs_de_ejemplo()) == len(PDFS), "faltan los PDF de ejemplo (public/ es sólo local)")
class FlujoPDF(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from parsers import PARSERS
        cls.hojas, cls.crudas = {}, {}
        rutas = pdfs_de_ejemplo()
        for i, (h, (banco, _)) in enumerate(PDFS.items()):
            movs, diag = PARSERS[banco](str(rutas[h]))
            cls.crudas[h] = (movs, diag)
            # Igual que app.py: copia de cada fila con su banco de origen.
            cls.hojas[f"H{i} {banco}"] = [dict(m, banco=banco) for m in movs]
        # Perfil del titular del extracto Santander grande: su CUIT se toma del
        # propio PDF (transferencias "mismo titular"), sin guardarlo en el repo.
        cls.hoja_santander = f"H{list(PDFS).index('0190cb4e17db0320')} santander"
        cuits = {re.search(r"(\d{11})\s*$", m["descripcion"]).group(1)
                 for m in cls.hojas[cls.hoja_santander]
                 if m["descripcion"].startswith("Transf recibida cvu mismo titular")}
        cls.perfil_titular = {"razon_social": "TITULAR DEL EXTRACTO", "cuits_propios": sorted(cuits)}
        cls.meta = {nombre: {"perfil": cls.perfil_titular if nombre == cls.hoja_santander
                             else C.perfil_vacio()}
                    for nombre in cls.hojas}
        cls.antes = copy.deepcopy(cls.hojas)
        cls.salida, cls.reporte = C.clasificar_hojas(cls.hojas, cls.meta, CATALOGO)
        cls.xlsx = generar_excel(cls.salida)
        cls.wb = openpyxl.load_workbook(io.BytesIO(cls.xlsx))

    def test_conteos_y_saldos(self):
        total = 0
        for h, (banco, esperado) in PDFS.items():
            movs, diag = self.crudas[h]
            with self.subTest(pdf=h, parser=banco):
                self.assertEqual(len(movs), esperado)
                self.assertEqual(len(diag.lineas_descartadas), 0)
                inicial = movs[0].get("saldo_inicial")
                if inicial is None:
                    inicial = movs[0]["saldo"] - (movs[0]["credito"] or 0) + (movs[0]["debito"] or 0)
                saldo = Decimal(str(round(inicial, 2)))
                cuenta = movs[0].get("cuenta")
                for m in movs:
                    if m.get("cuenta") != cuenta:  # nueva cuenta → nuevo saldo semilla
                        cuenta = m.get("cuenta")
                        saldo = Decimal(str(m["saldo_inicial"]))
                    saldo += Decimal(str(m["credito"] or 0)) - Decimal(str(m["debito"] or 0))
                    self.assertEqual(saldo, Decimal(str(m["saldo"])).quantize(Decimal("0.01")))
            total += len(movs)
        self.assertEqual(total, 7319)
        self.assertEqual(self.hojas, self.antes)

    def test_xlsx_final(self):
        validos = set(C.CATEGORIAS) | {"#N/D"}
        for nombre, filas in self.salida.items():
            ws = self.wb[nombre]
            col = 11 if any(f.get("cuenta") for f in filas) else 10
            with self.subTest(nombre):
                self.assertEqual(ws.cell(1, col).value, "Detalle")
                self.assertEqual(ws.max_row, len(filas) + 2)
                self.assertIsNone(ws.cell(2, col).value)
                for r, f in enumerate(filas, 3):
                    celda = ws.cell(r, col)
                    self.assertIn(celda.value, validos)
                    self.assertEqual(celda.data_type, "s")
                    self.assertEqual(celda.value, f["detalle"])
                    self.assertEqual(ws.cell(r, 3).value, f["descripcion"])
                    self.assertEqual((ws.cell(r, 5).value, ws.cell(r, 6).value, ws.cell(r, 7).value),
                                     (f["debito"], f["credito"], f["saldo"]))

    def test_columnas_a_i_identicas_a_la_version_original(self):
        original = _excel_original()
        viejo = openpyxl.load_workbook(io.BytesIO(original(self.antes)))
        celdas = 0
        for nombre in self.salida:
            a, b = viejo[nombre], self.wb[nombre]
            ultima = a.max_column  # I o J (Cuenta)
            self.assertEqual(b.max_column, ultima + 1)
            self.assertEqual(a.max_row, b.max_row)
            for fila in a.iter_rows(min_row=1, max_col=ultima):
                for ca in fila:
                    cb = b[ca.coordinate]
                    # repr: los StyleProxy de openpyxl no comparan bien con ==
                    estilo = lambda c: (c.value, c.data_type, c.number_format,  # noqa: E731
                                        repr(c.font), repr(c.fill), repr(c.alignment), repr(c.border))
                    self.assertEqual(estilo(ca), estilo(cb),
                                     f"{nombre}!{ca.coordinate}")
                    celdas += 1
            for letra, dim in a.column_dimensions.items():
                self.assertEqual(dim.width, b.column_dimensions[letra].width)
            self.assertEqual(a.freeze_panes, b.freeze_panes)
        self.assertGreater(celdas, 6000)

    def test_macro_real(self):
        """Distribución del Detalle en los extractos Macro de ejemplo (V2 y dos V1)."""
        esperados = {
            "0c57d3f1379d796e": {"imp 25.413": 34, "#N/D": 26, "Deudores por venta": 25,
                                 "Gastos y comisiones Bancarias": 22, "Iva Credito": 19,
                                 "Iva Percepcion": 18, "Retencion IIBB": 14, "Proveedores": 5, "Caja": 1},
            "9c777e07542770b3": {"Deudores por venta": 173, "imp 25.413": 34, "Retencion IIBB": 15,
                                 "#N/D": 12, "Proveedores": 9, "Gastos y comisiones Bancarias": 7,
                                 "Fondo comun de Inversion": 3, "Iva Credito": 2, "Iva Percepcion": 1},
            "6f04f66864e4dee9": {"Deudores por venta": 6144, "#N/D": 135, "imp 25.413": 39,
                                 "Retencion IIBB": 37, "Proveedores": 27, "Fondo comun de Inversion": 4},
        }
        for h, conteo in esperados.items():
            hoja = f"H{list(PDFS).index(h)} {PDFS[h][0]}"
            rep = [d for d in self.reporte if d["hoja"] == hoja]
            with self.subTest(hoja):
                self.assertEqual(dict(Counter(d["detalle"] for d in rep)), conteo)
                self.assertTrue(all(d["banco"] == "Macro" for d in rep))
                # Los movimientos entre cuentas propias nunca terminan en ventas.
                for d in rep:
                    n = C.normalizar(d["descripcion"])
                    if re.search(r"\b(?:MISMO|M) TIT(?:ULAR)?\b| AUT SDO\b", n):
                        self.assertEqual((d["detalle"], d["regla_id"]), ("#N/D", "MAC_OWN_TRANSFER_REVIEW"))

    def test_santander_real_con_perfil(self):
        """Con perfil: «mismo titular» se resuelve por CUIT (COMMON_OWN_ID); «ctas propias», por texto."""
        self.assertEqual(len(self.perfil_titular["cuits_propios"]), 1)
        rep = [d for d in self.reporte if d["hoja"] == self.hoja_santander]
        propias = [d for d in rep if d["detalle"] == "Transferencia entre cuentas"]
        por_cuit = [d for d in propias if d["regla_id"] == "COMMON_OWN_ID"]
        self.assertTrue(por_cuit)
        self.assertTrue(all(d["descripcion"].startswith("Transf recibida cvu mismo titular") for d in por_cuit))
        self.assertTrue(all(d["regla_id"] in ("COMMON_OWN_ID", "SAN_OWN_EXPLICIT") for d in propias))

    def test_santander_familias_reales_hasta_el_xlsx(self):
        """Las tres familias autorizadas en los dos PDF Santander, sin perfil (como la app)."""
        # (familia, dirección) → (detalle esperado, regla) según la decisión de negocio
        esperado = {
            ("propias", "Credito"): ("Transferencia entre cuentas", "SAN_OWN_EXPLICIT"),
            ("haberes", "Debito"): ("Sueldos a Pagar", "SAN_PAYROLL"),
            ("afip", "Debito"): ("Pago Arca", "SAN_ARCA_DIRECT"),
            ("anul_haberes", "Credito"): ("#N/D", "SAN_PAYROLL_ARCA_REVERSAL_REVIEW"),
            ("haberes_cci", "Debito"): ("#N/D", None),  # variante no autorizada
        }
        familias = (("propias", r"^PAGOS? CTAS? PROPIAS INTERBANKING\b"), ("haberes", r"^PAGO HABERES\b"),
                    ("afip", r"^PAGO AFIP SERVICIO INTERBANKING\b"),
                    ("anul_haberes", r"^ANUL PAGO HABERES\b"), ("haberes_cci", r"^PAGO DE HABERES\b"))
        conteos_esperados = {
            "23d7606f3d03935f": {("propias", "Credito"): 4, ("haberes", "Debito"): 12},
            "0190cb4e17db0320": {("propias", "Credito"): 19, ("haberes", "Debito"): 30, ("afip", "Debito"): 5,
                                 ("anul_haberes", "Credito"): 2, ("haberes_cci", "Debito"): 7},
        }
        for h, esperados in conteos_esperados.items():
            hoja = f"H{list(PDFS).index(h)} santander"
            filas, rep = C.clasificar_hojas({hoja: self.hojas[hoja]}, None, CATALOGO)
            ws = openpyxl.load_workbook(io.BytesIO(generar_excel(filas)))[hoja]
            self.assertEqual(ws["J1"].value, "Detalle")
            conteos = {}
            for i, (mov, dec) in enumerate(zip(self.hojas[hoja], rep)):
                op = C.normalizar(mov["descripcion_operativa"])
                direccion = "Credito" if mov["credito"] else "Debito"
                for familia, patron in familias:
                    if re.search(patron, op):
                        clave = (familia, direccion)
                        conteos[clave] = conteos.get(clave, 0) + 1
                        with self.subTest(pdf=h, fila=i + 3, familia=familia):
                            self.assertEqual((dec["detalle"], dec["regla_id"]), esperado[clave])
                            celda = ws.cell(i + 3, 10)
                            self.assertEqual(celda.value, esperado[clave][0])
                            self.assertEqual(celda.data_type, "s")
            self.assertEqual(conteos, esperados, h)


# ─────────────────────────────────────────────────────────────────────────────
CASOS_SANTANDER = json.loads(Path(__file__).with_name("casos_santander.json").read_text(encoding="utf-8"))


class CorreccionSantander(unittest.TestCase):
    """Tres familias autorizadas: propias, haberes y pago AFIP directo."""

    def test_casos_sinteticos(self):
        self.assertEqual(len(CASOS_SANTANDER), 32)
        for c in CASOS_SANTANDER:
            with self.subTest(c["id"]):
                d = C.categorizar_movimiento(c["movimiento"], c["config_cliente"], CATALOGO)
                self.assertEqual((d["detalle"], d["regla_id"]), (c["detalle_esperado"], c["regla_esperada"]))
                self.assertTrue(d["motivo"])

    @sin_paquete
    def test_misma_decision_que_la_referencia(self):
        sys.path.insert(0, str(PAQUETE))
        import motor_referencia as R
        ref = R.cargar_catalogo(PAQUETE / "reglas_bancarias.json")
        for c in CASOS_SANTANDER:
            a = C.categorizar_movimiento(c["movimiento"], c["config_cliente"], CATALOGO)
            b = R.categorizar_movimiento(c["movimiento"], c["config_cliente"], ref)
            self.assertEqual((a["detalle"], a["regla_id"], a["motivo"]),
                             (b["detalle"], b["regla_id"], b["motivo"]), c["id"])

    def test_reglas_en_el_catalogo(self):
        reglas = {r["id"]: r for r in JSON_CATALOGO["rules"]}
        esperadas = {
            "SAN_OWN_EXPLICIT": ("Transferencia entre cuentas", ["Debito", "Credito"]),
            "SAN_PAYROLL": ("Sueldos a Pagar", ["Debito"]),
            "SAN_ARCA_DIRECT": ("Pago Arca", ["Debito"]),
            "SAN_PAYROLL_ARCA_CREDIT_REVIEW": ("#N/D", ["Credito"]),
            "SAN_PAYROLL_ARCA_REVERSAL_REVIEW": ("#N/D", ["Debito", "Credito"]),
        }
        for rid, (det, dirs) in esperadas.items():
            r = reglas[rid]
            self.assertEqual((r["bank"], r["detalle"], r["directions"], r["enabled"]), ("Santander", det, dirs, True))
            self.assertTrue(r["note"] and r["status"])
        p = {rid: r["priority"] for rid, r in reglas.items()}
        # Antes de proveedores y del crédito residual; después de impuestos y comisiones
        for rid in esperadas:
            self.assertLess(p[rid], p["SAN_PAYMENTS"])
            self.assertLess(p[rid], p["COMMON_RESIDUAL_CREDIT"])
            self.assertGreater(p[rid], p["SAN_FEES"])
        self.assertEqual(p["SAN_ARCA_DIRECT"], p["SAN_ARCA"])
        # SAN_ARCA conserva la condición de segunda línea
        self.assertEqual(reglas["SAN_ARCA"]["secondary_patterns"], [r"^IMP (?:AFIP|ARCA)\b"])

    def test_importe_no_cambia_la_categoria(self):
        for importe in ("0.01", "1", "123456789.99"):
            self.assertEqual(detalle(mov("Santander", "Pago haberes", debito=importe)), "Sueldos a Pagar")
            self.assertEqual(detalle(mov("Santander", "Pagos ctas propias interbanking in", credito=importe)),
                             "Transferencia entre cuentas")

    def test_entradas_invalidas(self):
        for m in (mov("Santander", "Pago haberes", debito=float("nan")),
                  mov("Santander", "Pago haberes", debito=-10),
                  mov("Santander", "Pago afip servicio interbanking", debito=10, tipo_movimiento="Credito"),
                  mov(None, "Pago haberes", debito=10)):
            d = C.categorizar_movimiento(m, None, CATALOGO)
            self.assertEqual((d["detalle"], d["regla_id"]), ("#N/D", None))
            self.assertTrue(d["motivo"])

    def test_conflicto_de_igual_prioridad_sigue_en_nd(self):
        datos = copy.deepcopy(JSON_CATALOGO)
        datos["rules"].append({
            "id": "TEST_CONFLICTO_HABERES", "bank": "Santander", "priority": 50, "detalle": "Proveedores",
            "directions": ["Debito"], "enabled": True, "status": "test",
            "description_patterns": [r"^PAGO HABERES\b"], "predicate": None, "note": ""})
        d = C.categorizar_movimiento(mov("Santander", "Pago haberes", debito=1), None, C.compilar_catalogo(datos))
        self.assertEqual((d["detalle"], d["motivo"]), ("#N/D", "Conflicto de reglas de igual prioridad"))
        self.assertEqual(sorted(d["reglas_en_conflicto"]), ["SAN_PAYROLL", "TEST_CONFLICTO_HABERES"])

    def test_exclusiones_siguen_funcionando_en_transferencias(self):
        perfil = {"contrapartes_excluidas": [{"alias": ["SOCIO EJEMPLO"], "directions": ["Debito"],
                                              "motivo": "socio"}]}
        realizada = mov("Santander", "Transferencia realizada", debito=10,
                        descripcion_secundaria="A socio ejemplo / varios - var / 20111111112")
        self.assertEqual(detalle(realizada, perfil), "#N/D")
        recibida = mov("Santander", "Transferencia recibida", credito=10,
                       descripcion_secundaria="De socio ejemplo / varios - var / 20111111112")
        self.assertEqual(detalle(recibida, perfil), "Deudores por venta")


# ─────────────────────────────────────────────────────────────────────────────
CASOS_MACRO = json.loads(Path(__file__).with_name("casos_macro.json").read_text(encoding="utf-8"))


class CategorizacionMacro(unittest.TestCase):
    """Reglas de Macro (V1 y V2), tomadas del histórico conciliado de MacroV1."""

    def test_casos_sinteticos(self):
        self.assertEqual(len(CASOS_MACRO), 49)
        for c in CASOS_MACRO:
            with self.subTest(c["id"]):
                d = C.categorizar_movimiento(c["movimiento"], c["config_cliente"], CATALOGO)
                self.assertEqual((d["detalle"], d["regla_id"]), (c["detalle_esperado"], c["regla_esperada"]))
                self.assertTrue(d["motivo"])

    @sin_paquete
    def test_misma_decision_que_la_referencia(self):
        sys.path.insert(0, str(PAQUETE))
        import motor_referencia as R
        ref = R.cargar_catalogo(PAQUETE / "reglas_bancarias.json")
        # La referencia es anterior a Macro: se le agregan sólo los alias, sin tocarla.
        alias = {"MACRO": "Macro", "MACROV1": "Macro", "MACROV2": "Macro"}
        with mock.patch.dict(R.BANK_ALIASES, alias):
            for c in CASOS_MACRO:
                a = C.categorizar_movimiento(c["movimiento"], c["config_cliente"], CATALOGO)
                b = R.categorizar_movimiento(c["movimiento"], c["config_cliente"], ref)
                self.assertEqual((a["detalle"], a["regla_id"]), (b["detalle"], b["regla_id"]), c["id"])

    def test_reglas_en_el_catalogo(self):
        self.assertIn("Macro", JSON_CATALOGO["banks"])
        reglas = {r["id"]: r for r in JSON_CATALOGO["rules"] if r["bank"] == "Macro"}
        self.assertEqual(len(reglas), 13)
        self.assertTrue(all(r["enabled"] and r["status"] and r["note"] is not None for r in reglas.values()))
        p = {r["id"]: r["priority"] for r in JSON_CATALOGO["rules"]}
        # Mismo orden que los demás bancos: impuestos → comisiones → FCI → ARCA →
        # revisiones → proveedores → crédito residual.
        orden = ["MAC_TAX_25413", "MAC_IIBB", "MAC_IVA_PER", "MAC_IVA_CRED", "MAC_FEES", "MAC_FCI",
                 "MAC_ARCA_SOCIAL", "MAC_OWN_TRANSFER_REVIEW", "MAC_PAYMENTS", "COMMON_RESIDUAL_CREDIT"]
        self.assertEqual(orden, sorted(orden, key=p.get))
        # TRF MO CCDO imprime el CUIT del propio titular: va antes de COMMON_OWN_ID.
        self.assertLess(p["MAC_PAYMENTS_OTHER_HOLDER"], p["COMMON_OWN_ID"])
        self.assertEqual(p["MAC_IVA_PER_V2"], p["MAC_IVA_PER"])

    def test_importe_no_cambia_la_categoria(self):
        for importe in ("0.01", "1", "123456789.99"):
            self.assertEqual(detalle(mov("macro", "N/D RETENCION ING BRUTOS CORDOBA", debito=importe)),
                             "Retencion IIBB")
            self.assertEqual(detalle(mov("macrov2", "DB TR..AUT.SDO.MISMO TIT.", credito=importe)), "#N/D")

    def test_entradas_invalidas(self):
        for m in (mov("macro", "COMISION TRANSFERE", debito=float("nan")),
                  mov("macro", "COMISION TRANSFERE", debito=-10),
                  mov("macro", "COMISION TRANSFERE", debito=10, credito=10),
                  mov("macro", "   ", debito=10)):
            d = C.categorizar_movimiento(m, None, CATALOGO)
            self.assertEqual((d["detalle"], d["regla_id"]), ("#N/D", None))
            self.assertTrue(d["motivo"])

    def test_otros_bancos_no_toman_reglas_de_macro(self):
        self.assertEqual(detalle(mov("Santander", "N/D DBCR 25413 S/DB TASA GRAL", debito=1)), "#N/D")
        self.assertEqual(detalle(mov("Galicia", "TRF MO CCDO DIST T", debito=1)), "#N/D")


if __name__ == "__main__":
    unittest.main()

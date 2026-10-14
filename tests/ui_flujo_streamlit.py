"""Recorrido de la interfaz Streamlit con Playwright (verificación manual).

    python tests/ui_flujo_streamlit.py

Levanta la app en un puerto local y la usa como un usuario: sube PDF de
Galicia, BBVA y Santander (cambiando el selector entre uno y otro), descarga el
Excel y lo compara con `clasificar_hojas`. Después quita una hoja, comprueba
que el nombre del archivo elegido se conserve, renombra y limpia. La app no
tiene perfil de cliente: todo se categoriza sólo con el PDF.

Requiere playwright + chromium, los dos motores de pdftotext y los PDF de
ejemplo de public/ (sólo locales). No forma parte de `unittest discover`.
"""
import io
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import openpyxl
from playwright.sync_api import expect, sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import conciliacion as C  # noqa: E402
from parsers import PARSERS  # noqa: E402

PUERTO = 8599
# PDF de ejemplo (sólo locales, en public/), reconocidos por hash: el repo no
# guarda sus nombres de archivo.
sys.path.insert(0, str(RAIZ / "tests"))
from test_conciliacion import pdfs_de_ejemplo  # noqa: E402
_PDFS = pdfs_de_ejemplo()
GALICIA = _PDFS["b3f911d4f8fe2fa3"]
BBVA = _PDFS["9a50b4f494a18336"]
SANTANDER = _PDFS["23d7606f3d03935f"]


def esperar_puerto(puerto, segundos=60):
    fin = time.time() + segundos
    while time.time() < fin:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", puerto)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError("Streamlit no levantó")


def main():
    servidor = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(PUERTO),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tmp = Path(tempfile.mkdtemp())
    try:
        esperar_puerto(PUERTO)
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            page = nav.new_page(viewport={"width": 1100, "height": 1400}, accept_downloads=True)
            page.goto(f"http://127.0.0.1:{PUERTO}")
            expect(page.get_by_text("Conversor de Extractos Bancarios").first).to_be_visible(timeout=60000)

            def esperar_quieto():
                page.wait_for_timeout(400)
                expect(page.locator('[data-testid="stStatusWidget"]')).to_have_count(0, timeout=60000)

            def elegir_banco(nombre):
                page.locator('[data-testid="stSelectbox"]').first.click()
                page.locator('li[role="option"]').filter(has_text=nombre).first.click()
                esperar_quieto()

            def agregar_hoja(nombre, pdf):
                campo = page.get_by_label("Nombre de la hoja")
                campo.fill(nombre)
                campo.press("Enter")
                esperar_quieto()
                page.locator('[data-testid="stFileUploader"]').filter(has_text="Subí los PDFs") \
                    .locator('input[type="file"]').set_input_files(str(pdf))
                esperar_quieto()
                page.get_by_role("button", name="Agregar hoja").click()
                esperar_quieto()
                expect(page.locator(".success-box").filter(has_text=nombre)).to_be_visible()

            def caja_hoja(nombre):
                return page.locator(".info-box").filter(has=page.locator(f"strong:text-is('{nombre}')"))

            # 0) No hay sección de perfil: sólo se sube el PDF
            expect(page.get_by_text("Perfil del cliente")).to_have_count(0)
            expect(page.get_by_text("Recategorizar")).to_have_count(0)

            # 1) Tres bancos, cambiando el selector entre uno y otro
            elegir_banco("Galicia")
            agregar_hoja("Gal", GALICIA)
            elegir_banco("BBVA")
            agregar_hoja("BB", BBVA)
            elegir_banco("Santander")
            agregar_hoja("San", SANTANDER)

            # 2) Pendientes por hoja, calculados sin perfil (igual que la app)
            esperado, rep = C.clasificar_hojas(
                {"Gal": [dict(m, banco="galicia") for m in PARSERS["galicia"](str(GALICIA))[0]],
                 "BB": [dict(m, banco="bbva") for m in PARSERS["bbva"](str(BBVA))[0]],
                 "San": [dict(m, banco="santander") for m in PARSERS["santander"](str(SANTANDER))[0]]})
            pend = C.pendientes_por_hoja(rep)
            for hoja in ("Gal", "BB", "San"):
                expect(caja_hoja(hoja)).to_contain_text(f"{pend[hoja]} filas #N/D")
                expect(caja_hoja(hoja)).not_to_contain_text("Perfil")

            # 3) Macro avisa que no tiene reglas
            elegir_banco("MacroV2")
            expect(page.get_by_text("todavía no hay reglas de categorización")).to_be_visible()

            # 4) Nombre del archivo + descarga del Excel
            nombre = page.get_by_label("Nombre del archivo Excel")
            nombre.fill("prueba_ui")
            page.get_by_role("button", name="Aplicar", exact=True).click()
            esperar_quieto()
            with page.expect_download() as info:
                page.get_by_role("button", name="Descargar «prueba_ui.xlsx»").click()
            descarga = info.value
            assert descarga.suggested_filename == "prueba_ui.xlsx", descarga.suggested_filename
            wb = openpyxl.load_workbook(io.BytesIO(Path(descarga.path()).read_bytes()))
            assert wb.sheetnames == ["Gal", "BB", "San"], wb.sheetnames
            for hoja, col in (("Gal", 10), ("BB", 11), ("San", 10)):
                ws = wb[hoja]
                assert ws.cell(1, col).value == "Detalle"
                assert ws.cell(2, col).value is None
                valores = [ws.cell(r, col).value for r in range(3, ws.max_row + 1)]
                assert valores == [m["detalle"] for m in esperado[hoja]], (hoja, valores)
            # Santander: las familias corregidas llegan al Excel descargado
            ws = wb["San"]
            sueldos = sum(1 for r in range(3, ws.max_row + 1) if ws.cell(r, 10).value == "Sueldos a Pagar")
            propias = sum(1 for r in range(3, ws.max_row + 1) if ws.cell(r, 10).value == "Transferencia entre cuentas")
            assert (sueldos, propias) == (12, 4), (sueldos, propias)
            print("descarga OK:", {h: len(esperado[h]) for h in esperado}, "| Santander sueldos/propias:", sueldos, propias)

            # 5) Reporte de pendientes (si hay)
            if sum(pend.values()):
                with page.expect_download() as info:
                    page.get_by_role("button", name="Descargar reporte de pendientes").click()
                csv = Path(info.value.path()).read_text(encoding="utf-8-sig")
                assert len(csv.strip().splitlines()) == sum(pend.values()) + 1

            # 6) Quitar una hoja: el nombre elegido se conserva (regresión del st.rerun)
            page.get_by_role("button", name="🗑️").last.click()
            esperar_quieto()
            expect(caja_hoja("San")).to_have_count(0)
            expect(caja_hoja("Gal")).to_have_count(1)
            expect(page.get_by_role("button", name="Descargar «prueba_ui.xlsx» (2 hojas)")).to_be_visible()
            nombre.fill("otro_nombre")
            nombre.press("Enter")
            esperar_quieto()
            with page.expect_download() as info:
                page.get_by_role("button", name="Descargar «otro_nombre.xlsx» (2 hojas)").click()
            assert info.value.suggested_filename == "otro_nombre.xlsx"
            page.screenshot(path=str(tmp / "antes_de_limpiar.png"), full_page=True)

            # 7) Limpiar
            page.get_by_role("button", name="Limpiar").click()
            esperar_quieto()
            expect(page.locator(".info-box")).to_have_count(0)
            nav.close()
        print("Flujo Streamlit OK")
    finally:
        servidor.terminate()
        servidor.wait(timeout=20)


if __name__ == "__main__":
    main()

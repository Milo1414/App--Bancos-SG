"""Recorrido de la interfaz Streamlit con Playwright (verificación manual).

    python tests/ui_flujo_streamlit.py

Levanta la app en un puerto local, carga dos empresas con perfiles distintos
(Galicia con la empresa A, luego BBVA con la empresa B), cambia el selector,
descarga el Excel y lo compara con `clasificar_hojas`. Después recategoriza,
quita y limpia hojas. Requiere playwright + chromium y los dos motores de
pdftotext. No forma parte de `unittest discover` (no empieza con test_).
"""
import io
import json
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
PERFIL_A = {"cliente_id": "a", "razon_social": "EMPRESA A SA", "alias_titular": [],
            "cuits_propios": ["30111111118"]}
PERFIL_B = {"cliente_id": "b", "razon_social": "EMPRESA B SRL", "alias_titular": [],
            "cuits_propios": ["30222222226"]}
# PDF de ejemplo (sólo locales, en public/), reconocidos por hash: el repo no
# guarda sus nombres de archivo.
sys.path.insert(0, str(RAIZ / "tests"))
from test_conciliacion import pdfs_de_ejemplo  # noqa: E402
GALICIA = pdfs_de_ejemplo()["b3f911d4f8fe2fa3"]
BBVA = pdfs_de_ejemplo()["9a50b4f494a18336"]


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
    (tmp / "perfil_b.json").write_text(json.dumps(PERFIL_B), encoding="utf-8")
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

            perfil_exp = page.locator('[data-testid="stExpander"]').filter(has_text="Perfil del cliente").first

            def abrir_perfil():
                if not perfil_exp.locator("textarea").is_visible():
                    perfil_exp.locator("summary").click()

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

            # 1) Perfil A escrito a mano → Galicia
            expect(perfil_exp.locator("summary")).to_contain_text("Sin perfil")
            abrir_perfil()
            perfil_exp.locator("textarea").fill(json.dumps(PERFIL_A))
            perfil_exp.get_by_role("button", name="Aplicar perfil").click()
            esperar_quieto()
            expect(perfil_exp.locator("summary")).to_contain_text("EMPRESA A SA")
            elegir_banco("Galicia")
            agregar_hoja("Gal", GALICIA)

            # 2) Perfil B desde archivo → BBVA (el selector ya no es Galicia)
            abrir_perfil()
            perfil_exp.locator('input[type="file"]').set_input_files(str(tmp / "perfil_b.json"))
            esperar_quieto()
            perfil_exp.get_by_role("button", name="Aplicar perfil").click()
            esperar_quieto()
            expect(perfil_exp.locator("summary")).to_contain_text("EMPRESA B SRL")
            elegir_banco("BBVA")
            agregar_hoja("BB", BBVA)

            # 3) Un perfil inválido no se aplica
            abrir_perfil()
            perfil_exp.locator("textarea").fill('{"cuits_propios": ["123"]}')
            perfil_exp.get_by_role("button", name="Aplicar perfil").click()
            esperar_quieto()
            expect(page.get_by_text("Perfil inválido")).to_be_visible()
            expect(perfil_exp.locator("summary")).to_contain_text("EMPRESA B SRL")

            # 4) Cada hoja muestra su perfil y sus pendientes
            esperado, rep = C.clasificar_hojas(
                {"Gal": [dict(m, banco="galicia") for m in PARSERS["galicia"](str(GALICIA))[0]],
                 "BB": [dict(m, banco="bbva") for m in PARSERS["bbva"](str(BBVA))[0]]},
                {"Gal": {"perfil": PERFIL_A}, "BB": {"perfil": PERFIL_B}})
            pend = C.pendientes_por_hoja(rep)
            expect(caja_hoja("Gal")).to_contain_text("Perfil: EMPRESA A SA")
            expect(caja_hoja("Gal")).to_contain_text(f"{pend['Gal']} filas #N/D")
            expect(caja_hoja("BB")).to_contain_text("Perfil: EMPRESA B SRL")
            expect(caja_hoja("BB")).to_contain_text(f"{pend['BB']} filas #N/D")

            # 5) Macro avisa que no tiene reglas
            elegir_banco("MacroV2")
            expect(page.get_by_text("todavía no hay reglas de categorización")).to_be_visible()

            # 6) Nombre del archivo + descarga del Excel
            nombre = page.get_by_label("Nombre del archivo Excel")
            nombre.fill("prueba_ui")
            page.get_by_role("button", name="Aplicar", exact=True).click()
            esperar_quieto()
            boton = page.get_by_role("button", name="Descargar «prueba_ui.xlsx»")
            with page.expect_download() as info:
                boton.click()
            descarga = info.value
            assert descarga.suggested_filename == "prueba_ui.xlsx", descarga.suggested_filename
            wb = openpyxl.load_workbook(io.BytesIO(Path(descarga.path()).read_bytes()))
            assert wb.sheetnames == ["Gal", "BB"], wb.sheetnames
            for hoja, col in (("Gal", 10), ("BB", 11)):
                ws = wb[hoja]
                assert ws.cell(1, col).value == "Detalle"
                assert ws.cell(2, col).value is None
                valores = [ws.cell(r, col).value for r in range(3, ws.max_row + 1)]
                assert valores == [m["detalle"] for m in esperado[hoja]], (hoja, valores)
            print("descarga OK:", {h: len(esperado[h]) for h in esperado})

            # 7) Reporte de pendientes (si hay)
            if sum(pend.values()):
                with page.expect_download() as info:
                    page.get_by_role("button", name="Descargar reporte de pendientes").click()
                csv = Path(info.value.path()).read_text(encoding="utf-8-sig")
                assert len(csv.strip().splitlines()) == sum(pend.values()) + 1

            # 8) Recategorizar "Gal" con el perfil actual (B); "BB" no cambia
            page.locator('[data-testid="stExpander"]').filter(has_text="Recategorizar").locator("summary").click()
            page.locator('[data-testid="stMultiSelect"]').click()
            page.locator('li[role="option"]').filter(has_text="Gal").first.click()
            page.keyboard.press("Escape")
            page.get_by_role("button", name="Aplicar a las hojas elegidas").click()
            esperar_quieto()
            expect(caja_hoja("Gal")).to_contain_text("Perfil: EMPRESA B SRL")
            expect(caja_hoja("BB")).to_contain_text("Perfil: EMPRESA B SRL")

            # 9) Quitar una hoja y limpiar
            page.get_by_role("button", name="🗑️").last.click()
            esperar_quieto()
            expect(caja_hoja("BB")).to_have_count(0)
            expect(caja_hoja("Gal")).to_have_count(1)
            expect(page.get_by_role("button", name="Descargar «prueba_ui.xlsx» (1 hojas)")).to_be_visible()
            nombre.fill("otro_nombre")
            nombre.press("Enter")
            esperar_quieto()
            with page.expect_download() as info:
                page.get_by_role("button", name="Descargar «otro_nombre.xlsx» (1 hojas)").click()
            assert info.value.suggested_filename == "otro_nombre.xlsx"
            page.screenshot(path=str(tmp / "antes_de_limpiar.png"), full_page=True)
            page.get_by_role("button", name="Limpiar").click()
            esperar_quieto()
            expect(page.locator(".info-box")).to_have_count(0)
            page.screenshot(path=str(tmp / "final.png"), full_page=True)
            nav.close()
        print("Flujo Streamlit OK")
    finally:
        servidor.terminate()
        servidor.wait(timeout=20)


if __name__ == "__main__":
    main()

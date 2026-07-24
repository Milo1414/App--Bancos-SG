"""
=============================================================================
  CONVERSOR DE EXTRACTOS BANCARIOS A EXCEL — Interfaz Gráfica
  Bancos soportados: Macro | Galicia | Santander | Bancor | BBVA | Nación
=============================================================================

INSTALACIÓN (una sola vez):
  1. Instalar Python 3.10+: https://www.python.org/downloads/
     ⚠️  En la instalación, TILDAR "Add Python to PATH"
  2. Abrir una terminal (cmd) y ejecutar:
       pip install streamlit openpyxl
  3. Instalar Poppler:
       Descargar desde: https://github.com/oschwartz10612/poppler-windows/releases
       Descomprimir en C:\\poppler
       Agregar C:\\poppler\\Library\\bin al PATH del sistema
       (o C:\\poppler\\bin según la versión descargada)

USO:
  1. Abrir una terminal (cmd) en la carpeta donde está este archivo
  2. Ejecutar:  streamlit run app.py
  3. Se abre el navegador automáticamente
  4. Seleccionar banco, subir PDFs, descargar el Excel
=============================================================================
"""

import streamlit as st
import streamlit.components.v1 as components
import os
import tempfile

from utils import motores_faltantes
from parsers import PARSERS
from excel import generar_excel


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN DE BANCOS
#  Cada clave coincide con el parser registrado en PARSERS.
#  "display": nombre que se muestra en el selector.
#  "imagen":  captura de cómo se ve el inicio del extracto (o None si no hay).
#  Un banco puede tener más de un formato → futuras versiones (ej. MacroV2).
# ─────────────────────────────────────────────────────────────────────────────

_RAIZ = os.path.dirname(os.path.abspath(__file__))
CAPTURAS_DIR = os.path.join(_RAIZ, "public", "Captura bancos")

# El logo vive en public/, pero puede estar en la raíz en instalaciones viejas.
LOGO = next(
    (r for r in (os.path.join(_RAIZ, "public", "sg.jpg"), os.path.join(_RAIZ, "sg.jpg"))
     if os.path.exists(r)),
    "",
)

BANCOS = {
    "macro":     {"display": "MacroV1",  "imagen": "MacroV1.PNG"},
    "macrov2":   {"display": "MacroV2",  "imagen": "MacroV2.PNG"},
    "galicia":   {"display": "Galicia",  "imagen": "Galicia.PNG"},
    "santander": {"display": "Santander", "imagen": "Santander.PNG"},
    "bancor":    {"display": "Bancor",   "imagen": "Bancor.PNG"},
    "bbva":      {"display": "BBVA",     "imagen": "BBVA.PNG"},
    "nacion":    {"display": "Nación",   "imagen": "Nacion.PNG"},
}


def display_banco(clave: str) -> str:
    """Nombre a mostrar en el selector para una clave de parser."""
    info = BANCOS.get(clave)
    if info:
        return info["display"]
    return "BBVA" if clave.lower() == "bbva" else clave.capitalize()


def _fijar_scroll_desplegable():
    """Evita que el desplegable del selector "pierda" el primer banco.

    La lista de opciones es virtualizada (react-window): sólo dibuja los ítems
    del rango que cree visible. Al abrirla, Streamlit le pasa un
    `initialScrollOffset` para centrar la opción ya elegida; con Nación (la
    última de 7) ese cálculo da 120px. Pero las 7 opciones entran justas en el
    contenedor (280px de alto, 280px de contenido), así que NO hay overflow y
    ese scroll nunca llega al DOM: el `scrollTop` real queda en 0 mientras
    react-window sigue creyendo que va por 120px, y dibuja desde el índice 1.
    Resultado: MacroV1 no se renderiza y parece que el banco no existe.

    Por eso no alcanzaba con CSS ni con poner `scrollTop = 0`: no había nada
    que scrollear, el estado desincronizado estaba en React. La solución es
    despachar un evento `scroll` sintético: React lee el `scrollTop` real (0),
    corrige su estado y redibuja desde el primer ítem.

    Se identifica el desplegable por `data-baseweb="popover"` (atributo de la
    librería de componentes, más estable que los `data-testid` de Streamlit).
    Si una versión futura cambia esto, el desplegable vuelve a comportarse como
    antes: no rompe nada.
    """
    components.html(
        """
        <script>
        (function () {
            const doc = window.parent.document;

            function redibujarDesdeElPrimero() {
                doc.querySelectorAll('div[data-baseweb="popover"]').forEach(function (pop) {
                    // Una sola vez por desplegable: despachar el evento provoca
                    // un re-render, que a su vez dispara el observer.
                    if (pop.dataset.scrollCorregido === "1") { return; }
                    pop.dataset.scrollCorregido = "1";
                    pop.querySelectorAll("div").forEach(function (caja) {
                        caja.scrollTop = 0;
                        caja.dispatchEvent(new Event("scroll", { bubbles: false }));
                    });
                });
            }

            new MutationObserver(redibujarDesdeElPrimero)
                .observe(doc.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        height=0,
    )


def sufijo_cuenta(cuenta: str) -> str:
    """Sufijo corto para el nombre de hoja cuando el extracto trae varias cuentas.

    BBVA:    "267-015530/5"       → "15530-5"
    MacroV1: "4-399-0950295930-2" → "0950295930-2"
    """
    if "/" in cuenta:
        ultimo = cuenta.split("-")[-1]
        return f"{int(ultimo.split('/')[0])}-{ultimo.split('/')[-1]}"
    partes = cuenta.split("-")
    return "-".join(partes[2:]) if len(partes) > 3 else cuenta


def captura_banco(clave: str):
    """Ruta a la captura del banco, o None si no existe el archivo."""
    info = BANCOS.get(clave)
    if not info or not info.get("imagen"):
        return None
    ruta = os.path.join(CAPTURAS_DIR, info["imagen"])
    return ruta if os.path.exists(ruta) else None


# ─────────────────────────────────────────────────────────────────────────────
#  INTERFAZ GRÁFICA (Streamlit)
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Conversor de Extractos Bancarios",
        page_icon="🏦",
        layout="centered",
    )

    # ── Estilos ──
    st.markdown("""
    <style>
        .stApp { max-width: 800px; margin: 0 auto; }
        div[data-testid="stFileUploader"] {
            border: 2px dashed #1F4E79;
            border-radius: 10px;
            padding: 10px;
        }
        .success-box {
            background: rgba(76, 175, 80, 0.15);
            border-left: 4px solid #4caf50;
            color: inherit;;
            padding: 12px 16px;
            border-radius: 4px;
            margin: 8px 0;
        }
        .info-box {
            background: rgba(31, 78, 121, 0.15);
            border-left: 4px solid #1F4E79;
            color: inherit;
            padding: 12px 16px;
            border-radius: 4px;
            margin: 8px 0;
        }
        /* El componente que fija el scroll del desplegable no debe ocupar
           lugar: es sólo un <script>. */
        div[data-testid="stCustomComponentV1"] {
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
        }
    </style>
    """, unsafe_allow_html=True)

    _fijar_scroll_desplegable()

    col1, col2 = st.columns([1, 3])
    with col1:
        if os.path.exists(LOGO):
            st.image(LOGO, width=150)
    with col2:
        st.title("Conversor de Extractos Bancarios")
        st.caption("Convertí extractos bancarios en PDF a Excel — Macro, Galicia, Santander, Bancor, BBVA, Nación")

    # ── Verificar los dos motores de pdftotext ──
    faltan = motores_faltantes()
    if faltan:
        mensaje = ["⚠️ **Falta al menos un motor de `pdftotext`.**\n"]
        if "poppler" in faltan:
            mensaje.append(
                "**Poppler** (lo usa MacroV1):\n"
                "1. Descargar desde: [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases)\n"
                "2. Descomprimir en `C:\\poppler`\n"
                "3. Agregar `C:\\poppler\\Library\\bin` al PATH del sistema\n"
                "4. Reiniciar esta terminal y volver a ejecutar\n"
            )
        if "xpdf" in faltan:
            mensaje.append(
                "**Xpdf** (lo usan Galicia, Santander, Bancor, BBVA, Nación y MacroV2, "
                "porque son los únicos que necesitan la opción `-table`, que Poppler no tiene):\n"
                "1. Descargar desde: [xpdfreader.com](https://www.xpdfreader.com/download.html)\n"
                "2. Copiar `pdftotext.exe` dentro de la carpeta `bin/` de esta aplicación\n"
            )
        st.error("\n".join(mensaje))
        st.stop()

    # ── Estado de sesión para acumular hojas ──
    if "hojas" not in st.session_state:
        st.session_state.hojas = {}
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

    st.divider()

    # ── Formulario para agregar una hoja ──
    st.subheader("📄 Agregar extracto")

    col1, col2 = st.columns(2)
    with col1:
        banco = st.selectbox(
            "Banco",
            options=list(PARSERS.keys()),
            format_func=display_banco,
        )
    with col2:
        nombre_hoja = st.text_input(
            "Nombre de la hoja",
            max_chars=31,
            key="nombre_hoja",
        )

    # ── Previsualización del banco elegido ──
    captura = captura_banco(banco)
    if captura:
        st.image(
            captura,
            caption=f"Vista previa — así se ve el inicio del extracto de {display_banco(banco)}",
            use_container_width=True,
        )

    archivos = st.file_uploader(
        "Subí los PDFs del extracto",
        type=["pdf"],
        accept_multiple_files=True,
        help="Podés subir varios PDFs del mismo banco/cuenta. Se acumulan en la misma hoja.",
        key=f"pdf_uploader_{st.session_state.uploader_key}",
    )

    # ── Botón para limpiar archivos cargados ──
    if archivos:
        _, col_clear = st.columns([3, 1])
        with col_clear:
            if st.button("✕ Quitar todos los archivos", use_container_width=True):
                st.session_state.uploader_key += 1
                st.rerun()

    if st.button("➕ Agregar hoja", type="primary", use_container_width=True):
        if not nombre_hoja.strip():
            st.warning("Ingresá un nombre para la hoja.")
        elif not archivos:
            st.warning("Subí al menos un PDF.")
        else:
            parser = PARSERS[banco]
            todos_movs = []
            errores = []
            diagnosticos = []

            progress = st.progress(0, text="Procesando PDFs...")
            for idx, archivo in enumerate(archivos):
                try:
                    # Guardar PDF temporalmente para que pdftotext lo lea
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(archivo.read())
                        tmp_path = tmp.name

                    try:
                        movs, diag = parser(tmp_path)
                        todos_movs.extend(movs)
                        diagnosticos.append((archivo.name, banco, diag))
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)

                except Exception as e:
                    errores.append(f"{archivo.name}: {e}")
                finally:
                    progress.progress(
                        (idx + 1) / len(archivos),
                        text=f"Procesando {archivo.name}..."
                    )

            progress.empty()

            if errores:
                for err in errores:
                    st.error(f"❌ {err}")

            # ── Diagnóstico (collapsible) ──
            if diagnosticos:
                with st.expander("📋 Diagnóstico de procesamiento"):
                    for nombre_archivo, banco_nombre, diag in diagnosticos:
                        total = diag.total_lineas
                        con_fecha = diag.lineas_con_fecha
                        parseados = diag.movimientos_parseados
                        descartadas = len(diag.lineas_descartadas)
                        porcentaje = (descartadas / con_fecha * 100) if con_fecha else 0.0

                        st.caption(
                            f"📊 Diagnóstico ({nombre_archivo}): {total} líneas · "
                            f"{con_fecha} con fecha · {parseados} movimientos · "
                            f"{descartadas} descartadas ({porcentaje:.1f}%)"
                        )

                        if porcentaje > 5.0:
                            st.warning(
                                f"⚠️ Se descartaron {descartadas} de {con_fecha} líneas con fecha "
                                f"({porcentaje:.1f}%) en {nombre_archivo}. Revisá el log de diagnóstico."
                            )
                            with st.expander("Ver líneas descartadas"):
                                for d in diag.lineas_descartadas:
                                    st.text(
                                        f"Línea {d['linea_idx']}: [{d['motivo']}] \"{d['contenido']}\""
                                    )

                    # ── Botón de descarga del log (siempre que haya diagnósticos) ──
                    log_lines = []
                    for nombre_archivo, banco_nombre, diag in diagnosticos:
                        total = diag.total_lineas
                        con_fecha = diag.lineas_con_fecha
                        parseados = diag.movimientos_parseados
                        descartadas = len(diag.lineas_descartadas)
                        porcentaje = (descartadas / con_fecha * 100) if con_fecha else 0.0
                        log_lines.append(f"=== Diagnóstico: {nombre_archivo} ===")
                        log_lines.append(f"Banco: {banco_nombre}")
                        log_lines.append(f"Líneas totales: {total}")
                        log_lines.append(f"Líneas con fecha: {con_fecha}")
                        log_lines.append(f"Movimientos parseados: {parseados}")
                        log_lines.append(f"Líneas descartadas: {descartadas} ({porcentaje:.1f}%)")
                        log_lines.append("")
                        if diag.lineas_descartadas:
                            log_lines.append("Líneas descartadas:")
                            for d in diag.lineas_descartadas:
                                log_lines.append(
                                    f"  Línea {d['linea_idx']}: [{d['motivo']}] \"{d['contenido']}\""
                                )
                            log_lines.append("")
                    log_txt = "\n".join(log_lines)
                    st.download_button(
                        label="📋 Descargar log de diagnóstico",
                        data=log_txt,
                        file_name="diagnostico_extractos.txt",
                        mime="text/plain",
                    )

            if todos_movs:
                # Ordenar cronológicamente (stable sort preserva orden interno de cada PDF)
                def fecha_sort_key(m):
                    partes = m["fecha"].split("/")
                    return (int(partes[2]), int(partes[1]), int(partes[0]))
                todos_movs.sort(key=fecha_sort_key)

                base_name = nombre_hoja.strip()

                # Si el extracto trae varias cuentas (BBVA y MacroV1 las traen),
                # va una hoja por cuenta: mezclarlas rompería el saldo arrastrado.
                from collections import defaultdict
                movs_por_cuenta = defaultdict(list)
                for mov in todos_movs:
                    movs_por_cuenta[mov.get("cuenta") or ""].append(mov)

                if len(movs_por_cuenta) > 1:
                    hojas_agregadas = []
                    for cuenta, movs in movs_por_cuenta.items():
                        sheet_name = f"{base_name} - {sufijo_cuenta(cuenta)}"[:31]
                        st.session_state.hojas[sheet_name] = movs
                        hojas_agregadas.append((sheet_name, len(movs)))
                    resumen = " · ".join(f"<strong>{n}</strong> ({c:,})" for n, c in hojas_agregadas)
                    st.markdown(
                        f'<div class="success-box">✅ {resumen} — {len(archivos)} PDF(s)</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    sheet_name = base_name[:31]
                    st.session_state.hojas[sheet_name] = todos_movs
                    st.markdown(
                        f'<div class="success-box">✅ <strong>{sheet_name}</strong>: '
                        f'{len(todos_movs):,} movimientos de {len(archivos)} PDF(s)</div>',
                        unsafe_allow_html=True,
                    )
            elif not errores:
                st.warning("No se encontraron movimientos en los PDFs subidos.")

    # ── Hojas acumuladas ──
    if st.session_state.hojas:
        st.divider()
        st.subheader("📊 Hojas en el Excel")

        for nombre, movs in st.session_state.hojas.items():
            debitos = sum(1 for m in movs if m["debito"] is not None)
            creditos = sum(1 for m in movs if m["credito"] is not None)
            saldo_final = movs[-1]["saldo"] if movs else 0

            col_info, col_del = st.columns([5, 1])
            with col_info:
                st.markdown(
                    f'<div class="info-box">'
                    f'<strong>{nombre}</strong><br>'
                    f'{len(movs):,} movimientos &nbsp;·&nbsp; '
                    f'{debitos:,} débitos &nbsp;·&nbsp; '
                    f'{creditos:,} créditos &nbsp;·&nbsp; '
                    f'Saldo final: {saldo_final:,.2f}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_del:
                st.write("")  # Espaciado
                if st.button("🗑️", key=f"del_{nombre}", help=f"Quitar {nombre}"):
                    del st.session_state.hojas[nombre]
                    st.rerun()

        # ── Botón de descarga ──
        st.divider()

        # El nombre va dentro de un form a propósito. El link de descarga se
        # arma cuando se dibuja el botón, así que si el nombre se tomara del
        # text_input suelto, al escribirlo y clickear "Descargar" de una el
        # archivo bajaba con el nombre ANTERIOR (el click viaja con el link ya
        # dibujado, antes de que Streamlit reciba el texto nuevo). Con el form,
        # el nombre se confirma con Enter o con "Aplicar", y recién ahí se
        # redibuja el botón de descarga — que además muestra el nombre final.
        with st.form("form_nombre_archivo", border=False):
            col_txt, col_ok = st.columns([4, 1])
            with col_txt:
                st.text_input(
                    "Nombre del archivo Excel",
                    value="extractos_bancarios.xlsx",
                    key="nombre_archivo",
                )
            with col_ok:
                st.write("")  # Espaciado para alinear con el input
                st.form_submit_button("Aplicar", use_container_width=True)

        nombre_archivo = st.session_state.get("nombre_archivo", "").strip()
        nombre_archivo = nombre_archivo or "extractos_bancarios.xlsx"
        if not nombre_archivo.lower().endswith(".xlsx"):
            nombre_archivo += ".xlsx"

        col_dl, col_clear = st.columns([3, 1])
        with col_dl:
            excel_bytes = generar_excel(st.session_state.hojas)
            st.download_button(
                label=f"⬇️ Descargar «{nombre_archivo}» ({len(st.session_state.hojas)} hojas)",
                data=excel_bytes,
                file_name=nombre_archivo,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )
        with col_clear:
            if st.button("🔄 Limpiar", use_container_width=True, help="Borrar todas las hojas"):
                st.session_state.hojas = {}
                st.rerun()

    # ── Footer ──
    st.divider()
    st.caption(
        "Bancos soportados: Macro · Galicia · Santander · Bancor · BBVA · Nación &nbsp;|&nbsp; "
        "Requiere Poppler instalado"
    )


if __name__ == "__main__":
    main()

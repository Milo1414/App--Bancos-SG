"""
=============================================================================
  CONVERSOR DE EXTRACTOS BANCARIOS A EXCEL — Interfaz Gráfica
  Bancos soportados: Macro | Galicia | Santander | Bancor | BBVA
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
import os
import sys
import tempfile

from utils import poppler_disponible
from parsers import PARSERS
from excel import generar_excel


def resource_path(relative_path: str) -> str:
    """Devuelve la ruta absoluta a un recurso (bundleado o desarrollo)."""
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


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
    </style>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1, 3])
    with col1:
        st.image(resource_path("sg.jpg"), width=150)
    with col2:
        st.title("Conversor de Extractos Bancarios")
        st.caption("Convertí extractos bancarios en PDF a Excel — Macro, Galicia, Santander, Bancor, BBVA")

    # ── Verificar Poppler ──
    if not poppler_disponible():
        st.error(
            "⚠️ **Poppler no está instalado o no está en el PATH.**\n\n"
            "Este programa necesita `pdftotext` (parte de Poppler) para leer PDFs.\n\n"
            "**Instalación en Windows:**\n"
            "1. Descargar desde: [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases)\n"
            "2. Descomprimir en `C:\\poppler`\n"
            "3. Agregar `C:\\poppler\\Library\\bin` al PATH del sistema\n"
            "4. Reiniciar esta terminal y volver a ejecutar"
        )
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
            format_func=lambda x: "BBVA" if x.lower() == "bbva" else x.capitalize(),
        )
    with col2:
        nombre_hoja = st.text_input(
            "Nombre de la hoja",
            max_chars=31,
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

                sheet_name = nombre_hoja.strip()[:31]
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

        nombre_archivo = st.text_input(
            "Nombre del archivo Excel",
            value="extractos_bancarios.xlsx",
        )
        if not nombre_archivo.endswith(".xlsx"):
            nombre_archivo += ".xlsx"

        col_dl, col_clear = st.columns([3, 1])
        with col_dl:
            excel_bytes = generar_excel(st.session_state.hojas)
            st.download_button(
                label=f"⬇️ Descargar Excel ({len(st.session_state.hojas)} hojas)",
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
        "Bancos soportados: Macro · Galicia · Santander · Bancor · BBVA &nbsp;|&nbsp; "
        "Requiere Poppler instalado"
    )


if __name__ == "__main__":
    main()

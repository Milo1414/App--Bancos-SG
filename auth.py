# ─────────────────────────────────────────────────────────────────────────────
#  LOGIN POR CONTRASEÑA COMPARTIDA (sin base de datos)
#
#  La contraseña se define en los "Secrets" de Streamlit Cloud (o en el archivo
#  local .streamlit/secrets.toml) bajo la clave:  app_password = "..."
#
#  - Si NO hay contraseña configurada (ej. desarrollo local sin secrets), la app
#    se abre sin pedir nada, para no entorpecer las pruebas.
#  - La contraseña NUNCA se guarda en el repo; vive solo en los Secrets.
# ─────────────────────────────────────────────────────────────────────────────

import hmac
import streamlit as st


def _password_configurada() -> str | None:
    """Devuelve la contraseña configurada en los secrets, o None si no hay."""
    try:
        return st.secrets["app_password"]
    except Exception:
        # KeyError (no está la clave) o FileNotFoundError (no hay secrets.toml)
        return None


def requiere_login() -> bool:
    """
    Muestra la pantalla de login si corresponde.
    Devuelve True si el usuario está autenticado (o si no hay contraseña
    configurada); False si debe frenarse el render (contraseña incorrecta o
    aún no ingresada).
    """
    esperada = _password_configurada()

    # Sin contraseña configurada → acceso libre (desarrollo local).
    if not esperada:
        return True

    # Ya autenticado en esta sesión.
    if st.session_state.get("_autenticado"):
        return True

    # ── Pantalla de login ──
    st.markdown("### 🔒 Acceso")
    st.caption("Ingresá la contraseña para usar el conversor.")

    def _verificar():
        ingresada = st.session_state.get("_password_input", "")
        if hmac.compare_digest(str(ingresada), str(esperada)):
            st.session_state["_autenticado"] = True
            # No dejar la contraseña en memoria de sesión.
            st.session_state["_password_input"] = ""
        else:
            st.session_state["_autenticado"] = False
            st.session_state["_login_error"] = True

    st.text_input(
        "Contraseña",
        type="password",
        key="_password_input",
        on_change=_verificar,
    )

    if st.session_state.get("_login_error"):
        st.error("❌ Contraseña incorrecta.")

    return False

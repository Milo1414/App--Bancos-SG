"""
=============================================================================
  RUNNER PARA PYINSTALLER
  Lanza la app Streamlit empaquetada y abre el navegador automáticamente.
=============================================================================
"""

import os
import socket
import sys
import threading
import time
import webbrowser


def is_port_open(port: int, host: str = "localhost") -> bool:
    """Devuelve True si el puerto ya está ocupado."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def open_browser_delayed(url: str, delay: float = 2.5):
    """Espera unos segundos y abre la URL en el navegador predeterminado."""
    time.sleep(delay)
    webbrowser.open(url)


def get_app_path() -> str:
    """Resuelve la ruta absoluta de app.py dentro del bundle o desarrollo."""
    if hasattr(sys, '_MEIPASS'):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "app.py")


def main():
    # Buscar un puerto libre entre 8501 y 8510
    port = 8501
    for p in range(8501, 8511):
        if not is_port_open(p):
            port = p
            break

    app_path = get_app_path()
    url = f"http://localhost:{port}"

    # Abrir navegador en segundo plano
    browser_thread = threading.Thread(
        target=open_browser_delayed,
        args=(url, 3.0),
        daemon=True,
    )
    browser_thread.start()

    # Lanzar Streamlit programáticamente
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--server.port", str(port),
        "--server.headless", "true",
        "--global.developmentMode", "false",
    ]

    from streamlit.web.cli import main as st_main
    st_main()


if __name__ == "__main__":
    main()

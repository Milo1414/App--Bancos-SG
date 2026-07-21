# ─────────────────────────────────────────────────────────────────────────────
#  REGISTRO DE PARSERS
# ─────────────────────────────────────────────────────────────────────────────

PARSERS = {}


def registrar_parser(nombre_banco: str):
    def decorator(func):
        PARSERS[nombre_banco.lower()] = func
        return func
    return decorator


# Importar todos los módulos para que se registren automáticamente
from . import macro, macrov2, galicia, santander, bancor, bbva, nacion

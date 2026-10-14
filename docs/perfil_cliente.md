# Perfil del cliente (posibilidad futura, no activa)

Hoy la app solo pide el PDF. Lo que no se puede categorizar sin un dato extra
del dueño del extracto queda en `#N/D`. Este documento describe cómo se podría
agregar más adelante un perfil de cliente con **campos normales**, para que
menos filas queden pendientes.

El motor ya lo soporta: `clasificar_hojas(hojas, metadatos_hojas, catalogo)` y
`categorizar_movimiento(mov, config_cliente, catalogo)` aceptan un perfil, y
`validar_perfil` lo controla. Solo falta la interfaz.

## Qué resolvería

| Situación | Sin perfil (hoy) | Con perfil |
| --- | --- | --- |
| Transferencia a o desde otra cuenta **de la misma empresa**, cuando el texto del banco no lo dice (por ejemplo «TRANSF INMED CP EMPRESA X SA», «TRANSFERENCIA 30123456789», Santander «Transf recibida cvu mismo titular … /CUIT») | Proveedores, Deudores por venta o `#N/D`, según el caso | Transferencia entre cuentas |
| Pagos a socios, fideicomisos u otras cuentas que no son ninguna de las 13 categorías | Proveedores (si es débito) | `#N/D` |
| Familias ambiguas: Nación «BCA.E.TR.O/BCO», «DEB.TRAN.INTERB-LINK TIT»; Bancor «TRANSF.HB.EXENTO» | `#N/D` | Se resuelven si la contraparte es propia o un tercero conocido |
| Créditos que no encajan en ninguna regla | Deudores por venta | Deudores por venta, o `#N/D` si el cliente desactiva esa regla |

Las transferencias propias que el banco **sí** identifica por texto no necesitan
el perfil: Galicia «TRANSF. PROPIAS», BBVA «MOVIM. ENTRE CUENTAS», Bancor
«TRANS.CR.P/IN-PL.M/T» y Santander «Pagos ctas propias interbanking».

## Formulario propuesto

Un bloque plegable «Datos de la empresa (opcional)», arriba del formulario para
agregar hojas, con estos campos:

| Campo | Tipo de control | Ejemplo | Se guarda como |
| --- | --- | --- | --- |
| Razón social | Texto | `EMPRESA EJEMPLO SA` | `razon_social` |
| Otros nombres con que aparece en el banco | Área de texto, uno por línea | `EMPRESA EJEMPLO S A` | `alias_titular` |
| CUIT de la empresa | Texto; se aceptan varios separados por coma, con o sin guiones | `30-12345678-9` | `cuits_propios` |
| Cuentas, CBU o CVU propios | Área de texto, uno por línea, completos (no solo el final) | `0000000000000000000000` | `cuentas_propias[].referencias_extracto` |
| Contrapartes que no se categorizan | Tabla de 3 columnas: Nombre o CUIT · Aplica a (Pagos / Cobros / Ambos) · Motivo | `SOCIO EJEMPLO` · Pagos · cuenta particular | `contrapartes_excluidas` |
| Terceros conocidos | Área de texto, nombre o CUIT por línea | `PROVEEDOR CONOCIDO SA` | `contrapartes_verificadas` |
| Créditos no identificados van a «Deudores por venta» | Casilla, marcada por defecto | ☑ | `reglas_negocio.creditos_residuales_ventas` |

Botones: «Guardar datos» y «Borrar datos». Al costado, una línea de estado:
«Datos de la empresa: EMPRESA EJEMPLO SA» o «Sin datos de la empresa».

## Reglas que hay que respetar

* **Un campo vacío significa dato desconocido.** Nunca se completa con los datos
  de otra empresa ni con valores de ejemplo.
* **Validar al guardar**, con mensajes claros junto a cada campo:
  * un CUIT debe tener 11 dígitos;
  * no se acepta un nombre que sea solo la forma societaria («SA», «S.R.L.»),
    porque coincidiría con cualquier proveedor «… SA»;
  * se avisa si un nombre es muy corto;
  * se avisa si una cuenta parece un sufijo: hay que cargarla completa.
* **Cada hoja guarda una copia de los datos con que se cargó.** Cambiar los
  datos después no altera las hojas ya cargadas. Si se quiere, un botón
  «Volver a categorizar con los datos actuales» las actualiza, solo para las
  hojas que el usuario elija.
* **Mostrar en cada hoja con qué datos se categorizó**, para que no haya dudas
  al combinar extractos de varias empresas en un mismo Excel.
* **El nombre o CUIT del titular que figura en el encabezado del extracto no
  cuenta como contraparte.** Solo se usan los datos del propio movimiento.
* **Las exclusiones respetan la dirección elegida.** Excluir los pagos a un
  tercero no excluye los cobros de ese mismo tercero.
* **Opcional:** guardar y cargar estos datos como archivo para reutilizarlos
  entre sesiones. La app no tiene base de datos, así que hoy duran lo que dura
  la sesión del navegador.

La versión con edición de JSON existió durante la integración (14/10/2026) y se
quitó por decisión del usuario: la app tiene que funcionar subiendo solo el PDF.

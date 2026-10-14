# Categorización de movimientos (columna Detalle)

Después de extraer los movimientos del PDF, la app asigna a cada uno **una** de
las 13 categorías permitidas o el texto literal `#N/D`. Las reglas son
deterministas: dependen del banco de origen, de la descripción y de la dirección
real del importe. Cuando una regla lo pide, también usan el perfil del cliente.
Funciona sin conexión: no usa LLM, embeddings ni servicios externos.

## Dónde está cada cosa

| Archivo | Qué hace |
| --- | --- |
| `conciliacion.py` | Módulo puro, sin Streamlit. Normaliza, carga y valida el catálogo, clasifica, adapta las filas de los parsers y procesa lotes de hojas. |
| `assets/reglas_bancarias.json` | Catálogo de producción que lee `conciliacion.py` (ruta relativa a `__file__`). Es el del paquete sin los ejemplos de evidencia, que citan clientes reales. Una prueba verifica que ambas copias tengan exactamente las mismas reglas. |
| `assets/capturas/`, `assets/sg.jpg` | Vistas previas de cada banco, con datos ficticios, y el logo. |
| `public/` (**solo local, no se versiona**) | Extractos PDF reales, el paquete completo de conciliación (`conciliaciones_bancarias/`, con `motor_referencia.py` como oráculo) y los originales. Las pruebas que lo necesitan se saltean si no está. |
| `parsers/santander.py` | Ahora guarda también `descripcion_operativa` (primera línea) y `descripcion_secundaria` (continuaciones). `descripcion` exporta el mismo texto que antes. |
| `excel.py` | Agrega la columna **Detalle** al final. |
| `app.py` | Asigna el banco a cada fila, guarda el perfil de cliente por hoja y clasifica antes de exportar. |
| `tests/test_conciliacion.py` | Regresiones: `python -m unittest discover -s tests -v`. |
| `tests/ui_flujo_streamlit.py` | Recorrido de la interfaz con Playwright: `python tests/ui_flujo_streamlit.py`. |

## API de `conciliacion.py`

```python
cargar_catalogo(path=None)                       # valida y precompila; queda en caché
categorizar_movimiento(mov, config_cliente=None, catalogo=None)
    # -> {"detalle", "regla_id", "motivo", "tipo_movimiento", "descripcion_normalizada", ...}
clasificar_hojas(hojas, metadatos_hojas, catalogo)
    # -> (copias de las filas con "detalle", reporte con una decisión por fila)
adaptar_movimiento(fila_parser)                  # fila de un parser -> contrato del clasificador
validar_perfil(perfil) / perfil_vacio() / reporte_pendientes_csv(reporte)
```

Al cargar el catálogo se rechazan IDs duplicados, expresiones inválidas,
categorías fuera de la lista (incluida una con espacio final), predicados,
bancos o direcciones desconocidos y reglas sin condiciones. La resolución sigue
el JSON: se evalúa primero la menor prioridad y se juntan **todas** las reglas
que cumplen esa prioridad. Si dan detalles distintos, el resultado es `#N/D`
con `reglas_en_conflicto`.

### Contrato y adaptador

Los parsers entregan `mes`, `fecha`, `descripcion`, `debito`, `credito` y
`saldo`, y a veces `saldo_inicial` y `cuenta`. `debito` y `credito` son
magnitudes positivas; la columna que no corresponde queda en `None`. El
adaptador pasa al clasificador una **lista blanca** de campos:

* `banco`: lo agrega `app.py` con `dict(mov, banco=banco)` en el momento de
  procesar cada PDF. Nunca se deduce del nombre de la hoja ni del archivo, y
  tampoco del selector actual.
* `descripcion`: es `descripcion_operativa` si el parser la separó (Santander) y
  `descripcion` en los demás casos. También pasa `descripcion_secundaria`.
* `debito` y `credito` pasan sin reconvertirlos ni cambiarles el signo. La
  dirección sale de la columna no nula. `importe` con signo (+ crédito,
  − débito) y `tipo_movimiento` se aceptan si existen.
* `contraparte_nombre`, `contraparte_cuit`, `contraparte_cuenta` y
  `contraparte_tercero_verificado`: solo si el parser los obtiene del propio
  movimiento. Hoy ningún parser los entrega.
* **No** pasan `cuenta` (es la cuenta bancaria de origen, no la contraparte),
  Detalle previo, cuenta contable, notas, número de fila ni nombre de archivo.

Devuelven `#N/D` con su motivo: un banco ausente o desconocido, una descripción
vacía, un importe ausente, cero, no numérico, no finito, booleano o negativo,
DB y CR a la vez, o un `tipo_movimiento` que contradiga los importes.

## Perfil del cliente

El perfil usa la estructura de `config_cliente_ejemplo.json`. En la app se
carga o edita en **👤 Perfil del cliente**: se puede subir un `.json` o
pegarlo, y después hay que pulsar «Aplicar perfil». Antes de aplicarlo se
valida: un CUIT debe tener 11 dígitos y las direcciones solo pueden ser
`Debito` o `Credito`. El perfil inicial está vacío. Una lista vacía significa
*dato no configurado* y nunca se completa con los datos de otra empresa.

* Al agregar una hoja se guarda una **copia** del perfil actual en
  `st.session_state.meta_hojas[nombre]`, un diccionario paralelo a
  `st.session_state.hojas`, que mantiene su estructura. Cuando el PDF se divide
  por cuenta, cada hoja recibe su copia. Al reemplazar, quitar o limpiar hojas
  también se actualizan sus metadatos.
* Cambiar el perfil **no** modifica las hojas ya cargadas. Para aplicarlo a
  algunas está **🔁 Recategorizar con el perfil actual**, que solo afecta a las
  hojas elegidas.
* Cada hoja muestra su perfil y cuántas filas tienen `#N/D`. El botón
  «Descargar reporte de pendientes» entrega un CSV con hoja, fila de Excel,
  regla, motivo y conflictos. Esos datos no se agregan al Excel.

## Excel

| Columnas | Contenido |
| --- | --- |
| A–C | Nro de Mes, Fecha, Descripcion |
| D | vacía |
| E–I | Debito, Credito, Saldo, Saldo calculado, Diferencia (mismas fórmulas) |
| J | Cuenta (solo si la hoja tiene ese dato) |
| **J o K** | **Detalle**: J si la hoja no tiene Cuenta y K si la tiene. La posición se decide hoja por hoja. |

Detalle se escribe como texto: `#N/D` es una cadena (`data_type == "s"`) y no
un error de Excel. La fila SALDO INICIAL no lleva Detalle. Si llegara un valor
fuera de las 13 categorías, `generar_excel` falla en lugar de escribirlo.

## Macro

MacroV1 y MacroV2 siguen extrayendo igual que antes. El catálogo no tiene reglas
validadas para Macro, así que sus movimientos quedan en `#N/D` con el motivo
*Banco sin reglas validadas (Macro)*. La app lo avisa al elegir Macro en el
selector. Para incorporarlo hacen falta extractos Macro con Detalle conciliado
y casos esperados verificados.

## Qué se verificó (14/10/2026)

| Prueba | Resultado |
| --- | --- |
| `verificar_casos.py` (referencia, antes y después) | 108/108 |
| Los 108 casos desde la API de `conciliacion.py` | 108/108. También coinciden `regla_id` y `motivo` con la referencia en los 108. |
| Nueve PDF → parser → clasificación → `generar_excel` → lectura del XLSX | 677 movimientos (10, 77, 12, 44, 34, 14, 164, 34 y 288), 0 líneas con fecha descartadas y el saldo encadenado en Decimal coincide en todas las filas. Todas las celdas Detalle son una de las 13 categorías o `#N/D` y son texto. |
| A–I/J contra el `excel.py` original (copia en `tests/excel_original.py`) | Valores, fórmulas, formato numérico, fuentes, rellenos, alineación, bordes, anchos y `freeze_panes` iguales en las 6.267 celdas. La única diferencia es la columna Detalle agregada. |
| `descripcion` de los parsers | Igual a la versión original en los nueve PDF, Santander incluido. |
| MacroV2 | 164 filas extraídas, todas `#N/D` con el motivo de Macro. |
| Santander, segunda línea (sintético pasado por el parser real) | PAGO DE SERVICIOS + `IMP.AFIP: …` da Pago Arca (SAN_ARCA). Sin beneficiario o con otro servicio (EPEC) da `#N/D`. El número de página del pie no se toma como segunda línea y el titular/CUIT del encabezado no se adjunta. |
| Santander real (extracto de 288 movimientos) con perfil de su titular | «Transf recibida cvu mismo titular … /CUIT propio» da Transferencia entre cuentas (COMMON_OWN_ID). |
| `auditoria_diferencias.csv` (261 filas) con perfil vacío | Las 181 filas que no dependen del perfil coinciden con la predicción de referencia (detalle y regla). Las 80 restantes son COMMON_OWN_ID y necesitan el perfil del cliente, que el CSV no incluye. |
| Casos borde | Prefijos D/C, palabras IVA/CRÉDITO, prioridades frente al crédito residual, percepción antes de IVA, e-cheque de Nación, exclusión solo en débito, pies con impuestos y titular, familias ambiguas con y sin identidad, conflicto de igual prioridad, etiquetas históricas ignoradas, importe sin efecto dentro de una dirección, entradas inválidas, banco desconocido, Cuenta de origen sin uso como contraparte, catálogo y perfil sin mutar. |
| Interfaz Streamlit con Playwright | Perfil A escrito a mano + Galicia. Después, perfil B desde archivo + BBVA con el selector cambiado. Un perfil inválido se rechaza. Cada hoja muestra su perfil y sus pendientes. MacroV2 muestra el aviso. La descarga con nombre propio coincide celda a celda con `clasificar_hojas` (Detalle en J para Galicia y en K para BBVA). Después se probó el CSV de pendientes, la recategorización de una sola hoja, quitar una hoja, renombrar, volver a descargar y limpiar. |

### Qué **no** se verificó

* **Los cinco Excel históricos no están en el proyecto**, así que no se repitió
  la comparación de 12.348 filas. El 97,89 % de `validacion_corpus.json` es el
  dato retrospectivo del paquete, sobre el mismo corpus del que salieron las
  reglas. No mide la precisión en extractos nuevos ni es una garantía contable.
  El único `.xlsx` de `public/` es una salida de esta app sin Detalle y no sirve
  para esa comparación.
* No hay un PDF de **MacroV1**, así que su parser no se probó con un archivo real.
* SAN_ARCA solo se probó con texto sintético: los PDF Santander disponibles no
  incluyen un PAGO DE SERVICIOS con IMP.AFIP.
* No se desplegó en Streamlit Cloud.

## Hallazgos para revisar (no se agregaron reglas)

Los dos PDF Santander tienen familias reales que el catálogo no cubre. Con un
perfil vacío quedan en `#N/D` o caen en la regla de crédito residual. No se
inventaron reglas porque no hay Detalle conciliado de estos extractos:

* `Pagos ctas propias interbanking in` + nombre/CUIT del titular (**crédito**)
  no pertenece a la familia de transferencia de la referencia, así que hoy va a
  **Deudores por venta** aunque el texto dice «propias». Es la candidata más
  clara para una regla `SAN_OWN_EXPLICIT`, una vez que se valide.
* `Pago haberes` / `Pago de haberes por cci` (débito) da `#N/D`, cuando podría
  ser Sueldos a Pagar.
* `Pago afip servicio interbanking` (débito) da `#N/D`, cuando podría ser Pago
  Arca.
* `Iva percepcion rg 2408`, `II BB rta financiera cordoba`, `Pago interbanking
  b2b`, `Debito automatico`, `Transferencia inmediata` y otras familias similares
  dan `#N/D`.

## Revisión posterior (14/10/2026)

* **Perfil:** se rechazan las claves desconocidas, que antes se ignoraban sin
  aviso. Por ejemplo, con `cuit_propios` en lugar de `cuits_propios` el perfil
  parecía configurado sin estarlo. También se rechazan los alias que son solo la
  forma societaria (`SA`, `S.R.L.`…), porque convertían en «propio» cualquier
  pago a una «… SA». Un alias corto genera un aviso. Un `null` en una lista
  equivale a «no configurado» y ya no hace caer la API.
* **Interfaz:** avisa cuando hay cambios en el perfil que todavía no se
  aplicaron. Si falta el catálogo, muestra el error y sigue exportando con
  Detalle en `#N/D`, en lugar de hacer caer la página.
* **CSV de pendientes:** los importes van con coma decimal (`599,89`) para Excel
  en español. Los textos que Excel tomaría como fórmula llevan un `'` adelante.
* **Despliegue y datos privados:** `public/` dejó de versionarse (está en
  `.gitignore`) y se quitó de todo el historial del repositorio. Lo que la app
  necesita está en `assets/`: las capturas con datos ficticios, el logo y el
  catálogo sin evidencia. Los PDF de prueba se reconocen por su hash, así el
  repositorio no guarda sus nombres.

## Corrección adicional

Al probar la interfaz apareció un error que **ya existía** en la versión
original: después de quitar una hoja, el botón de descarga volvía a
`extractos_bancarios.xlsx` aunque el campo siguiera mostrando el nombre elegido.
La causa era que el `st.rerun()` de esos botones corta la corrida antes de
dibujar el campo y Streamlit descarta su estado. Ahora el nombre confirmado
también se guarda en `st.session_state.nombre_archivo_ok`.

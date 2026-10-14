# Corrección Santander: propias, haberes y pago AFIP directo (14/10/2026)

Registro de la corrección pedida en `PROMPT_01_CORREGIR_SANTANDER` (en `public/`,
solo local). Estas son las tres decisiones de negocio que autorizó el usuario:

| Descripción operativa | Dirección | Detalle |
| --- | --- | --- |
| Pagos ctas propias interbanking | Crédito o débito | Transferencia entre cuentas |
| Pago haberes | Débito | Sueldos a Pagar |
| Pago afip servicio interbanking | Débito | Pago Arca |

Las categorías salen de esa decisión. **No** salen del Detalle histórico: el
Excel histórico conciliado de Santander no contiene ninguna de estas tres
familias, así que no hay evidencia histórica para comparar.

## Reglas agregadas al catálogo

Se agregaron en `public/conciliaciones_bancarias/reglas_bancarias.json`, con su
evidencia, y en `assets/reglas_bancarias.json`, la copia de producción sin
evidencia. Una prueba exige que ambas copias tengan las mismas reglas.

| ID | Prioridad | Dirección | Patrón (texto normalizado) | Detalle |
| --- | ---: | --- | --- | --- |
| `SAN_ARCA_DIRECT` | 40 | Débito | `^PAGO AFIP SERVICIO INTERBANKING\b` | Pago Arca |
| `SAN_OWN_EXPLICIT` | 46 | Débito y crédito | `^PAGOS? CTAS? PROPIAS INTERBANKING\b` | Transferencia entre cuentas |
| `SAN_PAYROLL` | 50 | Débito | `^PAGO HABERES\b` | Sueldos a Pagar |
| `SAN_PAYROLL_ARCA_CREDIT_REVIEW` | 72 | Crédito | `^PAGO HABERES\b`, `^PAGO AFIP SERVICIO INTERBANKING\b` | `#N/D` |
| `SAN_PAYROLL_ARCA_REVERSAL_REVIEW` | 72 | Débito y crédito | `ANUL/ANULACION/DEV/DEVOLUCION/REVERSO/REINTEGRO (DE) PAGO (DE) HABERES` y `… PAGO AFIP` | `#N/D` |

### Por qué estas prioridades

* **40, 46 y 50 están entre las comisiones (30) y los pagos a proveedores
  (80).** Así, «COMISION PAGO HABERES» y «COM PAGO AFIP …» siguen siendo
  *Gastos y comisiones Bancarias*, porque los patrones nuevos están anclados al
  comienzo del texto. Además, todo se resuelve antes de Proveedores y antes del
  crédito residual (90).
* **`SAN_ARCA_DIRECT` comparte la prioridad 40 con `SAN_ARCA`, sin choque.**
  `SAN_ARCA` sigue exigiendo PAGO DE SERVICIOS más una segunda línea
  IMP.AFIP/IMP.ARCA; un PAGO DE SERVICIOS sin beneficiario o con EPEC sigue en
  `#N/D`.
* **`SAN_OWN_EXPLICIT` usa la prioridad 46, igual que las otras reglas de
  cuentas propias por texto** (Galicia, BBVA, Bancor). No exige nombre ni CUIT
  del cliente: el banco ya dice «ctas propias».
* **Los dos bloqueos (72) van antes del crédito residual.** Sin ellos, un
  crédito con estos textos o un reverso («Anul pago haberes por cci») caía en
  *Deudores por venta*. El bloqueo genérico de reversos no lo detectaba, porque
  busca «ANULACION» y no «ANUL».

### Decisiones de implementación

* **No se amplió la «familia de transferencia»** (`_FAMILIA_TRANSFERENCIA` en
  producción, `TRANSFER_FAMILY` en `motor_referencia.py`). Esa familia solo se
  usa para buscar la identidad del titular y aplicar exclusiones de
  contrapartes. «Pagos ctas propias» ya es propia por texto, y la contraparte de
  esa operación es el mismo titular, así que una exclusión de un tercero no
  corresponde. Por eso `motor_referencia.py` **no se modificó**, y producción y
  referencia siguen dando la misma decisión, con el mismo detalle, regla y
  motivo, en los 108 casos originales y en los 32 nuevos.
* **La variante «Pago de haberes por cci» (7 débitos en un PDF) queda en
  `#N/D`.** No está en la tabla autorizada; si corresponde a Sueldos, hace falta
  confirmarlo. Su reverso, «Anul pago haberes por cci» (2 créditos), queda
  bloqueado como `#N/D` por `SAN_PAYROLL_ARCA_REVERSAL_REVIEW`.
* **Las exclusiones de contrapartes siguen funcionando** en las transferencias
  Santander de la familia («Transferencia realizada/recibida»), con su
  dirección. No se aplican a las tres familias nuevas.

## Conteos reales en los PDF

Los PDF se identifican por los primeros 16 caracteres de su SHA-256; el
repositorio no guarda sus nombres. Los conteos se obtuvieron al parsear los PDF
y coinciden con los de la revisión original.

| PDF (sha256) | Movs. | Propias (créditos) | Haberes (débitos) | AFIP directo (débitos) | «Pago de haberes por cci» (débitos, sin autorizar) | «Anul pago haberes por cci» (créditos) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `23d7606f3d03935f` | 34 | 4 | 12 | 0 | 0 | 0 |
| `0190cb4e17db0320` | 288 | 19 | 30 | 5 | 7 | 2 |
| **Total** | 322 | **23** | **42** | **5** | 7 | 2 |

Resultado en el XLSX final, sin perfil de cliente, igual que en la app:

* las 23 propias dan *Transferencia entre cuentas*;
* las 42 de haberes dan *Sueldos a Pagar*;
* las 5 de AFIP directo dan *Pago Arca*;
* las 7 «por cci» y los 2 reversos dan `#N/D`, como texto.

## Pruebas

| Prueba | Resultado |
| --- | --- |
| `verificar_casos.py` (referencia, catálogo actualizado) | 108/108, mismas expectativas originales |
| 108 casos desde `conciliacion.py` + igualdad con la referencia | 108/108; detalle, regla y motivo iguales |
| `tests/casos_santander.json`: 32 casos sintéticos | 32/32 en producción y en la referencia. Cubren: propias en crédito y débito con perfil vacío, con una empresa nueva y con el crédito residual desactivado; variantes de puntuación, espacios y datos posteriores; haberes y AFIP en débito; sus créditos y reversos en `#N/D`; comisiones; PAGO DE SERVICIOS con y sin IMP.AFIP; textos en la segunda línea o en el pie; DB y CR simultáneos; importe cero; y el mismo texto en otro banco |
| Familias reales en los dos PDF Santander → XLSX | Conteos y categorías de la tabla anterior, celda J como texto |
| Nueve PDF frente a la versión original | 677 movimientos idénticos en fecha, descripción, débito/crédito, saldo, orden y cuenta, sin líneas descartadas |
| A–I/J del Excel frente al `excel.py` original | Valores, fórmulas y formatos iguales; Detalle en J sin Cuenta y en K con Cuenta, y SALDO INICIAL sin Detalle |
| Conflicto de igual prioridad (regla sintética que choca con `SAN_PAYROLL`) | `#N/D` con `reglas_en_conflicto` |
| Interfaz (Playwright) | Sin perfil. Galicia, BBVA y Santander con el selector cambiado; la descarga coincide con la clasificación, con 12 sueldos y 4 propias en la hoja Santander; reporte CSV; quitar una hoja conserva el nombre del archivo; renombrar y limpiar |
| `python -m unittest discover -s tests` | 51 pruebas OK |

## Límites

* **El 97,89 % histórico no se recalculó.** Los cinco Excel originales ahora
  están en `public/Conciliaciones Excels/` (solo locales), pero esta corrección
  no tiene muestras en ellos y el pedido no incluye repetir esa comparación.
* **Las reglas se basan en decisiones de negocio y en dos PDF.** No miden la
  precisión en extractos nuevos.
* Siguen sin regla, en `#N/D`, otras familias Santander: «Pago de haberes por
  cci», «Pago interbanking b2b», «Iva percepcion rg 2408», «II BB rta
  financiera cordoba», «Debito automatico» y «Transferencia inmediata».
* No hay un PDF de MacroV1. Macro sigue sin reglas y Plazo Fijo sigue
  desactivado.

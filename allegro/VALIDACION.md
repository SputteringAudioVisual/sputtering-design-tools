# Validación

## Versión 0.3.0: revisión global antes de fabricar

Prueba nativa en Allegro 17.2 P028 sobre una copia desechable con 303 pines, 10 vías y 15 slots ovales metalizados. La PCB original conserva su SHA-256 anterior a las pruebas.

- Auditorías sin cambios: máscara OBLONG_X idéntica, vías medidas en todas las capas y ancho mínimo/máximo real de las reglas conservadas. Una regla de prueba con ancho incorrecto se detecta y su asignación se revierte.
- Se sustituyen cuatro vías de alimentación de 0,60/0,30 a 0,80/0,40 mm mediante un padstack ya admitido por su regla. Se preservan red, posición, capas, propiedades y conexión a pistas; los pines y slots permanecen iguales.
- Se recrean cuatro referencias ausentes en el origen de su símbolo. Las existentes se conservan; la posición final de las nuevas requiere revisión manual.
- Fallos deliberados después de modificar vías, referencias y films: las tres operaciones revierten sus cambios. Los backups consecutivos funcionan con la carpeta ya existente y preservan la ruta de la placa activa.
- La exportación se bloquea tras corregir vías hasta actualizar shapes y DRC. La revisión termina con cero shapes desactualizados y dos DRC de la placa, comunicados para revisión.
- Se retiran TOP/BOTTOM antiguos y se comprueban exactamente siete films. Repetir vías, referencias, films y carga sin cambios no reaplica modificaciones.
- El ZIP contiene siete Gerber, un NC Drill circular y un NC Route con 15 slots metalizados. Comprobación independiente CRC/SHA-256 y de las posiciones y dimensiones de los 15 slots: 2,20 × 1,10 mm.

NC Drill puede terminar con éxito aunque omita los slots: el log indica que necesitan NC Route. La nueva validación detectó la ausencia de los 15 slots e impidió crear ese ZIP incompleto. Ahora se ejecuta `ncroute` y se verifica el recuento por metalización. Se detectan avisos WARNING en los logs aunque el proceso devuelva cero.

Test nativo: [tests/regression_030.il](tests/regression_030.il), **`REGRESSION_030_ALL_PASS` / `RESULT (t)`**. Requiere una copia con al menos una vía incorrecta, una referencia ausente y un slot oval metalizado, y reglas conservadas acordes al perfil. Cárgalo tras cargar las utilidades y ejecuta `skill pcbRegressionRun()` solo sobre esa copia; genera backups, fabricación y `validated.brd`. No se distribuye ninguna placa personal.

Pruebas de instalación y empaquetado: `python -m unittest discover -s tests -p 'test_*.py' -v` desde `allegro/`. Once casos cubren rutas con espacios/ñ, integridad, versiones protegidas, archivos ausentes/truncados, errores, slots ausentes, inclusión de NC Route por metalización y avisos escritos con estado cero.

Límites: no se ha realizado inspección visual CAM ni fabricación física de esta versión, ni se han certificado todas las jerarquías de grupos y caras de componentes. La herencia ambigua se omite. Slots rectangulares, rutas con arcos/compensación y padstacks avanzados requieren un flujo específico. Estos ensayos no aprueban la PCB para fabricar.

## Versión 0.2.2: información directa en consola

El usuario confirmó que `pcb_mascara_revisar` ya responde con 0.2.1, pero `pcb_utilidades_info` seguía sin mostrar salida en su sesión. La información utiliza ahora `axlUIWPrint(nil ...)`, que escribe directamente en la ventana principal sin depender del búfer de `printf`. Se incorpora el alias `pcb_info` y se conserva `pcb_utilidades_info`.

La prueba nativa en Allegro 17.2 P028 ejecutó ambos nombres desde el intérprete y comprobó sus alias, la versión y la función directa: **`INFO_ALIASES_PASS 0.2.2`**. Los tres mensajes informativos aparecen completos en la salida del proceso para ambas llamadas. La prueba no modifica la placa. Posteriormente, el usuario confirmó en su sesión gráfica la recarga 0.2.2 y la salida completa de `pcb_info`.

El usuario ejecutó además `pcb_fab_auditar` y `pcb_fab_exportar`: generó el paquete **v003** dentro del proyecto con manifiesto 0.2.2. Se comprobó la estructura de siete Gerber y un archivo de taladrado completos y la integridad SHA-256 de todas las entradas incluidas en el manifiesto del ZIP. Artwork devolvió avisos (1); el taladrado terminó correctamente (0). El manifiesto conserva `REQUIERE_REVISION_AVISOS`.

En esa placa, los avisos de artwork son DRC desactualizados y ocho ubicaciones de un padstack sin pad regular en TOP/BOTTOM. NC Drill generó automáticamente su tabla de herramientas. Estos hallazgos pertenecen a la placa probada; no se han corregido ni se consideran aprobación para fabricar. No se publican sus archivos ni rutas personales en el repositorio.

## Versión 0.2.1: ejecución de los nombres cortos

En una sesión gráfica del usuario, las llamadas directas `skill pcbMaskApply()`, `skill pcbMaskAudit()`, `skill pcbAplicarAnchos()` y `skill pcbAnchosAuditar()` respondieron, mientras que algunos accesos registrados no mostraban salida. Una prueba sin interfaz gráfica con los registros antiguos sí ejecutó todos los nombres; por tanto, no se reprodujo allí el silencio de esa sesión.

La versión 0.2.1 define los nombres públicos y de compatibilidad mediante `axlSetAlias` con las mismas llamadas directas que funcionaron. Retira antes los registros propios anteriores y verifica los valores mediante `axlGetAlias`. No modifica las funciones de máscara, textos, anchos ni fabricación.

`tests/command_dispatch.scr` ejecuta los nombres reales desde el intérprete de comandos, en lugar de llamar directamente a las funciones. La prueba comprueba también los alias y la ausencia de registros anteriores. Debe usarse exclusivamente con una copia desechable de la placa.

Resultado nativo en Allegro 17.2 P028: **`DISPATCH_ALIASES_OK t`**, 66 redes de señal con regla asignada, salida comprobada para información, máscara, anchos y textos, y un ZIP con manifiesto 0.2.1 e integridad CRC/SHA-256 correcta. Se partió de una sesión que había cargado 0.2.0 y se cargó el nuevo paquete dos veces antes de ejecutar los nombres por consola.

## Versión 0.2.0: instalación única y ZIP dentro del proyecto

Las seis pruebas automatizadas del empaquetador con Windows PowerShell 5.1 pasan: ruta con espacios y `ñ` e integridad SHA-256, protección de un ZIP existente, ausencia de un Gerber, archivo truncado, resultado de exportación con errores e invocación desde el shell de Windows con rutas entrecomilladas. También pasa la prueba de instalación: conservación de código de inicio ajeno y de sus bytes originales, conservación del perfil local y respaldo de los scripts antiguos antes de convertirlos en redirecciones.

La prueba nativa `tests/project_zip.il` termina en **`ALL_PASS t` / `RESULT (t)`** con Allegro 17.2 P028. Abre una copia de una PCB, cambia deliberadamente la carpeta de trabajo fuera de su proyecto y comprueba auditoría y corrección de máscara, ubicación del backup, conservación de la ruta original del diseño, dos ZIP consecutivos (`v001`, `v002`), restauración de la carpeta de trabajo, carga de la configuración exportada y rechazo de rutas absolutas o con `..`.

La resolución de la placa utiliza `axlGetDrawingName()`, que devuelve su ruta absoluta; `axlCurrentDesign()` solo devuelve el nombre de la ventana y no sirve para determinar la carpeta del proyecto.

El backup de máscara utiliza `axlSaveDesign(... ?writeModel t)` para escribir una copia sin cambiar la ruta de la placa activa. Renombrar únicamente el título no restaura esa asociación. El empaquetador se ejecuta de forma síncrona mediante `system`, para comprobar su código de salida y la existencia del ZIP antes de comunicar el resultado.

## Versión 0.1.0: validación inicial

Fecha: 23 de octubre de 2026. Entorno: Cadence Allegro PCB Editor 17.2 P028, Windows, ejecución nativa sin interfaz gráfica. Se utilizaron copias desechables de dos diseños distintos de dos capas y una tercera placa de prueba con fallos de máscara introducidos deliberadamente. Los originales no se modificaron.

| Caso | Pines | Vías | Resultado |
| --- | ---: | ---: | --- |
| Diseño A | 303 | 10 | Carga, textos, máscara, anchos, films y procesos de exportación comprobados. |
| Diseño B | 268 | 61 | Mismas comprobaciones en otro proyecto. |
| Placa de prueba | 301 | 10 | Un pin sin abertura y una vía con abertura corregidos; segunda ejecución sin nuevos cambios. |

## Comprobaciones realizadas

- Carga del paquete y registro de los comandos dentro de Allegro.
- Repetición de la normalización de referencias sin crear nuevos bloques de texto. El nombre compacto del bloque evita el fallo que provocaban los nombres largos en 17.2.
- Cambio del alto configurado a 1,20 mm con creación de un bloque distinto, conservando el bloque del perfil inicial.
- Normalización de máscara y repetición sin nuevos cambios; conservación del cobre y de los atributos del taladro comprobada por el propio comando antes de aplicar cada clon.
- Creación y reutilización de las vías de las reglas físicas. La verificación usa las capas reales: en una placa de dos capas no existe un pad consultable llamado `DEFAULT_INTERNAL`.
- Conservación de una regla física especial de prueba y del ancho de la regla `DEFAULT`.
- Configuración de los siete films y exportación de Gerber y taladrado. Restauración del directorio de trabajo y de `NCDPATH` tras exportar.
- Extracción independiente de la geometría antes y después con la utilidad nativa de Cadence: cobre, pads, pistas y gráficos coinciden, excluyendo las aperturas de máscara, todas las filas de texto y los rellenos dinámicos que Allegro puede recalcular. Las referencias se comprueban por separado.
- Comprobación independiente de 98, 95 y 102 referencias respectivamente: alto 0,79 mm, ancho 0,58 mm, trazo 0,15 mm; conservan posición, ángulo, espejo y justificación.
- Comprobación estructural de siete Gerber métricos 5.5 completos y un archivo Excellon métrico completo por caso.

## Avisos y límites

Los tres procesos de artwork terminaron con código de **avisos (1)**; el taladrado terminó sin avisos. Entre los avisos de las placas figuran DRC desactualizados y pads nulos en algunas definiciones. En la versión 0.1.0 el exportador conservaba los archivos y devolvía `nil` ante avisos. Desde 0.2.0 crea además el ZIP si los archivos están completos y marca los avisos explícitamente en el manifiesto. Estos ensayos no certifican que esas placas estén listas para fabricar.

No se ha certificado visualmente la salida en un visor CAM ni se ha fabricado una placa con esta versión. Tampoco se han validado placas multicapa, planos negativos, padstacks avanzados o todos los mecanismos de herencia de restricciones. El exportador rechaza estructuras fuera de su alcance documentado. La conservación de reglas especiales se comprobó con una asignación directa a una red; la búsqueda por grupos ascendientes requiere revisión en proyectos que utilicen esa organización.

## Repetir las pruebas

1. Crea una carpeta desechable con una **copia** de una placa y coloca el paquete `.il` en una subcarpeta llamada `package`.
2. Copia `tests/smoke.il` a esa carpeta como `test.il`. Ejecuta Allegro en ese directorio con la copia abierta y carga `test.il`. La prueba modifica esa copia, crea una regla `TEST_CUSTOM`, genera fabricación y guarda `validated.brd`.
3. Comprueba `validation.txt`: debe terminar en `ALL_PASS t` y `RESULT (t)`. Revisa los códigos `FAB_STATUS` y los logs de fabricación aunque la prueba termine correctamente.
4. Ejecuta la comprobación estructural, sin dependencias adicionales:

```powershell
python tests/verify_exports.py "ruta/a/Fabricacion/mi_placa_fab_v001"
```

Este último paso verifica cabeceras, formato y cierre de los archivos; no sustituye una inspección CAM ni los DRC de la placa.

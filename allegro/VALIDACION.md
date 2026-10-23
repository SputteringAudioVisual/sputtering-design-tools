# Validación de la versión inicial

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

Los tres procesos de artwork terminaron con código de **avisos (1)**; el taladrado terminó sin avisos. Entre los avisos de las placas figuran DRC desactualizados y pads nulos en algunas definiciones. El exportador conserva los archivos, comunica los resultados y devuelve `nil` en lugar de anunciar una exportación sin avisos. Estos ensayos no certifican que esas placas estén listas para fabricar.

No se ha certificado visualmente la salida en un visor CAM ni se ha fabricado una placa con esta versión. Tampoco se han validado placas multicapa, planos negativos, padstacks avanzados o todos los mecanismos de herencia de restricciones. El exportador rechaza estructuras fuera de su alcance documentado. La conservación de reglas especiales se comprobó con una asignación directa a una red; la búsqueda por grupos ascendientes requiere revisión en proyectos que utilicen esa organización.

## Repetir las pruebas

1. Crea una carpeta desechable con una **copia** de una placa y coloca el paquete `.il` en una subcarpeta llamada `package`.
2. Copia `tests/smoke.il` a esa carpeta como `test.il`. Ejecuta Allegro en ese directorio con la copia abierta y carga `test.il`. La prueba modifica esa copia, crea una regla `TEST_CUSTOM`, genera fabricación y guarda `validated.brd`.
3. Comprueba `validation.txt`: debe terminar en `ALL_PASS t` y `RESULT (t)`. Revisa los códigos `FAB_STATUS` y los logs de fabricación aunque la prueba termine correctamente.
4. Ejecuta la comprobación estructural, sin dependencias adicionales:

```powershell
python tests/verify_exports.py "ruta/a/Fabricacion/PCB_FAB"
```

Este último paso verifica cabeceras, formato y cierre de los archivos; no sustituye una inspección CAM ni los DRC de la placa.

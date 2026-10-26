# Estado de la aplicación — 26 de octubre de 2026

El flujo original de serigrafía mantiene su validación. El frontal continúa su desarrollo con exportación de fabricación, edición de textos y biblioteca reutilizable entre módulos.

## Más fuentes y reimportación de etiquetas — 26 de octubre de 2026

Se amplía el catálogo a 12 fuentes instaladas. El importador permite actualizar fuente/tamaño de etiquetas vinculadas existentes, conservando por defecto posiciones, textos editados y ajustes avanzados. Puede regenerar posición o contenido de forma explícita. La previsualización refleja el resultado, los textos manuales no se sustituyen y la operación admite deshacer/rehacer sin duplicar objetos.

Pasan **97 pruebas locales**; la geometría de tinta de las 12 tipografías se contrasta además con Gerbonara.

## Textos y reutilización entre módulos — 26 de octubre de 2026

Validación actual: **93 pruebas locales**; las comprobaciones posteriores del preajuste DPDT y del inicio de módulos nuevos también pasan.

Se añaden texto multilínea, giro, ancho, espaciado, interlineado, alineación, engrosado, estilo en lote y duplicado independiente. Las etiquetas importadas admiten cuatro lados, desplazamientos, prefijo/sufijo y eliminación de números finales, manteniendo el refdes de origen. Se actualiza el informe de fabricación para registrar los estilos exactos y validar la altura de caracteres sin confundirla con la altura de un bloque girado.

La biblioteca incluye variantes verificadas de RK09 y anclajes de interruptores, reglas por ambas caras, cobertura explícita de huellas y una biblioteca común reutilizable. Los interruptores nuevos cuyo diámetro requiere revisión no se seleccionan automáticamente. Las huellas sin regla no producen agujeros. **Nuevo módulo / frontal** elimina el estado del módulo anterior al iniciar otro documento.

La comprobación local abarca cuatro módulos distintos con sus Gerber y taladros reales: contornos y pines coinciden en los cuatro. La geometría de cuatro estilos de texto transformado también se contrastó con Gerbonara, con 13.130 comprobaciones de píxel. Los datos reales se conservan en el proyecto local y no se publican en el repositorio de la herramienta. La compatibilidad sigue dependiendo de una regla válida, el formato soportado y las versiones de PCB/Gerber alineadas.

## Fabricación del frontal y fuentes — 25 de octubre de 2026

Se añade **Gerber / ZIP…** para exportar el estado abierto del frontal a RS-274X + Excellon NPTH, contorno, serigrafías, máscaras cerradas y cobre opcional con separación de 0,3 mm. Genera ZIP numerado, vista SVG con tinta fija e informe SHA-256. Rechaza geometría fuera del panel, solapes y tinta sobre agujeros; las referencias de la PCB nunca forman parte del paquete. Los agujeros grandes conservan su diámetro para fresado CNC.

Validación actual: **82 pruebas locales pasan**, además de la lectura independiente de Gerbonara.

Se incorporan Consolas, Old English Text MT y Bahnschrift, con selección por elemento y en la importación de refdes. La fuente se guarda en el proyecto; pantalla, prueba de fabricación y Gerber comparten máscara de tinta. Las fuentes se convierten a geometría y sus archivos no se distribuyen. Las pruebas comprueban contorno/taladros exactos, cobre/máscara, equivalencia de área de tinta, las cuatro fuentes, controles de error, ZIP numerado e importación del documento abierto sin guardar. Un lector independiente Gerbonara contrasta unidades, posiciones/diámetros NPTH, polaridad y área de tinta, incluyendo huecos de caracteres de las cuatro fuentes.

## Medidas iniciales de agujeros — 25 de octubre de 2026

Se actualizan las plantillas manuales y la biblioteca de footprints a Ø8,128 mm para potenciómetro y Ø6,1 mm para jack, conservando Ø3,2 mm para rack. Los diámetros se contrastan con dos archivos Excellon de un frontal existente; no se publica su geometría. Se mantiene Ø6,5 mm para SPDT porque esa referencia no permite comprobarlo. La exportación conserva los diámetros exactos. Los proyectos guardados mantienen sus medidas y personalizaciones.

## Automatización del frontal — 25 de octubre de 2026

Se añade **Importar textos desde .brd…** como opción independiente: propone etiquetas refdes únicamente para componentes reconocidos con agujero, con altura, separación y posición encima/debajo ajustables. La previsualización no modifica el documento; al aplicar se crean textos editables, vinculados a la posición de PCB y exportables en SVG. La repetición conserva textos generados o manuales ya existentes. Generar de nuevo los agujeros no borra sus etiquetas. **Vaciar agujeros y textos** permite reiniciar el diseño conservando la PCB y admite deshacer. La escritura atómica también elimina su temporal si falla la escritura.

Pasan **75 pruebas locales**, incluidas siete nuevas regresiones de etiquetas: anclaje mecánico, agujero recolocado/diámetro editado, no duplicación, conservación de textos editados, guardado/reapertura, seguimiento de PCB, importación inválida atómica, previsualización/cancelación, deshacer/rehacer y arrastre.

Nueva opción **Agujeros desde footprints…**, con lectura de Allegro guardado mediante Extracta o una referencia JSON portátil. Se conserva el flujo de serigrafía. La biblioteca relaciona cada footprint con su tipo, diámetro, cara y anclaje mecánico. Admite editar esas reglas y exportarlas/importarlas para otros módulos.

La revisión muestra las propuestas antes de aplicar y dibuja círculos violetas sin modificar el proyecto. Los objetos manuales se conservan; las coincidencias y solapes manuales no se convierten en agujeros duplicados. Las actualizaciones de agujeros generados son idempotentes, admiten deshacer y guardan su referencia/posición relativa para seguir a la PCB al moverla o centrarla. Se mantiene su edición manual y la exportación SVG.


Pasan 68 pruebas locales, incluidas geometría mecánica, giro/cara mediante pines reales, unidades, componentes sin colocar, anclajes ambiguos, correspondencia con contorno/drills, conservación de manuales, biblioteca reutilizable, guardado/reapertura, vínculo a PCB, edición, previsualización, cancelación y deshacer. La PCB original permanece intacta; no se han subido los diseños de fabricación al repositorio de la herramienta.

## Actualización del frontal — 24 de octubre de 2026

Se retoma únicamente el frontal a petición de Luis: se corrige la acumulación de tornillos al cambiar HP y se añaden plantillas de agujero para potenciómetro, jack, SPDT, rack y personalizado. El editor de serigrafías conserva su estado validado.

El patrón de rack reemplaza los tornillos anteriores (incluidos los de proyectos antiguos) y se actualiza al aplicar otro ancho; no elimina agujeros de controles ni textos. Los preajustes preparan nuevas colocaciones, permiten editar el diámetro y conservan el tipo al guardar/reabrir. Las operaciones de edición y el cambio de patrón admiten deshacer/rehacer.

Se corrige también la prioridad de selección: pulsar un agujero o texto existente permite arrastrarlo, incluso con una herramienta de colocación activa, sin añadir otro objeto. Se conserva el punto de agarre con zoom y rejilla, se actualizan X/Y y el movimiento completo se deshace en un solo paso. Seleccionar sin mover no crea historial ni elimina la posibilidad de rehacer. Durante el arrastre de un objeto se mueve solo su dibujo, sin repintar las referencias Gerber en cada evento. La comprobación incluye eventos reales de ratón en la ventana de pruebas.

Validación actualizada: pasan las 55 pruebas locales, incluidas las 48 del cierre anterior y las regresiones de tornillos, plantillas y arrastre.

## Punto de entrada y flujo conservado

`Sputtering Design Tools.pyw` y `sputtering_design_tools.py` abren el editor de PCB y serigrafías. El frontal Eurorack es una ventana adicional del mismo proyecto; `--panel` permite abrirla directamente. Los accesos directos existentes siguen apuntando a la misma aplicación.

Se mantienen las capas Gerber, importación de imágenes, recetas de composición, alineación y transformación manual, elección de destinos, generación de capas y exportación. Los drills Excellon son referencias independientes y conservan su escala y posición.

## Correcciones entregadas

- Editor de conversión estable, vistas ampliadas, controles numéricos con coma decimal, pasos finos y botones de restablecimiento.
- Algoritmos con la misma polaridad. Blanco significa tinta sobre placa negra. Las opciones claros/oscuros distinguen fotografía positiva y negativa; Aplicar a PCB y exportación comparte los ajustes entre vista y archivo.
- Casillas de exportación visibles y preferencias de selección, receta y holgura recordadas durante la sesión.
- Paquete completo y ZIP numerado automáticos, sin sobrescribir el original. Se conservan las capas no editadas, taladros y parámetros; el manifiesto incluye SHA-256 y los ajustes aplicados.
- Recorte automático de la imagen por el contorno PCB en vista general, previsualización de exportación y Gerber, respetando la posición, escala y giro manuales. El marco completo permanece disponible para moverla. No se vuelve a centrar al exportar.

El recorte afecta al borde de la placa. No incorpora separación automática respecto a pads. Un contorno detectado debe estar cerrado; sin contorno cargado se mantiene la exportación libre. El lector conserva las limitaciones de formatos descritas en la guía.

## Validación del cierre

- 48 pruebas locales pasan en Python 3.12 con Tkinter, Pillow y NumPy. Incluyen el flujo original, conversión, polaridad, exportación, drills, frontal, colocación manual y recorte de contornos cóncavos/con vaciados.
- Luis confirma que la aplicación funciona correctamente y solicita dejarla en mantenimiento.

Las placas, imágenes y exportaciones reales permanecen en el proyecto local; no son necesarias para ejecutar las pruebas sintéticas del repositorio. Gerbonara se utilizó para la comprobación independiente y no es una dependencia de ejecución de la app. Este cierre valida el editor y su exportación; no sustituye el DRC eléctrico ni la aprobación de fabricación del diseño.

## Cómo retomar un fallo

Registrar qué acción lo provoca, resultado esperado/obtenido y una referencia o captura si existe. Reproducirlo sobre esta versión, corregirlo en un cambio acotado y conservar la estética y el flujo actuales.

Desde la carpeta de la aplicación:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas de interfaz requieren una sesión con Tkinter funcional. Después de modificar código, reiniciar la aplicación desde su acceso habitual. Los avisos CAM del diseño y el encaje mecánico del frontal se revisan por separado cuando se trabaje con una placa concreta.

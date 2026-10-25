# Estado de la aplicación — 23 de octubre de 2026

Estado: versión comprobada en uso por Luis. Desarrollo cerrado por ahora; se retomará cuando aparezca un fallo concreto. No se inicia una nueva ronda de rediseño ni de funciones.

## Automatización del frontal — 25 de octubre de 2026

Nueva opción **Agujeros desde footprints…**, con lectura de Allegro guardado mediante Extracta o una referencia JSON portátil. Se conserva el flujo de serigrafía. La biblioteca relaciona cada footprint con su tipo, diámetro, cara y anclaje mecánico. Admite editar esas reglas y exportarlas/importarlas para otros módulos.

La revisión muestra las propuestas antes de aplicar y dibuja círculos violetas sin modificar el proyecto. Los objetos manuales se conservan; las coincidencias y solapes manuales no se convierten en agujeros duplicados. Las actualizaciones de agujeros generados son idempotentes, admiten deshacer y guardan su referencia/posición relativa para seguir a la PCB al moverla o centrarla. Se mantiene su edición manual y la exportación SVG.

Comprobación real de la distorsión guardada: 23 centros reconocidos (10 potenciómetros, 8 jacks y 5 SPDT), con pines contrastados contra los drills del frontal. El proyecto de 26 HP conserva sus 15 objetos manuales; LVL2 y SCI quedan desmarcados inicialmente por solaparse con agujeros manuales. Se añade únicamente la referencia portátil de componentes al proyecto, con copia previa; los agujeros se aplican desde la revisión.

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
- Comprobación independiente de la exportación real con Gerbonara 1.6.3: 24.508 trazos de imagen conservados y recorte de los extremos físicos del trazo. Resultado: 0 mm² de tinta fuera del contorno y 0 mm² borrados dentro.
- La copia recortada `WAVEDISTEQ_3_testrouted_fab_v003_edit_v002.zip` conserva posición y escala. Cobre, máscaras, contorno, serigrafía superior y los 313 taladros permanecen idénticos al paquete anterior. CRC y SHA-256 comprobados; original intacto.
- Luis confirma que la aplicación funciona correctamente y solicita dejarla en mantenimiento.

Las placas, imágenes y exportaciones reales permanecen en el proyecto local; no son necesarias para ejecutar las pruebas sintéticas del repositorio. Gerbonara se utilizó para la comprobación independiente y no es una dependencia de ejecución de la app. Este cierre valida el editor y su exportación; no sustituye el DRC eléctrico ni la aprobación de fabricación del diseño.

## Cómo retomar un fallo

Registrar qué acción lo provoca, resultado esperado/obtenido y una referencia o captura si existe. Reproducirlo sobre esta versión, corregirlo en un cambio acotado y conservar la estética y el flujo actuales.

Desde la carpeta de la aplicación:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas de interfaz requieren una sesión con Tkinter funcional. Después de modificar código, reiniciar la aplicación desde su acceso habitual. Los avisos CAM del diseño y el encaje mecánico del frontal se revisan por separado cuando se trabaje con una placa concreta.

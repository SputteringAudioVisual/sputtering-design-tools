# Sputtering Design Tools

Herramientas de diseño para Eurorack. Incluye el editor Gerber original y un espacio de trabajo para crear frontales 3U sobre una PCB de referencia.

El flujo de serigrafía se conserva tras su validación del 23 de octubre de 2026. El frontal incorpora selección y arrastre, plantillas de agujeros y colocación desde footprints. Véase [estado actual y cómo retomar](ESTADO_ACTUAL.md).

## Pantalla principal: la serigrafía original

El inicio vuelve a ser **Gerber Silkscreen Editor**, con su barra, colores y controles originales. Siguen en su sitio Añadir capa, Importar Imagen, Editor de conversión, alineación, transformaciones, selección de capas del logo, Exportar Gerber y Generar capa nueva.

- **PCB y referencias → Añadir PCB + drills** añade archivos Gerber/Excellon o un ZIP. Los drills se dibujan en naranja, con círculo y centro, sobre las mismas coordenadas de la PCB. Son referencias: no se añaden a la lista de destinos de exportación Gerber.
- **Frontal Eurorack 3U…** abre una ventana adicional con las capas cargadas, incluidos los drills. Al abrirla o cerrarla, el logo, la conversión y la posición de la serigrafía principal se conservan.
- El formato drill se toma de la cabecera o de `nc_param.txt`, detectado en la misma carpeta/ZIP. Si no está definido se pide un formato explícito, en lugar de adivinar una escala.

`python sputtering_design_tools.py --panel` queda disponible para abrir solo el frontal de forma explícita. El lanzador normal, el acceso `.pyw` y el script Gerber histórico abren la interfaz de serigrafía.

## Tinta blanca sobre PCB negra

En el editor de conversión y en la imagen de la vista general, **blanco representa tinta**. El negro de la previsualización representa placa sin tinta; el azul del marco solo indica la selección. La vista general conserva los colores de las demás capas como referencias.

Las opciones **Claros → tinta blanca (foto positiva)** y **Oscuros → tinta blanca (foto negativa)** eligen qué zonas de la imagen se imprimen. Se conserva la opción que estuviera aplicada. El botón **Aplicar a PCB y exportación** transfiere algoritmo, umbral, contraste, selección de zonas y tamaño de píxel a la imagen general y al Gerber. El pie del editor indica si quedan ajustes sin aplicar.

Las vistas comparten preparación y máscara con el conversor Gerber. La original queda fija para comparar. Las previsualizaciones se limitan a 600 píxeles en el lado mayor; el Gerber utiliza la resolución física indicada. El ojo de exportación añade la receta de mezcla/ventanas sobre la capa base y muestra la serigrafía en blanco sobre negro; el cobre mantiene su propia paleta.

## Exportar la PCB con sus modificaciones

**Exportar Gerber** mantiene el diálogo de capas y recetas. Las casillas tienen una marca de alto contraste y la selección, modo y holgura se conservan al volver a abrir el diálogo durante la sesión. Las capas sin marcar conservan su contenido original en el paquete.

Si se ha cargado un ZIP o un proyecto con origen de fabricación registrado, se genera automáticamente una carpeta y un ZIP nuevos junto al ZIP de origen: por ejemplo, `mi_pcb_fab_v001_edit_v001.zip`. Las siguientes exportaciones usan el siguiente número libre. Si se cargaron archivos sueltos, se pide la carpeta de destino.

El paquete conserva los archivos originales no editados, incluidos taladros, parámetros e informes. Incluye las capas modificadas y un manifiesto nuevo con sumas SHA-256 y ajustes de conversión. El manifiesto anterior se conserva en `historial_editor/`. Los informes de Allegro corresponden al origen; las modificaciones necesitan su revisión CAM. La aplicación verifica el ZIP antes de dar la exportación por terminada y no sobrescribe el paquete original ni exportaciones anteriores.

Con un contorno PCB cargado, la imagen se **recorta automáticamente por el borde** en la vista general, en la previsualización de exportación y en el Gerber generado. Se respeta su posición, escala y giro actuales: no se centra ni se ajusta de nuevo al exportar. El marco completo sigue disponible para moverla a mano. El recorte incluye el ancho real de los trazos y funciona también al generar una capa nueva y con SVG. Los contornos cerrados pueden ser cóncavos o tener vaciados; si el contorno detectado está abierto, hay que cerrarlo antes de exportar. Sin contorno cargado se mantiene la exportación libre. El recorte no añade separación respecto a los pads.

## Frontal Eurorack 3U

Primero abre la interfaz de serigrafía y pulsa el menú **Frontal Eurorack 3U…**. Los siguientes controles pertenecen a esa ventana adicional.

Ejecuta `sputtering_design_tools.py` o abre `Sputtering Design Tools.pyw` con doble clic en Windows. Para abrir una demostración sintética:

```powershell
python sputtering_design_tools.py --demo
```

1. Usa **Cargar PCB / Gerber** para abrir el contorno y la serigrafía, sueltos o dentro de un ZIP. Se mantienen alineadas por sus coordenadas originales. No se leen `.brd` nativos de Allegro.
2. Elige la capa de contorno en la lista de referencia. Si el nombre contiene `outline`, `profile`, `edge_cuts` o termina en `.gko` / `.gm1`, se propone automáticamente; de lo contrario, confirma la capa manualmente.
3. Elige un ancho entero de HP y aplica. La altura es 128,5 mm y el ancho físico es `HP × 5,08 − tolerancia`. La tolerancia total inicial es 0,34 mm y se puede cambiar; no representa una medida universal para todos los fabricantes. [Referencia mecánica Doepfer](https://doepfer.de/a100_man/a100m_e.htm).
4. La PCB se centra en los dos ejes sin escalarla. Todas las capas comparten la misma traslación. **Mover PCB** permite ajustar después su posición. Un aviso indica si sobresale del frontal.
5. En **Tipo de agujero**, elige **Potenciómetro (Ø8,128 mm)**, **Jack 3,5 mm (Ø6,1 mm)**, **SPDT mini (Ø6,5 mm)**, **Tornillo de rack (Ø3,2 mm)** o **Personalizado**. Elegir tipo activa la colocación de agujeros y prepara su nombre y diámetro; no modifica objetos existentes. Los diámetros son plantillas iniciales editables para el casquillo de la pieza, no medidas universales para toda una familia. El tipo y el diámetro realmente usados se guardan en el proyecto. Para editar un agujero ya colocado, selecciónalo, cambia su diámetro y pulsa **Aplicar al objeto seleccionado**.
6. Haz clic para colocar o introduce X/Y y pulsa **Añadir en X / Y**. El origen es la esquina inferior izquierda; X/Y son el centro del objeto. **Texto** utiliza el tamaño como altura tipográfica. Arrastra para mover. La rejilla inicial es 0,5 mm; usa 0 para desactivarla. **Actualizar tornillos de rack Ø3,2** sustituye el patrón anterior, incluso en proyectos antiguos con duplicados, y conserva los agujeros de controles y textos. Al aplicar otro ancho, los tornillos de rack existentes se actualizan automáticamente. Ambas acciones admiten deshacer/rehacer.
7. Guarda en `.panel.json`: incluye las capas de referencia para que el proyecto sea portátil. **Exportar SVG** genera el frontal a escala 1:1, separando contorno, agujeros y textos; no incluye la PCB de referencia.

Para recolocar objetos, pulsa y arrastra directamente un agujero o texto existente: tienen prioridad aunque esté activa la herramienta **Agujero** o **Texto**, por lo que no se crean duplicados al intentar moverlos. En una zona vacía, la herramienta de colocación sigue añadiendo objetos. **Esc** pasa a selección. Puedes agarrar un objeto desde cualquier punto de su dibujo, sin que salte al centro del cursor; se respeta la rejilla, el zoom y el desplazamiento de la vista. Los campos X/Y se sincronizan al colocar, seleccionar y mover. Un arrastre completo ocupa un único paso de deshacer; un clic de selección no altera el historial. **Mover PCB** sigue siendo una herramienta explícita para desplazar solo la referencia.

La rueda hace zoom, el botón derecho desplaza la vista y el panel lateral tiene desplazamiento. Hay deshacer/rehacer; los campos de texto conservan sus propios atajos. El ejemplo `examples/demo.panel.json` es sintético y no representa un diseño real.

### Colocar agujeros desde los footprints de la PCB

En **2 · PCB de referencia**, pulsa **Agujeros desde footprints…**. El diálogo lee una PCB Allegro `.brd` guardada mediante el Extracta instalado, sin modificarla ni abrirla para edición. También admite una referencia `.pcb-components.json` previamente extraída; los datos quedan incorporados al proyecto portátil. La lectura se hace en segundo plano. Los Gerber por sí solos no contienen las identidades de componentes que necesita esta función.

Revisa la tabla de componentes, centros X/Y del panel, diámetro y acción. Doble clic o Espacio marca/desmarca filas. Los círculos violetas son previsualización y **Cancelar** no modifica el proyecto. **Aplicar seleccionados** añade o actualiza los agujeros reconocidos en una sola acción de deshacer. Repetirlo no duplica sus agujeros; los objetos manuales se conservan. Una coincidencia con un agujero manual se conserva y los solapes o agujeros fuera del frontal quedan desmarcados para revisión.

La biblioteca inicial reconoce nombres exactos:

| Footprint | Centro mecánico utilizado | Diámetro inicial editable |
|---|---|---:|
| `SPTR_RK09_123` | Centro entre sus dos anclajes mecánicos sin número de pin | 8,128 mm |
| `SPTR_PJ301M` | Centro del padstack `C150_H300`, situado bajo el casquillo | 6,1 mm |
| `SPTR_SPDT` | Centro del pin 2 | 6,5 mm |

Los diámetros son plantillas para ajustar al componente físico y los anclajes deben corresponder a su footprint. No se utiliza el centro de los pads eléctricos como aproximación. Las posiciones absolutas de pines extraídas por Cadence ya incluyen giro y espejo, por lo que no se vuelve a girar ni reflejar el agujero. La cara de cada regla se elige explícitamente; inicialmente es TOP. Los componentes sin colocar, sin regla, de otra cara o con anclajes ambiguos no generan agujeros por suposición.

Los valores iniciales de potenciómetro (8,128 mm), jack (6,1 mm) y rack (3,2 mm) se toman de una referencia de frontal existente. Se conserva exactamente 8,128 mm, sin redondear a 8 mm. La medida SPDT (6,5 mm) sigue siendo una plantilla editable, sin verificar en esa referencia. Los proyectos antiguos conservan sus medidas y reglas guardadas; cambiar el preajuste no modifica automáticamente sus agujeros.

En **Regla de tu biblioteca** puedes asociar otros nombres de footprint a un tipo, diámetro y centro (dos anclajes mecánicos, pin, padstack u origen explícito). **Guardar regla y recalcular** prepara los cambios en el diálogo; se incorporan al proyecto con **Aplicar seleccionados** y **Guardar**. **Importar/Exportar biblioteca de reglas…** permite reutilizarlos en otros módulos.

Los agujeros generados conservan la referencia del componente y siguen a la PCB al centrarla, desplazarla o cambiar el ancho del frontal. Siguen pudiéndose arrastrar y editar: un ajuste manual conserva su desplazamiento relativo a la PCB. Una nueva generación explícita vuelve a proponer el centro de la regla y su diámetro. Al cargar otra PCB de referencia, los agujeros anteriores quedan como objetos editables sin vinculación a la nueva placa.

La importación comprueba la coincidencia de límites de contorno y, si hay Excellon cargado, contrasta los pines THT con los taladros para detectar una versión desalineada. Actualmente la extracción de contorno desde Allegro admite líneas y rectángulos en `BOARD GEOMETRY/DESIGN_OUTLINE` u `OUTLINE`; se rechazan otros contornos. Esto no lee cambios de Allegro que aún no estén guardados. El lector utiliza los campos documentados de las vistas COMPONENT, COMPOSITE_PAD y FULL_GEOMETRY de la instalación Cadence.

### Importar etiquetas desde la PCB

En **2 · PCB de referencia**, **Importar textos desde .brd…** propone los refdes de los componentes con una regla de agujero. Utiliza la referencia de componentes guardada en el proyecto o permite leer un `.brd` / JSON actualizado. No importa todos los textos de serigrafía ni añade referencias de resistencias sin agujero.

Elige altura de texto, separación respecto al borde del agujero y posición **Encima/Debajo**, y pulsa **Actualizar previsualización**. La tabla y los textos violetas muestran lo que se añadirá; marca las referencias deseadas y pulsa **Aplicar seleccionados**. Los textos quedan editables, se exportan en SVG y admiten deshacer/rehacer. Si has movido o cambiado el diámetro de un agujero generado, la etiqueta usa esa posición y diámetro actuales. Al mover la PCB, las etiquetas generadas la acompañan. Una importación repetida conserva las etiquetas existentes y sus ajustes manuales en lugar de duplicarlas.

**Herramientas → Vaciar agujeros y textos (conservar PCB)** permite empezar el frontal desde cero manteniendo ancho, referencias y biblioteca; se puede deshacer. Los objetos vuelven al reabrir únicamente si forman parte del proyecto guardado: no son archivos temporales. Las lecturas `.brd` utilizan una carpeta temporal independiente que se elimina al finalizar.

### Exportar el frontal como PCB para JLCPCB

**Gerber / ZIP…** exporta el estado abierto del frontal, incluidos cambios aún sin guardar. Crea un ZIP numerado con `panel.GKO` (contorno físico), `panel-NPTH.drl` (todos los agujeros sin metalizar), `GTO/GBO` (serigrafías), `GTL/GBL` (cobre) y `GTS/GBS` (máscaras). No copia las capas de la PCB de referencia. El ZIP contiene solo archivos de fabricación; junto a él se guardan una vista SVG con geometría fija y un informe JSON con medidas, taladros y SHA-256. No se sobrescriben exportaciones anteriores.

El perfil es FR4 de dos capas con tinta en la cara superior. Las máscaras cerradas dejan cubierto el cobre. La opción **Relleno de cobre bajo la máscara** genera planos separados 0,3 mm del borde y de los agujeros; puede desactivarse para exportar sin cobre. Al pedir, selecciona máscara negra y serigrafía blanca para el acabado usado en la previsualización. El espesor, cantidad y resto de opciones se eligen en JLCPCB; el Gerber no establece colores ni espesor.

La exportación impide agujeros solapados/fuera del panel, menos de 0,2 mm de material entre taladros, tinta fuera del frontal y tinta a menos de 0,15 mm de un agujero. La altura impresa del texto debe alcanzar 1 mm. Los círculos de 8,128 mm se mantienen en Excellon: [JLCPCB indica que los agujeros desde 6,3 mm se fresan mediante CNC](https://jlcpcb.com/capabilities/pcb-capabilities/). Se utilizan [nombres de capas reconocibles y coordenadas absolutas en milímetros](https://jlcpcb.com/help/article/gerber-files-preparation). Revisar siempre contorno, taladros y texto en el visor CAM de la orden antes de confirmarla.

### Tipografías

Se añaden **Consola · Consolas**, **Gótica · Old English** e **Industrial · Bahnschrift**, además de Arial. La fuente se elige al colocar textos, al editar un texto seleccionado (**Aplicar al objeto seleccionado**) y al importar refdes. Se guarda con cada elemento. Se necesitan las fuentes instaladas; si falta una, se avisa en lugar de sustituirla silenciosamente al exportar.

La vista del frontal, la vista SVG de fabricación y el Gerber usan la misma máscara de tinta a 0,025 mm. Los contornos de los caracteres se convierten en regiones Gerber rellenas; los huecos de las letras se conservan. Se engrosan 0,075 mm por lado para proteger trazos finos. No se envían archivos de fuentes al fabricante. Para la gótica conviene usar texto mayor y revisar sus huecos. El SVG editable continúa disponible por separado y depende de las fuentes del equipo donde se abra.

### Alcance de esta primera versión

El SVG es un plano vectorial para continuar el diseño: los círculos representan cortes/agujeros, no taladros Excellon. Los textos permanecen editables y dependen de la fuente Arial/sans-serif; antes de fabricar, conviértelos a trazados en tu editor vectorial y comprueba medidas y encaje mecánico. La aplicación no comprueba distancias de tuercas, cuerpos de potenciómetros, componentes ni profundidad detrás del panel. Avisa de agujeros que se solapan o salen del borde; el aviso de posición del texto corresponde a su centro, no a toda su extensión tipográfica.

La referencia admite Gerber absoluto con supresión de ceros iniciales, aperturas C/R/O, líneas, arcos multicuadrante aproximados y regiones simples. Se admiten las declaraciones de transformación identidad de Allegro; se rechazan macros, transformaciones no soportadas, regiones de varios contornos y otros formatos de coordenadas. Las capas de referencia no se copian al paquete del frontal. La revisión de polaridades complejas y la validación del encaje mecánico corresponden a cada diseño.

### Comprobaciones

```powershell
python -m unittest discover -s tests -v
```

Las pruebas verifican unidades y aperturas, trazos modales, límites físicos, centrado, patrón de tornillos, validación, guardado/reapertura, escala y contenido SVG, carga ZIP y edición/deshacer/rehacer. Las pruebas de ventana requieren una instalación funcional de Tkinter.

## Versión inicial

Incorporada el 22 de octubre de 2026 como copia exacta del script existente. El hash de `BASELINE.md` identifica esa primera versión. El 23 de octubre se añadió el espacio de frontales y se corrigieron delimitadores, selección G54, operaciones modales y conversión de aperturas del lector para poder cargar las referencias a escala real. La comprobación del lector no equivale a validar un panel para fabricación.

Origen y verificación: [BASELINE.md](BASELINE.md).

## Ejecución

Requiere Python con Tkinter, Pillow y NumPy. Desde esta carpeta:

```powershell
python -m pip install Pillow numpy
python gerber_silkscreen_editor.py
```

La conversión vectorial SVG utiliza además `svgpathtools`; la previsualización SVG intenta utilizar Inkscape, que debe estar instalado y accesible en PATH. Estas funciones tienen limitaciones descritas en el plan.

```powershell
python -m pip install svgpathtools
```

Las versiones de dependencias todavía no están fijadas. Las instrucciones reflejan las importaciones del script; una instalación limpia y la validación funcional quedan pendientes.

## Control de cambios

El historial de Git sustituye a las copias numeradas del script. Conservar los Gerber de origen y utilizar una carpeta distinta para las exportaciones. Las siguientes correcciones se harán en cambios separados de esta incorporación inicial.

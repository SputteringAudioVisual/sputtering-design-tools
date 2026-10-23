# Sputtering Design Tools

Herramientas de diseño para Eurorack. Incluye el editor Gerber original y un espacio de trabajo para crear frontales 3U sobre una PCB de referencia.

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

Si se ha cargado un ZIP o un proyecto con origen de fabricación registrado, se genera automáticamente una carpeta y un ZIP nuevos junto al ZIP de origen: por ejemplo, `WAVEDISTEQ_3_testrouted_fab_v003_edit_v001.zip`. Las siguientes exportaciones usan el siguiente número libre. Si se cargaron archivos sueltos, se pide la carpeta de destino.

El paquete conserva los archivos originales no editados, incluidos taladros, parámetros e informes. Incluye las capas modificadas y un manifiesto nuevo con sumas SHA-256 y ajustes de conversión. El manifiesto anterior se conserva en `historial_editor/`. Los informes de Allegro corresponden al origen; las modificaciones necesitan su revisión CAM. La aplicación verifica el ZIP antes de dar la exportación por terminada y no sobrescribe el paquete original ni exportaciones anteriores.

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
5. Elige **Agujero** o **Texto** y haz clic para colocar, o introduce X/Y y pulsa **Añadir en X / Y**. El origen es la esquina inferior izquierda; X/Y son el centro del objeto. El tamaño es el diámetro del agujero o el tamaño tipográfico del texto, en mm. Selecciona y arrastra para mover; también puedes editar valores y aplicar. La rejilla inicial es 0,5 mm; usa 0 para desactivarla.
6. Puedes añadir un patrón inicial de tornillos de rack de 3,2 mm. Los taladros de jacks/potenciómetros se eligen manualmente según sus fichas; el valor inicial de 6,5 mm es una ayuda de edición, no una medida validada de tu componente.
7. Guarda en `.panel.json`: incluye las capas de referencia para que el proyecto sea portátil. **Exportar SVG** genera el frontal a escala 1:1, separando contorno, agujeros y textos; no incluye la PCB de referencia.

La rueda hace zoom, el botón derecho desplaza la vista y el panel lateral tiene desplazamiento. Hay deshacer/rehacer; los campos de texto conservan sus propios atajos. El ejemplo `examples/demo.panel.json` es sintético y no representa la PCB real de distorsión.

### Alcance de esta primera versión

El SVG es un plano vectorial para continuar el diseño: los círculos representan cortes/agujeros, no taladros Excellon. Los textos permanecen editables y dependen de la fuente Arial/sans-serif; antes de fabricar, conviértelos a trazados en tu editor vectorial y comprueba medidas y encaje mecánico. La aplicación no comprueba distancias de tuercas, cuerpos de potenciómetros, componentes ni profundidad detrás del panel. Avisa de agujeros que se solapan o salen del borde; el aviso de posición del texto corresponde a su centro, no a toda su extensión tipográfica.

La referencia admite Gerber absoluto con supresión de ceros iniciales, aperturas C/R/O, líneas, arcos multicuadrante aproximados y regiones simples. Se admiten las declaraciones de transformación identidad de Allegro; se rechazan macros, transformaciones no soportadas, regiones de varios contornos y otros formatos de coordenadas. No se exportan los Gerber cargados desde este espacio de trabajo. Se ha comprobado la carga del contorno y serigrafía superior reales de la PCB de distorsión (128,5 × 110 mm); siguen pendientes la revisión visual de polaridades complejas y la validación del encaje mecánico.

### Comprobaciones

```powershell
python -m unittest discover -s tests -v
```

Las pruebas verifican unidades y aperturas, trazos modales, límites físicos, centrado, patrón de tornillos, validación, guardado/reapertura, escala y contenido SVG, carga ZIP y edición/deshacer/rehacer. Las pruebas de ventana requieren una instalación funcional de Tkinter.

## Versión inicial

Incorporada el 22 de octubre de 2026 como copia exacta del script existente. El hash de `BASELINE.md` identifica esa primera versión. El 23 de octubre se añadió el espacio de frontales y se corrigieron delimitadores, selección G54, operaciones modales y conversión de aperturas del lector para poder cargar las referencias a escala real. La primera carga de la distorsión verifica dimensiones y geometría reconocida; no equivale a validar el panel para fabricación.

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

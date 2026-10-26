# Sputtering Design Tools

Herramientas de diseño de Sputtering Audio Visual, centradas inicialmente en PCB y Eurorack y abiertas a otros formatos en el futuro.

## Estado actual

El flujo de serigrafía conserva su validación del **23 de octubre de 2026**. El frontal sigue evolucionando y el **25 de octubre** incorpora agujeros automáticos desde footprints. Pasan **82 pruebas locales**. Historial y comprobaciones en [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md).

La pantalla principal conserva el editor Gerber y su flujo de serigrafía: capas, imágenes PNG/JPG/SVG, conversión, posición/escala/giro, alineación, recetas y selección de destinos. Los drills Excellon se muestran como referencia. Blanco representa tinta sobre PCB negra y la conversión aplicada se comparte entre la vista y la exportación.

La imagen se recorta automáticamente al contorno de la PCB **tal como esté colocada a mano**, sin centrarla ni cambiar su tamaño al exportar. La exportación genera un paquete completo y un ZIP numerado, conserva los archivos no editados y comprueba su integridad.

El frontal Eurorack 3U es una ventana adicional de la misma aplicación: ancho en HP, PCB a escala real, agujeros, textos, proyectos portátiles y SVG 1:1.

**Agujeros desde footprints…** lee una PCB Allegro guardada y reconoce potenciómetros, jacks y SPDT mediante una biblioteca de reglas reutilizable. Muestra los centros y diámetros antes de aplicarlos, conserva los objetos manuales y actualiza sus propios agujeros sin duplicarlos. Los agujeros generados siguen a la PCB al moverla o centrarla y también pueden editarse a mano. La biblioteca y las referencias de componentes se guardan con el proyecto; las reglas pueden importarse/exportarse para otros módulos.

**Importar textos desde .brd…** añade etiquetas refdes editables para los componentes con agujero. Incluye previsualización, altura y separación ajustables, posición encima/debajo y conservación de etiquetas existentes. Los textos siguen a la PCB y admiten deshacer.

**Gerber / ZIP…** exporta el frontal a un paquete de fabricación RS-274X y Excellon NPTH, con contorno, serigrafías, máscaras y cobre opcional. Los textos de Arial, Consolas, Old English y Bahnschrift se convierten a geometría; la previsualización comparte esa tinta. El paquete numerado incluye una vista de fabricación y un informe de integridad como archivos adicionales junto al ZIP.

Guía de uso, recorte, conversión y exportación: [FRONTAL_3U.md](FRONTAL_3U.md).

## Ejecución

Requiere Python con Tkinter, Pillow y NumPy. Desde la carpeta del repositorio:

```powershell
python -m pip install Pillow numpy
python sputtering_design_tools.py
```

En Windows, `Sputtering Design Tools.pyw` abre el editor sin consola. El script histórico `gerber_silkscreen_editor.py` abre la misma interfaz. `python sputtering_design_tools.py --panel` abre directamente el frontal.

La conversión vectorial SVG utiliza `svgpathtools`; su previsualización intenta utilizar Inkscape disponible en PATH. Las dependencias aún no están fijadas ni se ha certificado una instalación limpia.

## Comprobaciones

```powershell
python -m unittest discover -s tests -v
```

Las pruebas de ventana requieren Tkinter funcional. La comprobación independiente del recorte real utilizó Gerbonara, que no es una dependencia de la aplicación. Los diseños y archivos de fabricación reales se conservan fuera de este repositorio; la validación del editor no sustituye el DRC del diseño.

## Historial y alcance futuro

[BASELINE.md](BASELINE.md) identifica mediante SHA-256 el script original incorporado el 22 de octubre. Las correcciones posteriores se conservan en Git; no se utiliza ese hash para identificar la versión actual.

[ROADMAP.md](ROADMAP.md) recoge posibilidades futuras como blank panels, artworks y otros formatos. Quedan como referencia, sin iniciar trabajo adicional durante este cierre.

# Sputtering Design Tools

Herramientas de diseño para proyectos de Sputtering Audio Visual, inicialmente centradas en Eurorack y abiertas a otros formatos y usos en el futuro.

## Estado actual

La primera versión incorpora el editor Gerber existente, sin modificar su código. Permite cargar capas Gerber, importar imágenes, posicionarlas y generar capas o combinarlas con archivos existentes. Aunque el script conserva su nombre histórico `gerber_silkscreen_editor.py`, el alcance del repositorio no está limitado a la serigrafía.

Esta incorporación establece el punto de partida del control de versiones. Todavía no se dispone de planos para validar el funcionamiento real; las correcciones e interfaz se abordarán en cambios posteriores.

## Utilidades de Allegro

La carpeta [allegro](allegro/README.md) incorpora comandos SKILL para Allegro PCB Editor 17.2: normalización de referencias de serigrafía, máscara de pines y vías, reglas de anchos y exportación de fabricación para placas de dos capas. Los nombres `pcb_*` y los perfiles configurables permiten usarlos en diferentes proyectos.

**Empieza por la [guía de uso de Allegro](allegro/COMO_USAR.md)**: instalación y actualización, carga, comandos, configuración por proyecto, exportación de Gerber + NC Drill en ZIP con versión y solución de problemas. Versión actual: **0.2.2**.

La [referencia técnica](allegro/README.md) detalla los valores iniciales y las limitaciones; [VALIDACION.md](allegro/VALIDACION.md) recoge las pruebas y la confirmación en una sesión real. Una única implementación en `allegro/` sirve a todos los proyectos. El código del editor Gerber permanece intacto.

## Ejecución del editor actual

Requiere Python con Tkinter, Pillow y NumPy:

```powershell
python -m pip install Pillow numpy
python gerber_silkscreen_editor.py
```

La vía vectorial SVG utiliza además `svgpathtools`. La previsualización SVG intenta utilizar Inkscape, instalado y accesible en PATH:

```powershell
python -m pip install svgpathtools
```

Las dependencias aún no tienen versiones fijadas. El soporte SVG y la correspondencia entre vista previa y exportación necesitan revisión. Conservar los Gerber originales y exportar a una carpeta distinta.

## Evolución prevista

- Edición y composición de capas Gerber, más allá de silkscreen.
- Creación de paneles ciegos (blank panels) para Eurorack.
- Preparación de artworks y gráficos para paneles y placas.
- Ampliación a otros formatos y proyectos de diseño.

Estos puntos describen la dirección del proyecto; no son funciones implementadas en esta versión. El siguiente trabajo se detalla en [ROADMAP.md](ROADMAP.md).

## Referencia inicial

El script se conserva exactamente como se recibió. Su origen y SHA-256 están registrados en [BASELINE.md](BASELINE.md). Git sustituye a las copias numeradas para seguir su evolución.

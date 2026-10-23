# Ruta única de utilidades Allegro

Versión **0.2.2**. Esta es la referencia de carga para todos los proyectos y chats.

Instalación compartida:

```text
C:/SPB_Data/pcbenv/pcb_tools
```

En la línea **Command** de Allegro:

```lisp
skill load("C:/SPB_Data/pcbenv/pcb_tools/pcb_cargar.il")
```

Al abrir Allegro de nuevo, la carga es automática. Para confirmar qué versión está activa:

```text
pcb_info
```

`pcb_utilidades_info` permanece como sinónimo. El informe de versión utiliza la salida directa de la consola de Allegro, sin el búfer de `printf`.

Los nombres cortos ejecutan las llamadas directas `skill ...()` mediante alias de Allegro. La carga elimina los registros anteriores de estas utilidades y comprueba cada alias, de modo que recargar la sesión no conserva accesos antiguos.

Flujo habitual de comprobación y exportación:

```text
pcb_mascara_revisar
pcb_fab_auditar
pcb_fab_exportar
```

`pcb_mascara_revisar` y `pcb_fab_auditar` informan. `pcb_mascara` modifica los padstacks y crea una copia previa; úsalo solo si hay correcciones que aplicar. `pcb_textos` normaliza y limpia referencias; `pcb_anchos` configura reglas para el trazado posterior. Cargar el paquete nunca aplica estos cambios automáticamente.

La exportación configura los films y genera todo bajo la carpeta de la PCB guardada:

```text
<carpeta_del_brd>/Fabricacion/<nombre_placa>_fab_v001.zip
<carpeta_del_brd>/Fabricacion/<nombre_placa>_fab_v002.zip
```

El ZIP incluye Gerber, NC Drill, manifiesto con versión y SHA-256, informe, logs y configuración usada. La carpeta sin comprimir se conserva al lado. El código 1 de artwork significa **avisos**, no ausencia de avisos: el ZIP lo indica y requiere revisión. Los errores o archivos incompletos impiden crear un paquete nuevo.

Los informes y backups también quedan dentro del proyecto. Las rutas antiguas migradas son únicamente redirecciones; las copias de pruebas no se deben recomendar como rutas de trabajo. La opción antigua `pcbFabOutputRoot` queda retirada: cualquier personalización de salida debe ser una subcarpeta relativa dentro del proyecto mediante `pcbFabOutputSubdir`.

Las utilidades no recalculan ni corrigen por sí mismas todos los DRC, conexiones o problemas mecánicos. Revisa el paquete en un visor CAM antes de fabricar. Alcance del exportador: dos capas positivas TOP/BOTTOM.

Código y documentación: [propuesta de utilidades Allegro en GitHub](https://github.com/SputteringAudioVisual/sputtering-design-tools/pull/1).

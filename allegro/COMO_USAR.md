# Guía de uso de las utilidades Allegro

Versión **0.2.2**, para **Cadence Allegro PCB Editor 17.2 en Windows**. Sirven para distintas PCB: textos de referencia, máscara de soldadura, reglas de anchos y exportación de Gerber + NC Drill en ZIP con versión.

## 1. Instalar o actualizar

Descarga este repositorio desde GitHub (**Code > Download ZIP**) y descomprímelo. Si Windows muestra la casilla **Desbloquear** en las propiedades del ZIP descargado, márcala antes de extraerlo, tras comprobar su procedencia. Abre PowerShell en la carpeta `allegro`, donde está `Instalar-PcbTools.ps1`, y ejecuta:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\Instalar-PcbTools.ps1
```

Se instala una única copia de trabajo en **`C:/SPB_Data/pcbenv/pcb_tools`**, incluido el empaquetador. El instalador actualiza `allegro.ilinit`, conserva el código de inicio ajeno y el perfil `pcb_local.il`, y guarda los archivos anteriores bajo `C:/SPB_Data/pcbenv/pcb_tools_backups`. La política de ejecución indicada afecta solo a ese proceso de PowerShell.

Para actualizar, repite la instalación desde la nueva descarga y recarga Allegro como se indica abajo. No cargues los scripts directamente desde Descargas ni desde copias de pruebas. En este PC la instalación ya está hecha.

## 2. Cargar y comprobar

Abre una PCB guardada. Al iniciar Allegro las utilidades se cargan automáticamente con la configuración de inicio instalada. En una sesión ya abierta, o después de actualizar, escribe en la línea **Command**:

```lisp
skill load("C:/SPB_Data/pcbenv/pcb_tools/pcb_cargar.il")
```

Después escribe:

```text
pcb_info
```

Debe indicar **versión 0.2.2** y la carpeta central. Los mensajes `function … redefined` son normales al recargar; `t` es el retorno habitual de una operación correcta. Cargar el paquete no modifica la placa.

Ejecuta cada comando por separado y espera su resultado. Los nombres `pcb_*` se escriben directamente en **Command**, sin añadir `skill`.

## 3. Preparar la placa

Al probar en otro diseño, guarda primero una copia de la PCB. Ejecuta la auditoría de la operación que necesites, revisa su salida y aplica solo los cambios pertinentes:

| Revisar primero | Aplicar | Resultado |
| --- | --- | --- |
| `pcb_textos_auditar` | `pcb_textos` | Normaliza referencias conservando posición y giro; elimina duplicados y, por defecto, textos de valor/dispositivo asociados. |
| `pcb_mascara_revisar` | `pcb_mascara` | Expone los pads de componentes y cubre las vías mediante sus padstacks. Crea una copia de seguridad antes de corregir. |
| `pcb_anchos_auditar` | `pcb_anchos` | Asigna reglas físicas para el trazado posterior y conserva las reglas especiales existentes. |
| `pcb_fab_auditar` | `pcb_fab_exportar` | Comprueba las capas y genera el paquete de fabricación. |

No necesitas aplicar todos los comandos en cada placa. Si la máscara indica cero pines pendientes, cero vías abiertas y ningún conflicto adicional, no hay corrección que aplicar. El informe completo queda en `pcb_mascara_revision.txt` junto a la PCB.

Los textos empiezan en **0,79 × 0,58 mm**, con trazo **0,15 mm**. Las referencias sin texto asociado se avisan y no se crean automáticamente. `pcb_anchos` no redimensiona pistas ni vías existentes: configura señal a **0,40 mm** y alimentación a **0,80 mm**, salvo reglas especiales conservadas. Por eso puede informar de cero redes de potencia modificadas aunque existan alimentaciones.

Los cambios quedan **en memoria**. Revisa la placa y usa **File > Save**. Las utilidades no añaden conexiones de tierra ni resuelven islas de cobre. La referencia de [comportamiento y límites](README.md) detalla las geometrías admitidas por la herramienta de máscara.

## 4. Exportar Gerber y taladrado

El exportador admite **dos capas de cobre positivas llamadas TOP y BOTTOM**. Antes de fabricar, actualiza y revisa los DRC, las conexiones y los rellenos de cobre en Allegro. Después ejecuta:

```text
pcb_fab_auditar
```

La auditoría debe encontrar todas las capas necesarias. Comprueba su salida y ejecuta:

```text
pcb_fab_exportar
```

La exportación configura automáticamente siete films: cobre TOP/BOTTOM, máscara TOP/BOTTOM, serigrafía TOP/BOTTOM y contorno. No hace falta ejecutar antes `pcb_fab_configurar`; este último queda disponible si solo quieres preparar los films y revisarlos. Se reemplazan los films de esos siete nombres.

Los archivos son **Gerber RS-274X métrico 5.5** y **Enhanced Excellon métrico absoluto 5.5**. El taladrado combina PTH y NPTH en un único archivo; confirma que tu fabricante acepta ese formato.

La salida se crea dentro de la carpeta donde está guardado el `.brd`, aunque Allegro se iniciara desde otro directorio:

```text
mi_proyecto/
  mi_placa.brd
  pcb_mascara_revision.txt
  Copias_seguridad/
    mi_placa_antes_mascara_v001.brd
  Fabricacion/
    mi_placa_fab_v001/
    mi_placa_fab_v001.zip
    mi_placa_fab_v002/
    mi_placa_fab_v002.zip
```

Se elige la primera versión libre; nunca se sobrescribe una carpeta o ZIP anterior. El ZIP incluye:

- Los siete `.art` y el archivo `.drl` de taladrado.
- `LEEME_FABRICACION.txt` y `manifest.json`, con versiones, estado y comprobaciones SHA-256.
- `informes/photoplot.log` e `informes/ncdrill.log`.
- `parametros/`, con los parámetros y la configuración efectiva.

La carpeta sin comprimir se conserva al lado del ZIP. La exportación refleja el estado **en memoria** y no guarda la PCB: usa también **File > Save** para conservar los cambios del diseño y los films.

## 5. Interpretar el resultado

| Mensaje o situación | Qué hacer |
| --- | --- |
| Se muestra una ruta `ZIP …` sin avisos | El paquete se ha generado. Revisa contorno, alineación, cobre, máscara y taladros en un visor CAM antes de enviarlo. |
| `PAQUETE CON AVISOS: Gerber 1` | El paquete está completo, pero revisa `informes/photoplot.log`. El manifiesto indica `REQUIERE_REVISION_AVISOS`. |
| `DRC OUT OF DATE` | Actualiza la comprobación de reglas en Allegro, revisa el resultado y exporta de nuevo. |
| `Null REGULAR-PAD` | Hay una definición sin pad de cobre en la capa indicada. Revisa el padstack y sus coordenadas; puede corresponder a un taladro mecánico previsto o a una definición que deba corregirse. |
| NC Drill genera `nc_tools_auto.txt` | Ha creado automáticamente la tabla de herramientas. Revisa el log y los diámetros de taladro exportados. |
| Error de exportación o archivos incompletos | No se crea un ZIP nuevo. La carpeta de esa ejecución se conserva para revisar los logs. |

Una auditoría correcta confirma la estructura de capas, no las conexiones ni la fabricabilidad. Los avisos de la PCB no se corrigen ni se ocultan al comprimir.

## 6. Configurar otro proyecto

Copia [config_ejemplo.il](config_ejemplo.il) dentro de tu proyecto, por ejemplo como `pcb_perfil.il`. Edita los valores en milímetros y cárgalo antes de ejecutar las operaciones:

```lisp
skill load("C:/PCB/mi_proyecto/pcb_perfil.il")
```

Usa la ruta real del perfil, con `/` como separador. Los valores permanecen en la sesión al cambiar de placa y al recargar las utilidades; **el perfil de proyecto no se selecciona automáticamente**. Carga el perfil completo de cada proyecto antes de aplicar cambios. El perfil de ejemplo permite volver a los valores iniciales.

Para ajustes comunes a todas las placas, puedes usar `C:/SPB_Data/pcbenv/pcb_tools/pcb_local.il`: el cargador lo lee después de los valores iniciales y cada recarga vuelve a aplicarlo. Un perfil de proyecto cargado después prevalece hasta la siguiente recarga. El instalador conserva el archivo local al actualizar; no contiene una implementación alternativa de las herramientas.

Opciones frecuentes: `pcbTextRemoveValues = nil` conserva valores asociados; `pcbMaskMarginMM` cambia el margen de máscara; `pcbPowerNets` establece los nombres de alimentación. `pcbFabOutputSubdir` permite una subcarpeta relativa distinta de `Fabricacion`; se rechazan rutas absolutas o con `..`. El contorno usa por defecto `BOARD GEOMETRY/DESIGN_OUTLINE`, configurable con `pcbFabOutlineLayer`.

## 7. Solución de problemas y copias antiguas

- **Un comando no responde o aparece una versión vieja:** recarga el cargador único del apartado 2 y ejecuta `pcb_info`. Copia el mensaje completo si aparece un error. Desde 0.2.2 el informe se escribe directamente en la consola.
- **Ruta con `ñ` o tildes:** la instalación del código debe permanecer en la ruta ASCII indicada. El empaquetador se ha probado con rutas de proyecto con espacios y `ñ`; eso no convierte una carpeta de desarrollo en una ruta de carga recomendada.
- **Placa sin guardar o ruta de salida externa:** guarda primero el `.brd`. `pcbFabOutputRoot` está retirado; las salidas se anclan al proyecto y solo se admite una subcarpeta relativa.
- **Nombres `fx_*`:** siguen siendo alias a las mismas funciones. Usa los nombres `pcb_*` en nuevos proyectos. `pcb_utilidades_info` es sinónimo de `pcb_info`; `pcb_mascara_auditar` es sinónimo de `pcb_mascara_revisar`.
- **Scripts de instalaciones antiguas:** el instalador permite migrarlos con `-LegacyDirectories` y `-LegacyFiles`; guarda los originales e inventario `restauracion.json` y deja redirecciones al cargador central. No borres backups para resolver un problema de carga.

Los padstacks, textos y reglas nuevos se incorporan al `.brd`; los informes y exportaciones quedan en su proyecto. El ZIP se puede trasladar sin las rutas de este PC. Las bibliotecas externas preexistentes de Capture no se copian automáticamente.

Para detalles técnicos consulta [README.md](README.md); para pruebas y alcance confirmado, [VALIDACION.md](VALIDACION.md).

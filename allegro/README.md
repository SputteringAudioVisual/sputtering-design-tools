# Utilidades PCB para Cadence Allegro

Comandos SKILL reutilizables para preparar serigrafía, máscara, reglas de pistas y archivos de fabricación. Versión **0.2.2**, destinada a **Allegro PCB Editor 17.2 en Windows**. No dependen del nombre de la placa ni de una carpeta personal.

## Por dónde empezar

- **[Guía de uso paso a paso](COMO_USAR.md):** instalación, carga, comandos, perfiles, exportación y solución de problemas.
- **Esta página:** referencia del comportamiento, valores iniciales y limitaciones.
- **[Validación](VALIDACION.md):** pruebas realizadas, confirmación en sesión gráfica y límites pendientes.
- **[Perfil de ejemplo](config_ejemplo.il):** configuración editable para otro proyecto.

La única instalación de trabajo es **`C:/SPB_Data/pcbenv/pcb_tools`**. El código mantenido en GitHub está únicamente en `allegro/`; los nombres anteriores `fx_*` son alias de compatibilidad hacia las mismas funciones.

El cargador registra los comandos sin modificar la placa. Los cambios se revisan en Allegro y se guardan con **File > Save**. Los informes, backups y paquetes de fabricación quedan junto al `.brd`, dentro de su proyecto.

## Configuración

Las dimensiones de configuración siempre son milímetros; la conversión a unidades del diseño es automática. Los valores iniciales están en [pcb_config.il](pcb_config.il) y solo se asignan si la variable aún no está definida. Un perfil cargado conserva sus valores al recargar el paquete, salvo que `pcb_local.il` vuelva a establecerlos. Para aplicar otro perfil o volver a los valores iniciales, carga explícitamente el perfil completo correspondiente; cambiar de placa no selecciona un perfil automáticamente.

## Serigrafía

Valores iniciales: **alto 0,79 mm, ancho 0,58 mm y trazo 0,15 mm**. La referencia conserva posición, giro y justificación; cambia de capa a `REF DES/SILKSCREEN_TOP` o `BOTTOM` según la cara del componente.

Se eliminan referencias duplicadas y, de forma predeterminada, los demás textos asociados al símbolo (valores o nombres de dispositivo). Para conservar estos últimos, usa `pcbTextRemoveValues = nil`. No se borran textos independientes, dibujos del encapsulado ni marcas gráficas de polaridad. Las referencias sin texto asociado se señalan; no se inventa una posición para ellas.

Cada conjunto de dimensiones obtiene su propio bloque de texto. Cambiar la configuración no altera bloques compartidos por otros textos del diseño.

## Soldermask

En Allegro, las geometrías de soldermask representan **aberturas**. Los pads de componentes reciben una abertura que cubre su cobre, por cada cara donde exista cobre. Se conserva una abertura previa suficientemente grande. Las vías quedan sin abertura propia. El margen inicial es `0.0 mm`; usa `pcbMaskMarginMM` para aumentarlo según el fabricante.

La herramienta clona los padstacks necesarios dentro de la placa; no modifica la biblioteca `.pad`, las capas de pasta ni el cobre del pad. Comprueba que el resto de geometrías y atributos de taladro de cada clon coincidan. Ante un error durante la aplicación, revierte la transacción. Allegro puede recalcular los rellenos dinámicos: revisa sus DRC después.

Compatible con geometrías simples circulares, cuadradas y rectangulares, pines SMD y taladros pasantes circulares. Los padstacks avanzados, ranuras, geometrías especiales, microvías y backdrilling requieren revisión específica. No se eliminan aperturas adicionales del encapsulado o de la placa. El informe detecta vías expuestas por otras aberturas; esas situaciones requieren revisión manual. La ausencia de abertura en el archivo no garantiza que el fabricante pueda cubrir físicamente cualquier diámetro de vía.

## Anchos y vías para el trazado

Por defecto: señal **0,40 mm**, vía **0,60/0,30 mm**; alimentación **0,80 mm**, vía **0,80/0,40 mm**. La lista `pcbPowerNets` reconoce nombres completos, sin distinguir mayúsculas, inicialmente `+12V`, `-12V`, `0`, `GND`, `VCC`, `VDD`. Ajusta esta lista para cada esquema.

Se crean los conjuntos físicos `PCB_SIGNAL` y `PCB_POWER`. La regla `DEFAULT` permanece intacta. Se conservan las reglas físicas especiales asignadas a redes o grupos ascendientes cuando `pcbPreserveCustomRules = t`. El comando informa de las redes omitidas. Puedes desactivar esta conservación deliberadamente en tu perfil para reemplazar sus asignaciones. Las otras clases de restricciones no se normalizan.

Los padstacks de vías incorporan sus diámetros en el nombre para permitir cambiar de perfil. Estas reglas **no redimensionan pistas ni vías ya colocadas** y no implican una comprobación eléctrica o térmica de esos anchos. Tras cambiar reglas, revisa Constraint Manager y los DRC.

## Fabricación

El exportador se limita a placas de **dos capas positivas llamadas TOP y BOTTOM**. Rechaza estructuras multicapa, nombres de cobre diferentes y planos negativos. Los otros comandos pueden usarse independientemente del exportador.

Genera siete films: cobre superior e inferior, máscara superior e inferior, serigrafía superior e inferior y contorno. El contorno usa `BOARD GEOMETRY/DESIGN_OUTLINE`, configurable con `pcbFabOutlineLayer`. Al configurar se reemplazan los films de esos nombres; revisa los films propios que ya tenga la placa.

Salida: Gerber RS-274X métrico 5.5 y NC Drill Enhanced Excellon métrico absoluto 5.5, con PTH y NPTH combinados. Cada ejecución crea una carpeta y un ZIP numerados **dentro de la carpeta donde está guardado el `.brd`**, independientemente de la carpeta desde la que se inició Allegro:

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

Se selecciona la primera versión libre; no se sobrescriben carpetas ni ZIP anteriores. `pcbFabOutputSubdir` permite cambiar `Fabricacion` por otra subcarpeta relativa del proyecto; se rechazan rutas absolutas y componentes `..`. La antigua opción `pcbFabOutputRoot` ya no se usa. Si no puede localizarse la placa guardada, el comando pide guardarla y se detiene.

El ZIP contiene los siete `.art`, todos los `.drl`, `LEEME_FABRICACION.txt`, un `manifest.json` con versión y sumas SHA-256, los registros en `informes/` y los parámetros y la configuración efectiva de las utilidades en `parametros/`. Se verifica la integridad de cada archivo comprimido. No se añaden bases de datos PCB, archivos temporales ni enlaces a carpetas externas al ZIP.

La auditoría comprueba estructura y existencia de capas; **no certifica** conexiones, DRC, rellenos, contenido del contorno ni fabricabilidad. Antes de enviar, revisa los avisos de `photoplot.log` y `ncdrill.log` y comprueba los archivos en un visor CAM, especialmente contorno, taladros, máscara y serigrafía. Una placa con islas de tierra inconexas seguirá teniéndolas.

El exportador devuelve la ruta del ZIP si los archivos están completos. Si Allegro emite avisos (código 1), también crea el ZIP, lo señala en consola y marca el manifiesto como `REQUIERE_REVISION_AVISOS`. Ante errores de exportación o archivos incompletos no crea un ZIP nuevo y conserva la carpeta para diagnosticar. `pcbFabLastResult` contiene `(carpeta resultadoGerber resultadoTaladro)` y `pcbFabLastZip` contiene el último ZIP de una exportación completada.

## Proyecto autocontenido

Todos los archivos generados por estas utilidades quedan dentro de la carpeta del `.brd`: fabricación, informes y copias de seguridad. Las definiciones de padstacks, bloques de texto y reglas nuevas se incorporan a la base de datos, sin crear bibliotecas auxiliares fuera del proyecto. La configuración usada para cada exportación viaja en el ZIP. Mover ese paquete no requiere las rutas de este PC.

La instalación común contiene el código de las herramientas; no contiene diseños ni salidas de fabricación. Esto no copia ni modifica las bibliotecas externas preexistentes de otros programas del proyecto, como Capture.

## Migración desde los comandos anteriores

Sustituye el prefijo `fx_` por `pcb_`: `fx_textos` pasa a `pcb_textos`, `fx_mascara` a `pcb_mascara`, `fx_anchos` a `pcb_anchos` y `fx_fab_exportar` a `pcb_fab_exportar`. Se conservan alias de compatibilidad que ejecutan la misma implementación general. También se acepta `pcb_mascara_auditar` y el antiguo nombre indicado por error `fx_mascara_auditar`.

El instalador puede convertir entradas antiguas en redirecciones mediante `-LegacyDirectories` y `-LegacyFiles`, guardando los originales y un inventario de restauración en `pcbenv/pcb_tools_backups`. Así, cargar una ruta antigua no vuelve a activar una versión divergente.

Si una placa antigua conserva una regla `POWER_0P8`, el comando de anchos la considera una regla especial y la conserva. Para migrar esa asignación, hazlo explícitamente desde Constraint Manager o con un perfil que desactive `pcbPreserveCustomRules`, revisando antes la auditoría.

## Validación y alcance

Consulta [VALIDACION.md](VALIDACION.md). Se incluye [tests/smoke.il](tests/smoke.il) como prueba de integración para ejecutar **solo en copias desechables** dentro de Allegro. No se incluyen placas, bibliotecas personales ni archivos de fabricación de proyectos.

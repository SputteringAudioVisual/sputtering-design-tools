# Utilidades PCB para Cadence Allegro

Comandos SKILL reutilizables para preparar serigrafía, máscara, reglas de pistas y archivos de fabricación. Destinados a **Allegro PCB Editor 17.2 en Windows**. No dependen del nombre de la placa ni de una carpeta personal.

## Instalación y carga

1. Copia los archivos `.il` de esta carpeta a `C:/SPB_Data/pcbenv/pcb_tools`.
2. Con una placa abierta, escribe en la línea **Command** de Allegro:

```lisp
skill load("C:/SPB_Data/pcbenv/pcb_tools/pcb_utilidades.il")
skill pcbCargar("C:/SPB_Data/pcbenv/pcb_tools")
```

Usa una ruta sin tildes ni `ñ` para evitar problemas de carga en versiones antiguas. Se pueden incluir ambas expresiones, sin el prefijo `skill`, en el archivo personal `allegro.ilinit`. Al arrancar solo se registran comandos: no se modifica la placa automáticamente.

Para personalizar una placa, copia `config_ejemplo.il`, ajusta sus valores y cárgalo antes de ejecutar un comando. También puede cargarse antes de `pcbCargar`. Los valores se conservan al recargar el paquete. Las dimensiones de configuración siempre son milímetros; la conversión a unidades del diseño es automática.

## Comandos

| Comando | Acción |
| --- | --- |
| `pcb_textos_auditar` | Informa de las referencias, duplicados y textos asociados que se modificarían. |
| `pcb_textos` | Conserva una referencia por componente, la lleva a la serigrafía de su cara y normaliza sus dimensiones. |
| `pcb_mascara_revisar` | Revisa aberturas de pines y vías; genera `pcb_mascara_revision.txt` en el directorio de trabajo. |
| `pcb_mascara` | Abre máscara sobre pads de componentes y elimina aberturas propias de vías; crea una copia de seguridad previa. |
| `pcb_anchos_auditar` | Cuenta redes de señal, alimentación y redes con reglas especiales que se conservarán. |
| `pcb_anchos` | Asigna reglas físicas de señal y alimentación para el trazado posterior. |
| `pcb_fab_auditar` | Comprueba si existen las capas necesarias y si la estructura es compatible con este exportador. |
| `pcb_fab_configurar` | Crea o reemplaza los siete films de fabricación descritos abajo. |
| `pcb_fab_exportar` | Configura films y ejecuta Gerber y NC Drill en una carpeta nueva. |

Comienza por la auditoría correspondiente. Los cambios de textos, máscara, reglas y films quedan **en memoria**: revisa y guarda la placa en Allegro. No se añaden pistas, vías ni conexiones de tierra. Guarda una copia antes de usar estas herramientas en otro diseño.

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

Salida: Gerber RS-274X métrico 5.5 y NC Drill Enhanced Excellon métrico absoluto 5.5, con PTH y NPTH combinados. Cada ejecución crea una carpeta `Fabricacion/PCB_FAB`, `PCB_FAB_1`, etc. bajo el directorio de trabajo. Para otra ubicación, define `pcbFabOutputRoot` con una ruta absoluta.

La auditoría comprueba estructura y existencia de capas; **no certifica** conexiones, DRC, rellenos, contenido del contorno ni fabricabilidad. Antes de enviar, revisa los avisos de `photoplot.log` y `ncdrill.log` y comprueba los archivos en un visor CAM, especialmente contorno, taladros, máscara y serigrafía. Una placa con islas de tierra inconexas seguirá teniéndolas.

El exportador devuelve la carpeta cuando ambos procesos terminan sin avisos. Si hay avisos o errores devuelve `nil`, muestra los resultados y conserva los archivos para revisarlos. Para diagnósticos, `pcbFabLastResult` contiene `(carpeta resultadoGerber resultadoTaladro)`; Allegro devuelve `t` sin avisos, `1` con avisos y otros códigos ante errores.

## Migración desde los comandos anteriores

Sustituye el prefijo `fx_` por `pcb_`: `fx_textos` pasa a `pcb_textos`, `fx_mascara` a `pcb_mascara`, `fx_anchos` a `pcb_anchos` y `fx_fab_exportar` a `pcb_fab_exportar`. Los originales pueden conservarse como copia, pero conviene cargar solo este paquete en el inicio.

Si una placa antigua conserva una regla `POWER_0P8`, el comando de anchos la considera una regla especial y la conserva. Para migrar esa asignación, hazlo explícitamente desde Constraint Manager o con un perfil que desactive `pcbPreserveCustomRules`, revisando antes la auditoría.

## Validación y alcance

Consulta [VALIDACION.md](VALIDACION.md). Se incluye [tests/smoke.il](tests/smoke.il) como prueba de integración para ejecutar **solo en copias desechables** dentro de Allegro. No se incluyen placas, bibliotecas personales ni archivos de fabricación de proyectos.

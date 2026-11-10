# Flujo entre Allegro, serigrafía y frontal

Estado documentado el 8 de noviembre de 2026. El contrato de identidad y
versiones está en `CONTRATO_TRAZABILIDAD_PCB.md`; su esquema y ejemplo están en
`fabrication-manifest-v1.schema.json` y
`fabrication-manifest-v1.example.json`.

## Uso

1. En el asistente de Allegro, vincular el `.brd` con su identidad de PCB y
   declarar la revisión. La revisión PCB (`1.0`, `1.1`, `2.0`...) describe el
   diseño, no cuántas veces se ha exportado.
2. Generar y sellar el ZIP de fabricación. Cada ZIP sellado recibe un ID único
   y una etiqueta `F001`, `F002`...; una nueva F no cambia por sí sola la
   revisión PCB. El ZIP conserva su manifiesto, inventario y hashes.
3. Al terminar, aceptar la oferta del asistente para abrir **el mismo `.brd` y
   el ZIP recién generado** en el editor de serigrafía. Si se abre a mano,
   elegir el `.brd` y, cuando se solicite, el ZIP exacto. El editor comprueba
   identidad, revisión, archivos y relación con el BRD antes de asociarlos.
4. Desde la serigrafía, aceptar la oferta de abrir el frontal en otra ventana
   o usar el menú `PCB y referencias → Importar textos de referencia en el
   frontal…`. El importador muestra las referencias de los componentes
   colocados. Las que no tienen anclaje mecánico conocido se colocan desde el
   origen del componente y quedan sin seleccionar hasta revisar su posición.
5. Guardar las ediciones en el proyecto del editor. Al exportar Gerbers
   modificados, crear una edición `E001`, `E002`... vinculada a la F raíz y al
   ZIP padre exacto. Una E conserva la revisión de la PCB original y exige
   revisión CAM antes de fabricar.

## Recuperación y límites

- El nombre `*_fab_vNNN.zip` se conserva por compatibilidad. La identidad de
  la liberación se lee del manifiesto; no se elige una F por el número del
  nombre ni por encontrar una carpeta extraída junto al ZIP.
- No se reescribe un ZIP sellado. Si cambia la PCB o la fabricación, generar
  otra liberación y conservar las anteriores para comparar o recuperar.
- Un ZIP histórico sin identidad declarada puede importarse como procedencia
  incompleta cuando el contorno coincide; no recibe retroactivamente una
  revisión PCB ni un ID de origen inventado.
- La comprobación de archivos y procedencia no sustituye la inspección CAM.

## Estado de integración

- El asistente actualizado está instalado en
  `C:\SPB_Data\pcbenv\pcb_assistant`. La instalación conserva copias de los
  archivos reemplazados y verifica que las utilidades Allegro existentes no
  cambien.
- Se verificó la apertura de Tk, un paquete de fabricación real con su BRD y
  la preparación completa del proyecto en una copia temporal. Pasaron 186
  pruebas del editor y 32 del
  asistente.
- La guía detallada para abrir proyectos está en
  `../GUIA_CARGA_PROYECTO.txt`.

## Registro en Git

El código del editor se mantiene en `codex/eurorack-front-panel`. El asistente
Allegro tiene su rama de publicación `codex/allegro-assistant-beta`. Cada chat
debe registrar documentación y código de su herramienta en su rama, indicando
el commit y las comprobaciones. Este documento registra el punto de unión.
Los `.brd`, ZIP de fabricación, proyectos de usuario, logs y copias de
seguridad no forman parte de los commits de integración.

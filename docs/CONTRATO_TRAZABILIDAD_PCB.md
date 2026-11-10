# Trazabilidad entre Allegro y el editor Gerber · versión 1

Contrato compartido por los dos productores. El manifiesto de un paquete nuevo declara `schema: "sputtering.fabrication.v1"`. El esquema JSON y el ejemplo de esta carpeta son la referencia de interoperabilidad. Los nombres de archivos no sustituyen a los identificadores.

## Identidad y revisiones

| Campo | Significado |
| --- | --- |
| `project_id` | UUID estable de una placa física, independiente de la ruta o nombre del `.brd`. |
| `project_name` | Nombre legible de esa placa. Puede cambiar sin cambiar su UUID. |
| `pcb_revision` | Revisión **MAYOR.MENOR**, declarada por el usuario, por ejemplo `1.0`. |
| `module_id` | Opcional: agrupación de PCB, frontal y arte; nunca sustituye a `project_id`. |
| `fabrication_release_id` | UUID nuevo para cada paquete final, original o derivado. |
| `release_label` | Etiqueta legible: `F001`, `F002`… para originales; `E001`, `E002`… para derivados. |

Cada PCB física tiene su propio `project_id`: el frontal de un módulo y su PCB de componentes no comparten ese ID aunque pertenezcan al mismo `module_id`.

La primera revisión se declara expresamente; no se infiere de `V1_3.brd`, de una fecha ni del número de un ZIP antiguo. Cambios eléctricos, de cobre, taladros, contorno o colocación incrementan la revisión mayor (`1.0` → `2.0`). Correcciones solo de serigrafía o documentación en Allegro incrementan la menor (`1.0` → `1.1`). Reexportar el mismo diseño crea otra liberación F sin incrementar su revisión PCB. Cambiar un Gerber en el editor crea una edición E: conserva la revisión PCB del origen y no la cambia silenciosamente.

## Campos del manifiesto

Los originales usan `release_kind: "allegro_original"`, `fabrication_sequence` entero y `base_fabrication_release_id` igual a su propio ID. Su `parent_release_id`, `parent_archive_sha256` y `parent_manifest_sha256` son `null`.

Los derivados usan `release_kind: "gerber_derived"`, `fabrication_edit_sequence` entero y un `fabrication_release_id` nuevo. `parent_release_id` identifica el paquete inmediatamente anterior; `parent_archive_sha256` es el SHA-256 de sus bytes ZIP y `parent_manifest_sha256` el de sus bytes `manifest.json`. `base_fabrication_release_id` sigue identificando la liberación original de Allegro a través de todas las ediciones, cuando consta.

Todos incluyen:

- `created_utc`: fecha real de creación en UTC, formato ISO 8601.
- `tools`: lista de `{name, version}`; una versión no comprobada se deja `null`.
- `profile`: parámetros reales del productor. No se confunde con el perfil del padre.
- `release_status`: `pending_cam_review` o `pending_cam_review_with_warnings`. Producir un paquete no aprueba su fabricación.
- `provenance_status`: `verified` si la cadena y la identidad constan y se han verificado; `incomplete` cuando faltan datos del origen. Verificar hashes no valida el circuito.
- `source_board_sha256`: hash de la copia BRD exacta usada por Allegro. Los derivados lo conservan si estaba verificado, no lo reemplazan por el de otro BRD seleccionado después.
- `source_board`: en el original, `{project_relative_path, sha256, bytes}` de la copia dentro del proyecto. El BRD no necesita incluirse en el ZIP destinado al fabricante.
- `files`: lista exhaustiva de miembros del ZIP salvo el propio `manifest.json`, que no puede contener su hash recursivamente. Cada entrada tiene `path`, `name`, `bytes`, `sha256`, `role` y `layer`. `name` es un alias de `path` y debe ser idéntico.

Se conservan los campos existentes `board`, `fabrication_version`, `status`, `source_status`, `generator_status` y `lineage` cuando correspondan. El estado compartido es `release_status`; `status` conserva el significado histórico del productor. La procedencia y los estados del padre nunca se convierten en la validación del paquete nuevo.

El hash del ZIP final y el hash de su manifiesto se registran **fuera** del ZIP, en el índice/historial del proyecto o en la asociación del editor.

El productor puede incluir `source_saved_board_sha256`, `source_saved_board_observed_utc` y `source_saved_board_observation: "export_requested"`: describen el archivo guardado observado al solicitar la exportación. Sirven para detectar después que ese archivo ha cambiado. No se confunden con el hash del snapshot, no demuestran equivalencia eléctrica y no descartan cambios en memoria. Los derivados pueden conservar esa observación indicando que pertenece al origen.

## Archivos y funciones

| Archivo actual de Allegro | `role` | `layer` |
| --- | --- | --- |
| `COPPER_TOP.art` / `COPPER_BOTTOM.art` | `copper.top` / `copper.bottom` | `TOP` / `BOTTOM` |
| `MASK_TOP.art` / `MASK_BOTTOM.art` | `soldermask.top` / `soldermask.bottom` | `TOP` / `BOTTOM` |
| `SILK_TOP.art` / `SILK_BOTTOM.art` | `silkscreen.top` / `silkscreen.bottom` | `TOP` / `BOTTOM` |
| `OUTLINE.art` | `profile` | `null` |
| `PCB_DRILL.drl` | `drill.plated_and_nonplated` | `null` |
| rutas NC `.rou` metalizadas / no metalizadas | `route.plated` / `route.nonplated` | `null` |
| informes, configuración, otros | `report` / `config` / `other` | `null` |

Los nombres actuales se conservan; un fabricante puede exigir otra denominación y eso será una salida nueva, no una modificación del origen. No se presume que un taladro esté separado por metalizado: el núcleo actual combina PTH y NPTH.

## Flujo, integridad e historial

1. Allegro vincula el archivo abierto a una identidad y revisión declaradas, ejecuta la revisión y captura la copia exacta de origen. Genera los archivos en una salida nueva, incorpora decisiones/excepciones y el manifiesto, verifica hashes/CRC y **sella** la liberación. Solo entonces la presenta como final.
2. El editor importa el ZIP como conjunto, verifica sus miembros, alias, hashes e identidad y conserva intactos el paquete y el manifiesto originales. No añade capas de otra liberación por coincidencia de nombres.
3. Una edición/exportación crea otra liberación E con ID propio, padre exacto y raíz F. Los miembros no editados conservan sus bytes. Se vuelve a requerir revisión CAM.
4. Volver a Allegro o generar otra F crea otra asociación; no reemplaza la anterior ni mueve sus etiquetas de revisión. Las vistas muestran placa, revisión PCB, F/E asociada y estado de asociación.

Una liberación sellada es inmutable. No se reanota ni se sobrescribe para corregir metadatos. Una nueva salida recibe otro ID y referencias de procedencia. El índice conserva el historial y permite recuperar/comparar paquetes sin mezclar sus capas.

### Índice portable del productor Allegro

La raíz común es la carpeta que contiene `allegro` y Capture, cuando existe esa disposición; si no, se usa la carpeta del BRD. La identidad se guarda en `Sputtering/pcb/<project_id>/project.json`, con `schema: "sputtering.pcb-identity.v1"`, `latest_declared_revision` y el registro de revisiones declaradas. Cada liberación ocupa `releases/<fabrication_release_id>/` debajo de esa identidad. El editor consulta ese esquema/ruta/campo para detectar una revisión declarada más nueva; no modifica el registro de Allegro. No se confunde con `sputtering.pcb-project.v1`, usado por el editor para sus copias y posiciones.

`release.json` solo se crea al sellar: contiene IDs/nombre/revisión/etiqueta, `archive_project_path` relativo a la raíz común, `archive_sha256`, `manifest_sha256`, `source_board` y `release_status`. `source.brd` conserva su copia exacta. `reservation.json` reserva una etiqueta, pero **no es una liberación final**; puede existir `failed.json` y quedar un salto de numeración. No se reutilizan etiquetas fallidas.

El vínculo del archivo es `<carpeta del BRD>/Asistente/<stem>/identidad_pcb.json`, con `project_id`, `pcb_revision` y `project_relative_path` del registro. Renombrar o recuperar un BRD requiere vincularlo explícitamente a la identidad existente; no se deduce por similitud de nombres. Los vínculos e índices necesarios para reabrir el proyecto son relativos y sobreviven a trasladar su carpeta.

Los ZIP conservan el nombre legado `<archivo>_fab_vNNN.zip`; `fabrication_version` sigue siendo el contador del generador, que puede diferir de F001… si ya había salidas antiguas o se cambió el nombre del BRD. La identidad primaria es el UUID y la etiqueta del manifiesto, mostrados por las interfaces. No se renombran ZIP históricos para hacer coincidir contadores.

El editor mantiene su índice de ediciones y referencia la F raíz. Puede consultar el índice original para advertir de una F o revisión PCB más nueva cuando conoce la raíz del proyecto. Una E no sustituye automáticamente a la F asociada al diseño de Allegro ni importa sus cambios al BRD. Sin acceso al índice/fuente, el estado de actualidad se presenta como desconocido.

**Desfase:** distinguir al menos revisión PCB diferente, archivo fuente guardado cambiado, asociación vigente en la última comprobación, y estado desconocido. Si la herramienta no puede observar ediciones en memoria de Allegro, debe indicarlo y pedir una nueva revisión; no afirmar que está al día basándose solo en el nombre del archivo.

## Históricos y migración

Los ZIP existentes no se renombran, reescriben ni reciben revisiones PCB o UUID retroactivos. Pueden importarse por su SHA-256 y mostrarse como **histórico con procedencia incompleta**. Una edición nueva de un histórico recibe ID propio y hashes del padre, pero deja `project_id`, `pcb_revision`, `base_fabrication_release_id` y `source_board_sha256` en `null` cuando no constan. Declarar hoy la identidad de un BRD no cambia sus ZIP antiguos.

Un lector v1 rechaza alias discrepantes, rutas absolutas o con `..`, miembros duplicados, archivos fuera del manifiesto, hashes/tamaños incorrectos y mezcla de liberaciones. No deduce funciones de capas para sustituir metadatos contradictorios.

## Alcance del primer contrato

Este v1 cubre **Allegro → paquete original → editor Gerber → paquete derivado**. Un frontal generado desde cero por PanelEditor es otra PCB y otro productor: no se etiqueta como `allegro_original` ni hereda la identidad de la PCB de componentes. Sus salidas actuales conservan sus metadatos; si se editan como Gerber sin procedencia v1, el nuevo derivado declara procedencia incompleta. La futura incorporación de `panel_original` necesita una extensión acordada, no una identidad inventada.

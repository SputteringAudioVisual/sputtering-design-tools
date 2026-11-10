# Sputtering Design Tools

Herramientas de diseño para Eurorack. Incluye el editor Gerber original y un espacio de trabajo para crear frontales 3U sobre una PCB de referencia.

El flujo de serigrafía se conserva tras su validación del 23 de octubre de 2026. El frontal incorpora selección y arrastre, plantillas de agujeros y colocación desde footprints. Véase [estado actual y cómo retomar](ESTADO_ACTUAL.md).

Para empezar sin configurar rutas: [guía breve de carga](GUIA_CARGA_PROYECTO.txt), también disponible en **Ayuda → Guía rápida de carga…** y copiada en los módulos nuevos.

## Proyecto completo desde una PCB

Al terminar una liberación F en el **Asistente Allegro**, acepta abrirla en **Editor PCB y serigrafías**: se pasan el `.brd` y el **ZIP exacto recién sellado**, sin volver a elegir otra fabricación por nombre o fecha. El editor prepara el módulo, abre la serigrafía y ofrece abrir el frontal en otra ventana.

También puedes abrir un `.brd` desde **Abrir proyecto…**, **PCB y referencias → Abrir PCB .brd y preparar proyecto…**, **Cargar PCB / Gerber…** en el frontal o al elegir la PCB en el importador. Se necesitan Cadence Extracta y fabricación Gerber/taladros exportada de esa revisión. La app busca fabricación vecina y selecciona la revisión original más reciente identificada. Si la preparación desde el editor principal falla, ofrece elegir explícitamente el ZIP correcto. También admite archivos sueltos junto al `.brd`, tomando solo los archivos de fabricación de esa carpeta.

Se comprueban manifiestos y el registro geométrico de los componentes reconocidos contra taladros/ranuras. La falta de reglas mecánicas ya no impide cargar una placa: una F identificada admite comprobar el contorno y la identidad/revisión, y además el hash del BRD guardado cuando consta. Un ZIP histórico sin componentes reconocidos requiere selección explícita y coincidencia del contorno; queda pendiente revisar su registro de taladros/serigrafía. Esto no crea reglas ni propone agujeros para footprints desconocidos. El tipo de comprobación utilizado se guarda como `fabrication_check` en `project.json`. Una F con identidad/revisión distinta de la vinculada se rechaza. Los ZIP editados de serigrafía no se seleccionan automáticamente como fabricación original.

Se crea `Sputtering/<módulo>` en la **raíz compartida del proyecto Capture/Allegro**. Si el `.brd` está en `allegro`, Sputtering se crea junto a esa carpeta; si está directamente en la raíz, se crea junto al `.brd`. Los módulos existentes conservan su ubicación y se reconocen también en la ubicación anterior. Al continuar se conservan agujeros, textos, ancho y centrado. La estructura es:

```text
<proyecto>/
  Capture/ o archivos .opj y .dsn
  allegro/<PCB y fabricación original>
  Sputtering/<módulo>/
    modulo.module.json
    GUIA_CARGA_PROYECTO.txt
    <módulo>.panel.json
    project.json
    pcb/<copia del .brd>
    fabricacion/<ZIP verificado y archivos>
    components.json
    biblioteca_agujeros.json
    serigrafia_pcb/pcb.silk.json
    serigrafia_pcb/assets/ y fabricacion/
    arte_frontal/frontal.silk.json
    arte_frontal/assets/ y fabricacion/
    exports/frontal/
    exports/serigrafia/
    exports/arte_frontal/
    versiones/<etapa>/v0001/...
    historial/
```

Las rutas necesarias son relativas a la carpeta del módulo; se puede mover entera y abrir `modulo.module.json` desde cualquiera de las apps. La app de frontales abre el frontal; la de serigrafías abre la PCB. Las rutas originales quedan como procedencia, sin ser necesarias para reabrir. El frontal usa sus copias fijadas hasta una importación explícita. Las fuentes `.brd` se copian y leen sin modificarlas. Los proyectos e imágenes son locales y están excluidos del repositorio de la aplicación. Se necesita la app instalada y las tipografías utilizadas; la portabilidad de los datos no instala el software ni las fuentes.

El editor de serigrafía guarda la imagen, ajustes, posición, capas y recetas dentro de la etapa activa al importar, exportar, guardar o cerrar. Las exportaciones numeradas van a `exports/serigrafia` para la PCB de componentes, `exports/frontal` para el panel sin foto y `exports/arte_frontal` para el panel con imagen. El ZIP de origen se mantiene intacto.

### Continuar de la PCB al frontal y a su imagen

1. Abre desde Allegro el `.brd` con su ZIP F exacto, o carga el `.brd` manualmente y confirma su fabricación. La app prepara la carpeta completa.
2. Edita la serigrafía de la PCB en su etapa. **Módulo → Frontal del módulo** abre el frontal guardado con la PCB original como referencia, aunque estés trabajando en la imagen del panel.
3. En el frontal ajusta agujeros y textos. **5. Imagen del frontal…** guarda el documento y utiliza su ZIP más reciente vinculado a ese guardado, o genera uno si ha cambiado.
4. Se abre la etapa `arte_frontal`, conservando la imagen y sus ajustes existentes. Si cambia el tamaño físico del frontal, se pide conservar una variante antes de adaptar la imagen. Un cambio de etiquetas actualiza la base sin volver a importar la foto.
5. Exporta desde esa etapa. El ZIP final registra revisión editable, módulo, paquete de origen y sus sumas. Los nombres nuevos son estables por módulo, por ejemplo `nombre_frontal_arte_edit_v001.zip`, sin prefijos de hash visibles.

Abrir un ZIP registrado de frontal desde el editor continúa su etapa editable; abrir una exportación registrada de imagen continúa el proyecto que la produce, evitando usar el resultado aplanado como nueva base de la misma imagen. **Módulo** permite cambiar de etapa y abrir su carpeta. Los accesos locales pueden actualizarse al trasladar una carpeta; el archivo `modulo.module.json` sigue siendo la entrada portable.

**PCB y referencias → Importar textos de referencia en el frontal…** abre o reutiliza la ventana del frontal y su importador con vista previa. La lista incluye todos los componentes colocados en TOP/BOTTOM, aunque no tengan regla de agujero. Los componentes reconocidos usan su anclaje mecánico; los demás parten del origen de su footprint y aparecen como **Revisar posición**, sin seleccionarse automáticamente. Un agujero ya vinculado conserva su centro y diámetro como referencia de separación del texto. Reimportar permite mantener nombres editados, posiciones y tamaños, o cambiar el estilo del conjunto. Importar etiquetas no crea agujeros.

Para la integración entre aplicaciones, el lanzador acepta `--board <archivo.brd> --fabrication <liberacion.zip>` como pareja obligatoria. Abre primero serigrafía y ofrece el frontal; esa pareja no se utiliza con `--panel`. Abrir un proyecto guardado sigue usando `--project` o `modulo.module.json`.

### Versiones y recuperación

Cada guardado con cambios conserva un número de revisión por etapa. Las representaciones equivalentes de números como `0` y `0.0` no generan revisiones falsas. Los documentos JSON y los metadatos necesarios se copian a `versiones`; los recursos binarios se comparten mediante rutas locales fijadas y sumas SHA-256. Un bloqueo del sistema operativo protege las actualizaciones del índice cuando las dos apps guardan etapas distintas.

**Módulo → Versiones y recuperación…** muestra los guardados. **Recuperar revisión seleccionada** guarda primero el trabajo abierto, comprueba los recursos y crea una revisión nueva con el contenido recuperado, manteniendo las anteriores y sus exportaciones. **Comprobar proyecto** verifica documentos actuales, guardados, recursos y archivos registrados. Las exportaciones nuevas contienen su referencia `lineage`; las capas Gerber individuales y SVG dentro del módulo también reciben un nombre numerado. Un destino externo elegido expresamente sigue siendo una copia externa.

La consolidación de proyectos anteriores copia y verifica los originales antes de publicar la carpeta nueva. `MIGRACION.json` documenta la procedencia; `historial_importado` conserva los ZIP previos. Los paquetes antiguos sin identificador de guardado se marcan con revisión desconocida: no se les atribuye una revisión editable inventada. Si no existía la imagen editable de la PCB, se conserva el último Gerber con ella integrada y se indica esa limitación. Las carpetas anteriores pueden quedar como respaldo con una redirección al proyecto activo.

### Identidad de placa y liberaciones Allegro/Gerber

El editor consume y genera derivados del [contrato compartido de fabricación v1](../../docs/CONTRATO_TRAZABILIDAD_PCB.md). **Guardado 0001** identifica una edición recuperable; **PCB 1.0**, la revisión declarada en Allegro; **F001**, un paquete original de Allegro; **E001**, una edición Gerber. Cada paquete nuevo tiene un UUID propio y conserva la identidad y revisión de su placa, la liberación raíz, el padre inmediato y los hashes exactos del ZIP y manifiesto de origen. El contador E se asigna bajo bloqueo dentro del destino de exportación; el UUID es la identidad del paquete aunque se exporte a otra carpeta.

**Módulo → Liberaciones y comparación…** muestra los paquetes fijados y las exportaciones, su asociación y los archivos añadidos, eliminados o modificados entre dos ZIP. Permite recuperar la edición guardada asociada cuando existe. Los paquetes sellados nunca se modifican al consultar o recuperar.

Al cargar un `.brd`, el vínculo explícito del Asistente Allegro permite encontrar la fabricación por identidad y revisión incluso tras renombrar la PCB. El editor lee `allegro/Asistente/<nombre>/identidad_pcb.json` y el registro `Sputtering/pcb/<UUID>/project.json` (`sputtering.pcb-identity.v1`); no los escribe ni importa código del asistente. Las reservas o exportaciones fallidas no se consideran liberaciones. Una revisión declarada distinta, una F posterior o un BRD guardado cambiado se indican por separado. Coincidir con la observación del archivo guardado no demuestra que Allegro carezca de cambios en memoria.

La importación v1 comprueba el inventario completo, tamaños, hashes, nombres y funciones de capas; no admite capas añadidas de otro paquete. Los ZIP anteriores mantienen compatibilidad y sus derivados se identifican con procedencia incompleta, sin inventar revisiones ni identidad de placa. Para archivos sueltos, se conserva dentro del resultado una copia ZIP exacta de la base utilizada. Los datos privados de trabajo no se incorporan al repositorio de la app.

Los frontales generados desde cero siguen usando su informe y guardados actuales: son una placa física distinta y todavía no tienen liberación original dentro del contrato v1. Editar su Gerber puede producir una E con procedencia incompleta; no hereda la identidad física de la PCB de componentes. Los paquetes siguen pendientes de revisión CAM antes de fabricar.

Se admiten como referencias los taladros redondos y las ranuras rectas horizontales/verticales Excellon `.rou` (G00/M15/G01/M16). Las ranuras participan en la comprobación de los pads y se conservan en el paquete; no se convierten en agujeros redondos de la PCB. Los arcos, diagonales y formatos ambiguos se rechazan de forma explícita. La fabricación sigue teniendo que existir: si no se encuentra o no coincide, la app informa del problema y conserva el proyecto anterior.

## Pantalla principal: la serigrafía original

El inicio vuelve a ser **Gerber Silkscreen Editor**, con su barra y controles originales. Siguen en su sitio Añadir capa, Importar Imagen, Editor de conversión, alineación, transformaciones, selección de capas del logo, Exportar Gerber y Generar capa nueva.

La barra superior añade **Abrir proyecto**, **Abrir Gerbers / ZIP**, **Guardar proyecto** (Ctrl+S) y **Guardar como**. Un ZIP suelto también se puede guardar: se propone `Sputtering/<nombre>_arte` junto al ZIP. Ese proyecto conserva capas, visibilidad, colores, imagen/SVG en `assets`, transformación, conversión, destinos y recetas. Guarda una copia del ZIP en `fabricacion` y las exportaciones en `exports/serigrafia`. Se mueve la carpeta entera y se abre su `.silk.json`; no necesita los archivos originales. Dentro de un módulo se mantiene la etapa y carpeta correspondientes; los proyectos Allegro antiguos siguen siendo compatibles.

Abrir un ZIP o usar **Abrir Gerbers / ZIP** sustituye el conjunto anterior; no mezcla la PCB de componentes con el frontal. Los archivos individuales del menú **Añadir PCB + drills** siguen siendo referencias adicionales. Al cambiar de proyecto se guarda la sesión asociada; si una imagen todavía no tiene proyecto, se permite guardarla antes de cambiar. Cerrar una edición de imagen sin proyecto abre el guardado; cancelarlo conserva la ventana. Los controles pendientes del editor de conversión se confirman antes de guardar. Al reabrir se restauran también el ancho y alto físicos de la imagen, corrigiendo el destino de esas dos propiedades.

La barra muestra siempre las dimensiones exactas del contorno cargado. Los ajustes de imagen con referencia **PCB outline** y su recorte utilizan ese contorno, aunque esté oculto; no usan los límites del cobre ni los de otra capa visible. El modo **Silk bbox** sigue disponible para alinear con geometría visible.

Los nombres visibles de las capas se deducen de `FileFunction`, extensión y nombre: GTO/GBO son serigrafía superior/inferior, GTL/GBL cobre, GTS/GBS máscara y GKO contorno. Se conserva el nombre de archivo como identificador de fabricación. Las exportaciones antiguas `panel.GTO` se reconocen sin renombrarlas. Las nuevas exportaciones del frontal incluyen nombres descriptivos como `<proyecto>_contorno.GKO`, `<proyecto>_serigrafia_superior.GTO` y `<proyecto>_taladros_NPTH.drl`, con manifiesto actualizado y la misma geometría.

### Imagen con los textos del frontal

En **Exportar Gerber**, la receta **Respetar textos** conserva la serigrafía original sobre la imagen. **Recortar base** hace la operación contraria y puede quitar los textos cubiertos por la imagen. Las recetas se asignan por función/extensión de la capa, sin depender del idioma de su etiqueta, y sus preferencias se guardan con claves compatibles con JSON.

En **Respetar textos** puedes elegir **Recuadro** (inicial) o **Contorno / erosión**, y su margen en milímetros. Recuadro limpia el rectángulo completo de cada etiqueta; Contorno erosiona la imagen alrededor de la tinta, conservando imagen entre trazos separados. El contorno se calcula a 0,025 mm con un elemento cuadrado y se recorta a los límites del frontal. Las letras originales se redibujan después; su grosor y el algoritmo de conversión de la fotografía se conservan. La previsualización y el Gerber consumen las mismas ventanas.

Los nuevos Gerber del frontal incluyen comentarios `G04 SPUTTERING_TEXTBOX_MM` con el recuadro físico de cada texto completo. Son metadatos de geometría y no añaden tinta. Los Gerber externos sin esos metadatos conservan la protección anterior por su geometría al usar Recuadro; Contorno puede calcularse desde su tinta. La forma elegida y el margen se guardan al confirmar las capas de exportación, además de al guardar o cerrar el proyecto. La lista de capas se desplaza si no cabe en la ventana.

**Generar capa nueva** también incluye los textos y sus ventanas cuando la capa de destino cargada es un frontal con esos metadatos. Reutiliza la forma y el margen elegidos para esa capa en la exportación. En los demás casos sigue generando una capa solo con la imagen y lo indica al finalizar. Para pedir la fabricación se utiliza el ZIP completo de **Exportar Gerber**. Al reemitir regiones no se convierten sus bordes en trazos adicionales: se mantiene el grosor original de las letras.

### Guardar y encontrar las exportaciones

Ambas apps muestran la ruta del proyecto activo. En el frontal se guarda un `.panel.json` con textos, agujeros y referencias; en una edición independiente de serigrafía se guarda un `.silk.json` con capas, imagen, posición y conversión. **Guardar como…** está visible en las dos barras, y **Ctrl+Mayús+S** abre esa acción. Para conservar los recursos asociados se mueve la carpeta completa del proyecto.

Al abrir un `.panel.json` independiente sin metadatos Allegro, la sesión de serigrafía se guarda como `<nombre>.image_session.json` junto a él, con imágenes en `assets`. Dos frontales en una misma carpeta conservan sesiones separadas. Los proyectos Allegro existentes mantienen su `image_session.json` habitual.

El frontal usa **Guardar proyecto y generar ZIP**: guarda primero el documento editable y luego crea una exportación numerada en `exports/frontal`, también en proyectos sin `.brd`. Si el guardado se cancela o falla, no se genera el ZIP. Serigrafías conserva sus controles de guardado y confirma los ajustes de conversión y las recetas antes de exportar; una sesión asociada no continúa exportando si falla su guardado.

Al terminar una exportación, ambas apps muestran una ruta seleccionable y los botones **Copiar ruta** y **Abrir carpeta**. El mismo diálogo se utiliza para la capa Gerber individual. Un ZIP es una copia para fabricar; el archivo de proyecto permite seguir editando.

- **PCB y referencias → Añadir PCB + drills** añade archivos Gerber/Excellon o un ZIP. Los drills se dibujan en naranja, con círculo y centro, sobre las mismas coordenadas de la PCB. Son referencias: no se añaden a la lista de destinos de exportación Gerber.
- **Frontal Eurorack 3U…** abre una ventana adicional con las capas cargadas, incluidos los drills. Al abrirla o cerrarla, el logo, la conversión y la posición de la serigrafía principal se conservan.
- El formato drill se toma de la cabecera o de `nc_param.txt`, detectado en la misma carpeta/ZIP. Si no está definido se pide un formato explícito, en lugar de adivinar una escala.

`python sputtering_design_tools.py --panel` queda disponible para abrir solo el frontal de forma explícita. El lanzador normal, el acceso `.pyw` y el script Gerber histórico abren la interfaz de serigrafía.

## Tinta blanca sobre PCB negra

La vista predeterminada usa **PCB negra y serigrafía blanca**, tanto en el editor de serigrafías como en el frontal. Las capas de serigrafía se reconocen por nombre SILK, extensión GTO/GBO o cabecera Gerber de leyenda; las demás capas y los taladros conservan sus colores de referencia. En el frontal, la PCB situada detrás sigue dibujándose en tonos de referencia para distinguirla del texto que se imprimirá.

En el editor de conversión y en la imagen de la vista general, **blanco representa tinta**. El negro de la previsualización representa placa sin tinta; el azul del marco solo indica la selección. Estos colores de pantalla no modifican la geometría ni las exportaciones.

Las opciones **Claros → tinta blanca (foto positiva)** y **Oscuros → tinta blanca (foto negativa)** eligen qué zonas de la imagen se imprimen. Se conserva la opción que estuviera aplicada. El botón **Aplicar a PCB y exportación** transfiere algoritmo, umbral, contraste, selección de zonas y tamaño de píxel a la imagen general y al Gerber. El pie del editor indica si quedan ajustes sin aplicar.

**Umbral B/N · compartido** y el umbral del editor son el mismo valor, sincronizado en ambos sentidos. **Cerrar y aplicar**, la X del editor, exportar o generar una capa nueva confirman los números escritos y los ajustes pendientes antes de continuar; un valor inválido permite corregir el campo. Bayer usa su trama fija y no depende del umbral.

Las vistas comparten preparación y máscara con el conversor Gerber. La original queda fija para comparar. La máscara se calcula a la resolución física de fabricación y solo después se adapta su tamaño a la pantalla: reducir la imagen en gris antes de convertir alteraba el umbral y la trama. Los cálculos grandes de dithering se realizan en segundo plano y se indica cuándo siguen pendientes. Los puntos aislados de un píxel se exportan como flashes Gerber; no se eliminan por ser más cortos que un trazo. El ojo de exportación añade la receta de mezcla/ventanas sobre la capa base y muestra la serigrafía en blanco sobre negro; el cobre mantiene su propia paleta.

La vista ajustada calcula la cobertura de tinta de la máscara ya convertida para evitar cuadros o bandas de moiré. Cerca de un píxel de pantalla por punto, interpolar no era suficiente: se aplica un filtro de densidad antes del escalado, incluso si coincide el tamaño nativo. Los grises de esa vista representan cobertura, no añaden grises al Gerber. Con ampliaciones enteras de al menos 2× se conservan los puntos nítidos. **Ver puntos 1:1…** muestra siempre la máscara binaria intacta, sin ese filtrado de la vista de conjunto, con barras de desplazamiento y arrastre. Esa ventana muestra el estado del momento en que se abrió; se vuelve a abrir para inspeccionar ajustes posteriores. El escalado de pantalla no cambia los puntos exportados.

Los ZIP creados antes de esta corrección conservan su contenido anterior. Hay que volver a exportar la imagen para incluir los puntos recuperados y revisar el resultado con sus ajustes de umbral y contraste.

### Ajuste automático y conversión reactiva

En **Editor de conversión**, **Auto · ajustar imagen** analiza una copia reducida de la imagen y propone un punto de partida: umbral para dibujos/logos o **Floyd rápido · fotografía** para fotografías. Ajusta también el contraste: amplía los tonos de imágenes apagadas, entre 1 y 3, usando los percentiles 5 y 95 para evitar que unos pocos píxeles extremos determinen el resultado. Después calcula el umbral sobre la imagen con ese contraste aplicado. Las imágenes uniformes o con rango de tonos amplio conservan contraste 1. **Revertir Auto** recupera los ajustes previos, incluido el contraste, a la última pulsación de Auto. La sugerencia conserva posición, tamaño físico, giro, píxel y selección de zonas de tinta; se revisa en la vista y se confirma al aplicar, cerrar o exportar como los ajustes manuales. El análisis es local.

**Ajustes finos** despliega Brillo, Gamma (medios tonos), Nitidez y Suavizado en píxeles de la imagen. Sus valores neutros son 1, 1, 1 y 0. Los parámetros se guardan en la sesión del proyecto y en el manifiesto de exportación, y se utilizan tanto en la vista como en el Gerber. En difusión de error, brillo y gamma permiten controlar la cantidad de tinta de forma más directa que cambiar solo el umbral.

Los métodos habituales están visibles y **Más algoritmos y tramas** despliega los demás. Se añaden Bayer 2×2 y trama agrupada 4×4, junto al modo nativo rápido para fotografías. Las tramas fijas utilizan Brillo/Gamma y tamaño de píxel; el umbral se desactiva cuando no interviene. Se mantiene la cuadrícula física de fabricación y la conservación de puntos aislados. El [conversor Bitmap de Design Family Market](https://bitmap.designfamilymarket.com/) se consultó como referencia de controles y tipos de trama; la conversión se implementa y ejecuta en la app local.

El modo Floyd rápido usa la difusión nativa de Pillow y una curva de medios tonos para que el umbral sea ajustable. Es una opción distinta: no reproduce exactamente la distribución del Floyd anterior, que sigue disponible. Abrir una imagen no aplica Auto ni cambia de método.

Se ha retirado el retoque de barrido/perturbación de Atkinson tras comparar la misma foto con el código anterior a las optimizaciones. Atkinson vuelve a producir sus puntos originales: los defectos comunes de la vista se corrigen en la representación compartida, sin modificar cada algoritmo para ocultarlos. La comparación sobre la foto de reproducción confirmó igualdad píxel a píxel con los siete algoritmos anteriores, incluido Atkinson restaurado. Floyd rápido sigue siendo una opción diferente del Floyd original.

Los cambios sucesivos de controles se agrupan brevemente y cancelan los cálculos obsoletos. Rotación, tonos y muestreo se reutilizan mientras solo cambie el umbral o el algoritmo. El original de comparación permanece fijo y la ventana principal actualiza únicamente la imagen cuando cambia el B/N, sin redibujar todas las capas. El resultado final se calcula a la resolución física, sin una segunda conversión B/N distinta para la vista.

## Exportar la PCB con sus modificaciones

**Exportar Gerber** mantiene el diálogo de capas y recetas. Las casillas tienen una marca de alto contraste y la selección, modo y holgura se conservan al volver a abrir el diálogo durante la sesión. Las capas sin marcar conservan su contenido original en el paquete.

En un proyecto autocontenido, se generan la carpeta y el ZIP nuevos dentro de `exports/serigrafia`. En el flujo de archivos sueltos o ZIP sin proyecto completo se conserva el destino anterior: junto al ZIP de origen, o en la carpeta elegida si no había ZIP. Las siguientes exportaciones usan el siguiente número libre y conservan el paquete de origen.

El paquete conserva los archivos originales no editados, incluidos taladros, parámetros e informes. Incluye las capas modificadas y un manifiesto nuevo con sumas SHA-256 y ajustes de conversión. El manifiesto anterior se conserva en `historial_editor/`. Los informes de Allegro corresponden al origen; las modificaciones necesitan su revisión CAM. La aplicación verifica el ZIP antes de dar la exportación por terminada y no sobrescribe el paquete original ni exportaciones anteriores.

Con un contorno PCB cargado, la imagen se **recorta automáticamente por el borde** en la vista general, en la previsualización de exportación y en el Gerber generado. Se respeta su posición, escala y giro actuales: no se centra ni se ajusta de nuevo al exportar. El marco completo sigue disponible para moverla a mano. El recorte incluye el ancho real de los trazos y funciona también al generar una capa nueva y con SVG. Los contornos cerrados pueden ser cóncavos o tener vaciados; si el contorno detectado está abierto, hay que cerrarlo antes de exportar. Sin contorno cargado se mantiene la exportación libre. El recorte no añade separación respecto a los pads.

## Frontal Eurorack 3U

Primero abre la interfaz de serigrafía y pulsa el menú **Frontal Eurorack 3U…**. Los siguientes controles pertenecen a esa ventana adicional.

La barra azul ordena las acciones principales: **1. Cargar PCB / Gerber… → 2. Importar agujeros… → 3. Importar textos… → 4. Exportar Gerber / ZIP…**. Después de cargar la PCB, ajusta el ancho y el centrado en el lateral antes de importar objetos. La fila superior separa **Guardar proyecto** (documento editable) de **Exportar dibujo SVG…**. Los botones y campos usan texto claro y estados de foco, pulsación y desactivación diferenciados; el tema se limita al frontal y sus diálogos.

### Selección múltiple y edición directa de textos

- Para recolocar las etiquetas sin arrastrar: pulsa **Etiquetas PCB** encima del dibujo y después **Mover…**. Introduce ΔX/ΔY en milímetros (derecha/arriba positivos; izquierda/abajo negativos). Se conserva la distribución del grupo. El título manual queda fuera de esa selección.
- Los botones de flecha y las flechas del teclado sobre el panel desplazan la selección según **Paso (mm)**. Mayús multiplica el paso por diez; Alt lo divide por diez. Mantener pulsada una flecha ocupa un único paso de deshacer. Los campos de edición conservan sus flechas normales.
- **Solo textos** está activado por defecto para los movimientos precisos y la alineación: los agujeros seleccionados no se desplazan. Se puede desmarcar para trabajar con ellos. **Misma X / Misma Y** alinea los objetos elegibles con el activo; si el activo es un agujero protegido se utiliza el primer texto seleccionado. **Esc** cancela un arrastre que estaba en curso; Deshacer recupera los movimientos ya aplicados.
- La PCB se muestra como una imagen de referencia en caché y los objetos del frontal siguen siendo editables. Seleccionar o mover no repinta sus miles de trazos ni cambia los datos de fabricación. Zoom, desplazamiento, visibilidad y cambios de PCB reconstruyen la vista cuando corresponde.
- **Ctrl + clic** añade o quita objetos de la selección; **Mayús + clic** añade. En modo **Seleccionar**, arrastra un recuadro en una zona vacía para seleccionar un grupo. La lista de objetos admite Ctrl/Mayús y **Ctrl+A** selecciona todo cuando se trabaja sobre el panel.
- Arrastra un objeto seleccionado para mover el grupo conservando su distribución. **Duplicar selección** crea copias independientes y **Eliminar selección** borra el grupo. Cada operación ocupa un paso de deshacer.
- Los botones **MAYÚSCULAS** y **minúsculas**, encima del panel y junto al campo de texto, cambian únicamente los textos seleccionados. Conservan posición, tipografía, formato y referencia original de PCB. **Aplicar estilo a textos seleccionados** cambia su estilo conservando sus contenidos distintos. Los campos individuales y **Actualizar objeto activo** siguen editando solo el objeto activo indicado en el lateral.
- **Doble clic sobre un texto** abre su edición directamente sobre el panel. **Enter** o **Aplicar texto** confirma; **Mayús+Enter** añade una línea; **Esc** o **Cancelar** descarta. No cambia su posición ni su estilo. Guardar o exportar confirma primero el texto pendiente; si no es válido, permite corregirlo antes de continuar. Mientras se escribe, los atajos de selección, borrado y deshacer de objetos no afectan al panel.

Ejecuta `sputtering_design_tools.py` o abre `Sputtering Design Tools.pyw` con doble clic en Windows. Para abrir una demostración sintética:

```powershell
python sputtering_design_tools.py --demo
```

1. Usa **Cargar PCB / Gerber** para abrir un `.brd` y preparar su proyecto completo, o el contorno y la serigrafía sueltos o en ZIP. Se mantienen alineados por sus coordenadas originales. El `.brd` se lee mediante Cadence Extracta; la geometría visible procede de su fabricación comprobada.
2. Elige la capa de contorno en la lista de referencia. Si el nombre contiene `outline`, `profile`, `edge_cuts` o termina en `.gko` / `.gm1`, se propone automáticamente; de lo contrario, confirma la capa manualmente.
3. Elige un ancho entero de HP y aplica. La altura es 128,5 mm y el ancho físico es `HP × 5,08 − tolerancia`. La tolerancia total inicial es 0,34 mm y se puede cambiar; no representa una medida universal para todos los fabricantes. [Referencia mecánica Doepfer](https://doepfer.de/a100_man/a100m_e.htm).
4. La PCB se centra en los dos ejes sin escalarla. Todas las capas comparten la misma traslación. **Mover PCB** permite ajustar después su posición. Un aviso indica si sobresale del frontal.
5. En **Tipo de agujero**, elige **Potenciómetro (Ø8,128 mm)**, **Jack 3,5 mm (Ø6,1 mm)**, **SPDT mini (Ø6,5 mm)**, **DPDT (Ø6,5 mm inicial, revisable)**, **Tornillo de rack (Ø3,2 mm)** o **Personalizado**. Elegir tipo activa la colocación de agujeros y prepara su nombre y diámetro; no modifica objetos existentes. Los diámetros son plantillas iniciales editables para el casquillo de la pieza, no medidas universales para toda una familia. El tipo y el diámetro realmente usados se guardan en el proyecto. Para editar un agujero ya colocado, selecciónalo, cambia su diámetro y pulsa **Actualizar objeto activo**.
6. Haz clic para colocar o introduce X/Y y pulsa **Añadir nuevo en X / Y**. El origen es la esquina inferior izquierda; X/Y son el centro del objeto. **Texto** utiliza el tamaño como altura tipográfica. Arrastra para mover. La rejilla inicial es 0,5 mm; usa 0 para desactivarla. **Actualizar tornillos de rack Ø3,2** sustituye el patrón anterior, incluso en proyectos antiguos con duplicados, y conserva los agujeros de controles y textos. Al aplicar otro ancho, los tornillos de rack existentes se actualizan automáticamente. Ambas acciones admiten deshacer/rehacer.
7. Guarda en `.panel.json`: incluye las capas de referencia para que el proyecto sea portátil. **Exportar SVG** genera el frontal a escala 1:1, separando contorno, agujeros y textos; no incluye la PCB de referencia.

Para recolocar objetos, pulsa y arrastra directamente un agujero o texto existente: tienen prioridad aunque esté activa la herramienta **Agujero** o **Texto**, por lo que no se crean duplicados al intentar moverlos. En una zona vacía, la herramienta de colocación sigue añadiendo objetos. **Esc** pasa a selección. Puedes agarrar un objeto desde cualquier punto de su dibujo, sin que salte al centro del cursor; se respeta la rejilla, el zoom y el desplazamiento de la vista. Los campos X/Y se sincronizan al colocar, seleccionar y mover. Un arrastre completo ocupa un único paso de deshacer; un clic de selección no altera el historial. **Mover PCB** sigue siendo una herramienta explícita para desplazar solo la referencia.

La rueda hace zoom, el botón derecho desplaza la vista y el panel lateral tiene desplazamiento. Hay deshacer/rehacer; los campos de texto conservan sus propios atajos. El ejemplo `examples/demo.panel.json` es sintético y no representa la PCB real de distorsión.

### Colocar agujeros desde los footprints de la PCB

En **PCB de referencia**, pulsa **Importar agujeros desde .brd…**. El diálogo lee una PCB Allegro `.brd` guardada mediante el Extracta instalado, sin modificarla ni abrirla para edición. También admite una referencia `.pcb-components.json` previamente extraída; los datos quedan incorporados al proyecto portátil. La lectura se hace en segundo plano. Los Gerber por sí solos no contienen las identidades de componentes que necesita esta función.

Revisa la tabla de componentes, centros X/Y del panel, diámetro y acción. Doble clic o Espacio marca/desmarca filas. Los círculos violetas son previsualización y **Cancelar** no modifica el proyecto. **Aplicar agujeros seleccionados** añade o actualiza los agujeros reconocidos en una sola acción de deshacer. Repetirlo no duplica sus agujeros; los objetos manuales se conservan. Una coincidencia con un agujero manual se conserva y los solapes o agujeros fuera del frontal quedan desmarcados para revisión.

La biblioteca inicial reconoce nombres exactos:

| Footprint | Centro mecánico utilizado | Diámetro inicial editable |
|---|---|---:|
| `SPTR_RK09_123` | Centro entre sus dos anclajes mecánicos sin número de pin | 8,128 mm |
| `SPTR_PJ301M` | Centro del padstack `C150_H300`, situado bajo el casquillo | 6,1 mm |
| `SPTR_SPDT` | Centro del pin 2 | 6,5 mm |

Estos centros se han contrastado con la geometría de la distorsión; los diámetros siguen siendo plantillas para ajustar al componente físico. No se utiliza el centro de los pads eléctricos como aproximación. Las posiciones absolutas de pines extraídas por Cadence ya incluyen giro y espejo, por lo que no se vuelve a girar ni reflejar el agujero. La cara de cada regla se elige explícitamente; inicialmente es TOP. Los componentes sin colocar, sin regla, de otra cara o con anclajes ambiguos no generan agujeros por suposición.

Los valores iniciales de potenciómetro (8,128 mm), jack (6,1 mm) y rack (3,2 mm) se toman de una referencia de frontal existente. Se conserva exactamente 8,128 mm, sin redondear a 8 mm. La medida SPDT (6,5 mm) sigue siendo una plantilla editable, sin verificar en esa referencia. Los proyectos antiguos conservan sus medidas y reglas guardadas; cambiar el preajuste no modifica automáticamente sus agujeros.

En **Regla de tu biblioteca** puedes asociar otros nombres de footprint a un tipo, diámetro y centro (dos anclajes mecánicos, pin, padstack u origen explícito). **Guardar regla y recalcular** prepara los cambios en el diálogo; se incorporan al proyecto con **Aplicar seleccionados** y **Guardar**. **Importar/Exportar biblioteca de reglas…** permite reutilizarlos en otros módulos.

Los agujeros generados conservan la referencia del componente y siguen a la PCB al centrarla, desplazarla o cambiar el ancho del frontal. Siguen pudiéndose arrastrar y editar: un ajuste manual conserva su desplazamiento relativo a la PCB. Una nueva generación explícita vuelve a proponer el centro de la regla y su diámetro. Al cargar otra PCB de referencia, los agujeros anteriores quedan como objetos editables sin vinculación a la nueva placa.

La importación comprueba la coincidencia de límites de contorno y, si hay Excellon cargado, contrasta los pines THT con los taladros para detectar una versión desalineada. Actualmente la extracción de contorno desde Allegro admite líneas y rectángulos en `BOARD GEOMETRY/DESIGN_OUTLINE` u `OUTLINE`; se rechazan otros contornos. Esto no lee cambios de Allegro que aún no estén guardados. El lector utiliza los campos documentados de las vistas COMPONENT, COMPOSITE_PAD y FULL_GEOMETRY de la instalación Cadence.

### Reutilizar la herramienta en otros módulos

**Herramientas → Nuevo módulo / frontal** inicia un documento sin capas, agujeros, textos ni referencias de componentes del anterior, y ofrece guardar los cambios pendientes. Carga los Gerber/drills del módulo nuevo y lee su `.brd` guardado. Las coordenadas no dependen de un nombre de proyecto ni de una ruta de fabricación. Se comprueban el contorno y los pines contra los taladros cargados; una versión desalineada se rechaza.

En el importador, **Compatibilidad de la PCB…** muestra todas las huellas, cantidades, anclajes disponibles y motivos de exclusión. Se reconocen RK09 normal/invertido, doble, variantes con anclajes MH1/MH2, PJ301M y los interruptores configurados. El centro siempre procede de anclajes explícitos; no se supone que el origen del símbolo sea el eje. `BOTH` permite una regla para ambas caras, usando los pines absolutos de Cadence, que ya incluyen giro y espejo.

Las reglas nuevas de mini-SPDT, DPDT y variantes de interruptor quedan desmarcadas para revisar diámetro/anclaje; **Marcar todos válidos** no las confirma. Una selección individual es explícita; guardar una regla revisada la configura para futuras propuestas. Los LED y pulsadores muestran una sugerencia de centro entre pines, pero requieren definir el diámetro o corte: no se genera un agujero por el nombre del componente. La herramienta coloca agujeros circulares; los recortes de otras formas necesitan un flujo de edición adicional.

**Usar esta biblioteca en todos los módulos** guarda las reglas en `%LOCALAPPDATA%/SputteringDesignTools/footprint-hole-rules.json`. Los módulos nuevos reutilizan esa biblioteca. Las reglas guardadas dentro de un proyecto tienen prioridad, para conservar sus personalizaciones. La biblioteca se puede exportar/importar como JSON; no requiere la ruta de la biblioteca Allegro original. Las huellas nuevas que aún no tengan regla se muestran como pendientes. La lectura `.brd` sigue necesitando Extracta y un contorno formado por líneas/rectángulos; no es una promesa de compatibilidad con cualquier formato o huella sin revisar.

### Opciones de las etiquetas importadas

En **2 · PCB de referencia**, **Importar textos desde .brd…** propone los refdes de los componentes con una regla de agujero. Utiliza la referencia de componentes guardada en el proyecto o permite leer un `.brd` / JSON actualizado. No importa todos los textos de serigrafía ni añade referencias de resistencias sin agujero.

Elige altura de texto, separación respecto al borde del agujero y posición **Encima/Debajo/Izquierda/Derecha**, y pulsa **Actualizar previsualización**. La tabla y los textos violetas muestran lo que se añadirá; marca las referencias deseadas y pulsa **Aplicar seleccionados**. Los textos quedan editables, se exportan en SVG y admiten deshacer/rehacer. Si has movido o cambiado el diámetro de un agujero generado, la etiqueta usa esa posición y diámetro actuales. Al mover la PCB, las etiquetas generadas la acompañan. Una importación repetida permite actualizar el estilo de las etiquetas existentes sin duplicarlas.

**Herramientas → Vaciar agujeros y textos (conservar PCB)** permite empezar el frontal desde cero manteniendo ancho, referencias y biblioteca; se puede deshacer. Los objetos vuelven al reabrir únicamente si forman parte del proyecto guardado: no son archivos temporales. Las lecturas `.brd` utilizan una carpeta temporal independiente que se elimina al finalizar.

### Exportar el frontal como PCB para JLCPCB

**Gerber / ZIP…** guarda y exporta el estado abierto del frontal. Crea un ZIP numerado con archivos descriptivos de contorno `GKO`, agujeros sin metalizar `drl`, serigrafías `GTO/GBO`, cobre `GTL/GBL` y máscaras `GTS/GBS`. No copia las capas de la PCB de referencia. El ZIP contiene solo archivos de fabricación; junto a él se guardan una vista SVG con geometría fija y un informe JSON con medidas, taladros y SHA-256. No se sobrescriben exportaciones anteriores.

El perfil es FR4 de dos capas con tinta en la cara superior. Las máscaras cerradas dejan cubierto el cobre. La opción **Relleno de cobre bajo la máscara** genera planos separados 0,3 mm del borde y de los agujeros; puede desactivarse para exportar sin cobre. Al pedir, selecciona máscara negra y serigrafía blanca para el acabado usado en la previsualización. El espesor, cantidad y resto de opciones se eligen en JLCPCB; el Gerber no establece colores ni espesor.

La exportación impide agujeros solapados/fuera del panel, menos de 0,2 mm de material entre taladros, tinta fuera del frontal y tinta a menos de 0,15 mm de un agujero. La altura impresa del texto debe alcanzar 1 mm. Los círculos de 8,128 mm se mantienen en Excellon: [JLCPCB indica que los agujeros desde 6,3 mm se fresan mediante CNC](https://jlcpcb.com/capabilities/pcb-capabilities/). Se utilizan [nombres de capas reconocibles y coordenadas absolutas en milímetros](https://jlcpcb.com/help/article/gerber-files-preparation). Revisar siempre contorno, taladros y texto en el visor CAM de la orden antes de confirmarla.

### Reimportar y actualizar etiquetas

Activa **Actualizar ya importadas** para cambiar fuente y tamaño de las etiquetas vinculadas existentes sin duplicarlas. Está activo inicialmente, junto con **Conservar posiciones**, **Conservar textos editados** y **Conservar tamaños**: así se mantiene la colocación manual, el contenido personalizado y los demás ajustes avanzados. Desmarca **Conservar tamaños** para imponer el tamaño elegido a todas las etiquetas. Puedes desmarcar la conservación de posiciones para recolocarlas o la de texto para regenerar prefijos/sufijos y nombres. Desactivar la actualización conserva las existentes como antes. Los textos manuales sin vínculo no se reemplazan. La tabla muestra Añadir / Actualizar y los cambios se previsualizan; aplicar constituye un solo paso de deshacer.

### Edición avanzada de textos

El campo de texto permite hasta ocho líneas. Cada objeto guarda giro en grados, ancho entre 25–400 %, separación entre letras, interlineado, alineación izquierda/centro/derecha y engrosado de tinta por lado. **Actualizar objeto activo** confirma los ajustes. **Aplicar estilo a todos los textos** cambia tamaño/estilo sin alterar contenido, posiciones, agujeros ni vínculos a la PCB, con una sola acción de deshacer. **Duplicar objeto seleccionado** crea una copia editable independiente del vínculo automático del original.

La importación de refdes permite **Encima/Debajo/Izquierda/Derecha**, separación desde el borde real del agujero, desplazamientos X/Y, prefijo y sufijo, y quitar los números finales. Los centros de los componentes siguen identificados por su refdes original aunque la etiqueta visible se abrevie. Las etiquetas existentes conservan sus ediciones al repetir la importación. El ancho y alto para la colocación se calculan con la fuente real.

El giro, ancho y espaciados se comparten entre pantalla, vista de fabricación y Gerber. El informe de exportación incluye los estilos realmente utilizados. El engrosado inicial sigue siendo 0,075 mm por lado; reducirlo puede producir detalles demasiado finos para serigrafía. El SVG editable mantiene texto y transformaciones; la vista de fabricación conserva la geometría exacta de tinta.

### Fuentes disponibles

Se añaden **Consola · Consolas**, **Gótica · Old English** e **Industrial · Bahnschrift**, además de Arial. Fuentes disponibles: **Arial, Consolas, Old English Text MT, Bahnschrift, Impact, Arial Narrow, Stencil, OCR A Extended, Agency FB, Rockwell, Magneto y Georgia**. La fuente se elige al colocar textos, al editar un texto seleccionado (**Actualizar objeto activo**) y al importar refdes. Se guarda con cada elemento. Se necesitan las fuentes instaladas; si falta una, se avisa en lugar de sustituirla silenciosamente al exportar.

La vista del frontal, la vista SVG de fabricación y el Gerber usan la misma máscara de tinta a 0,025 mm. Los contornos de los caracteres se convierten en regiones Gerber rellenas; los huecos de las letras se conservan. Se engrosan 0,075 mm por lado para proteger trazos finos. No se envían archivos de fuentes al fabricante. Para la gótica conviene usar texto mayor y revisar sus huecos. El SVG editable continúa disponible por separado y depende de las fuentes del equipo donde se abra.

### SVG editable y lector de referencias

El SVG es un plano vectorial para continuar el diseño: los círculos representan cortes/agujeros, no taladros Excellon. Los textos permanecen editables y dependen de la fuente Arial/sans-serif; antes de fabricar, conviértelos a trazados en tu editor vectorial y comprueba medidas y encaje mecánico. La aplicación no comprueba distancias de tuercas, cuerpos de potenciómetros, componentes ni profundidad detrás del panel. Avisa de agujeros que se solapan o salen del borde; el aviso de posición del texto corresponde a su centro, no a toda su extensión tipográfica.

La referencia admite Gerber absoluto con supresión de ceros iniciales, aperturas C/R/O, líneas, arcos multicuadrante aproximados y regiones simples. Se admiten las declaraciones de transformación identidad de Allegro; se rechazan macros, transformaciones no soportadas, regiones de varios contornos y otros formatos de coordenadas. Las capas cargadas son referencias y no se copian al paquete del frontal. Siguen pendientes la revisión visual de polaridades complejas y la validación del encaje mecánico de cada diseño.

### Comprobaciones

```powershell
python -m unittest discover -s tests -v
```

Las pruebas verifican unidades y aperturas, trazos modales, límites físicos, centrado, patrón de tornillos, validación, guardado/reapertura, escala y contenido SVG, carga ZIP y edición/deshacer/rehacer. Las pruebas de ventana requieren una instalación funcional de Tkinter.

## Versión inicial

Incorporada el 22 de octubre de 2026 como copia exacta del script existente. El hash de `BASELINE.md` identifica esa primera versión. El 23 de octubre se añadió el espacio de frontales y se corrigieron delimitadores, selección G54, operaciones modales y conversión de aperturas del lector para poder cargar las referencias a escala real. La primera carga de la distorsión verifica dimensiones y geometría reconocida; no equivale a validar el panel para fabricación.

Origen y verificación: [BASELINE.md](BASELINE.md).
Revisión y mejoras pendientes: [plan de evolución](../../docs/PLAN_GERBER_SILKSCREEN_EDITOR.md).

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

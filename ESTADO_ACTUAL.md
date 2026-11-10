# Estado de la aplicación — 8 de noviembre de 2026

El flujo original de serigrafía mantiene su validación. El frontal continúa su desarrollo con exportación de fabricación, edición de textos y biblioteca reutilizable entre módulos.

## Apertura directa desde Allegro y etiquetas sin regla de agujero — 8 de noviembre de 2026

El lanzador recibe juntos el BRD y el ZIP F exacto mediante `--board` y `--fabrication`. El editor abre serigrafía, prepara sus copias locales y ofrece el frontal en una ventana adicional. La apertura manual conserva la búsqueda automática y ofrece seleccionar el ZIP cuando falla la preparación. La fabricación elegida se mantiene incluso al reimportar desde una copia local del BRD.

La carga admite placas sin reglas mecánicas reconocidas: verifica la identidad/revisión y el contorno disponibles, además del hash observado del BRD cuando consta. Un paquete histórico sin registro mecánico necesita selección explícita y contorno coincidente. Se registra el nivel de comprobación en `fabrication_check`; cargar referencias no crea propuestas de agujeros desconocidos ni sustituye la comprobación de su encaje.

El menú PCB y referencias abre o reutiliza el importador de textos del frontal. Aparecen todos los componentes colocados en TOP/BOTTOM; los que carecen de anclaje mecánico parten del origen del footprint y requieren revisar/seleccionar su posición. Se mantienen las opciones de reimportación y conservación de etiquetas. Si ya hay un agujero vinculado, se respeta su diámetro para separar el texto aunque falte su regla actual.

Se documentan el recorrido de usuario, las carpetas, los niveles de comprobación y el enlace entre Guardado, PCB y F/E en README y guía. Los tres documentos canónicos del contrato compartido se incorporan al historial de esta rama, idénticos a los publicados por el asistente Allegro, para que las referencias funcionen en un clon nuevo.

Pasan **186 pruebas completas**, incluidas apertura de la liberación exacta sin reglas mecánicas, selección explícita de históricos, reutilización del importador, referencias sin agujero y separación de etiquetas respecto a un agujero existente sin regla actual.

## Coordinación de liberaciones con Allegro — 8 de noviembre de 2026

El editor incorpora el contrato compartido `sputtering.fabrication.v1`: consume F originales y produce E con UUID nuevo, identidad/revisión de placa conservadas, raíz y padre exactos, hashes e inventario completo. Los históricos mantienen procedencia incompleta; no se reescriben. Los frontales creados desde cero conservan su flujo anterior y no toman la identidad física de la PCB de componentes.

El vínculo explícito del Asistente Allegro se consulta en modo lectura y permite continuar un módulo tras renombrar su BRD. La interfaz distingue Guardado, PCB y F/E, muestra cambios observados en el BRD guardado y mantiene explícitamente sin comprobar la memoria de Allegro. El menú Módulo añade consulta, comparación de archivos entre liberaciones y recuperación de la edición asociada, si existe. La guía explica los números y la actualización desde Allegro.

Pasan **182 pruebas completas**. Incluyen lectura/exportación con el mismo validador, ZIP corruptos, inventario estricto, F→E→E con hashes exactos, protección frente a UUID reutilizado, comparación desde la ventana sin alterar paquetes y reanudación del módulo tras un renombrado explícitamente vinculado. El fixture F compartido y las E001/E002 sintéticas han sido verificados por ambos productores; el asistente también ha confirmado que una F002 nativa de prueba pasa el lector estricto del editor. No se han modificado circuitos ni paquetes reales para adoptar el contrato.

## Carga autónoma con Capture y Allegro — 8 de noviembre de 2026

Abrir proyecto acepta directamente `.brd`, ZIP y proyectos guardados. Para módulos nuevos, la app reconoce `allegro` y crea `Sputtering/<nombre>` en la raíz compartida con Capture, sin mover los archivos CAD. Conserva el reconocimiento de módulos ya existentes junto al `.brd`. Abrir otra PCB con igual nombre en un proyecto diferente inicia o continúa ese módulo sin heredar el frontal anterior. Los guardados de archivos sueltos también proponen carpetas junto a su proyecto; los diálogos nuevos no usan la carpeta del código como almacén predeterminado.

La búsqueda de fabricación acepta Gerber y taladros sueltos junto al `.brd`. Cuando esa carpeta contiene fuentes CAD, se seleccionan solo los archivos de fabricación y sus parámetros; `.brd`, `.dsn` y `.opj` quedan fuera del paquete de fabricación. Las referencias nativas guardadas se conservan como copias locales separadas.

Se añade `GUIA_CARGA_PROYECTO.txt`: accesible desde Ayuda en ambas apps y copiada dentro de cada módulo preparado. Describe primera carga desde el acceso genérico, requisitos, carpetas automáticas, guardado, exportación y reapertura con `modulo.module.json`.

Pasan las 10 comprobaciones de módulo y las 10 de preparación/referencias. El recorrido del botón Abrir proyecto incluye primera carga en una raíz Capture/Allegro, guardado sin seleccionar ruta, exportación y reapertura, verificando los originales. Extracta también ha leído una copia real de PCB: 103 componentes, contorno correcto y hash idéntico. Se ha verificado que el acceso genérico del escritorio abre la app sin un proyecto preseleccionado.

## Módulo autocontenido y recorrido continuo — 3 de noviembre de 2026

Los módulos nuevos se crean en `Sputtering/<módulo>` junto al `.brd`. `modulo.module.json` relaciona frontal, serigrafía PCB, imagen del frontal, guardados y exportaciones mediante rutas relativas. Las copias fijadas de circuito/fabricación y los recursos necesarios permanecen dentro de esa carpeta. Los guardados generan revisiones por etapa, sin duplicarlas cuando el contenido no cambia. Se verifican sumas de documentos, recursos y resultados; un bloqueo de sistema operativo protege el índice compartido por las dos apps. Recuperar desde el menú Módulo conserva el trabajo actual y crea una revisión adicional.

El frontal incorpora **5. Imagen del frontal…**. Utiliza una exportación vinculada al guardado actual o crea una nueva, abre la misma etapa de imagen y conserva su transformación/conversión al actualizar textos. Las exportaciones de PCB, frontal e imagen tienen carpetas separadas dentro del módulo y referencias al guardado y origen exactos. Las capas individuales y SVG también se numeran dentro del módulo. Desde una imagen de frontal, abrir el frontal recupera la PCB original como referencia; no sustituye esa referencia por las capas del panel.

Pasan **164 pruebas completas** y las **7 pruebas específicas de módulo** tras añadir la comprobación del botón de recuperación. Abarcan guardados sin cambios, nueva lectura de la misma PCB, actualización de etiquetas manteniendo la foto, exportación vinculada, cambio de etapas, traslado de carpeta eliminando fuentes originales, detección de alteraciones, migración conservadora y recuperación desde los controles de la app.

La distorsión real se ha consolidado junto al `.brd`, conservando la última edición del 3 de noviembre (contraste 2,05, umbral 0, contorno 0,4 mm y la posición guardada). Se validó allí y en una copia trasladada, manteniendo 27 agujeros y 25 textos. Los accesos del escritorio apuntan al nuevo módulo; los proyectos anteriores siguen como respaldo y redirigen a la edición actual. Los paquetes previos sin revisión editable guardada se identifican como históricos; la imagen antigua de la PCB se conserva integrada en el último ZIP, sin inventar una sesión editable. Los diseños privados no se añaden al repositorio de la app.

## Ventanas de texto y guardado de ambas apps — 3 de noviembre de 2026

La receta **Respetar textos** permite **Recuadro** o **Contorno / erosión**, con margen por capa. Recuadro conserva el resultado anterior; Contorno dilata la tinta compuesta a 0,025 mm con un elemento cuadrado para erosionar la imagen. Usa regiones claras y huecos antes de calcular la protección. La previsualización y el exportador comparten ventanas; las letras originales y los algoritmos de foto se conservan. Generar una capa individual de frontal reutiliza la forma y margen guardados. Se corrige además que la vista de recuadros reemplazaba accidentalmente la variable de dimensiones y que dibujaba los bordes de las regiones como trazos extra.

Ambas apps muestran la ruta del proyecto, ofrecen Guardar como en la barra y Ctrl+Mayús+S, y terminan las exportaciones con una ruta seleccionable, Copiar ruta y Abrir carpeta. El frontal guarda antes de generar su ZIP; cancelar o fallar ese guardado detiene la exportación. Los frontales sin metadatos Allegro también usan exports/frontal y conservan sesiones de imagen separadas por nombre de archivo. Serigrafías guarda las recetas después de confirmarlas y corrige la conversión de claves antiguas al guardar imágenes, evitando claves no válidas para JSON. Un fallo al guardar la sesión impide exportar o sustituir la edición.

Pasan **157 pruebas de la batería completa**, seguidas de las **8 pruebas de proyectos** tras añadir la sesión de imagen de frontales independientes. Sobre copias del proyecto real se recorren los botones de guardado de ambas apps, ambos modos de vista previa, el diálogo real de recetas y la exportación completa; reabrir conserva la imagen de 171,1927 × 128,3945 mm, su posición y contraste 1,72 sobre el frontal de 131,74 × 128,5 mm. Las otras capas del ZIP quedan idénticas al origen y los proyectos originales mantienen sus hashes. La captura nativa falló dos veces por tiempo de espera; la validación de controles se hizo mediante Tkinter y queda pendiente la inspección visual de Windows. Las copias y exportaciones de validación se conservan localmente en validation-output, fuera del repositorio.

## Conversión reactiva, ajustes finos y Auto — 2 de noviembre de 2026

Se añade Auto como propuesta reversible, con análisis local de histograma y clasificación de dibujo/fotografía. Revertir Auto recupera los valores previos; no se modifican tamaño, posición, giro, píxel o polaridad elegida. Los ajustes finos incluyen brillo, gamma, nitidez y suavizado, con valores neutros compatibles con el comportamiento anterior. Se persisten en la sesión y el manifiesto y se aplican también al Gerber. Se añaden Floyd rápido nativo, Bayer 2×2 y trama agrupada 4×4. Los métodos menos habituales se recogen en un apartado desplegable.

La difusión anterior admite cancelación entre filas; los valores obsoletos dejan de consumir tiempo antes del último ajuste. Se reutilizan los tonos preparados y el muestreo al variar el umbral, se agrupan las actualizaciones de controles y se mantiene fija la imagen original de comparación. El B/N principal se calcula en segundo plano y solo renueva la imagen superpuesta; se conservan las capas cargadas. El trabajo pendiente se cancela al cerrar. El modo nativo rápido es una alternativa con otra distribución de puntos y curva de umbral, no una sustitución silenciosa de los métodos anteriores.

Pasan **135 pruebas**, incluidas ocho nuevas sobre Auto reversible, controles visibles, parámetros, cancelación, respuesta de la interfaz, caché, transparencia y coherencia con exportación. La prueba de puntos escritos en Gerber se amplía a los diez algoritmos. Se comparan además **252 casos con la versión anterior**, con máscaras idénticas en los métodos heredados usando ajustes neutros. En una imagen sintética de 858 × 1143 píxeles, Floyd anterior tardó 2,67 s y el modo nativo 0,029 s; son métodos diferentes y tiempos locales. No se modificaron los diseños ni los ZIP del usuario.

## Posicionamiento preciso y selección rápida — 2 de noviembre de 2026

Se añaden desplazamientos ΔX/ΔY en milímetros, flechas con paso editable, Mayús ×10 y Alt ÷10, alineación de centros X/Y y selección directa de etiquetas vinculadas a PCB. Solo textos protege los agujeros por defecto en estas acciones; se puede desactivar. Las posiciones vinculadas se actualizan conservando su desplazamiento respecto a la PCB. Una pulsación mantenida de flecha ocupa un paso de deshacer y Esc cancela el arrastre en curso. El proyecto guardado del usuario no se recoloca automáticamente.

La vista de referencia se compone en una imagen en caché con las mismas coordenadas y capas. Seleccionar y mover actualiza únicamente los objetos editables; el grupo arrastrado usa una operación común de Canvas. El historial comparte la geometría de referencia de solo lectura y copia sus indicadores de visibilidad, los objetos y metadatos editables. Se reconstruye la referencia al cambiar vista, tamaño, centrado o capas. No se rasterizan los archivos de fabricación ni cambia la exportación.

En la prueba local con 23 etiquetas, la secuencia de selección bajó de 10,29 s a 0,88 s y el gesto de arrastre de 10,22 s a 0,39 s. Son tiempos medidos en este equipo y no una garantía para cualquier proyecto. El archivo guardado quedó intacto. Pasan **127 pruebas**, incluidas siete regresiones nuevas de movimientos exactos, protección de agujeros, alineación, vínculos, historial, teclado, campos de edición, cancelación, controles visibles y representación de referencia con miles de primitivas.

## Proyecto autocontenido y pads con ranuras — 29 de octubre de 2026

La primera apertura de un `.brd` busca fabricación vecina y prepara `panel-projects/<módulo>` con copia del circuito, paquete verificado completo, componentes, biblioteca, frontal, imagen/ajustes de serigrafía y carpetas de exportación. Se utilizan rutas locales relativas al proyecto y se mantienen los orígenes como información. Las revisiones originales se ordenan por identidad y versión; los paquetes editados se excluyen. Una revisión nueva incompatible no provoca una sustitución silenciosa por una antigua. Los proyectos existentes se respaldan antes de actualizar y conservan sus objetos y traslación manual.

Se añaden referencias `.rou` para ranuras rectas horizontales y verticales, con comprobación de herramienta, formato y secuencia de fresado. Sus centros participan en la validación de pads junto con los taladros; se mantiene la tolerancia de registro de 0,05 mm. No se omite la comprobación cuando un componente utiliza ranuras. Los formatos o movimientos no admitidos se rechazan. El editor original muestra las ranuras y conserva los archivos en la exportación.

Los frontales guardados abren con las fuentes fijadas en la carpeta del proyecto; no necesitan localizar de nuevo los originales. La importación de componentes prepara esa misma carpeta en segundo plano. La imagen y sus parámetros se guardan en el proyecto al importar, exportar, guardar sesión o cerrar la aplicación. Se conserva el centrado manual al abrir el frontal desde el editor de serigrafías. Los botones del importador permanecen visibles y la biblioteca queda en un apartado desplegable.

Pasan **120 pruebas** en la suite completa, con diez comprobaciones nuevas de descubrimiento, copias, movimiento de carpeta, revisiones incompatibles, cancelación, manifiestos, rutas, ranuras, sesión de imagen, importación y exportación local. Después de los ajustes finales de apertura local también pasan las diez pruebas del nuevo flujo y una comprobación de ambas apps con el proyecto real. Los datos de fabricación y circuitos reales se mantienen únicamente en la carpeta privada de trabajo.

## Coherencia B/N, previsualización y Gerber — 29 de octubre de 2026

Se corrigen tres diferencias: el umbral general y el del editor ahora comparten variable; cerrar o exportar confirma los demás ajustes pendientes, y las vistas convierten a resolución física antes de reducir el resultado binario para pantalla. El exportador conserva los puntos aislados de un píxel como flashes D03: antes descartaba rachas de tinta más cortas que el ancho del trazo, eliminando muchos puntos de dithering. Se mantienen polaridad, recorte y recetas existentes.

La X del editor y Cerrar y aplicar confirman campos válidos; los valores inválidos detienen cierre/exportación/generación y permiten corregir el campo. Las previsualizaciones grandes de difusión se calculan fuera del hilo de interfaz, con una sola tarea activa y cancelación de consultas al cerrar. Se limpian las trazas de la variable compartida para poder reabrir el editor.

La validación reúne **110 pruebas**, con seis regresiones nuevas: reducción binaria frente a reducción de gris, comparación de la tinta de siete algoritmos con los puntos realmente escritos en Gerber (con y sin holgura), sincronización de umbral, cierre/exportación con ajustes pendientes, rechazo de valores inválidos e interfaz activa durante el cálculo. Gerbonara confirma además los 60 flashes y sus coordenadas en una trama que anteriormente se exportaba sin puntos. Los ZIP ya existentes requieren una nueva exportación; no se modifican automáticamente.

## Selección múltiple y edición directa — 27 de octubre de 2026

Se añaden MAYÚSCULAS/minúsculas para los textos seleccionados, accesibles encima del panel y junto al editor lateral. Ctrl + clic añade o quita objetos, Mayús + clic añade, y un recuadro en modo Seleccionar permite formar grupos. La lista admite selección extendida. Se pueden mover, duplicar, borrar o aplicar estilo a los textos del grupo en una única operación de deshacer. El objeto activo continúa teniendo sus propiedades individuales; un contador aclara cuántos objetos y textos están seleccionados.

El doble clic en texto abre un editor sobre el panel, con Enter/Aplicar para confirmar, Mayús+Enter para nueva línea y Esc/Cancelar para descartar. La operación conserva estilo, posición y vínculo de PCB. Guardar o exportar confirma la edición pendiente con validación; los atajos de objetos no actúan mientras se escribe. La conversión de mayúsculas/minúsculas valida todo el lote antes de cambiar el documento. Los duplicados son independientes y el arrastre de grupo conserva distancias y coordenadas vinculadas.

Pasan **104 pruebas locales**, incluidas siete regresiones nuevas de selección con modificadores/lista/recuadro, arrastre de grupo, texto en lote, atomicidad, vínculos, duplicado/borrado/deshacer, edición directa, guardado, cancelación y teclado. La comprobación del doble clic usa los eventos reales de Tk y verifica que no se crean textos duplicados; la suite mantiene la validación del editor original y la exportación Gerber del documento abierto.

## Legibilidad de botones y orden de trabajo — 27 de octubre de 2026

El frontal y sus diálogos usan controles oscuros propios con texto claro de 10 puntos, acciones principales en azul y foco de teclado visible. Se evita la mezcla de fondos nativos claros con texto tenue sin cambiar el tema global del editor original. Se aclaran los nombres de guardar, actualizar un objeto y exportar, se amplía ligeramente el lateral y se separa una barra numerada para cargar PCB, importar agujeros, importar textos y exportar Gerber/ZIP. La exportación incorpora un botón Cancelar explícito.

Pasan las **36 pruebas existentes de frontal, textos y biblioteca**. Se comprueba además que los botones caben en ventanas de 950 × 620 y tamaño normal, que los estilos principales se conservan al abrir diálogos y que el tema y los botones globales mantienen su configuración. La captura visual de Windows no pudo completarse por un tiempo de espera del servicio de ventanas; la comprobación de tamaño se hace sobre los controles reales de Tk.

## Más fuentes y reimportación de etiquetas — 26 de octubre de 2026

Se amplía el catálogo a 12 fuentes instaladas. El importador permite actualizar fuente/tamaño de etiquetas vinculadas existentes, conservando por defecto posiciones, textos editados y ajustes avanzados. Puede regenerar posición o contenido de forma explícita. La previsualización refleja el resultado, los textos manuales no se sustituyen y la operación admite deshacer/rehacer sin duplicar objetos.

Pasan **97 pruebas locales**; la geometría de tinta de las 12 tipografías se contrasta además con Gerbonara.

## Textos y reutilización entre módulos — 26 de octubre de 2026

Validación actual: **93 pruebas locales**; las comprobaciones posteriores del preajuste DPDT y del inicio de módulos nuevos también pasan.

Se añaden texto multilínea, giro, ancho, espaciado, interlineado, alineación, engrosado, estilo en lote y duplicado independiente. Las etiquetas importadas admiten cuatro lados, desplazamientos, prefijo/sufijo y eliminación de números finales, manteniendo el refdes de origen. Se actualiza el informe de fabricación para registrar los estilos exactos y validar la altura de caracteres sin confundirla con la altura de un bloque girado.

La biblioteca incluye variantes verificadas de RK09 y anclajes de interruptores, reglas por ambas caras, cobertura explícita de huellas y una biblioteca común reutilizable. Los interruptores nuevos cuyo diámetro requiere revisión no se seleccionan automáticamente. Las huellas sin regla no producen agujeros. **Nuevo módulo / frontal** elimina el estado del módulo anterior al iniciar otro documento.

La comprobación local abarca cuatro módulos distintos con sus Gerber y taladros reales: contornos y pines coinciden en los cuatro. La geometría de cuatro estilos de texto transformado también se contrastó con Gerbonara, con 13.130 comprobaciones de píxel. Los datos reales se conservan en el proyecto local y no se publican en el repositorio de la herramienta. La compatibilidad sigue dependiendo de una regla válida, el formato soportado y las versiones de PCB/Gerber alineadas.

## Fabricación del frontal y fuentes — 25 de octubre de 2026

Se añade **Gerber / ZIP…** para exportar el estado abierto del frontal a RS-274X + Excellon NPTH, contorno, serigrafías, máscaras cerradas y cobre opcional con separación de 0,3 mm. Genera ZIP numerado, vista SVG con tinta fija e informe SHA-256. Rechaza geometría fuera del panel, solapes y tinta sobre agujeros; las referencias de la PCB nunca forman parte del paquete. Los agujeros grandes conservan su diámetro para fresado CNC.

Validación actual: **82 pruebas locales pasan**, además de la lectura independiente de Gerbonara.

Se incorporan Consolas, Old English Text MT y Bahnschrift, con selección por elemento y en la importación de refdes. La fuente se guarda en el proyecto; pantalla, prueba de fabricación y Gerber comparten máscara de tinta. Las fuentes se convierten a geometría y sus archivos no se distribuyen. Las pruebas comprueban contorno/taladros exactos, cobre/máscara, equivalencia de área de tinta, las cuatro fuentes, controles de error, ZIP numerado e importación del documento abierto sin guardar. Un lector independiente Gerbonara contrasta unidades, posiciones/diámetros NPTH, polaridad y área de tinta, incluyendo huecos de caracteres de las cuatro fuentes.

## Medidas iniciales de agujeros — 25 de octubre de 2026

Se actualizan las plantillas manuales y la biblioteca de footprints a Ø8,128 mm para potenciómetro y Ø6,1 mm para jack, conservando Ø3,2 mm para rack. Los diámetros se contrastan con dos archivos Excellon de un frontal existente; no se publica su geometría. Se mantiene Ø6,5 mm para SPDT porque esa referencia no permite comprobarlo. La exportación conserva los diámetros exactos. Los proyectos guardados mantienen sus medidas y personalizaciones.

## Automatización del frontal — 25 de octubre de 2026

Se añade **Importar textos desde .brd…** como opción independiente: propone etiquetas refdes únicamente para componentes reconocidos con agujero, con altura, separación y posición encima/debajo ajustables. La previsualización no modifica el documento; al aplicar se crean textos editables, vinculados a la posición de PCB y exportables en SVG. La repetición conserva textos generados o manuales ya existentes. Generar de nuevo los agujeros no borra sus etiquetas. **Vaciar agujeros y textos** permite reiniciar el diseño conservando la PCB y admite deshacer. La escritura atómica también elimina su temporal si falla la escritura.

Pasan **75 pruebas locales**, incluidas siete nuevas regresiones de etiquetas: anclaje mecánico, agujero recolocado/diámetro editado, no duplicación, conservación de textos editados, guardado/reapertura, seguimiento de PCB, importación inválida atómica, previsualización/cancelación, deshacer/rehacer y arrastre.

Nueva opción **Agujeros desde footprints…**, con lectura de Allegro guardado mediante Extracta o una referencia JSON portátil. Se conserva el flujo de serigrafía. La biblioteca relaciona cada footprint con su tipo, diámetro, cara y anclaje mecánico. Admite editar esas reglas y exportarlas/importarlas para otros módulos.

La revisión muestra las propuestas antes de aplicar y dibuja círculos violetas sin modificar el proyecto. Los objetos manuales se conservan; las coincidencias y solapes manuales no se convierten en agujeros duplicados. Las actualizaciones de agujeros generados son idempotentes, admiten deshacer y guardan su referencia/posición relativa para seguir a la PCB al moverla o centrarla. Se mantiene su edición manual y la exportación SVG.

Comprobación real de la distorsión guardada: 23 centros reconocidos (10 potenciómetros, 8 jacks y 5 SPDT), con pines contrastados contra los drills del frontal. El proyecto de 26 HP conserva sus 15 objetos manuales; LVL2 y SCI quedan desmarcados inicialmente por solaparse con agujeros manuales. Se añade únicamente la referencia portátil de componentes al proyecto, con copia previa; los agujeros se aplican desde la revisión.

Pasan 68 pruebas locales, incluidas geometría mecánica, giro/cara mediante pines reales, unidades, componentes sin colocar, anclajes ambiguos, correspondencia con contorno/drills, conservación de manuales, biblioteca reutilizable, guardado/reapertura, vínculo a PCB, edición, previsualización, cancelación y deshacer. La PCB original permanece intacta; no se han subido los diseños de fabricación al repositorio de la herramienta.

## Actualización del frontal — 24 de octubre de 2026

Se retoma únicamente el frontal a petición de Luis: se corrige la acumulación de tornillos al cambiar HP y se añaden plantillas de agujero para potenciómetro, jack, SPDT, rack y personalizado. El editor de serigrafías conserva su estado validado.

El patrón de rack reemplaza los tornillos anteriores (incluidos los de proyectos antiguos) y se actualiza al aplicar otro ancho; no elimina agujeros de controles ni textos. Los preajustes preparan nuevas colocaciones, permiten editar el diámetro y conservan el tipo al guardar/reabrir. Las operaciones de edición y el cambio de patrón admiten deshacer/rehacer.

Se corrige también la prioridad de selección: pulsar un agujero o texto existente permite arrastrarlo, incluso con una herramienta de colocación activa, sin añadir otro objeto. Se conserva el punto de agarre con zoom y rejilla, se actualizan X/Y y el movimiento completo se deshace en un solo paso. Seleccionar sin mover no crea historial ni elimina la posibilidad de rehacer. Durante el arrastre de un objeto se mueve solo su dibujo, sin repintar las referencias Gerber en cada evento. La comprobación incluye eventos reales de ratón en la ventana de pruebas.

Validación actualizada: pasan las 55 pruebas locales, incluidas las 48 del cierre anterior y las regresiones de tornillos, plantillas y arrastre.

## Punto de entrada y flujo conservado

`Sputtering Design Tools.pyw` y `sputtering_design_tools.py` abren el editor de PCB y serigrafías. El frontal Eurorack es una ventana adicional del mismo proyecto; `--panel` permite abrirla directamente. Los accesos directos existentes siguen apuntando a la misma aplicación.

Se mantienen las capas Gerber, importación de imágenes, recetas de composición, alineación y transformación manual, elección de destinos, generación de capas y exportación. Los drills Excellon son referencias independientes y conservan su escala y posición.

## Correcciones entregadas

- Editor de conversión estable, vistas ampliadas, controles numéricos con coma decimal, pasos finos y botones de restablecimiento.
- Algoritmos con la misma polaridad. Blanco significa tinta sobre placa negra. Las opciones claros/oscuros distinguen fotografía positiva y negativa; Aplicar a PCB y exportación comparte los ajustes entre vista y archivo.
- Casillas de exportación visibles y preferencias de selección, receta y holgura recordadas durante la sesión.
- Paquete completo y ZIP numerado automáticos, sin sobrescribir el original. Se conservan las capas no editadas, taladros y parámetros; el manifiesto incluye SHA-256 y los ajustes aplicados.
- Recorte automático de la imagen por el contorno PCB en vista general, previsualización de exportación y Gerber, respetando la posición, escala y giro manuales. El marco completo permanece disponible para moverla. No se vuelve a centrar al exportar.

El recorte afecta al borde de la placa. No incorpora separación automática respecto a pads. Un contorno detectado debe estar cerrado; sin contorno cargado se mantiene la exportación libre. El lector conserva las limitaciones de formatos descritas en la guía.

## Validación del cierre

- 48 pruebas locales pasan en Python 3.12 con Tkinter, Pillow y NumPy. Incluyen el flujo original, conversión, polaridad, exportación, drills, frontal, colocación manual y recorte de contornos cóncavos/con vaciados.
- Comprobación independiente de la exportación real con Gerbonara 1.6.3: 24.508 trazos de imagen conservados y recorte de los extremos físicos del trazo. Resultado: 0 mm² de tinta fuera del contorno y 0 mm² borrados dentro.
- La copia recortada `WAVEDISTEQ_3_testrouted_fab_v003_edit_v002.zip` conserva posición y escala. Cobre, máscaras, contorno, serigrafía superior y los 313 taladros permanecen idénticos al paquete anterior. CRC y SHA-256 comprobados; original intacto.
- Luis confirma que la aplicación funciona correctamente y solicita dejarla en mantenimiento.

Las placas, imágenes y exportaciones reales permanecen en el proyecto local; no son necesarias para ejecutar las pruebas sintéticas del repositorio. Gerbonara se utilizó para la comprobación independiente y no es una dependencia de ejecución de la app. Este cierre valida el editor y su exportación; no sustituye el DRC eléctrico ni la aprobación de fabricación del diseño.

## Cómo retomar un fallo

Registrar qué acción lo provoca, resultado esperado/obtenido y una referencia o captura si existe. Reproducirlo sobre esta versión, corregirlo en un cambio acotado y conservar la estética y el flujo actuales.

Desde la carpeta de la aplicación:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas de interfaz requieren una sesión con Tkinter funcional. Después de modificar código, reiniciar la aplicación desde su acceso habitual. Los avisos CAM del diseño y el encaje mecánico del frontal se revisan por separado cuando se trabaje con una placa concreta.

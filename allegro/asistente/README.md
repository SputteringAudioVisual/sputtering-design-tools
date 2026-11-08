# Asistente externo de PCB · beta 0.2.0

Ventana opcional para guiar el trabajo con Allegro 17.2: colocación → reglas → ruteo → revisión → fabricación. Ejecuta las utilidades SKILL 0.3.0 existentes mediante un complemento independiente y muestra sus resultados. No usa reconocimiento de pantalla ni simula pulsaciones sobre Allegro.

**Las utilidades actuales se conservan.** No se modifica ningún archivo de `pcb_tools`, ningún alias `pcb_*` ni `allegro.ilinit`. Puedes seguir trabajando con los comandos de siempre y cerrar el asistente cuando quieras.

## Instalar y abrir

Requisitos: Windows, Allegro PCB Editor 17.2 y utilidades 0.3.0 instaladas en `C:/SPB_Data/pcbenv/pcb_tools`; Python 3.10 o posterior con Tkinter. La instalación de Luis usa Python 3.12. No hay paquetes de Python adicionales ni servicio de red.

Desde PowerShell, dentro de esta carpeta:

```powershell
./Install-Assistant.ps1
```

El instalador crea `C:/SPB_Data/pcbenv/pcb_assistant` y el acceso directo **PCB - Asistente** en el escritorio. Comprueba que los archivos existentes de las utilidades no han cambiado. Si actualizas el asistente, conserva sus archivos anteriores en su propia carpeta `Backups`. No copia bibliotecas de Cadence ni Python.

Abre el acceso directo y selecciona la placa `.brd` guardada:

- **Abrir Allegro y conectar:** inicia Allegro con la placa y carga la conexión automáticamente. Si Allegro ya está abierto, usa la opción siguiente para evitar abrir dos veces la misma placa.
- **Conectar con Allegro ya abierto:** copia un único comando `skill load(...)` al portapapeles. Pégalo una vez en la consola de Allegro y pulsa Intro. Después, los botones de la aplicación ejecutan las operaciones sin copiar comandos.

La conexión solo se acepta si Allegro tiene abierta exactamente la placa seleccionada. Termina cualquier herramienta activa con Done o Esc antes de pulsar un botón del asistente.

Para explorar la interfaz sin abrir ni modificar ninguna placa:

```powershell
python app.py --demo
```

## Los seis pasos

1. **Abrir y conectar.** Comprueba el nombre de la placa y el estado de conexión. Cargar las utilidades no cambia el diseño.
2. **Colocar componentes.** Inspecciona la placa y revisa footprint, pin 1, polaridades, conectores, desacoplo y caminos de retorno. Marca la colocación como revisada. El asistente no decide por ti si el circuito está bien diseñado.
3. **Preparar reglas.** Introduce los nombres reales de las redes de alimentación, separados por `;`, y los anchos de señal y alimentación. Aplica las reglas y la máscara. Los valores iniciales 0,40/0,80 mm son una propuesta que debes adaptar a corriente, cobre y fabricante; las reglas especiales se conservan. Aplicar reglas no redimensiona pistas existentes. `VEE` no se interpreta como masa; tampoco se unen retornos de entrada y salida de un convertidor aislado.
4. **Rutear.** Usa el router manual o el autorouter de Allegro. Este asistente todavía no controla el autorouter. Comprueba islas de cobre y conexiones pendientes.
5. **Revisar.** Actualiza rellenos y DRC, consulta las auditorías y comprueba las referencias de una copia guardada. Puedes recuperar referencias que falten y guardar el original con copia previa. Las referencias recuperadas se crean en el origen del componente y necesitan revisión de posición.
6. **Exportar fabricación.** Pulsa **Revisar DRC y comprobar copia guardada**. El asistente cuenta automáticamente conexiones sin rutear, pines y componentes sin colocar, DRC, rellenos y máscara. Comprueba las dos confirmaciones visuales (colocación/polaridades y revisión CAM) y crea el ZIP versionado. No edites la placa entre esa comprobación y la exportación; si cambias algo, repite la comprobación final.

La tabla inferior distingue **Correcto**, **Pendiente**, **Revisar**, **Aceptado** y **Omitido**. La salida de SKILL queda plegada en **Ver detalle técnico**. **Abrir carpeta de resultados** muestra el historial de esa placa. Las confirmaciones visuales están juntas en la pantalla de exportación; puedes trabajar directamente en ese paso si tu PCB ya está preparada.

Debajo de la tabla aparece **Último ZIP**, con su ruta completa, **Abrir carpeta exportada** y **Copiar ruta**. Al seleccionar de nuevo una placa, se recupera su última exportación registrada (también las realizadas con la beta anterior). Esta ruta identifica un paquete existente; no implica que se haya actualizado después de editar la placa.

Al sellar una nueva F, el asistente ofrece abrir **ese BRD y ese ZIP exacto** en el Editor PCB y serigrafías. El editor prepara el proyecto del módulo, conserva la procedencia y ofrece abrir el frontal en otra ventana. El ZIP no se elige por el nombre de un paquete antiguo de la carpeta.

### Pasar al editor de serigrafía y al frontal

1. Termina la revisión y crea la liberación desde **Exportar fabricación**.
2. En **Liberación lista**, acepta abrirla en el editor. El asistente entrega las rutas exactas del BRD seleccionado y del ZIP que acaba de sellar; no busca otro paquete por nombre.
3. El editor abre o prepara el módulo autocontenido, carga la fabricación y conserva la identidad, revisión y F de origen. Desde allí puedes aceptar abrir el frontal en otra ventana del mismo proyecto.
4. Si prefieres continuar más tarde, rechaza la apertura: el ZIP queda sellado y accesible en **Último ZIP**. Si falla el arranque del editor, el paquete ya generado se conserva; consulta el mensaje y abre el editor manualmente con esa PCB y ese ZIP.

La apertura directa utiliza el acceso instalado **`Apps de Luis/Editor PCB y serigrafias.lnk`** del escritorio. Ese acceso debe apuntar al editor actual; el asistente lo consulta y no lo modifica. En otro equipo será necesario instalar ese acceso para usar esta integración. El editor sigue siendo una aplicación separada: sus cambios generan una E nueva, sin sobrescribir la F.

## Placa, revisión y liberación de fabricación

Antes de tu primera exportación nueva pulsa **Placa y revisión…**. Declara el nombre y una revisión como `1.0` o la que realmente corresponda; el programa no la deduce del nombre del archivo. Se crea una identidad estable para esa PCB física. Si renombras o recuperas el BRD, elige en ese diálogo la identidad existente para conservarla. El frontal y la PCB de componentes son placas diferentes; no deben compartir identidad solo por pertenecer al mismo módulo.

- Cobre, circuito, taladros, contorno o colocación: incrementa la revisión mayor, por ejemplo `1.0` → `2.0`.
- Solo serigrafía o documentación en Allegro: incrementa la menor, `1.0` → `1.1`.
- Reexportar el mismo diseño conserva su revisión PCB y crea otra liberación: **F001, F002…** Cada una tiene UUID propio, fecha, perfil, herramientas, estado y copia BRD de origen.
- Una edición en el editor Gerber crea una **E001, E002…**, vinculada a la F original y a su padre inmediato. No cambia silenciosamente la revisión PCB de Allegro.

El generador conserva sus nombres `<archivo>_fab_vNNN.zip` por compatibilidad. Ese contador puede diferir de F001… si ya había ZIP antiguos o se renombró el BRD: los identificadores y etiquetas del manifiesto son la referencia común. Un fallo puede dejar un salto F; no se reutiliza una etiqueta reservada.

El asistente configura los films y captura el BRD exacto en el mismo comando que genera los Gerber. Incluye el informe y manifiesto completo antes de **sellar** el ZIP. Desde ese momento no se reanota ni sobrescribe esa liberación; otra exportación produce otro ID. La copia BRD se conserva localmente dentro del proyecto y se referencia por su hash; no se añade al ZIP destinado al fabricante.

**Liberaciones…** muestra el historial de esa identidad. Puedes abrir sus carpetas, comparar los hashes de dos paquetes y recuperar el BRD de origen como otro archivo en la carpeta Allegro. Recuperar no reemplaza la PCB abierta ni sobrescribe archivos existentes. Los ZIP anteriores a este sistema siguen intactos como históricos sin identidad/revisión atribuida.

La cabecera muestra nombre, revisión PCB y F asociada. Indica si el archivo guardado cambió, si hay otra revisión declarada o si el paquete fue alterado. Igualdad del archivo guardado no demuestra que Allegro no tenga ediciones en memoria: repite la revisión final después de editar. El editor Gerber consulta la misma identidad y conserva sus E con su procedencia.

El [contrato común](../../docs/CONTRATO_TRAZABILIDAD_PCB.md), su esquema y ejemplo se publican en `docs/`. En la instalación se incluyen en `documentacion/`. El v1 cubre Allegro → Gerber → edición derivada. Los frontales generados desde cero son otro productor y no reciben una procedencia falsa de Allegro.

## Comprobación automática de conectividad

El asistente lee los atributos nativos `net->unconnected` y `net->unplaced` documentados por Cadence para Allegro 17.2. Suma las conexiones pendientes por red, muestra qué redes tienen pendientes y comprueba por separado los pines sin colocar, porque el primer contador no los incluye. No cuenta líneas visibles ni usa `NET_RATT_COUNT` de extracta. La exportación vuelve a consultar estos datos después de actualizar rellenos y DRC.

Con cero conexiones pendientes aparece **Correcto**; no hay casilla manual para confirmar ese número. Si hay pendientes conocidas que quieres conservar, puedes aceptar ese aviso con un motivo, y el ZIP conserva el número real: nunca se convierte en cero por aceptar el aviso. Un dato que Allegro no haya podido proporcionar se presenta como sin comprobar.

## Serigrafía opcional y avisos aceptados

No necesitas crear una referencia de serigrafía para todos los conectores. En **Revisar** o **Exportar fabricación**:

- Para omisiones concretas, escribe sus nombres en **Sin referencia a propósito**, por ejemplo `J1; J2`, y pulsa **Guardar opciones de serigrafía**. Se conserva la comprobación para los demás componentes.
- Si no quieres comprobar los textos de esa placa, desmarca **Revisar referencias de serigrafía (opcional)**. Esto no crea, borra, mueve ni cambia textos.
- Para aceptar otro aviso conocido (por ejemplo un DRC revisado, una abertura de máscara intencionada o referencias duplicadas), selecciónalo en la tabla y pulsa **Aceptar aviso seleccionado…**. Escribe un motivo. Puedes retirar la aceptación antes de exportar.

Las opciones de serigrafía se guardan por placa en `Asistente/<placa>/opciones_exportacion.json`. Las aceptaciones de avisos se aplican a la comprobación actual, con los datos concretos mostrados; una nueva revisión o un cambio realizado por el asistente las invalida. Si Allegro encuentra una cantidad distinta durante la exportación, solicita revisar de nuevo. Las ediciones directas de Allegro siguen requiriendo repetir la revisión final, aunque conserven los mismos contadores.

Con exclusiones activas o la comprobación de textos desactivada, el asistente no ejecuta la recuperación general, porque volvería a crear también las referencias que has decidido omitir. Puedes recuperar referencias concretas manualmente en Allegro.

La aplicación guarda las decisiones y sus motivos en el historial y en **`informes/ASISTENTE_REVISION.json` dentro del ZIP**, con su hash en el manifiesto. Un paquete con omisiones o avisos aceptados figura como `EXPORTADO_CON_EXCEPCIONES_USUARIO`; los avisos originales de los generadores se conservan por separado. Los Gerber y taladros no se alteran al incorporar este informe.

Las operaciones que no han podido terminar (otra placa abierta, conexión perdida, copia incoherente, rellenos que no se han podido actualizar o generación de archivos fallida) necesitan completarse para producir el paquete. No se presentan como avisos ya comprobados que puedan aceptarse.

Después de actualizar desde 0.1.0, cierra y vuelve a abrir **solo el asistente**. Allegro puede seguir abierto con tu trabajo: usa **Conectar con Allegro ya abierto** y pega una vez el nuevo comando de conexión.

## Archivos dentro del proyecto

El asistente conserva el historial completo de resultados en `Asistente/<nombre de placa>/historial.jsonl` y el perfil de anchos aplicado en `perfil.json`. Las copias se guardan en `Copias_seguridad`, los informes de máscara junto al `.brd` y el paquete Gerber + NC Drill + rutas de slots, cuando corresponde, en `Fabricacion`, igual que con las utilidades existentes. No se guarda automáticamente encima del `.brd`: usa el botón de guardar o File > Save.

La identidad y liberaciones están en `Sputtering/pcb/<project_id>/` dentro de la raíz común con Capture/Allegro. El vínculo de cada archivo está en `Asistente/<nombre>/identidad_pcb.json`. Los registros usan rutas relativas: al mover el proyecto se conservan las asociaciones, fuentes e historial. Las copias de origen exactas de cada F están en `releases/<release_id>/source.brd` y los índices guardan los hashes del ZIP y manifiesto finales.

Las carpetas `sessions` y `scratch` de la aplicación son intercambio y trabajo temporal de la conexión; no son bibliotecas necesarias para reabrir la PCB. Las salidas permanentes y las copias de la placa quedan dentro del proyecto. No subas esas carpetas temporales a GitHub.

## Límites de esta beta

- **Cero DRC y cero conexiones pendientes son comprobaciones distintas.** Ambas se leen automáticamente. El número de conexiones pendientes no certifica que las conexiones del esquema sean las deseadas ni que el diseño eléctrico sea correcto.
- El asistente no analiza corrientes, estabilidad de una PSU, compatibilidad de footprints ni distancias de aislamiento. Ofrece recomendaciones y ejecuta comprobaciones concretas.
- La limpieza destructiva de textos (`pcb_textos` / `pcbSilkAplicar`) no se ofrece como botón: se detectó una pérdida de referencias después de guardar. La auditoría y la recuperación de referencias permanecen disponibles y son voluntarias. La verificación externa usa `extracta` sobre una copia; las ausencias intencionadas se pueden excluir o aceptar.
- Los resultados conocidos de componentes sin colocar, textos, DRC y máscara pueden aceptarse individualmente con un motivo. Las comprobaciones incompletas y los fallos de ejecución no se confunden con esos resultados.
- Las ediciones hechas directamente en Allegro no se detectan continuamente. Los resultados corresponden al momento indicado por la operación. Repite la revisión final después de editar; no se certifica automáticamente que el estado siga intacto entre dos clics.
- Una exportación con avisos necesita revisar sus logs y el visor CAM. Crear el ZIP no equivale a aprobarlo para fabricación.
- La ruta de instalación del complemento debe ser ASCII. Los proyectos pueden tener espacios y caracteres españoles de Windows-1252, incluida `ñ`. Otros caracteres, por ejemplo emoji en la ruta, no están admitidos por este puente de Allegro 17.2.
- La versión del núcleo admitida en esta beta es 0.3.0. No se descarga ni se sustituye automáticamente.

## Si Allegro no responde

El asistente mantiene una sola operación pendiente y **no la reenvía automáticamente**. Revisa si Allegro espera Done/Esc o tiene un diálogo abierto. No vuelvas a aplicar cambios suponiendo que el primer intento falló. Cerrar el asistente no cancela una operación ya enviada. Una vez revisada o terminada la operación en Allegro, puedes cerrar la ventana y crear una nueva conexión.

Para desconectar el complemento sin cerrar Allegro, cuando no haya ninguna operación pendiente:

```lisp
skill pcbwaStop()
```

Allegro conserva sus comandos habituales. Para retirar el asistente, ciérralo, desconecta o cierra Allegro y elimina únicamente el acceso directo y `C:/SPB_Data/pcbenv/pcb_assistant`. No borres `pcb_tools` ni las carpetas del proyecto.

## Desarrollo y pruebas

```powershell
python -m unittest discover -s tests -v
```

`workflow.py` contiene las condiciones de avance/exportación, `transport.py` el intercambio de mensajes, `saved_board.py` la lectura independiente de referencias guardadas, `app.py` la ventana y `bridge/pcb_assistant_bridge.il` el complemento de Allegro. Las solicitudes contienen datos y una acción de una lista cerrada; no se evalúa código recibido. El temporizador solo publica el estado de conexión y solicita un comando; las operaciones de base de datos se ejecutan fuera de él.

`editor_handoff.py` resuelve el acceso de escritorio y construye la apertura con `--board` y `--fabrication`. Sus pruebas comprueban que se transmiten ambos archivos exactos, que se usa el directorio del acceso sin reescribirlo y que un ZIP ausente impide lanzar el proceso. El instalador comprueba Tcl/Tk con una expresión sin comillas internas en el argumento de Python, evitando el fallo de interpretación de PowerShell; el mensaje de éxito se escribe desde PowerShell.

Consulta [VALIDACION.md](VALIDACION.md) para saber qué está probado y qué sigue pendiente. Esta beta añade una capa opcional; no reemplaza la versión estable de las utilidades.

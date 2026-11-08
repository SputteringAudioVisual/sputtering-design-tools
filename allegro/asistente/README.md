# Asistente externo de PCB · beta 0.1.0

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
6. **Exportar fabricación.** Pulsa **Revisar DRC y comprobar copia guardada**. Confirma en Allegro que quedan cero conexiones sin rutear y que revisarás los archivos en CAM. Luego crea el ZIP versionado. No edites la placa entre esa comprobación y la exportación; si cambias algo, repite la comprobación final.

En el registro inferior aparecen la salida de SKILL y las recomendaciones. **Abrir carpeta de resultados** muestra el historial de esa placa.

## Archivos dentro del proyecto

El asistente conserva el historial completo de resultados en `Asistente/<nombre de placa>/historial.jsonl` y el perfil de anchos aplicado en `perfil.json`. Las copias se guardan en `Copias_seguridad`, los informes de máscara junto al `.brd` y el paquete Gerber + NC Drill + rutas de slots, cuando corresponde, en `Fabricacion`, igual que con las utilidades existentes. No se guarda automáticamente encima del `.brd`: usa el botón de guardar o File > Save.

Las carpetas `sessions` y `scratch` de la aplicación son intercambio y trabajo temporal de la conexión; no son bibliotecas necesarias para reabrir la PCB. Las salidas permanentes y las copias de la placa quedan dentro del proyecto. No subas esas carpetas temporales a GitHub.

## Límites de esta beta

- **Cero DRC no demuestra continuidad eléctrica.** La confirmación de cero conexiones sin rutear es manual. No se usa `NET_RATT_COUNT` como prueba: devolvió cero en una placa sin rutear durante las pruebas.
- El asistente no analiza corrientes, estabilidad de una PSU, compatibilidad de footprints ni distancias de aislamiento. Ofrece recomendaciones y ejecuta comprobaciones concretas.
- La limpieza destructiva de textos (`pcb_textos` / `pcbSilkAplicar`) no se ofrece como botón: se detectó una pérdida de referencias después de guardar. La auditoría y la recuperación de referencias permanecen disponibles. La verificación externa usa `extracta` sobre una copia y bloquea la exportación si falta una referencia de silkscreen o hay duplicados.
- Se bloquea la exportación cuando falta una comprobación, hay componentes sin colocar, referencias ausentes, DRC, rellenos pendientes o máscara que requiere revisión. Las geometrías adicionales de máscara requieren revisión fuera de esta beta.
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

Consulta [VALIDACION.md](VALIDACION.md) para saber qué está probado y qué sigue pendiente. Esta beta añade una capa opcional; no reemplaza la versión estable de las utilidades.

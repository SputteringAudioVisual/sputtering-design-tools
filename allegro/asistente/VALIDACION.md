# Validación de la beta 0.1.1

Entorno: Windows, Python 3.12, Allegro PCB Designer 17.2 P028, utilidades 0.3.0. Pruebas sobre copias de placas; no se modifica la PSU original.

## Comprobado

- 17 pruebas automáticas: bloqueo con datos desconocidos o comprobaciones pendientes, aceptación de resultados conocidos con motivo, invalidación y cambio de cantidades; exclusiones específicas de referencias y desactivación opcional de su revisión; conservación de los demás controles; rechazo de otra placa/sesión; respuesta incompleta; una única operación pendiente; rutas con `ñ`; anchos no finitos; acciones no permitidas; referencias guardadas ausentes o duplicadas; informe de decisiones en ZIP con CRC, manifiesto y hashes coherentes.
- Carga del complemento en Allegro real y recepción estructurada de auditoría: 15 componentes, 45 pines, 8 redes, cero vías y cuatro referencias ausentes en la copia de PSU.
- Ejecución del mismo despachador de comandos para anchos, máscara, recuperación de referencias, revisión DRC y copia guardada.
- Recuperación de cuatro referencias: `extracta` lee 15 componentes con 15 referencias de silkscreen persistidas después de guardar la copia; no faltan ni sobran referencias.
- Se rechaza exportar sin comprobación previa y actuar sobre otra placa. Una solicitud repetida con el mismo identificador no vuelve a ejecutarse.
- Conexión automática en Allegro con interfaz real: el temporizador renueva la conexión y atiende las solicitudes de inspección, revisión y copia guardada sin intervención en la consola.
- Flujo de los controles de la ventana, ejecutado mediante el bucle de eventos de Tk: revisión → copia → comprobación con `extracta` → confirmaciones → exportación. Antes de las confirmaciones se mantiene el bloqueo. El ZIP de prueba contiene siete `.art`, NC Drill y CRC válidos. Se trata de una copia de prueba cuya conectividad no se ha aprobado para fabricar; no es una PCB terminada.
- Los seis pasos se construyen y cambian correctamente en la prueba de interfaz. Esto no sustituye la comprobación visual con la escala del monitor del usuario.
- Versión 0.1.1: prueba sobre una copia de la PSU guardada con cuatro referencias de conectores ausentes. Exportación completa primero excluyéndolas y después aceptando el aviso con un motivo; no se ejecuta recuperación ni edición de textos. Los dos ZIP incluyen el informe de decisiones y el manifiesto identifica las excepciones. Se comprueban CRC y hashes; el archivo original conserva su hash durante la prueba. El caso de cinco referencias ausentes recibido en la consola se cubre además en las pruebas de condiciones de exportación.

## Pendiente de cerrar antes de considerarlo estable

- Verificación visual de todos los pasos con la escala de la pantalla del usuario. La herramienta de captura de ventanas devolvió `window capture timed out: timed out waiting on channel`.
- Detección automática fiable de conexiones sin rutear y de cambios hechos fuera del asistente. Por ahora requiere comprobación manual y repetir la revisión final.

No se ha corregido ni modificado el núcleo 0.3.0 en este trabajo. El asistente evita automatizar la limpieza destructiva de textos por el fallo de persistencia ya detectado.

Las pruebas de integración son optativas: `tests/native_smoke.py --source <placa> --scratch <carpeta ASCII nueva>` crea una copia, inicia una sesión propia de Allegro, ejecuta las auditorías y termina únicamente el proceso de prueba creado. `--exercise-ui` añade los controles de Tk y un ZIP de prueba marcado como no apto para fabricar. Nunca uses una PCB que otra sesión esté editando como origen de esa prueba. Los proyectos de prueba y sus logs no se distribuyen con el código.

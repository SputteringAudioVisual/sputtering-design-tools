; Resolve project files from the SAVED BOARD, never from Allegro's launch cwd.
unless(boundp('pcbReviewPendingFiles) pcbReviewPendingFiles=nil)
procedure(pcbProyectoArchivo()
  prog((archivo)
    unless(axlDBGetDesign() error("PCB: no hay una placa abierta."))
    ; axlCurrentDesign() returns only the title/basename in Allegro 17.2.
    ; axlGetDrawingName() is the documented absolute on-disk drawing path.
    archivo=axlGetDrawingName()
    unless(archivo error("PCB: guarda la placa antes de usar las utilidades."))
    unless(rexMatchp("\\.[bB][rR][dD]$" archivo) archivo=strcat(archivo ".brd"))
    unless(rexMatchp("^[A-Za-z]:/" archivo) || rexMatchp("^/" archivo)
      archivo=strcat(getWorkingDir() "/" archivo))
    unless(isFile(archivo)
      error("PCB: no se encuentra la placa guardada: %s. Guarda primero el proyecto." archivo))
    return(archivo)
  )
)

procedure(pcbProyectoDirectorio()
  buildString(reverse(cdr(reverse(parseString(pcbProyectoArchivo() "/\\")))) "/")
)

procedure(pcbProyectoNombre()
  let((archivo)
    archivo=car(last(parseString(pcbProyectoArchivo() "/\\")))
    substring(archivo 1 strlen(archivo)-4)
  )
)

; Snapshot of current memory. Never redirects the active drawing to a backup.
procedure(pcbProyectoBackup(etiqueta)
  prog((archivo carpeta n anterior resultado original)
    original=pcbProyectoArchivo()
    unless(rexMatchp("^[A-Za-z0-9_]+$" etiqueta) error("PCB: etiqueta de backup no valida."))
    carpeta=pcbProyectoRutaSalida("Copias_seguridad")
    unless(isDir(carpeta) || createDirHier(carpeta) error("PCB: no se pudo crear la carpeta de backups."))
    n=1
    archivo=sprintf(nil "%s/%s_antes_%s_v%03d.brd" carpeta pcbProyectoNombre() etiqueta n)
    while(isFile(archivo)
      n=n+1
      archivo=sprintf(nil "%s/%s_antes_%s_v%03d.brd" carpeta pcbProyectoNombre() etiqueta n))
    anterior=getWorkingDir()
    resultado=errset(axlSaveDesign(?design archivo ?noMru t ?noConfirm t ?writeModel t) t)
    changeWorkingDir(anterior)
    unless(resultado && car(resultado) && equal(original pcbProyectoArchivo())
      error("PCB: no se pudo crear el backup sin cambiar la placa activa."))
    printf("PCB: backup %s\n" archivo)
    return(archivo)
  )
)

; Workers return a nonnegative count, or raise an error to roll back everything.
procedure(pcbProyectoAplicar(etiqueta worker)
  prog((backup tx resultado)
    backup=pcbProyectoBackup(etiqueta)
    tx=axlDBTransactionStart()
    unless(tx error("PCB: no se pudo iniciar la transaccion."))
    resultado=errset(apply(worker nil) t)
    if(resultado && numberp(car(resultado)) && car(resultado)>=0 then
      axlDBTransactionCommit(tx)
      printf("PCB: %s terminado; cambios en memoria. Revisa y guarda la placa.\n" etiqueta)
      return(car(resultado))
    else
      axlDBTransactionRollback(tx)
      printf("PCB: %s cancelado y revertido. Backup: %s\n" etiqueta backup)
      return(nil))
  )
)

procedure(pcbRevisionPendiente(@optional marcar)
  let((archivo)
    unless(boundp('pcbReviewPendingFiles) pcbReviewPendingFiles=nil)
    archivo=pcbProyectoArchivo()
    when(marcar
      unless(member(archivo pcbReviewPendingFiles)
        pcbReviewPendingFiles=cons(archivo pcbReviewPendingFiles)))
    member(archivo pcbReviewPendingFiles)
  )
)

procedure(pcbRevisionWorker()
  prog((shapes drc)
    shapes=axlShapeDynamicUpdate(nil t)
    unless(numberp(shapes) && shapes==0 && axlDBDynamicShapes(nil)==0
      error("PCB: no se pudieron actualizar todos los rellenos."))
    drc=axlDRCUpdate(t)
    unless(numberp(drc) error("PCB: fallo al actualizar los DRC."))
    printf("PCB: rellenos actualizados; DRC encontrados: %d. Revisa tambien conexiones y CAM.\n" drc)
    return(drc)
  )
)

procedure(pcbRevisionActualizar()
  let((resultado)
    resultado=pcbProyectoAplicar("revision" 'pcbRevisionWorker)
    when(numberp(resultado)
      pcbReviewPendingFiles=remove(pcbProyectoArchivo() pcbReviewPendingFiles))
    resultado
  )
)

procedure(pcbProyectoRutaSalida(subcarpeta)
  ; Output settings are relative subdirectories INSIDE the project.
  ; Reject absolute paths, parent traversal and Windows path metacharacters.
  prog((partes)
    unless(stringp(subcarpeta) && strlen(subcarpeta)>0
      error("PCB: la carpeta de salida debe ser relativa al proyecto."))
    when(rexMatchp("^[\\\\/]" subcarpeta) || rexMatchp("[:\"*?<>|]" subcarpeta)
      error("PCB: la salida debe quedar dentro del proyecto; no se permiten rutas absolutas."))
    partes=parseString(subcarpeta "/\\")
    when(member(".." partes) || member("." partes)
      error("PCB: no se permiten componentes . o .. en la salida."))
    return(strcat(pcbProyectoDirectorio() "/" buildString(partes "/")))
  )
)

procedure(pcbProyectoGuardarConfiguracion(carpeta)
  prog((f valor)
    f=outfile(strcat(carpeta "/config_utilidades.il") "w")
    unless(f error("PCB: no se pudo guardar la configuracion del paquete."))
    fprintf(f "; Configuration snapshot for this fabrication package. Dimensions in mm.\n")
    foreach(variable '(pcbTextHeightMM pcbTextWidthMM pcbTextStrokeMM
      pcbTextCharSpaceMM pcbTextLineSpaceMM pcbTextRemoveValues pcbMaskMarginMM
      pcbSignalWidthMM pcbPowerWidthMM pcbSignalViaPadMM pcbSignalViaDrillMM
      pcbPowerViaPadMM pcbPowerViaDrillMM pcbPowerNets pcbPreserveCustomRules
      pcbFabOutputSubdir pcbFabOutlineLayer)
      valor=eval(variable)
      if(listp(valor) && valor then fprintf(f "%L = '%L\n" variable valor)
        else fprintf(f "%L = %L\n" variable valor)))
    close(f)
    return(t)
  )
)

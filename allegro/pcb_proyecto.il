; Resolve project files from the SAVED BOARD, never from Allegro's launch cwd.
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

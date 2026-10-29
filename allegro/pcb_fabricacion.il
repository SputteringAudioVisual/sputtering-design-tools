; pcb_fabricacion.il
; Configuracion y exportacion de Gerber + NC Drill para Allegro 17.2.
;
; Salida:
;   Gerber RS-274X, metric, formato 5.5
;   NC Drill Enhanced Excellon, metric, absoluto, formato 5.5
;   Una carpeta nueva por ejecucion; nunca sobreescribe una anterior.
;
; Comandos:
;   pcb_fab_auditar    - comprueba capas y configuracion sin modificar
;   pcb_fab_configurar - crea/reemplaza los siete films; no exporta
;   pcb_fab_exportar   - configura y genera Gerber + NC Drill

; Output root is configurable in pcb_config.il.

procedure(pcbFabCapas()
  list(
    list("COPPER_BOTTOM" list("ETCH/BOTTOM" "PIN/BOTTOM" "VIA CLASS/BOTTOM"))
    list("COPPER_TOP"    list("ETCH/TOP" "PIN/TOP" "VIA CLASS/TOP"))
    list("MASK_BOTTOM"   list("PACKAGE GEOMETRY/SOLDERMASK_BOTTOM"
                               "PIN/SOLDERMASK_BOTTOM"
                               "VIA CLASS/SOLDERMASK_BOTTOM"))
    list("MASK_TOP"      list("PACKAGE GEOMETRY/SOLDERMASK_TOP"
                               "PIN/SOLDERMASK_TOP"
                               "VIA CLASS/SOLDERMASK_TOP"))
    list("OUTLINE"       list(pcbFabOutlineLayer))
    list("SILK_BOTTOM"   list("PACKAGE GEOMETRY/SILKSCREEN_BOTTOM"
                               "REF DES/SILKSCREEN_BOTTOM"))
    list("SILK_TOP"      list("PACKAGE GEOMETRY/SILKSCREEN_TOP"
                               "REF DES/SILKSCREEN_TOP"))
  )
)

; Count actual pin/via holes. DB spells the enum OVAL_SLOT as "OVAL SLOT".
procedure(pcbFabRanuras()
  let((plated nonPlated especiales ps tipo)
    plated=0 nonPlated=0 especiales=0
    foreach(item pcbMaskItems()
      ps=car(item)->definition
      tipo=if(stringp(ps->holeType) then buildString(parseString(upperCase(ps->holeType) " _") "_") else "")
      when(equal(tipo "OVAL_SLOT")
        if(equal(ps->plating "PLATED") then plated=plated+1 else nonPlated=nonPlated+1))
      when(ps->isThrough && !member(tipo '("CIRCLE_DRILL" "OVAL_SLOT"))
        especiales=especiales+1))
    list(plated nonPlated especiales)
  )
)

procedure(pcbFabNuevaCarpeta()
  let((base carpeta indice raiz partes nombre directorio char)
    nombre = pcbProyectoNombre()
    base = ""
    for(i 1 strlen(nombre)
      char=substring(nombre i 1)
      base=strcat(base if(rexMatchp("^[A-Za-z0-9_-]$" char) then char else "_")))
    unless(strlen(base)>0 base="PCB")
    raiz = pcbProyectoRutaSalida(pcbFabOutputSubdir)
    createDirHier(raiz)
    indice = 1
    carpeta = sprintf(nil "%s/%s_fab_v%03d" raiz base indice)
    while(isDir(carpeta) || isFile(strcat(carpeta ".zip"))
      indice = indice + 1
      carpeta = sprintf(nil "%s/%s_fab_v%03d" raiz base indice)
    )
    if(createDirHier(carpeta) then carpeta else nil)
  )
)

procedure(pcbFabEscribirArtParam(carpeta)
  let((puerto archivo)
    archivo = sprintf(nil "%s/art_param.txt" carpeta)
    puerto = outfile(archivo "w")
    if(puerto == nil then
      nil
    else
      fprintf(puerto "DEVICE-TYPE           GERBER_RS274X\n")
      fprintf(puerto "OUTPUT-UNITS          MM\n")
      fprintf(puerto "FILM-SIZE             2400000 1600000\n")
      fprintf(puerto "FORMAT                5.5\n")
      fprintf(puerto "ABORT-ON-ERROR        YES\n")
      fprintf(puerto "SCALE                 1\n")
      fprintf(puerto "SUPPRESS-LEAD-ZEROES  YES\n")
      fprintf(puerto "SUPPRESS-TRAIL-ZEROES NO\n")
      fprintf(puerto "SUPPRESS-EQUAL        YES\n")
      fprintf(puerto "UNDEF-APT-CONT        NO\n")
      close(puerto)
      t
    )
  )
)

procedure(pcbFabEscribirNcParam(carpeta)
  let((puerto archivo)
    archivo = sprintf(nil "%s/nc_param.txt" carpeta)
    puerto = outfile(archivo "w")
    if(puerto == nil then
      nil
    else
      fprintf(puerto "INTEGER-PLACES         5\n")
      fprintf(puerto "DECIMAL-PLACES         5\n")
      fprintf(puerto "X-OFFSET               0.000000\n")
      fprintf(puerto "Y-OFFSET               0.000000\n")
      fprintf(puerto "FEEDRATE               1\n")
      fprintf(puerto "COORDINATES            ABSOLUTE\n")
      fprintf(puerto "OUTPUT-UNITS           METRIC\n")
      fprintf(puerto "TOOL-ORDER             INCREASING\n")
      fprintf(puerto "REPEAT-CODES           NO\n")
      fprintf(puerto "SUPPRESS-LEAD-ZEROES   YES\n")
      fprintf(puerto "SUPPRESS-TRAIL-ZEROES  NO\n")
      fprintf(puerto "SUPPRESS-EQUAL         NO\n")
      fprintf(puerto "TOOL-SELECT            YES\n")
      fprintf(puerto "OPTIMIZE_DRILLING      YES\n")
      fprintf(puerto "ENHANCED_EXCELLON      YES\n")
      fprintf(puerto "HEADER                 none\n")
      fprintf(puerto "LEADER                 12\n")
      fprintf(puerto "CODE                   ASCII\n")
      fprintf(puerto "SEPARATE               NO\n")
      fprintf(puerto "SEPARATE-ROUTING       YES\n")
      fprintf(puerto "DRILLING               LAYER-PAIR\n")
      fprintf(puerto "BACKDRILL              NO\n")
      fprintf(puerto "CAVITY                 NO\n")
      fprintf(puerto "COUNTER                NO\n")
      fprintf(puerto "TOLERANCE_DRILL        NO\n")
      fprintf(puerto "TOLERANCE_TRAVEL       NO\n")
      fprintf(puerto "TOOL_SIZE              NO\n")
      fprintf(puerto "ROTATION               NO\n")
      fprintf(puerto "NON_STANDARD           NO\n")
      fprintf(puerto "TOTAL_DRILL            NO\n")
      fprintf(puerto "SEPARATE_SLOT          NO\n")
      fprintf(puerto "SUPPRESS_TOLERANCE     NO\n")
      fprintf(puerto "SUPPRESS_TOOLSIZE      NO\n")
      fprintf(puerto "SUPPRESS_ROTATION      NO\n")
      close(puerto)
      t
    )
  )
)

procedure(pcbFabAuditar()
  prog((diseno films film capa faltan existentes actuales extras ranuras)
    diseno = axlDBGetDesign()
    if(diseno == nil then
      printf("\nPCB FAB: No hay ningun diseno abierto.\n")
      nil
    else
      faltan = nil
      existentes = 0
      films = pcbFabCapas()
      unless(equal(axlConductorTopLayer() "TOP") && equal(axlConductorBottomLayer() "BOTTOM") &&
        length(axlSubclassRoute()) == 2
        printf("PCB FAB: exportacion disponible solo para placas de dos capas TOP/BOTTOM.\n")
        return(nil))
      foreach(entrada axlGetXSection()
        when(nth(7 entrada)
          printf("PCB FAB: no se exportan planos negativos automaticamente.\n") return(nil)))
      foreach(film films
        foreach(capa cadr(film)
          if(axlIsLayer(capa) then
            existentes = existentes + 1
          else
            faltan = cons(capa faltan)
          )
        )
      )
      printf("\nPCB FAB: auditoria; no se ha modificado el diseno.\n")
      printf("PCB FAB: films previstos: %d\n" length(films))
      actuales=axlGetParam("artwork")->groupMembers
      extras=setof(nombre actuales !member(nombre foreach(mapcar entrada films car(entrada))))
      printf("PCB FAB: films actuales: %d; adicionales a retirar al configurar: %L\n" length(actuales) extras)
      printf("PCB FAB: rellenos fuera de fecha: %d; DRC registrados (pueden estar desactualizados): %d.\n"
        axlDBDynamicShapes(nil) axlDRCGetCount())
      printf("PCB FAB: capas encontradas: %d\n" existentes)
      if(faltan then
        printf("PCB FAB: AVISO - capas ausentes: %L\n" reverse(faltan))
      else
        printf("PCB FAB: todas las capas necesarias existen.\n")
      )
      printf("PCB FAB: Gerber RS-274X metric 5.5.\n")
      printf("PCB FAB: NC Enhanced Excellon metric absolute 5.5.\n")
      printf("PCB FAB: PTH y NPTH se generan en un unico archivo.\n")
      ranuras=pcbFabRanuras()
      printf("PCB FAB: slots ovales: %d metalizados; %d no metalizados; %d taladros especiales no admitidos.\n"
        car(ranuras) cadr(ranuras) nth(2 ranuras))
      return(!faltan && nth(2 ranuras)==0)
    )
  )
)

procedure(pcbFabFilmsCorrectos()
  let((nombres films correcto param)
    films=pcbFabCapas()
    nombres=axlGetParam("artwork")->groupMembers
    correcto=length(nombres)==length(films)
    foreach(film films
      param=axlGetParam(strcat("artwork:" car(film)))
      unless(member(car(film) nombres) && param &&
        length(param->groupMembers)==length(cadr(film)) &&
        !setof(capa cadr(film) !member(capa param->groupMembers)) &&
        !param->negative && !param->mirrored && param->rotation==0 &&
        equal(param->offset 0:0) && !param->drawHolesOnly && !param->suppressShapeFill
        correcto=nil))
    correcto
  )
)

procedure(pcbFabConfigurarWorker()
  let((films ancho nombres)
    films=pcbFabCapas()
    nombres=foreach(mapcar film films car(film))
    foreach(nombre axlGetParam("artwork")->groupMembers
      unless(member(nombre nombres)
        unless(axlDeleteObject(axlGetParam(strcat("artwork:" nombre)))
          error("PCB FAB: no se pudo retirar el film %s." nombre))
        printf("PCB FAB: film antiguo retirado: %s.\n" nombre)))
    ancho=axlMKSConvert(0.10 "millimeters" car(axlDBGetDesignUnits()))
    foreach(film films
      unless(axlFilmCreate(car(film)
        ?negative nil ?undefineLineWidth ancho ?rotation 0 ?xOffset 0.0 ?yOffset 0.0
        ?mirrored nil ?fullContact nil ?suppressUnconnectPads nil
        ?drawMissingPadApertures t ?useApertureRotation t ?suppressShapeFill nil
        ?vectorBasedPad nil ?drawHolesOnly nil ?layers cadr(film)
        ?domains list("artwork" "visibility"))
        error("PCB FAB: fallo creando film %s." car(film))))
    unless(pcbFabFilmsCorrectos() error("PCB FAB: el conjunto final no coincide con los siete films previstos."))
    printf("PCB FAB: exactamente siete films verificados; cambios en memoria.\n")
    7
  )
)

procedure(pcbFabConfigurar()
  prog(()
    unless(pcbFabAuditar() return(nil))
    when(pcbFabFilmsCorrectos()
      printf("PCB FAB: los siete films ya coinciden; no se cambia nada.\n")
      return(t))
    return(numberp(pcbProyectoAplicar("films" 'pcbFabConfigurarWorker)))
  )
)

procedure(pcbFabExportarWorker()
  let((formatoArt resultadoArt resultadoNc resultadoRoute ranuras)
    formatoArt = "artwork -f COPPER_BOTTOM -f COPPER_TOP -f MASK_BOTTOM -f MASK_TOP -f OUTLINE -f SILK_BOTTOM -f SILK_TOP %s"
    resultadoArt = axlRunBatchDBProgram("artwork" formatoArt
      ?logfile "photoplot" ?startMsg "PCB Gerber RS-274X" ?warnProgram t)
    resultadoNc = axlRunBatchDBProgram("nctape" "nctape -o -n PCB_DRILL.drl %s"
      ?logfile "ncdrill" ?startMsg "PCB NC Drill" ?warnProgram t)
    ranuras=pcbFabRanuras()
    resultadoRoute=t
    when(car(ranuras)+cadr(ranuras)>0
      resultadoRoute=axlRunBatchDBProgram("ncroute" "ncroute -o PCB_SLOTS.rou %s"
        ?logfile "ncroute" ?startMsg "PCB NC Route slots" ?warnProgram t))
    list(resultadoArt resultadoNc resultadoRoute)
  )
)

procedure(pcbFabComprimir(carpeta estados)
  prog((f helper comando previo resultado ejecutable ranuras)
    helper=strcat(pcbToolsRoot "/pcb_empaquetar.ps1")
    unless(isFile(helper) error("PCB: falta el empaquetador %s." helper))
    when(rexMatchp("[\"%]" helper) error("PCB: ruta del empaquetador no compatible."))
    f=outfile(strcat(carpeta "/pcb_export_info.txt") "w")
    unless(f error("No se pudo escribir la informacion del paquete."))
    fprintf(f "tools_version=%s\n" pcbToolsVersion)
    fprintf(f "artwork_status=%d\n" if(car(estados)==t then 0 else car(estados)))
    fprintf(f "ncdrill_status=%d\n" if(cadr(estados)==t then 0 else cadr(estados)))
    fprintf(f "ncroute_status=%d\n" if(nth(2 estados)==t then 0 else nth(2 estados)))
    ranuras=pcbFabRanuras()
    fprintf(f "expected_plated_slots=%d\nexpected_nonplated_slots=%d\n" car(ranuras) cadr(ranuras))
    close(f)
    ejecutable=strcat(getShellEnvVar("SystemRoot") "/System32/WindowsPowerShell/v1.0/powershell.exe")
    ; system waits for this non-Cadence process and preserves its exit code.
    ; The outer quotes implement Windows cmd.exe /c quoting for an exe path.
    comando=sprintf(nil "\"\"%s\" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File \"%s\" -Directory \"%s\" > \"%s/pcb_zip.log\" 2>&1\"" ejecutable helper carpeta carpeta)
    previo=getWorkingDir()
    resultado=errset(progn(
      changeWorkingDir(carpeta)
      system(comando)) t)
    changeWorkingDir(previo)
    unless(resultado && car(resultado)==0 && isFile(strcat(carpeta ".zip"))
      printf("PCB FAB: resultado del empaquetador %L\n" resultado)
      printf("PCB FAB: no se pudo crear el ZIP. Los archivos siguen en %s\n" carpeta)
      return(nil))
    return(strcat(carpeta ".zip"))
  )
)

procedure(pcbFabExportar()
  prog((carpeta anterior ncdAnterior resultado estados zip)
    pcbFabLastResult = nil
    pcbFabLastZip = nil
    ; Resolve and validate the saved project before changing films or writing.
    pcbProyectoRutaSalida(pcbFabOutputSubdir)
    when(axlDBDynamicShapes(nil)>0 || pcbRevisionPendiente()
      printf("PCB FAB: exportacion detenida: recalcula y revisa rellenos/DRC con pcb_revision_actualizar.\n")
      return(nil))
    unless(pcbFabConfigurar() return(nil))
    carpeta = pcbFabNuevaCarpeta()
    unless(carpeta error("No se pudo crear la carpeta de salida."))
    unless(pcbFabEscribirArtParam(carpeta) && pcbFabEscribirNcParam(carpeta)
      error("No se pudieron escribir los parametros de fabricacion."))
    pcbProyectoGuardarConfiguracion(carpeta)
    anterior = getWorkingDir()
    ncdAnterior = getShellEnvVar("NCDPATH")
    resultado = errset(progn(
      changeWorkingDir(carpeta)
      setShellEnvVar("NCDPATH" carpeta)
      pcbFabExportarWorker()) t)
    ; Restore environment even when the exporter raises an error.
    changeWorkingDir(anterior)
    if(ncdAnterior then setShellEnvVar("NCDPATH" ncdAnterior) else unsetShellEnvVar("NCDPATH"))
    printf("PCB FAB: salida %s\n" carpeta)
    unless(resultado printf("PCB FAB: ERROR de exportacion; revisa los logs.\n") return(nil))
    estados = car(resultado)
    pcbFabLastResult = list(carpeta car(estados) cadr(estados) nth(2 estados))
    unless(member(car(estados) '(t 1)) && member(cadr(estados) '(t 1)) && member(nth(2 estados) '(t 1))
      printf("PCB FAB: ERROR Gerber %L; taladro %L; slots %L. No se crea ZIP.\n" car(estados) cadr(estados) nth(2 estados))
      return(nil))
    zip=pcbFabComprimir(carpeta estados)
    unless(zip return(nil))
    pcbFabLastZip=zip
    printf("PCB FAB: ZIP %s\n" zip)
    if(car(estados)==t && cadr(estados)==t && nth(2 estados)==t && !pcbFabLogsConAvisos(carpeta) then
      printf("PCB FAB: procesos finalizados sin avisos. Comprueba el paquete en un visor CAM.\n")
    else
      printf("PCB FAB: PAQUETE CON AVISOS: Gerber %L; taladro %L; slots %L. Revisa logs e informe del ZIP.\n" car(estados) cadr(estados) nth(2 estados)))
    return(zip)
  )
)

procedure(pcbFabLogsConAvisos(carpeta)
  let((f linea avisos)
    foreach(nombre '("photoplot.log" "ncdrill.log" "ncroute.log")
      when(isFile(strcat(carpeta "/" nombre))
        f=infile(strcat(carpeta "/" nombre))
        when(f
          while(gets(linea f)
            when(rexMatchp("WARNING" upperCase(linea)) avisos=t))
          close(f))))
    avisos
  )
)

printf("\nPCB FAB: script cargado. Ejecuta primero pcb_fab_auditar.\n")

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
      fprintf(puerto "SEPARATE-ROUTING       NO\n")
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
  prog((diseno films film capa faltan existentes)
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
      printf("PCB FAB: capas encontradas: %d\n" existentes)
      if(faltan then
        printf("PCB FAB: AVISO - capas ausentes: %L\n" reverse(faltan))
      else
        printf("PCB FAB: todas las capas necesarias existen.\n")
      )
      printf("PCB FAB: Gerber RS-274X metric 5.5.\n")
      printf("PCB FAB: NC Enhanced Excellon metric absolute 5.5.\n")
      printf("PCB FAB: PTH y NPTH se generan en un unico archivo.\n")
      return(not(faltan))
    )
  )
)

procedure(pcbFabConfigurar()
  let((diseno films film ancho resultado)
    diseno = axlDBGetDesign()
    if(diseno == nil then
      printf("\nPCB FAB: No hay ningun diseno abierto.\n")
      nil
    else
      if(not(pcbFabAuditar()) then
        printf("PCB FAB: configuracion cancelada porque faltan capas.\n")
        nil
      else
        ancho = axlMKSConvert(0.10 "millimeters" car(axlDBGetDesignUnits()))
        resultado = t
        films = pcbFabCapas()
        foreach(film films
          unless(axlFilmCreate(car(film)
            ?negative nil
            ?undefineLineWidth ancho
            ?rotation 0
            ?xOffset 0.0
            ?yOffset 0.0
            ?mirrored nil
            ?fullContact nil
            ?suppressUnconnectPads nil
            ?drawMissingPadApertures t
            ?useApertureRotation t
            ?suppressShapeFill nil
            ?vectorBasedPad nil
            ?drawHolesOnly nil
            ?layers cadr(film)
            ?domains list("artwork" "visibility"))
            resultado = nil
            printf("PCB FAB: ERROR creando film %s.\n" car(film))
          )
        )
        if(resultado then
          printf("\nPCB FAB: siete films configurados correctamente.\n")
          printf("PCB FAB: el diseno NO se ha guardado.\n")
        )
        resultado
      )
    )
  )
)

procedure(pcbFabExportarWorker()
  let((formatoArt resultadoArt resultadoNc)
    formatoArt = "artwork -f COPPER_BOTTOM -f COPPER_TOP -f MASK_BOTTOM -f MASK_TOP -f OUTLINE -f SILK_BOTTOM -f SILK_TOP %s"
    resultadoArt = axlRunBatchDBProgram("artwork" formatoArt
      ?logfile "photoplot" ?startMsg "PCB Gerber RS-274X" ?warnProgram t)
    resultadoNc = axlRunBatchDBProgram("nctape" "nctape -o -n PCB_DRILL.drl %s"
      ?logfile "ncdrill" ?startMsg "PCB NC Drill" ?warnProgram t)
    list(resultadoArt resultadoNc)
  )
)

procedure(pcbFabComprimir(carpeta estados)
  prog((f helper comando previo resultado ejecutable)
    helper=strcat(pcbToolsRoot "/pcb_empaquetar.ps1")
    unless(isFile(helper) error("PCB: falta el empaquetador %s." helper))
    when(rexMatchp("[\"%]" helper) error("PCB: ruta del empaquetador no compatible."))
    f=outfile(strcat(carpeta "/pcb_export_info.txt") "w")
    unless(f error("No se pudo escribir la informacion del paquete."))
    fprintf(f "tools_version=%s\n" pcbToolsVersion)
    fprintf(f "artwork_status=%d\n" if(car(estados)==t then 0 else car(estados)))
    fprintf(f "ncdrill_status=%d\n" if(cadr(estados)==t then 0 else cadr(estados)))
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
    pcbFabLastResult = list(carpeta car(estados) cadr(estados))
    unless(member(car(estados) '(t 1)) && member(cadr(estados) '(t 1))
      printf("PCB FAB: ERROR Gerber %L; taladro %L. No se crea un ZIP de fabricacion.\n" car(estados) cadr(estados))
      return(nil))
    zip=pcbFabComprimir(carpeta estados)
    unless(zip return(nil))
    pcbFabLastZip=zip
    printf("PCB FAB: ZIP %s\n" zip)
    if(car(estados)==t && cadr(estados)==t then
      printf("PCB FAB: procesos finalizados sin avisos. Comprueba el paquete en un visor CAM.\n")
    else
      printf("PCB FAB: PAQUETE CON AVISOS: Gerber %L; taladro %L. Revisa el informe dentro del ZIP.\n" car(estados) cadr(estados)))
    return(zip)
  )
)

axlCmdRegister("pcb_fab_auditar" 'pcbFabAuditar)
axlCmdRegister("pcb_fab_configurar" 'pcbFabConfigurar)
axlCmdRegister("pcb_fab_exportar" 'pcbFabExportar)

printf("\nPCB FAB: script cargado. Ejecuta primero pcb_fab_auditar.\n")

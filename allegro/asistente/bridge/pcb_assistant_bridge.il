; Optional external assistant bridge. Existing pcb_* utilities are not modified.
; ASCII source, cp1252 data. No eval / evalstring / request-supplied code.
unless(boundp('pcbwaTimer) pcbwaTimer=nil)
unless(boundp('pcbwaPending) pcbwaPending=nil)
unless(boundp('pcbwaSeen) pcbwaSeen=nil)

procedure(pcbwaLine(f)
  let((line parts)
    unless(gets(line f) error("PCB ASISTENTE: solicitud incompleta."))
    parts=parseString(line "\r\n")
    unless(length(parts)==1 error("PCB ASISTENTE: campo vacio o invalido."))
    car(parts)))

procedure(pcbwaBoard()
  let((name)
    name=axlGetDrawingName()
    when(name
      unless(rexMatchp("\\.[bB][rR][dD]$" name) name=strcat(name ".brd")))
    name))

procedure(pcbwaHeartbeat()
  let((f)
    f=outfile(strcat(pcbwaRoot "/heartbeat.tsv"))
    when(f
      fprintf(f "token\t%s\nboard\t%s\nprotocol\t3\n" pcbwaToken or(pcbwaBoard() "-"))
      close(f))))

procedure(pcbwaTimerCB(window timer elapsed)
  ; Timer only updates a short heartbeat and posts a command. Never saves,
  ; modifies a board, opens forms or keeps database ids across callbacks.
  pcbwaHeartbeat()
  when(!pcbwaPending && isFile(strcat(pcbwaRoot "/request.tsv"))
    pcbwaPending=t
    axlShellPost("pcbwa_dispatch")))

procedure(pcbwaStart(folder token core)
  prog(()
  ; Deliberately not autoloaded by pcb_cargar.il or allegro.ilinit.
  unless(rexMatchp("^[a-f0-9]+$" token) error("PCB ASISTENTE: token invalido."))
  when(pcbwaTimer axlUIWTimerRemove(pcbwaTimer))
  pcbwaTimer=nil
  pcbwaPending=nil
  pcbwaRoot=folder pcbwaToken=token pcbwaSeen=nil pcbwaSnapshotJob=nil
  unless(isDir(folder) error("PCB ASISTENTE: carpeta de sesion inexistente."))
  unless(isFile(strcat(core "/pcb_cargar.il")) error("PCB ASISTENTE: no se encuentran las utilidades."))
  load(strcat(core "/pcb_cargar.il"))
  unless(boundp('pcbToolsVersion) && equal(pcbToolsVersion "0.3.0")
    error("PCB ASISTENTE: esta beta requiere utilidades 0.3.0."))
  axlCmdRegister("pcbwa_dispatch" 'pcbwaDispatch ?cmdType "interactive")
  pcbwaHeartbeat()
  pcbwaTimer=axlUIWTimerAdd(nil 1000 nil 'pcbwaTimerCB)
  unless(pcbwaTimer error("PCB ASISTENTE: no se pudo iniciar la conexion."))
  printf("PCB ASISTENTE: conectado. Las operaciones se solicitan desde la ventana externa.\n")
  return(t)))

procedure(pcbwaStop()
  when(pcbwaTimer axlUIWTimerRemove(pcbwaTimer))
  pcbwaTimer=nil pcbwaPending=nil
  t)

; Documented net attributes, algroskill/02dbdesc.html, table Net Attributes:
; unconnected = remaining physical connections, excluding unplaced symbols.
; unplaced = unplaced pins. Do not use NET_RATT_COUNT or visible ratsnest lines.
procedure(pcbwaConnectivity()
  prog((remaining unplacedPins details known)
    remaining=0 unplacedPins=0 known=t
    foreach(net axlDBGetDesign()->nets
      if(numberp(net->unconnected) && net->unconnected>=0 && numberp(net->unplaced) && net->unplaced>=0 then
        remaining=remaining+fix(net->unconnected)
        unplacedPins=unplacedPins+fix(net->unplaced)
        when(net->unconnected>0
          details=cons(sprintf(nil "%s: %d" net->name fix(net->unconnected)) details))
      else known=nil))
    return(list(if(known then remaining else nil) if(known then unplacedPins else nil) reverse(details)))))

procedure(pcbwaCollect(f)
  prog((design placed unplaced missing mask missingRefs ref connectivity)
    design=axlDBGetDesign()
    unless(design error("PCB ASISTENTE: no hay placa abierta."))
    placed=0 unplaced=0
    foreach(c design->components
      if(c->symbol then
        placed=placed+1 ref=c->name
        unless(setof(txt axlDBGetAttachedText(c->symbol) equal(txt->text ref))
          missingRefs=cons(ref missingRefs))
      else unplaced=unplaced+1))
    missing=pcbSilkFaltantesAuditar()
    mask=pcbMaskAudit()
    unless(listp(mask) && length(mask)==6 error("PCB ASISTENTE: auditoria de mascara incompleta."))
    fprintf(f "placed\t%d\nunplaced\t%d\nmissing\t%d\n" placed unplaced car(missing))
    foreach(ref missingRefs fprintf(f "missing_ref\t%s\n" ref))
    fprintf(f "drc\t%L\nshapes\t%L\n" axlDRCGetCount() axlDBDynamicShapes(nil))
    connectivity=pcbwaConnectivity()
    fprintf(f "unrouted\t%L\nunplaced_pins\t%L\n" car(connectivity) cadr(connectivity))
    foreach(detail nth(2 connectivity) fprintf(f "unrouted_net\t%s\n" detail))
    fprintf(f "mask_pins\t%d\nmask_vias\t%d\nmask_extras\t%d\nmask_conflicts\t%d\n"
      nth(2 mask) nth(3 mask) nth(4 mask) nth(5 mask))
    foreach(net design->nets fprintf(f "net\t%s\n" net->name))
    fprintf(f "core\t%s\nsignal_mm\t%.3f\npower_mm\t%.3f\n" pcbToolsVersion pcbSignalWidthMM pcbPowerWidthMM)
    fprintf(f "power_nets\t%s\n" buildString(pcbPowerNets "|"))
    return(list(unplaced car(missing) mask missingRefs connectivity))))

procedure(pcbwaAllowed(code count waivers)
  count==0 || member(sprintf(nil "%s:%d" code count) waivers))

procedure(pcbwaDo(action nets signal power ticket job f checkTexts excluded waivers)
  prog((result snapshot checks mask missingCount drc connectivity)
    case(action
      ("inspect"
        pcbSilkAuditar() pcbAnchosAuditar() pcbFabAuditar())
      ("widths"
        unless(rexMatchp("^[0-9.]+$" signal) && rexMatchp("^[0-9.]+$" power)
          error("PCB ASISTENTE: anchos no validos."))
        unless(atof(signal)>=0.1 && atof(signal)<=10.0 && atof(power)>=0.1 && atof(power)<=10.0
          error("PCB ASISTENTE: anchos fuera de rango."))
        pcbwaSnapshotJob=nil
        pcbPowerNets=if(equal(nets "-") then nil else parseString(nets "|"))
        pcbSignalWidthMM=atof(signal) pcbPowerWidthMM=atof(power)
        unless(pcbAplicarAnchos() error("PCB ASISTENTE: no se aplicaron los anchos.")))
      ("mask"
        pcbwaSnapshotJob=nil
        unless(pcbMaskApply() error("PCB ASISTENTE: no se aplico la mascara.")))
      ("references"
        pcbwaSnapshotJob=nil
        result=pcbSilkRecrear()
        unless(result error("PCB ASISTENTE: no se recuperaron las referencias.")))
      ("review"
        pcbwaSnapshotJob=nil
        result=pcbRevisionActualizar()
        unless(numberp(result) error("PCB ASISTENTE: revision fallida."))
        fprintf(f "fresh_drc\t%L\n" result))
      ("snapshot"
        snapshot=pcbProyectoBackup("asistente_verificacion")
        pcbwaSnapshotJob=job
        fprintf(f "snapshot\t%s\n" snapshot))
      ("save"
        pcbwaSnapshotJob=nil
        pcbProyectoBackup("asistente_guardar")
        unless(axlSaveDesign(?noConfirm t) error("PCB ASISTENTE: no se guardo la placa.")))
      ("export"
        unless(pcbwaSnapshotJob && equal(ticket pcbwaSnapshotJob)
          error("PCB ASISTENTE: falta comprobar una copia guardada reciente."))
        ; Always refresh DRC and shapes again, even if the UI has a prior result.
        drc=pcbRevisionActualizar()
        unless(numberp(drc) error("PCB ASISTENTE: no se pudo actualizar la revision."))
        unless(pcbwaAllowed("drc" drc waivers)
          error("PCB ASISTENTE: DRC no aceptados (%d). Revisa el resumen del asistente." drc))
        checks=pcbwaCollect(f) mask=nth(2 checks)
        connectivity=nth(4 checks)
        unless(numberp(car(connectivity)) && numberp(cadr(connectivity))
          error("PCB ASISTENTE: no se pudo comprobar la conectividad."))
        unless(pcbwaAllowed("unrouted" car(connectivity) waivers) && pcbwaAllowed("unplaced_pins" cadr(connectivity) waivers)
          error("PCB ASISTENTE: hay conexiones o pines pendientes no aceptados. Revisa el resumen."))
        missingCount=length(setof(ref nth(3 checks) !member(upperCase(ref) excluded)))
        unless(pcbwaAllowed("unplaced" car(checks) waivers) &&
          (!checkTexts || pcbwaAllowed("missing" missingCount waivers)) &&
          pcbwaAllowed("mask_pins" nth(2 mask) waivers) && pcbwaAllowed("mask_vias" nth(3 mask) waivers) &&
          pcbwaAllowed("mask_extras" nth(4 mask) waivers) && pcbwaAllowed("mask_conflicts" nth(5 mask) waivers)
          error("PCB ASISTENTE: hay avisos nuevos o todavia no aceptados. Repite la comprobacion final."))
        pcbwaSnapshotJob=nil
        result=pcbFabExportar()
        unless(result error("PCB ASISTENTE: no se genero el paquete."))
        fprintf(f "zip\t%s\n" result)
        fprintf(f "exceptions\t%s\n" buildString(waivers "|"))
        fprintf(f "warnings\t%s\n" if(pcbFabLogsConAvisos(car(pcbFabLastResult)) then "1" else "0")))
      (t error("PCB ASISTENTE: accion no permitida.")))
    unless(equal(action "export") pcbwaCollect(f))
    return(t)))

procedure(pcbwaDispatch()
  prog((request magic token job action board nets signal power ticket extra checkTexts excluded waivers
        f log oldPo oldErr result output)
    pcbwaPending=t
    request=infile(strcat(pcbwaRoot "/request.tsv"))
    unless(request pcbwaPending=nil return(nil))
    result=errset(list(pcbwaLine(request) pcbwaLine(request) pcbwaLine(request)
      pcbwaLine(request) pcbwaLine(request) pcbwaLine(request) pcbwaLine(request)
      pcbwaLine(request) pcbwaLine(request) pcbwaLine(request) pcbwaLine(request) pcbwaLine(request)) t)
    extra=gets(extra request)
    close(request)
    deleteFile(strcat(pcbwaRoot "/request.tsv"))
    unless(result && !extra pcbwaPending=nil return(nil))
    result=car(result)
    magic=nth(0 result) token=nth(1 result) job=nth(2 result) action=nth(3 result)
    board=nth(4 result) nets=nth(5 result) signal=nth(6 result) power=nth(7 result) ticket=nth(8 result)
    checkTexts=nth(9 result) excluded=nth(10 result) waivers=nth(11 result)
    unless(equal(magic "PCBWA3") && equal(token pcbwaToken) && member(checkTexts '("0" "1")) &&
      strlen(job)==32 && rexMatchp("^[a-f0-9]+$" job) &&
      member(action '("inspect" "widths" "mask" "references" "review" "snapshot" "save" "export"))
      pcbwaPending=nil return(nil))
    checkTexts=equal(checkTexts "1")
    excluded=if(equal(excluded "-") then nil else parseString(excluded "|"))
    waivers=if(equal(waivers "-") then nil else parseString(waivers "|"))
    when(member(job pcbwaSeen) || isFile(strcat(pcbwaRoot "/" job ".result.tsv"))
      pcbwaPending=nil return(nil))
    pcbwaSeen=cons(job pcbwaSeen)
    output=strcat(pcbwaRoot "/" job ".result.tsv")
    f=outfile(output)
    log=outfile(strcat(pcbwaRoot "/" job ".log"))
    unless(f && log
      when(f close(f)) when(log close(log)) pcbwaPending=nil return(nil))
    fprintf(f "id\t%s\ntoken\t%s\naction\t%s\nboard\t%s\n" job token action or(pcbwaBoard() "-"))
    oldPo=poport oldErr=errport
    poport=log errport=log
    result=errset(
      if(equal(lowerCase(board) lowerCase(or(pcbwaBoard() "-"))) then
        pcbwaDo(action nets signal power ticket job f checkTexts excluded waivers)
      else error("PCB ASISTENTE: la placa activa no coincide. No se ejecuta la operacion.")) t)
    poport=oldPo errport=oldErr
    close(log)
    fprintf(f "status\t%s\ncomplete\t1\n" if(result && car(result) then "ok" else "error"))
    close(f)
    pcbwaPending=nil
    pcbwaHeartbeat()
    printf("PCB ASISTENTE: %s, %s.\n" action if(result && car(result) then "terminado" else "revisar error"))
    return(t)))

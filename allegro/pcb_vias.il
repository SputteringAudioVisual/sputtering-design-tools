; Opt-in replacement of ordinary existing vias. Never changes pins or rules.
procedure(pcbViasItems()
  setof(item pcbMaskItems() cadr(item)=='via)
)

procedure(pcbViasPadEspecial(ps)
  prog((capa w h)
    unless(ps->isThrough && equal(ps->usage "Through") &&
      equal(ps->holeType "CIRCLE_DRILL") && equal(ps->plating "PLATED")
      return("no es un taladro circular pasante metalizado"))
    when(ps->isPadRef || ps->derived || ps->multiDrillData || ps->holeCounterType ||
      ps->backdrillDiameter || ps->uvia || ps->spanLockCount>0 || ps->drillNonStandard ||
      setof(valor append(ps->holeTolerance ps->holeToleranceY) valor!=0.0) ||
      (ps->drillToolSize && !equal(ps->drillToolSize ""))
      return("padstack avanzado, microvia o backdrill"))
    unless(abs(xCoord(ps->drillOffset))<0.0000001 && abs(yCoord(ps->drillOffset))<0.0000001
      return("taladro desplazado"))
    foreach(p ps->pads
      when(pcbMaskHasFigure(p)
        capa=pcbMaskKey(p->layer)
        if(equal(p->type "REGULAR") && member(capa axlSubclassRoute()) then
          w=xCoord(cadr(p->bBox))-xCoord(car(p->bBox))
          h=yCoord(cadr(p->bBox))-yCoord(car(p->bBox))
          unless(equal(p->figureName "CIRCLE") && abs(w-h)<0.0000001 &&
            abs(xCoord(p->offset))<0.0000001 && abs(yCoord(p->offset))<0.0000001
            return("pad de cobre especial o desplazado"))
        else
          unless(equal(p->type "REGULAR") && member(capa '("SOLDERMASK_TOP" "SOLDERMASK_BOTTOM")) &&
            equal(p->figureName "CIRCLE")
            return("geometria auxiliar especial")))))
    foreach(capa axlSubclassRoute()
      unless(pcbMaskHasFigure(pcbMaskPad(ps capa))
        return("falta pad de cobre en una capa de la via")))
    return(nil)
  )
)

procedure(pcbViasPlan(v)
  prog((red pad drill razon reglas permitidas destino ps nombre)
    unless(equal(v->objType "via") error("PCB: se esperaba una via, nunca un pin."))
    red=v->net
    if(pcbEsRedPotencia(red->name) then
      pad=pcbPowerViaPadMM drill=pcbPowerViaDrillMM
    else pad=pcbSignalViaPadMM drill=pcbSignalViaDrillMM)
    unless(pad>drill && drill>0 error("PCB: dimensiones de via no validas."))
    when(pcbAnchosViaCumple(v->definition pad drill)
      return(list('conforme pad drill nil)))
    razon=pcbViasPadEspecial(v->definition)
    when(v->fixedByTestPoint || v->testPoint || assoc('FIXED axlDBGetProperties(v))
      razon="via fija o punto de prueba")
    unless(v->isThrough razon="via no pasante")
    when(razon return(list('omitida pad drill razon)))
    reglas=pcbAnchosReglas(red nil)
    unless(reglas reglas=list("DEFAULT"))
    when(length(reglas)!=1 return(list('omitida pad drill "reglas heredadas ambiguas")))
    unless(member(car(reglas) axlCnsList('physical))
      return(list('omitida pad drill "regla fisica no verificable")))
    permitidas=axlCnsGetViaList(car(reglas))
    foreach(nombre permitidas
      ps=axlDBFindByName('padstack nombre)
      when(ps && !pcbViasPadEspecial(ps) && pcbAnchosViaCumple(ps pad drill) && !pcbMaskNeeds(ps 'via)
        unless(destino destino=nombre)))
    when(permitidas && !destino
      return(list('omitida pad drill "la regla fisica no permite una via compatible con el perfil")))
    unless(destino
      destino=pcbAnchosViaNombre(if(pcbEsRedPotencia(red->name) then "PWR" else "SIG") pad drill))
    return(list('cambiar pad drill destino))
  )
)

procedure(pcbViasAuditar()
  let((total pendientes omitidas plan v)
    total=0 pendientes=0 omitidas=0
    foreach(item pcbViasItems()
      v=car(item) plan=pcbViasPlan(v) total=total+1
      when(car(plan)=='cambiar
        pendientes=pendientes+1
        printf("PCB VIA: %s en %L: %s -> %s (%.2f/%.2f mm).\n"
          v->net->name v->xy v->definition->name nth(3 plan) cadr(plan) nth(2 plan)))
      when(car(plan)=='omitida
        omitidas=omitidas+1
        printf("PCB VIA: OMITIDA %s en %L: %s.\n" v->net->name v->xy nth(3 plan))))
    printf("PCB VIA: auditoria sin cambios: %d vias; %d sustituibles; %d requieren revision manual.\n"
      total pendientes omitidas)
    list(total pendientes omitidas)
  )
)

procedure(pcbViasWorker()
  let((v plan destino despues count oldName xy red span props conectadas rotation mirrored)
    count=0
    foreach(item pcbViasItems()
      v=axlDBRefreshId(car(item)) plan=pcbViasPlan(v)
      when(car(plan)=='cambiar
        oldName=v->definition->name xy=v->xy red=v->net->name span=v->startEnd
        rotation=v->rotation mirrored=v->isMirrored
        props=axlDBGetProperties(v) conectadas=axlDBGetConnect(v)
        destino=pcbCrearVia(nth(3 plan) cadr(plan) nth(2 plan))
        despues=car(axlReplacePadstack(v destino))
        unless(despues && equal(despues->objType "via") && equal(despues->xy xy) &&
          equal(despues->net->name red) && equal(despues->startEnd span) &&
          equal(despues->rotation rotation) && equal(despues->isMirrored mirrored) &&
          equal(axlDBGetProperties(despues) props) &&
          pcbAnchosViaCumple(despues->definition cadr(plan) nth(2 plan)) &&
          !pcbMaskNeeds(despues->definition 'via)
          error("PCB: la sustitucion de una via no conserva sus invariantes."))
        foreach(cline conectadas
          unless(member(axlDBRefreshId(cline) axlDBGetConnect(despues))
            error("PCB: la sustitucion desconectaria una pista. Se revierte todo.")))
        count=count+1
        printf("PCB VIA: cambiada %s en %L: %s -> %s.\n" red xy oldName despues->definition->name)))
    count
  )
)

procedure(pcbViasNormalizar()
  prog((audit resultado)
    audit=pcbViasAuditar()
    when(cadr(audit)==0
      printf("PCB VIA: no hay vias ordinarias sustituibles.\n") return(t))
    resultado=pcbProyectoAplicar("vias" 'pcbViasWorker)
    when(numberp(resultado) && resultado>0
      pcbRevisionPendiente(t)
      printf("PCB VIA: OBLIGATORIO ejecutar pcb_revision_actualizar y revisar DRC/conexiones antes de exportar.\n"))
    return(resultado)
  )
)

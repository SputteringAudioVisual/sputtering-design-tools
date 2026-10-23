; Allegro PCB Editor 17.2. Soldermask = ABERTURAS, no material de mascara.
; Cargar: skill load(".../pcb_mascara.il")
; pcb_mascara_revisar: solo informa. pcb_mascara: aplica en memoria y crea backup.
; No exporta ni cambia bibliotecas .pad. No guarda encima de la placa.
; Limite: normalizacion de padstacks circulares/cuadrados/rectangulares simples.
; La auditoria avisa si existen otras aberturas de mascara en la geometria.

unless(boundp('pcbMaskMarginMM) pcbMaskMarginMM = 0.0)
unless(boundp('pcbMaskSequence) pcbMaskSequence = 0)

procedure(pcbMaskKey(layer)
  if(stringp(layer) then car(last(parseString(upperCase(layer) "/"))) else layer)
)

procedure(pcbMaskPad(ps layer)
  car(setof(p ps->pads equal(p->type "REGULAR") && equal(pcbMaskKey(p->layer) layer)))
)

procedure(pcbMaskHasFigure(p)
  p && p->figureName && !equal(p->figureName "NULL")
)

procedure(pcbMaskContains(copper mask delta)
  prog((cb mb cx cy mx my cr mr dx dy ok)
    unless(pcbMaskHasFigure(mask) return(nil))
    cb = copper->bBox mb = mask->bBox
    unless(member(copper->figureName '("CIRCLE" "SQUARE" "RECTANGLE")) &&
      member(mask->figureName '("CIRCLE" "SQUARE" "RECTANGLE"))
      error("Figura especial: revisar mascara de %s" copper->parent->name))
    when(member(mask->figureName '("SQUARE" "RECTANGLE"))
      return(xCoord(car(mb)) <= xCoord(car(cb))-delta+0.0000001 &&
        yCoord(car(mb)) <= yCoord(car(cb))-delta+0.0000001 &&
        xCoord(cadr(mb)) >= xCoord(cadr(cb))+delta-0.0000001 &&
        yCoord(cadr(mb)) >= yCoord(cadr(cb))+delta-0.0000001))
    mx = xCoord(mask->offset) my = yCoord(mask->offset)
    mr = (xCoord(cadr(mb))-xCoord(car(mb)))/2.0
    when(equal(copper->figureName "CIRCLE")
      cx=xCoord(copper->offset) cy=yCoord(copper->offset)
      cr=(xCoord(cadr(cb))-xCoord(car(cb)))/2.0 + delta
      dx=cx-mx dy=cy-my
      return(sqrt(dx*dx+dy*dy)+cr <= mr+0.0000001))
    ok=t
    foreach(x list(xCoord(car(cb))-delta xCoord(cadr(cb))+delta)
      foreach(y list(yCoord(car(cb))-delta yCoord(cadr(cb))+delta)
        dx=x-mx dy=y-my
        when(sqrt(dx*dx+dy*dy)>mr+0.0000001 ok=nil)))
    return(ok)
  )
)

procedure(pcbMaskArea(polys)
  let((area)
    area = 0.0
    foreach(poly polys area = area + abs(poly->area))
    area
  )
)

procedure(pcbMaskNeeds(ps mode)
  let((bad copper mask required delta missing)
    bad = nil
    delta = axlMKSConvert(pcbMaskMarginMM "millimeters" car(axlDBGetDesignUnits()))
    foreach(side '("TOP" "BOTTOM")
      mask = pcbMaskPad(ps strcat("SOLDERMASK_" side))
      if(mode == 'via then
        when(pcbMaskHasFigure(mask) bad = t)
      else
        copper = pcbMaskPad(ps if(equal(side "TOP") then axlConductorTopLayer() else axlConductorBottomLayer()))
        when(pcbMaskHasFigure(copper)
          unless(pcbMaskContains(copper mask delta) bad=t)
        )
      )
    )
    bad
  )
)

procedure(pcbMaskItems()
  let((items vias)
    foreach(c axlDBRefreshId(axlDBGetDesign())->components
      c = axlDBRefreshId(c)
      when(c->symbol
        foreach(pin axlDBRefreshId(c->symbol)->pins
          pin = axlDBRefreshId(pin)
          when(pin->definition items = cons(list(pin 'pin) items))
        )
      )
    )
    foreach(net axlDBRefreshId(axlDBGetDesign())->nets
      foreach(branch axlDBRefreshId(net)->branches
        foreach(v axlDBRefreshId(branch)->children
          when(equal(v->objType "via") && !member(v vias)
            vias = cons(v vias)
            items = cons(list(v 'via) items)
          )
        )
      )
    )
    reverse(items)
  )
)

procedure(pcbMaskExtras()
  let((objects)
    ; Las formas adicionales pueden destapar vias aunque su padstack no tenga
    ; abertura. No se borran: podrian pertenecer a conectores o testpoints.
    foreach(side '("TOP" "BOTTOM")
      foreach(cls '("PACKAGE GEOMETRY" "BOARD GEOMETRY")
        objects = append(objects axlDBGetShapes(strcat(cls "/SOLDERMASK_" side)))
      )
    )
    foreach(sym axlDBGetDesign()->symbols
      foreach(child sym->children
        when(child->layer && rexMatchp("SOLDERMASK_" child->layer)
          unless(member(child objects) objects = cons(child objects))
        )
      )
    )
    objects
  )
)

procedure(pcbMaskBoxOverlap(a b)
  xCoord(car(a)) <= xCoord(cadr(b)) && xCoord(cadr(a)) >= xCoord(car(b)) &&
  yCoord(car(a)) <= yCoord(cadr(b)) && yCoord(cadr(a)) >= yCoord(car(b))
)

procedure(pcbMaskOpenings(items extras)
  let((openings obj cls polys)
    foreach(item items
      obj = car(item)
      cls = if(cadr(item) == 'via then "VIA CLASS" else "PIN")
      foreach(side '("TOP" "BOTTOM")
        polys = axlPolyFromDB(obj ?layer strcat(cls "/SOLDERMASK_" side) ?padType 'REGULAR)
        foreach(poly polys openings = cons(list(side obj poly) openings))
      )
    )
    foreach(obj extras
      unless(equal(obj->objType "text")
        polys = axlPolyFromDB(obj ?line2poly t)
        foreach(poly polys
          openings = cons(list(if(rexMatchp("_TOP$" obj->layer) then "TOP" else "BOTTOM") obj poly) openings)
        )
      )
    )
    openings
  )
)

procedure(pcbMaskViaConflicts(v openings)
  let((hit copper)
    foreach(side '("TOP" "BOTTOM")
      copper = axlPolyFromDB(v ?layer strcat("ETCH/" if(equal(side "TOP") then axlConductorTopLayer() else axlConductorBottomLayer())) ?padType 'REGULAR)
      foreach(poly copper
        foreach(entry openings
          when(equal(car(entry) side) && cadr(entry) != v &&
            pcbMaskBoxOverlap(poly->bBox nth(2 entry)->bBox)
            when(pcbMaskArea(axlPolyOperation(list(poly) list(nth(2 entry)) 'AND)) > 0.00000001
              hit = t)
          )
        )
      )
    )
    hit
  )
)

procedure(pcbMaskAudit()
  prog((items ps badPins badVias pins vias f path extras openings conflicts)
    unless(axlDBGetDesign() printf("PCB MASK: no hay placa abierta.\n") return(nil))
    items = pcbMaskItems()
    pins = 0 vias = 0 badPins = 0 badVias = 0
    path = strcat(pcbProyectoDirectorio() "/pcb_mascara_revision.txt")
    f = outfile(path)
    unless(f error("No se puede escribir el informe en el directorio del proyecto"))
    fprintf(f "PCB MASCARA - revision de padstacks. Margen: %.4f mm\n" pcbMaskMarginMM)
    foreach(item items
      ps = car(item)->definition
      if(cadr(item) == 'pin then pins = pins + 1 else vias = vias + 1)
      when(pcbMaskNeeds(ps cadr(item))
        if(cadr(item) == 'pin then badPins = badPins + 1 else badVias = badVias + 1)
        fprintf(f "%L xy=%L padstack=%s\n" cadr(item) car(item)->xy ps->name)
      )
    )
    extras = pcbMaskExtras()
    openings = pcbMaskOpenings(items extras)
    conflicts = 0
    foreach(item items
      when(cadr(item) == 'via && pcbMaskViaConflicts(car(item) openings)
        conflicts = conflicts + 1
        fprintf(f "VIA EXPUESTA POR OTRA ABERTURA xy=%L\n" car(item)->xy)
      )
    )
    fprintf(f "\nPines: %d; pendientes: %d\nVias: %d; con abertura propia: %d\n" pins badPins vias badVias)
    fprintf(f "Geometrias adicionales de soldermask: %d\n" length(extras))
    fprintf(f "Vias afectadas por otras aberturas: %d\n" conflicts)
    when(extras
      fprintf(f "REVISAR: existen aberturas adicionales fuera de los padstacks. No se certifica el tentado efectivo de todas las vias.\n")
    )
    fprintf(f "Esta revision no sustituye la comprobacion de los Gerber ni la capacidad de tentado del fabricante.\n")
    close(f)
    printf("\nPCB MASK: %d pines (%d pendientes); %d vias (%d abiertas).\n" pins badPins vias badVias)
    printf("PCB MASK: informe %s; %d geometrias adicionales de mascara.\n" path length(extras))
    when(extras printf("PCB MASK: revisar aberturas adicionales antes de afirmar que todas las vias estan cubiertas.\n"))
    when(conflicts > 0 printf("PCB MASK: %d vias se solapan con otras aberturas. No se mueven ni se cubren pads de componentes.\n" conflicts))
    return(list(pins vias badPins badVias length(extras) conflicts))
  )
)

procedure(pcbMaskPadSpec(p)
  let((w h fig)
    fig = p->figureName
    unless(member(fig '("NULL" "CIRCLE" "SQUARE" "RECTANGLE"))
      error("Padstack especial no normalizado automaticamente: %s (%s)" p->parent->name fig)
    )
    w = xCoord(cadr(p->bBox)) - xCoord(car(p->bBox))
    h = yCoord(cadr(p->bBox)) - yCoord(car(p->bBox))
    make_axlPadStackPad(?layer pcbMaskKey(p->layer) ?type concat(p->type)
      ?figure concat(fig) ?figureSize list(w h) ?offset p->offset)
  )
)

procedure(pcbMaskDrill(ps)
  prog(()
  when(ps->isPadRef || ps->derived || ps->multiDrillData || ps->holeCounterType || ps->backdrillDiameter
    error("Padstack avanzado no normalizado automaticamente: %s" ps->name)
  )
  when(ps->isThrough
    unless(equal(ps->holeType "CIRCLE_DRILL")
      error("Taladro especial no normalizado automaticamente: %s" ps->name))
    ; fixed es la inversa de padSuppresion (pads opcionales en capas internas).
    return(make_axlPadStackDrill(?usage ps->usage ?fixed !ps->padSuppresion
      ?spanLockCount (ps->spanLockCount > 0) ?uvia ps->uvia
      ?holeType 'CIRCLE_DRILL ?plating concat(ps->plating)
      ?drillDiameter ps->drillDiameter ?drillToolSize ps->drillToolSize
      ?holeTolerance ps->holeTolerance ?holeToleranceY ps->holeToleranceY
      ?offset ps->drillOffset ?drillNonStandard ps->drillNonStandard
      ?figure concat(ps->drillFigureName)
      ?figureSize list(ps->drillFigureWidth ps->drillFigureHeight)
      ?drillChar ps->drillChar))
  )
  unless(member(ps->usage '("Smd" "Surface_pin"))
    error("Padstack sin taladro no compatible: %s" ps->name))
  return(nil)
  )
)

procedure(pcbMaskDrillSignature(ps)
  list(ps->drillDiameter ps->drillOffset ps->holeType ps->plating
    ps->holeTolerance ps->holeToleranceY ps->drillToolSize ps->drillNonStandard
    ps->drillChar ps->drillFigureName ps->drillFigureWidth ps->drillFigureHeight
    ps->usage ps->uvia ps->spanLockCount ps->padSuppresion)
)

procedure(pcbMaskSamePad(a b)
  if(!pcbMaskHasFigure(a) then !pcbMaskHasFigure(b) else
    a && b && equal(a->figureName b->figureName) && equal(a->offset b->offset) &&
      equal(a->bBox b->bBox) && equal(a->type b->type))
)

procedure(pcbMaskClone(ps mode)
  let((specs copper mask spec size delta name n new drill)
    drill = pcbMaskDrill(ps)
    foreach(p ps->pads
      when(pcbMaskHasFigure(p) && !member(pcbMaskKey(p->layer) '("SOLDERMASK_TOP" "SOLDERMASK_BOTTOM"))
        specs = cons(pcbMaskPadSpec(p) specs)
      )
    )
    delta = axlMKSConvert(pcbMaskMarginMM "millimeters" car(axlDBGetDesignUnits()))
    foreach(side '("TOP" "BOTTOM")
      copper = pcbMaskPad(ps if(equal(side "TOP") then axlConductorTopLayer() else axlConductorBottomLayer()))
      mask = pcbMaskPad(ps strcat("SOLDERMASK_" side))
      if(mode == 'via || !pcbMaskHasFigure(copper) then
        spec = make_axlPadStackPad(?layer strcat("SOLDERMASK_" side)
          ?type 'REGULAR ?figure 'NULL ?figureSize 0:0)
      else
        ; Mantiene una abertura anterior que ya cubra el pad y el margen.
        if(pcbMaskContains(copper mask delta) then
          spec = pcbMaskPadSpec(mask)
        else
          spec = pcbMaskPadSpec(copper)
          spec->layer = strcat("SOLDERMASK_" side)
          size = spec->figureSize
          spec->figureSize = list(xCoord(size) + 2*delta yCoord(size) + 2*delta)
        )
      )
      unless(equal(spec->figure 'NULL) specs = cons(spec specs))
    )
    pcbMaskSequence = pcbMaskSequence + 1
    n = pcbMaskSequence
    name = sprintf(nil "PCBM_%s_%d" if(mode == 'pin then "PIN" else "VIA") n)
    while(setof(p axlDBRefreshId(axlDBGetDesign())->padstacks equal(p->name name))
      pcbMaskSequence = pcbMaskSequence + 1
      n = pcbMaskSequence
      name = sprintf(nil "PCBM_%s_%d" if(mode == 'pin then "PIN" else "VIA") n))
    ; El constructor no debe reinterpretar comprobaciones de taladro de una
    ; definicion existente. Se valida su identidad geom?trica antes de usarla.
    new = axlDBCreatePadStack(name drill reverse(specs) t)
    unless(new error("No se pudo crear padstack de mascara para %s" ps->name))
    unless(equal(pcbMaskDrillSignature(ps) pcbMaskDrillSignature(new))
      printf("PCB MASK: taladro original %L; copia %L\n" pcbMaskDrillSignature(ps) pcbMaskDrillSignature(new))
      error("La copia alteraria atributos del taladro: %s. Operacion cancelada." ps->name))
    foreach(p ps->pads
      unless(member(pcbMaskKey(p->layer) '("SOLDERMASK_TOP" "SOLDERMASK_BOTTOM"))
        mask = car(setof(q new->pads equal(pcbMaskKey(q->layer) pcbMaskKey(p->layer)) && equal(q->type p->type)))
        unless(pcbMaskSamePad(p mask)
          printf("PCB MASK: pad original %L; copia %L\n" p->?? when(mask mask->??))
          error("La copia alteraria una capa ajena a soldermask: %s %L %s" ps->name p->layer p->type))
      )
    )
    when(pcbMaskNeeds(new mode) error("La mascara generada no supera la revision: %s" ps->name))
    new
  )
)

procedure(pcbMaskApplyWorker()
  let((items ps mode cache key entry new count result)
    items = pcbMaskItems()
    count = 0
    foreach(item items
      ps = car(item)->definition mode = cadr(item)
      when(pcbMaskNeeds(ps mode)
        key = sprintf(nil "%s_%L" ps->name mode)
        entry = assoc(key cache)
        if(entry then new = cadr(entry) else
          new = pcbMaskClone(ps mode)
          cache = cons(list(key new) cache))
        result = axlReplacePadstack(car(item) new)
        unless(result error("No se pudo cambiar un padstack; se revierte la operacion."))
        count = count + 1
      )
    )
    count
  )
)

procedure(pcbMaskApplyChecked()
  let((r)
    r = errset(pcbMaskApplyWorker() t)
    if(r then car(r) else nil)
  )
)

procedure(pcbMaskApply()
  prog((original backup n tx result audit carpeta anterior guardado)
    unless(axlDBGetDesign() printf("PCB MASK: no hay placa abierta.\n") return(nil))
    when(pcbMaskMarginMM < 0.0 error("El margen de soldermask no puede ser negativo."))
    audit = pcbMaskAudit()
    when(nth(2 audit) == 0 && nth(3 audit) == 0
      printf("PCB MASK: padstacks ya conformes. No se modifica nada.\n") return(t))
    original = pcbProyectoArchivo()
    carpeta = strcat(pcbProyectoDirectorio() "/Copias_seguridad")
    unless(createDirHier(carpeta) error("No se pudo crear la carpeta de copias del proyecto."))
    n = 1 backup = sprintf(nil "%s/%s_antes_mascara_v%03d.brd" carpeta pcbProyectoNombre() n)
    while(isFile(backup) n = n + 1 backup = sprintf(nil "%s/%s_antes_mascara_v%03d.brd" carpeta pcbProyectoNombre() n))
    anterior = getWorkingDir()
    ; writeModel creates a snapshot WITHOUT changing the active drawing path.
    guardado = errset(axlSaveDesign(?design backup ?noMru t ?noConfirm t ?writeModel t) t)
    changeWorkingDir(anterior)
    unless(guardado && car(guardado)
      error("No se pudo guardar la copia de seguridad. No se modifica la mascara."))
    ; Guardar invalida los dbids: se obtienen de nuevo dentro del worker.
    tx = axlDBTransactionStart()
    unless(tx error("No se puede iniciar transaccion de mascara."))
    result = errset(axlDBCloak('pcbMaskApplyChecked()) t)
    return(if(result && numberp(car(result)) then
      axlDBTransactionCommit(tx)
      printf("PCB MASK: %d pines/vias corregidos. Backup: %s\n" car(result) backup)
      pcbMaskAudit()
      printf("PCB MASK: cambios en memoria. Guarda la placa cuando los revises.\n")
      printf("PCB MASK: Allegro puede recalcular los rellenos; revisa sus DRC antes de fabricar.\n")
      t
    else
      axlDBTransactionRollback(tx)
      printf("PCB MASK: operacion cancelada y revertida. Backup: %s\n" backup)
      nil
    ))
  )
)

axlCmdRegister("pcb_mascara_revisar" 'pcbMaskAudit ?cmdType "general")
axlCmdRegister("pcb_mascara" 'pcbMaskApply ?cmdType "general")
printf("PCB MASK cargado: pcb_mascara_revisar / pcb_mascara.\n")

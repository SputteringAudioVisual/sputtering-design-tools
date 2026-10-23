; Physical rules for new routing. Does not resize existing tracks or vias.
procedure(pcbEsRedPotencia(nombre)
  member(upperCase(nombre) foreach(mapcar n pcbPowerNets upperCase(n)))
)

procedure(pcbAnchosReglaAjena(obj visitados)
  let((prop ajena)
    unless(member(obj visitados)
      visitados = cons(obj visitados)
      prop = assoc('PHYSICAL_CONSTRAINT_SET axlDBGetProperties(obj))
      when(prop && !member(upperCase(cadr(prop)) '("PCB_SIGNAL" "PCB_POWER" "DEFAULT"))
        ajena = t)
      foreach(grupo obj->parentGroups
        when(pcbAnchosReglaAjena(grupo visitados) ajena = t))
    )
    ajena
  )
)

procedure(pcbCrearVia(nombre diametroPad diametroTaladro)
  prog((drill pads tamPad tamTaladro unidades existente regular)
    unless(diametroTaladro > 0 && diametroPad > diametroTaladro
      error("PCB: diametros de via no validos."))
    unidades = car(axlDBGetDesignUnits())
    tamPad = axlMKSConvert(diametroPad "millimeters" unidades)
    tamTaladro = axlMKSConvert(diametroTaladro "millimeters" unidades)
    existente = axlDBFindByName('padstack nombre)
    when(existente
      unless(abs(existente->drillDiameter - tamTaladro) < 0.0000001
        error("PCB: existe un padstack incompatible llamado %s." nombre))
      ; The database expands DEFAULT_INTERNAL into actual stackup layers.
      ; Two-layer boards do not expose a DEFAULT_INTERNAL pad at all.
      foreach(capa axlSubclassRoute()
        regular = car(setof(p existente->pads equal(p->type "REGULAR") &&
          equal(buildString(parseString(car(last(parseString(upperCase(p->layer) "/"))) " _") "_") capa)))
        unless(regular && equal(regular->figureName "CIRCLE") &&
          abs(xCoord(cadr(regular->bBox))-xCoord(car(regular->bBox))-tamPad) < 0.0000001
          error("PCB: geometria incompatible en %s / %s." nombre capa)))
      return(existente))
    drill = make_axlPadStackDrill(?usage "Through" ?holeType 'CIRCLE_DRILL
      ?drillDiameter tamTaladro ?plating 'PLATED)
    foreach(capa list(axlConductorTopLayer() "DEFAULT_INTERNAL" axlConductorBottomLayer())
      pads = cons(make_axlPadStackPad(?layer capa ?type 'REGULAR ?figure 'CIRCLE
        ?figureSize list(tamPad tamPad)) pads))
    existente = axlDBCreatePadStack(nombre drill pads nil)
    unless(existente error("PCB: no se pudo crear la via %s." nombre))
    return(existente)
  )
)

procedure(pcbAnchosViaNombre(prefijo pad drill)
  sprintf(nil "PCB_VIA_%s_%d_%d" prefijo fix(pad*1000+0.5) fix(drill*1000+0.5))
)

procedure(pcbAnchosCset(nombre ancho via)
  prog((tipos)
    unless(member(nombre axlCnsList('physical))
      unless(axlCNSCreate('physical nombre nil) error("No se pudo crear %s" nombre)))
    foreach(tipo '(width_min width_max)
      unless(axlCNSSetPhysical(nombre nil tipo sprintf(nil "%.6f MM" ancho))
        error("No se pudo configurar %s %L" nombre tipo)))
    tipos = axlCNSGetPhysical(nil nil nil)
    when(member('neckwidth_max tipos)
      unless(axlCNSSetPhysical(nombre nil 'neckwidth_max sprintf(nil "%.6f MM" ancho))
        error("No se pudo configurar el neck width de %s" nombre)))
    when(member('necklength_max tipos)
      unless(axlCNSSetPhysical(nombre nil 'necklength_max 0)
        error("No se pudo desactivar neck length de %s" nombre)))
    foreach(anterior axlCnsGetViaList(nombre) axlCnsDeleteVia(nombre anterior))
    unless(axlCnsAddVia(nombre via) error("No se pudo asignar la via de %s" nombre))
    return(t)
  )
)

procedure(pcbAnchosProcesar(aplicar)
  prog((normales potencia omitidas viaSenal viaPotencia destino)
    unless(axlDBGetDesign() printf("PCB: no hay placa abierta.\n") return(nil))
    unless(pcbSignalWidthMM > 0 && pcbPowerWidthMM > 0
      error("PCB: los anchos deben ser positivos."))
    normales = 0 potencia = 0 omitidas = 0
    when(aplicar
      viaSenal = pcbAnchosViaNombre("SIG" pcbSignalViaPadMM pcbSignalViaDrillMM)
      viaPotencia = pcbAnchosViaNombre("PWR" pcbPowerViaPadMM pcbPowerViaDrillMM)
      pcbCrearVia(viaSenal pcbSignalViaPadMM pcbSignalViaDrillMM)
      pcbCrearVia(viaPotencia pcbPowerViaPadMM pcbPowerViaDrillMM)
      pcbAnchosCset("PCB_SIGNAL" pcbSignalWidthMM viaSenal)
      pcbAnchosCset("PCB_POWER" pcbPowerWidthMM viaPotencia))
    foreach(red axlDBGetDesign()->nets
      if(pcbPreserveCustomRules && pcbAnchosReglaAjena(red nil) then
        omitidas = omitidas + 1
        printf("PCB: se conserva la regla especial de %s.\n" red->name)
      else
        if(pcbEsRedPotencia(red->name) then
          potencia = potencia + 1 destino = "PCB_POWER"
        else
          normales = normales + 1 destino = "PCB_SIGNAL")
        when(aplicar
          unless(axlDBAddProp(red list("PHYSICAL_CONSTRAINT_SET" destino))
            error("PCB: no se pudo asignar la regla a %s." red->name)))
      ))
    printf("PCB: senal %.3f mm: %d redes; potencia %.3f mm: %d; omitidas: %d.\n"
      pcbSignalWidthMM normales pcbPowerWidthMM potencia omitidas)
    printf("PCB: DEFAULT se conserva. Las pistas y vias existentes no se redimensionan.\n")
    when(aplicar printf("PCB: cambios en memoria. Revisa y guarda la placa.\n"))
    return(t)
  )
)

procedure(pcbAnchosAuditar() pcbAnchosProcesar(nil))
procedure(pcbAplicarAnchos()
  prog((tx resultado)
    unless(axlDBGetDesign() return(nil))
    tx = axlDBTransactionStart()
    unless(tx error("No se pudo iniciar la transaccion de anchos."))
    resultado = errset(pcbAnchosProcesar(t) t)
    if(resultado && car(resultado) then
      axlDBTransactionCommit(tx) return(t)
    else
      axlDBTransactionRollback(tx)
      printf("PCB: anchos cancelados y revertidos.\n") return(nil))
  )
)
axlCmdRegister("pcb_anchos_auditar" 'pcbAnchosAuditar)
axlCmdRegister("pcb_anchos" 'pcbAplicarAnchos)

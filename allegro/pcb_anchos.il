; Physical rules for new routing. Does not resize existing tracks or vias.
procedure(pcbEsRedPotencia(nombre)
  member(upperCase(nombre) foreach(mapcar n pcbPowerNets upperCase(n)))
)

; A direct assignment takes precedence. Multiple inherited assignments are
; reported separately; never guess which group wins in an ambiguous hierarchy.
procedure(pcbAnchosReglas(obj visitados)
  let((prop reglas)
    unless(member(obj visitados)
      visitados = cons(obj visitados)
      prop = assoc('PHYSICAL_CONSTRAINT_SET axlDBGetProperties(obj))
      if(prop then reglas=list(cadr(prop)) else
        foreach(grupo obj->parentGroups
          foreach(regla pcbAnchosReglas(grupo visitados)
            unless(member(regla reglas) reglas=cons(regla reglas)))))
    )
    reglas
  )
)

procedure(pcbAnchosReglaAjena(obj visitados)
  setof(regla pcbAnchosReglas(obj visitados)
    !member(upperCase(regla) '("PCB_SIGNAL" "PCB_POWER" "DEFAULT")))
)

procedure(pcbAnchosRevisarReglas(red)
  let((reglas esperado unidades minimo maximo problemas)
    reglas=pcbAnchosReglas(red nil)
    esperado=if(pcbEsRedPotencia(red->name) then pcbPowerWidthMM else pcbSignalWidthMM)
    unidades=car(axlDBGetDesignUnits())
    problemas=0
    when(length(reglas)>1
      printf("PCB: AVISO %s: varias reglas heredadas %L; revisar precedencia en Constraint Manager.\n" red->name reglas)
      problemas=problemas+1)
    foreach(regla reglas
      foreach(capa axlSubclassRoute()
        minimo=axlCNSGetPhysical(regla capa 'width_min)
        maximo=axlCNSGetPhysical(regla capa 'width_max)
        if(numberp(minimo) && numberp(maximo) then
          minimo=axlMKSConvert(minimo unidades "millimeters")
          maximo=axlMKSConvert(maximo unidades "millimeters")
          printf("PCB: %s / %s / %s: ancho min %.3f; max %.3f mm (0=sin limite); perfil %.3f mm.\n"
            red->name regla capa minimo maximo esperado)
          when(abs(minimo-esperado)>0.00001 || (maximo!=0 && abs(maximo-esperado)>0.00001)
            problemas=problemas+1
            printf("PCB: AVISO: la regla conservada difiere del perfil; no se modifica.\n"))
        else
          problemas=problemas+1
          printf("PCB: AVISO: no se puede verificar el ancho de %s / %s / %s.\n" red->name regla capa))))
    problemas
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

procedure(pcbAnchosViaCumple(ps padMM drillMM)
  let((unidades pad drill regular ancho alto cumple)
    unidades = car(axlDBGetDesignUnits())
    pad = axlMKSConvert(padMM "millimeters" unidades)
    drill = axlMKSConvert(drillMM "millimeters" unidades)
    cumple=equal(ps->holeType "CIRCLE_DRILL") && equal(ps->plating "PLATED") &&
      abs(ps->drillDiameter-drill)<0.0000001
    foreach(capa axlSubclassRoute()
      regular=car(setof(p ps->pads equal(p->type "REGULAR") &&
        equal(car(last(parseString(upperCase(p->layer) "/"))) upperCase(capa))))
      if(regular then
        ancho=xCoord(cadr(regular->bBox))-xCoord(car(regular->bBox))
        alto=yCoord(cadr(regular->bBox))-yCoord(car(regular->bBox))
        unless(equal(regular->figureName "CIRCLE") &&
          abs(xCoord(regular->offset))<0.0000001 && abs(yCoord(regular->offset))<0.0000001 &&
          abs(ancho-pad)<0.0000001 && abs(alto-pad)<0.0000001 cumple=nil)
      else cumple=nil))
    cumple
  )
)

procedure(pcbAnchosAuditarVias()
  prog((vistas total incorrectas pad drill nombre)
    total = 0
    incorrectas = 0
    foreach(red axlDBGetDesign()->nets
      foreach(rama axlDBRefreshId(red)->branches
        foreach(obj axlDBRefreshId(rama)->children
          when(equal(obj->objType "via") && !member(obj vistas)
            vistas = cons(obj vistas)
            total = total + 1
            if(pcbEsRedPotencia(red->name) then
              pad = pcbPowerViaPadMM drill = pcbPowerViaDrillMM
            else
              pad = pcbSignalViaPadMM drill = pcbSignalViaDrillMM)
            nombre = obj->definition->name
            unless(pcbAnchosViaCumple(obj->definition pad drill)
              incorrectas = incorrectas + 1
              printf("PCB: AVISO VIA: red %s usa %s en %L; esperada %.2f/%.2f mm.\n"
                red->name nombre obj->xy pad drill))
          )
        )
      )
    )
    printf("PCB: vias existentes revisadas: %d; fuera de la regla prevista: %d.\n"
      total incorrectas)
    return(incorrectas)
  )
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
  prog((normales potencia omitidas omitidasPotencia viaSenal viaPotencia destino avisos)
    unless(axlDBGetDesign() printf("PCB: no hay placa abierta.\n") return(nil))
    unless(pcbSignalWidthMM > 0 && pcbPowerWidthMM > 0
      error("PCB: los anchos deben ser positivos."))
    normales = 0 potencia = 0 omitidas = 0 omitidasPotencia = 0 avisos=0
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
        when(pcbEsRedPotencia(red->name) omitidasPotencia = omitidasPotencia + 1)
        printf("PCB: se conserva la regla especial de %s.\n" red->name)
        avisos=avisos+pcbAnchosRevisarReglas(red)
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
    when(omitidasPotencia > 0
      printf("PCB: %d redes de potencia se cuentan como omitidas porque conservan una regla especial.\n"
        omitidasPotencia))
    pcbAnchosAuditarVias()
    pcbAnchosLastRuleWarnings=avisos
    printf("PCB: avisos de reglas conservadas: %d.\n" avisos)
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

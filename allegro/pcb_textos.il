; Reference text style is configurable in pcb_config.il.
procedure(pcbSilkCrearBloque()
  prog((bloque unidades nombre estilo ancho alto trazo charSpace lineSpace)
    unless(pcbTextHeightMM > 0 && pcbTextWidthMM > 0 && pcbTextStrokeMM > 0 &&
      pcbTextCharSpaceMM >= 0 && pcbTextLineSpaceMM >= 0
      error("PCB: dimensiones de texto no validas."))
    unidades = car(axlDBGetDesignUnits())
    ancho = axlMKSConvert(pcbTextWidthMM "millimeters" unidades)
    alto = axlMKSConvert(pcbTextHeightMM "millimeters" unidades)
    trazo = axlMKSConvert(pcbTextStrokeMM "millimeters" unidades)
    charSpace = axlMKSConvert(pcbTextCharSpaceMM "millimeters" unidades)
    lineSpace = axlMKSConvert(pcbTextLineSpaceMM "millimeters" unidades)
    ; Allegro 17.2 rejects long text-block comments. Use compact micrometer
    ; dimensions, check the naming result and never silently create duplicates.
    nombre = sprintf(nil "PCB_S_%d_%d_%d_%d_%d"
      fix(pcbTextHeightMM*1000+0.5) fix(pcbTextWidthMM*1000+0.5)
      fix(pcbTextStrokeMM*1000+0.5) fix(pcbTextCharSpaceMM*1000+0.5)
      fix(pcbTextLineSpaceMM*1000+0.5))
    bloque = axlDBTextBlockFindName(nombre)
    when(bloque
      estilo = axlGetParam(sprintf(nil "paramTextBlock:%d" bloque))
      unless(estilo && abs(estilo->height-alto) < 0.0000001 &&
        abs(estilo->width-ancho) < 0.0000001 && abs(estilo->photoWidth-trazo) < 0.0000001 &&
        abs(estilo->charSpace-charSpace) < 0.0000001 && abs(estilo->lineSpace-lineSpace) < 0.0000001
        error("PCB: existe un bloque con nombre reservado y dimensiones distintas: %s" nombre)))
    unless(bloque
      bloque = axlDBTextBlockCreate(1 ?width ancho ?height alto ?photoWidth trazo
        ?charSpace charSpace ?lineSpace lineSpace)
      when(bloque
        unless(axlDBTextBlockSetName(bloque nombre)
          error("PCB: no se pudo nombrar el bloque de texto %s." nombre))))
    return(bloque)
  )
)

procedure(pcbSilkCapaDestino(simbolo)
  if(simbolo->isMirrored then
    "REF DES/SILKSCREEN_BOTTOM"
  else
    "REF DES/SILKSCREEN_TOP"
  )
)

procedure(pcbSilkProcesar(aplicar)
  prog((diseno bloque componente simbolo refdes textos texto
       capaDestino referencias otros conservar
       nComponentes nMovidos nFormato nDuplicados nValores nSinRef)

    diseno = axlDBGetDesign()
    if(diseno == nil then
      printf("\nPCB: No hay ningun diseno abierto.\n")
      nil
    else
      nComponentes = 0
      nMovidos = 0
      nFormato = 0
      nDuplicados = 0
      nValores = 0
      nSinRef = 0

      if(aplicar then
        bloque = pcbSilkCrearBloque()
        unless(bloque
          printf("\nPCB: No se pudo crear o encontrar el bloque de texto configurado.\n")
          return(nil)
        )
      )

      foreach(componente diseno->components
        simbolo = componente->symbol
        when(simbolo
          nComponentes = nComponentes + 1
          refdes = componente->name
          capaDestino = pcbSilkCapaDestino(simbolo)
          textos = axlDBGetAttachedText(simbolo)
          referencias = nil
          otros = nil

          foreach(texto textos
            if(texto->text == refdes then
              referencias = cons(texto referencias)
            else
              otros = cons(texto otros)
            )
          )

          if(referencias == nil then
            nSinRef = nSinRef + 1
            printf("PCB: AVISO: %s no tiene texto de referencia asociado.\n" refdes)
          else
            ; Prioriza una referencia que ya este en la capa correcta.
            conservar = nil
            foreach(texto referencias
              when(texto->layer == capaDestino
                unless(conservar conservar = texto)
              )
            )
            unless(conservar conservar = car(referencias))

            unless(conservar->layer == capaDestino
              nMovidos = nMovidos + 1
              when(aplicar axlChangeLayer(conservar capaDestino))
            )

            nFormato = nFormato + 1
            when(aplicar axlDBChangeText(conservar nil bloque))

            foreach(texto referencias
              unless(texto == conservar
                nDuplicados = nDuplicados + 1
                when(aplicar axlDeleteObject(texto))
              )
            )
          )

          ; Los textos asociados que no coinciden con el refdes son valores
          ; o nombres de dispositivo. Los graficos del footprint no entran aqui.
          foreach(texto otros
            when(pcbTextRemoveValues nValores = nValores + 1)
            when(aplicar && pcbTextRemoveValues axlDeleteObject(texto))
          )
        )
      )

      if(aplicar then
        printf("\nPCB: limpieza de textos aplicada.\n")
      else
        printf("\nPCB: auditoria de textos; no se ha modificado el diseno.\n")
      )
      printf("PCB: componentes colocados revisados: %d\n" nComponentes)
      printf("PCB: referencias a mover a silkscreen: %d\n" nMovidos)
      printf("PCB: referencias: %d; alto %.3f / ancho %.3f / trazo %.3f mm.\n" nFormato pcbTextHeightMM pcbTextWidthMM pcbTextStrokeMM)
      printf("PCB: referencias duplicadas a eliminar: %d\n" nDuplicados)
      printf("PCB: textos de valor/dispositivo a eliminar: %d\n" nValores)
      printf("PCB: componentes sin referencia asociada: %d\n" nSinRef)
      if(aplicar then
        printf("PCB: el diseno NO se ha guardado; revisalo y usa File > Save.\n")
      else
        printf("PCB: si el informe es correcto, ejecuta pcb_textos.\n")
      )
      return(t)
    )
  )
)

procedure(pcbSilkAuditar()
  pcbSilkProcesar(nil)
)

procedure(pcbSilkAplicar()
  prog((tx resultado)
    unless(axlDBGetDesign() return(nil))
    tx = axlDBTransactionStart()
    unless(tx error("No se pudo iniciar la transaccion de textos."))
    resultado = errset(pcbSilkProcesar(t) t)
    if(resultado && car(resultado) then
      axlDBTransactionCommit(tx) return(t)
    else
      axlDBTransactionRollback(tx)
      printf("PCB: textos cancelados y revertidos.\n") return(nil))
  )
)

procedure(pcbSilkRefdesPresentes(nombre)
  let((textos)
    foreach(obj append(list(axlDBGetDesign()) axlDBGetDesign()->symbols)
      foreach(txt axlDBGetAttachedText(obj)
        when(equal(txt->text nombre) textos=cons(txt textos))))
    textos
  )
)

procedure(pcbSilkFaltantesProcesar(aplicar)
  let((faltan omitidas creadas bloque sym ref orient textos)
    faltan=0 omitidas=0 creadas=0
    when(aplicar bloque=pcbSilkCrearBloque())
    foreach(comp axlDBGetDesign()->components
      sym=comp->symbol ref=comp->name
      when(sym && !setof(txt axlDBGetAttachedText(sym) equal(txt->text ref))
        faltan=faltan+1
        if(pcbSilkRefdesPresentes(ref) || assoc('FIXED axlDBGetProperties(sym)) then
          omitidas=omitidas+1
          printf("PCB REF: OMITIDA %s: existe texto en otro objeto o el simbolo esta fijo; revisar manualmente.\n" ref)
        else
          printf("PCB REF: %s en origen %L, capa %s; REQUIERE colocar el texto manualmente.\n"
            ref sym->xy pcbSilkCapaDestino(sym))
          when(aplicar
            orient=make_axlTextOrientation(?textBlock sprintf(nil "%d" bloque)
              ?rotation 0.0 ?mirrored sym->isMirrored ?justify "center")
            unless(axlDBCreateText(ref sym->xy orient pcbSilkCapaDestino(sym) sym)
              error("PCB: no se pudo crear la referencia %s." ref))
            textos=setof(txt axlDBGetAttachedText(sym) equal(txt->text ref))
            unless(length(textos)==1 && equal(car(textos)->xy sym->xy) &&
              equal(car(textos)->layer pcbSilkCapaDestino(sym))
              error("PCB: la referencia nueva no quedo asociada correctamente a %s." ref))
            creadas=creadas+1))))
    printf("PCB REF: faltantes %d; omitidas %d; creadas %d. No se borra ni se mueve texto existente.\n"
      faltan omitidas creadas)
    if(aplicar then creadas else list(faltan omitidas))
  )
)

procedure(pcbSilkFaltantesAuditar() pcbSilkFaltantesProcesar(nil))
procedure(pcbSilkFaltantesWorker() pcbSilkFaltantesProcesar(t))
procedure(pcbSilkRecrear()
  prog((audit)
    audit=pcbSilkFaltantesAuditar()
    when(car(audit)==cadr(audit) return(t))
    return(pcbProyectoAplicar("referencias" 'pcbSilkFaltantesWorker))
  )
)

printf("\nPCB: script de textos cargado. Ejecuta primero pcb_textos_auditar.\n")

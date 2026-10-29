; Load this file, then: skill pcbCargar("C:/SPB_Data/pcbenv/pcb_tools")
procedure(pcbCargar(carpeta @optional forzar)
  prog((resultado firmas ruta archivos)
    ruta=if(rexMatchp("^[A-Za-z]:/" carpeta) || rexMatchp("^/" carpeta)
      then carpeta else strcat(getWorkingDir() "/" carpeta))
    archivos='("pcb_config.il" "pcb_proyecto.il" "pcb_anchos.il" "pcb_textos.il"
      "pcb_mascara.il" "pcb_vias.il" "pcb_fabricacion.il" "pcb_comandos.il")
    foreach(archivo append(archivos '("pcb_local.il" "pcb_empaquetar.ps1"))
      firmas=cons(list(archivo when(isFile(strcat(ruta "/" archivo))
        fileTimeModified(strcat(ruta "/" archivo)))) firmas))
    when(!forzar && boundp('pcbToolsRoot) && equal(ruta pcbToolsRoot) &&
      boundp('pcbToolsLoadedSignatures) && equal(firmas pcbToolsLoadedSignatures) &&
      boundp('pcbToolsVersion) && equal(pcbToolsVersion "0.3.0")
      pcbInstalarComandos()
      pcbUtilidadesInfo()
      printf("PCB: carga existente verificada; sin redefinir funciones. pcb_recargar fuerza la actualizacion.\n")
      return(t))
    pcbToolsRoot = if(rexMatchp("^[A-Za-z]:/" carpeta) || rexMatchp("^/" carpeta)
      then carpeta else strcat(getWorkingDir() "/" carpeta))
    pcbToolsVersion = "0.3.0"
    load(strcat(pcbToolsRoot "/pcb_config.il"))
    load(strcat(pcbToolsRoot "/pcb_proyecto.il"))
    when(isFile(strcat(pcbToolsRoot "/pcb_local.il"))
      load(strcat(pcbToolsRoot "/pcb_local.il")))
    foreach(archivo '("pcb_anchos.il" "pcb_textos.il" "pcb_mascara.il" "pcb_vias.il" "pcb_fabricacion.il" "pcb_comandos.il")
      resultado = errset(load(strcat(pcbToolsRoot "/" archivo)) t)
      unless(resultado && car(resultado)
        error("PCB: no se pudo cargar %s. Revisa la ruta y los archivos." archivo))
    )
    pcbInstalarComandos()
    pcbToolsLoadedSignatures=firmas
    pcbUtilidadesInfo()
    return(t)
  )
)

procedure(pcbRecargar() pcbCargar(pcbToolsRoot t))

procedure(pcbUtilidadesInfo()
  ; GUI output must not depend on printf's buffered output port.
  axlUIWPrint(nil "PCB: utilidades %s cargadas desde %s" pcbToolsVersion pcbToolsRoot)
  axlUIWPrint(nil "PCB: comandos pcb_textos / pcb_mascara / pcb_anchos / pcb_fab_exportar.")
  axlUIWPrint(nil "PCB: primero usa sus auditorias. Cargar no modifica la placa.")
  t
)

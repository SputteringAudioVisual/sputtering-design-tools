; Set up capture, then invoke real commands from an Allegro .scr, not callbacks.
pcbDispatchOriginalPoport=poport
pcbDispatchOriginalErrport=errport
pcbDispatchOutput=outfile("dispatch_output.txt" "w")
poport=pcbDispatchOutput
errport=pcbDispatchOutput
procedure(pcbDispatchMarker(message)
  printf("DISPATCH_MARKER %s\n" message)
  drain(pcbDispatchOutput)
  t
)
procedure(pcbDispatchFinish()
  let((f normal mapped)
    foreach(net axlDBGetDesign()->nets
      when(equal(cadr(assoc('PHYSICAL_CONSTRAINT_SET axlDBGetProperties(net))) "PCB_SIGNAL")
        mapped=cons(net->name mapped)))
    printf("DISPATCH_RESULT signal_nets=%d\n" length(mapped))
    foreach(pair '(("pcb_utilidades_info" "skill pcbUtilidadesInfo()")
      ("pcb_mascara" "skill pcbMaskApply()")
      ("pcb_mascara_revisar" "skill pcbMaskAudit()")
      ("pcb_anchos" "skill pcbAplicarAnchos()")
      ("pcb_anchos_auditar" "skill pcbAnchosAuditar()"))
      unless(equal(axlGetAlias(car(pair)) cadr(pair)) error("Invalid command alias %s" car(pair)))
      when(assoc(car(pair) axlCmdList()) error("Stale command registration %s" car(pair))))
    printf("DISPATCH_ALIASES_OK t\n")
    poport=pcbDispatchOriginalPoport
    errport=pcbDispatchOriginalErrport
    close(pcbDispatchOutput)
    t
  )
)
pcbDispatchMarker("SETUP")

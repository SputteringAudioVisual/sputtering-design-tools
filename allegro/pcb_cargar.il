; Single supported entrypoint for the standard Windows installation.
pcbToolsLoadRoot="C:/SPB_Data/pcbenv/pcb_tools"
unless(isCallable('pcbCargar) && boundp('pcbToolsBootstrapTime) &&
  equal(pcbToolsBootstrapTime fileTimeModified(strcat(pcbToolsLoadRoot "/pcb_utilidades.il")))
  load(strcat(pcbToolsLoadRoot "/pcb_utilidades.il"))
  pcbToolsBootstrapTime=fileTimeModified(strcat(pcbToolsLoadRoot "/pcb_utilidades.il")))
pcbCargar(pcbToolsLoadRoot)

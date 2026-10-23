; Legacy command names forward to the one general implementation.
; No project-specific configuration is loaded by these aliases.
axlCmdRegister("fx_textos_auditar" 'pcbSilkAuditar)
axlCmdRegister("fx_textos" 'pcbSilkAplicar)
axlCmdRegister("fx_anchos_auditar" 'pcbAnchosAuditar)
axlCmdRegister("fx_anchos" 'pcbAplicarAnchos)
axlCmdRegister("fx_mascara_revisar" 'pcbMaskAudit ?cmdType "general")
axlCmdRegister("fx_mascara_auditar" 'pcbMaskAudit ?cmdType "general")
axlCmdRegister("fx_mascara" 'pcbMaskApply ?cmdType "general")
axlCmdRegister("pcb_mascara_auditar" 'pcbMaskAudit ?cmdType "general")
axlCmdRegister("fx_fab_auditar" 'pcbFabAuditar)
axlCmdRegister("fx_fab_configurar" 'pcbFabConfigurar)
axlCmdRegister("fx_fab_exportar" 'pcbFabExportar)

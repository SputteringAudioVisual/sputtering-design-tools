; Read-only smoke test for the unbuffered information entrypoint.
procedure(pcbInfoCheck()
  let((f)
    unless(equal(axlGetAlias("pcb_info") "skill pcbUtilidadesInfo()") error("pcb_info alias missing"))
    unless(equal(axlGetAlias("pcb_utilidades_info") "skill pcbUtilidadesInfo()") error("legacy info alias missing"))
    unless(equal(pcbToolsVersion "0.2.2") error("wrong version"))
    unless(pcbUtilidadesInfo() error("info failed"))
    f=outfile("info_check.txt" "w")
    fprintf(f "INFO_ALIASES_PASS %s\n" pcbToolsVersion)
    close(f)
    t
  )
)

; Integration test: launch Allegro from a directory OUTSIDE the board project.
; Test setup must define pcbTestPackageRoot before loading this file.
pcbTestOriginalPoport=poport
pcbTestOriginalErrport=errport
pcbTestCapturedOutput=outfile("native_output.txt" "w")
poport=pcbTestCapturedOutput
errport=pcbTestCapturedOutput
procedure(pcbZipTestLog(tag value)
  let((f) f=outfile("project_zip_test.txt" "a") fprintf(f "%s %L\n" tag value) close(f))
)
procedure(pcbZipAssert(value message) unless(value error("TEST: %s" message)))
procedure(pcbZipProjectTest()
  prog((proyecto launch a b cfg result)
    when(boundp('pcbTestAutoloadValid)
      pcbZipTestLog("AUTOLOAD" pcbTestAutoloadValid)
      pcbZipAssert(pcbTestAutoloadValid "central installation must load at startup"))
    load(strcat(pcbTestPackageRoot "/pcb_cargar.il"))
    changeWorkingDir(pcbTestLaunchDirectory)
    proyecto=pcbProyectoDirectorio()
    launch=getWorkingDir()
    pcbZipTestLog("PROJECT" proyecto)
    pcbZipAssert(!equal(proyecto launch) "launch cwd must be outside project")
    pcbZipAssert(pcbMaskAudit() "mask audit")
    pcbZipAssert(isFile(strcat(proyecto "/pcb_mascara_revision.txt")) "audit must be inside project")
    pcbZipAssert(!isFile(strcat(launch "/pcb_mascara_revision.txt")) "audit leaked into launch cwd")
    pcbZipAssert(pcbMaskApply() "mask correction")
    pcbZipAssert(isFile(strcat(proyecto "/Copias_seguridad/input_antes_mascara_v001.brd")) "backup must be inside project")
    pcbZipAssert(equal(launch getWorkingDir()) "mask must restore launch cwd")
    pcbZipAssert(equal(proyecto pcbProyectoDirectorio()) "backup must preserve active board path")
    pcbZipTestLog("LAYERS" axlSubclassRoute())
    pcbZipTestLog("FAB_AUDIT" pcbFabAuditar())
    a=pcbFabExportar()
    pcbZipTestLog("FIRST_ZIP" a)
    pcbZipAssert(a && isFile(a) && rexMatchp("_v001.zip$" a) "first versioned ZIP")
    pcbZipAssert(equal(launch getWorkingDir()) "launch cwd restored")
    cfg=strcat(car(pcbFabLastResult) "/config_utilidades.il")
    pcbTextHeightMM=1.20
    load(cfg)
    pcbZipAssert(abs(pcbTextHeightMM-0.79)<0.0000001 "configuration snapshot is loadable")
    b=pcbFabExportar()
    pcbZipTestLog("SECOND_ZIP" b)
    pcbZipAssert(b && isFile(b) && rexMatchp("_v002.zip$" b) "second versioned ZIP")
    pcbZipAssert(isFile(a) "first ZIP preserved")
    pcbFabOutputSubdir="../fuera"
    result=errset(pcbFabExportar() nil)
    pcbZipAssert(!result "parent traversal must be refused")
    pcbFabOutputSubdir="C:/outside"
    result=errset(pcbFabExportar() nil)
    pcbZipAssert(!result "absolute output must be refused")
    pcbFabOutputSubdir="Fabricacion"
    pcbZipTestLog("ALL_PASS" t)
    return(t)
  )
)
pcbZipTestLog("BEGIN" t)
pcbZipTestLog("RESULT" errset(pcbZipProjectTest() t))
poport=pcbTestOriginalPoport
errport=pcbTestOriginalErrport
close(pcbTestCapturedOutput)

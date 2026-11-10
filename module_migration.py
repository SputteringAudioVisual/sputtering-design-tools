"""Consolidate existing module work by verified copying, retaining old originals."""
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import zipfile
from module_project import (INDEX,create,read,write,local,digest,record_save,stage_path,verify,locked)


def consolidate(panel,artwork,destination,pcb_packages=()):
    from pcb_project import load_project
    from silkscreen_project import load,save
    panel,artwork,destination=Path(panel).resolve(),Path(artwork).resolve(),Path(destination).resolve()
    document=load_project(panel);load(artwork)  # Validate references before creating anything.
    if destination.exists():raise ValueError('La carpeta de destino ya existe; no se sobrescribe un módulo.')
    documents=[panel,*artwork.parent.glob('*.silk.json')]
    before={str(p):digest(p.read_bytes()) for p in documents}
    # Build alongside destination; a failed copy never publishes a partial module.
    destination.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(prefix='.module-import-',dir=destination.parent) as temp:
        root=Path(temp)/'module'
        shutil.copytree(panel.parent,root,ignore=shutil.ignore_patterns('.module.lock',INDEX,'versiones','modulo.trasladado.json'))
        new_panel=root/panel.name
        document.save(new_panel,track=False)
        meta=json.loads((root/'project.json').read_text(encoding='utf-8'))
        create(root,destination.name,new_panel,Path(meta['source_board']).name)
        record_save(new_panel,'panel')
        art_root=root/'arte_frontal';art_root.mkdir()
        for name in ('assets','fabricacion'):
            if (artwork.parent/name).exists():shutil.copytree(artwork.parent/name,art_root/name)
        new_art=stage_path(root,'panel_artwork')
        ordered=sorted(artwork.parent.glob('*.silk.json'),key=lambda p:p.stat().st_mtime)
        ordered=[p for p in ordered if p!=artwork]+[artwork]
        for original in ordered:
            refs,state,views,source,view=load(original)
            clean={k:v for k,v in state.items() if not k.startswith('_')}
            save(new_art,refs,clean,views,source,view)
        # Establish a PCB editing stage even if no original image session was
        # saved. Historic manufactured ZIPs are retained without inventing it.
        from panel_model import PanelDocument
        pcb_path=stage_path(root,'pcb_silkscreen');pcb_path.parent.mkdir()
        state=dict(schema='sputtering.image-session.v1',enabled=False)
        old_session=root/'image_session.json'
        if old_session.exists():
            state=json.loads(old_session.read_text(encoding='utf-8'))
            for key in ('image','svg'):
                if state.get(key):
                    src=local(root,state[key]);dst=local(pcb_path.parent,state[key]);dst.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(src,dst)
        from pcb_project import fabrication_source
        pcb_source=fabrication_source(new_panel);pcb_refs=PanelDocument.load(new_panel).layers
        flattened=False
        if not old_session.exists():
            candidates=[]
            for candidate in pcb_packages:
                with zipfile.ZipFile(candidate) as z:
                    m=json.loads(z.read('manifest.json')) if 'manifest.json' in z.namelist() else {}
                    if m.get('source_sha256')==meta['fabrication_sha256'] and m.get('changes'):
                        valid=all(digest(z.read(item['name']))==item['sha256'] for item in m.get('files',[]))
                        if valid:candidates.append(Path(candidate))
            if candidates:
                pcb_source=max(candidates,key=lambda p:p.stat().st_mtime)
                from panel_model import load_references
                pcb_refs,errors=load_references([pcb_source])
                if errors:raise ValueError('; '.join(errors))
                flattened=True
        save(pcb_path,pcb_refs,state,{},pcb_source)
        # Current artwork exports and loose generated layers stay together.
        output=root/'exports'/'arte_frontal';output.mkdir(parents=True,exist_ok=True)
        for file in (artwork.parent/'exports'/'serigrafia').iterdir():
            if file.is_file():shutil.copy2(file,output/file.name)
        historical=root/'historial_importado'/'fabricacion_pcb';historical.mkdir(parents=True)
        for package in pcb_packages:
            package=Path(package);target=historical/package.name
            if target.exists() and target.read_bytes()!=package.read_bytes():raise ValueError('Paquetes históricos con nombres duplicados.')
            shutil.copy2(package,target)
        # Register every package byte-for-byte. Old exports do not have an
        # editing revision ID: mark that explicitly instead of guessing one.
        packages=list(root.rglob('*.zip'));by_hash={digest(p.read_bytes()):p.relative_to(root).as_posix() for p in packages}
        imported=[]
        for file in packages:
            if 'exports' not in file.parts and 'historial_importado' not in file.parts:continue
            with zipfile.ZipFile(file) as archive:
                if archive.testzip():raise ValueError('ZIP histórico dañado: '+file.name)
                manifest=json.loads(archive.read('manifest.json')) if 'manifest.json' in archive.namelist() else {}
                mismatches=[]
                for entry in manifest.get('files',[]):
                    try:raw=archive.read(entry['name'])
                    except KeyError:mismatches.append(entry['name']);continue
                    if digest(raw)!=entry['sha256']:mismatches.append(entry['name'])
            stage='panel_artwork' if output in file.parents else 'panel' if file.parent.name=='frontal' else 'pcb_silkscreen'
            record=dict(path=file.relative_to(root).as_posix(),sha256=digest(file.read_bytes()),
                created_utc=datetime.fromtimestamp(file.stat().st_mtime,timezone.utc).isoformat(),
                lineage=dict(module_id=read(root)['id'],stage=stage,revision=None),
                details=dict(imported=True,original_manifest_mismatches=mismatches))
            source_hash=manifest.get('source_sha256')
            if source_hash in by_hash:record['source']=dict(path=by_hash[source_hash],sha256=source_hash)
            imported.append(record)
        for file in (root/'exports').rglob('*'):
            if not file.is_file() or file.suffix.lower()=='.zip':continue
            stage='panel_artwork' if output in file.parents else 'panel' if (root/'exports'/'frontal') in file.parents else 'pcb_silkscreen'
            record=dict(path=file.relative_to(root).as_posix(),sha256=digest(file.read_bytes()),
                created_utc=datetime.fromtimestamp(file.stat().st_mtime,timezone.utc).isoformat(),
                lineage=dict(module_id=read(root)['id'],stage=stage,revision=None),details=dict(imported=True,type='loose_output'))
            sibling=file.with_suffix('.zip')
            if sibling.exists():record['source']=dict(path=sibling.relative_to(root).as_posix(),sha256=digest(sibling.read_bytes()))
            imported.append(record)
        with locked(root):
            data=read(root);data['artifacts'].extend(imported)
            if flattened:data['stages']['pcb_silkscreen']['note']='Imagen integrada en los Gerber del último ZIP; no existía su sesión editable original.'
            write(root,data)
        report=dict(schema='sputtering.module-migration.v1',sources=before,
                    documents=dict(panel=new_panel.name,panel_artwork=new_art.relative_to(root).as_posix()),
                    imported_packages=len(packages),registered_outputs=len(imported),missing_original_pcb_image_session=not old_session.exists(),
                    validation=verify(root))
        from panel_model import atomic_write
        atomic_write(root/'MIGRACION.json',json.dumps(report,ensure_ascii=False,indent=2))
        atomic_write(root/'LEEME.md','# '+destination.name+'\n\n'
            'Abre modulo.module.json desde cualquiera de las dos apps.\n'
            'Frontal: '+new_panel.name+'\nImagen del frontal: arte_frontal/frontal.silk.json\n'
            'Serigrafía PCB: serigrafia_pcb/pcb.silk.json\n\n'
            'exports/frontal: panel sin foto. exports/arte_frontal: panel con imagen.\n'
            'exports/serigrafia: PCB de componentes. versiones: guardados numerados.\n'
            'historial_importado: paquetes previos, sin atribuirles una revisión editable inexistente.\n'
            'Puedes mover la carpeta completa; todas las referencias necesarias son relativas.\n')
        # Old launchers assumed the ChatGPT workspace layout; replace their
        # content with a pointer rather than leaving a broken executable.
        app_folder=Path(__file__).resolve().parent
        for filename,entry,project in [('ABRIR_FRONTAL.pyw','PanelEditor',new_panel.relative_to(root)),
                ('ABRIR_SERIGRAFIA_PCB.pyw','DesignToolsApp',pcb_path.relative_to(root)),
                ('ABRIR_IMAGEN_FRONTAL.pyw','DesignToolsApp',new_art.relative_to(root))]:
            module='panel_editor' if entry=='PanelEditor' else 'design_app'
            atomic_write(root/filename,'from pathlib import Path\nimport sys\n'
                f'sys.path.insert(0,{str(app_folder)!r})\nfrom {module} import {entry}\n'
                f'{entry}(project=Path(__file__).parent/{project.as_posix()!r}).mainloop()\n')
        atomic_write(root/'ABRIR_PROYECTO.txt','Abre modulo.module.json desde cualquiera de las dos apps.\n'
            'La carpeta contiene PCB, frontal, imagen, versiones y exportaciones.\nConsulta LEEME.md y MIGRACION.json.\n')
        if any(digest(Path(p).read_bytes())!=h for p,h in before.items()):
            raise ValueError('Un proyecto cambió durante la copia. Vuelve a guardar y cerrar antes de trasladarlo.')
        root.rename(destination)
    return destination/INDEX


def redirect_old(old,target):
    """Leave a small routing record; originals remain a recoverable backup."""
    from panel_model import atomic_write
    old,target=Path(old).resolve(),Path(target).resolve()
    pointer=old.parent/'modulo.trasladado.json'
    data=json.loads(pointer.read_text(encoding='utf-8')) if pointer.exists() else dict(schema='sputtering.module-redirect.v1',projects={})
    data['projects'][old.name]=str(target)
    atomic_write(pointer,json.dumps(data,ensure_ascii=False,indent=2))
    atomic_write(old.parent/'TRASLADADO_A.txt','La edición continúa en:\n'+str(target)+'\n\nEsta carpeta se conserva como respaldo; los accesos directos abren la carpeta nueva.\n')


def resolve_redirect(path):
    path=Path(path).resolve();seen=set()
    while (path.parent/'modulo.trasladado.json').exists():
        if path in seen:raise ValueError('Redirección de proyecto circular.')
        seen.add(path)
        data=json.loads((path.parent/'modulo.trasladado.json').read_text(encoding='utf-8'))
        if data.get('schema')!='sputtering.module-redirect.v1':raise ValueError('Redirección de módulo no reconocida.')
        target=data['projects'].get(path.name)
        if not target:break
        path=Path(target)
        if not path.is_file():raise ValueError('El módulo se ha trasladado de nuevo. Abre su modulo.module.json desde la nueva carpeta.')
    return path

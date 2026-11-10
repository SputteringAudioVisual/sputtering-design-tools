"""Validate the package as one inventory; never trust matching layer names."""
import hashlib
import json
from pathlib import PurePosixPath
import re
import zipfile

MANUFACTURING={'.art','.gbr','.ger','.gto','.gbo','.gko','.gm1','.gtl','.gbl',
               '.gts','.gbs','.pho','.drl','.xln','.exc','.rou'}


def entry_name(entry):
    name=entry.get('path',entry.get('name'))
    if not isinstance(name,str) or not name or '\\' in name or ':' in name:
        raise ValueError('Ruta inválida en el manifiesto.')
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path)!=name:
        raise ValueError('Ruta inválida en el manifiesto: '+name)
    if 'name' in entry and entry['name']!=name:
        raise ValueError('Nombre y ruta discrepantes en el manifiesto: '+name)
    return name


def validate_manifest(payload,manifest,require_complete=False):
    if not isinstance(manifest,dict):raise ValueError('El manifiesto no es un objeto JSON.')
    if 'files' not in manifest:
        if require_complete:raise ValueError('Falta el inventario del manifiesto.')
        return []
    entries=manifest['files']
    if not isinstance(entries,list):raise ValueError('Inventario del manifiesto inválido.')
    seen=set();normalised=[]
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('Archivo de manifiesto inválido.')
        name=entry_name(entry)
        if require_complete and name=='manifest.json':raise ValueError('El manifiesto no puede inventariarse a sí mismo.')
        if name.casefold() in seen:raise ValueError('Archivo duplicado en el manifiesto: '+name)
        seen.add(name.casefold())
        sha=entry.get('sha256');size=entry.get('bytes')
        if not isinstance(sha,str) or not re.fullmatch('[0-9a-fA-F]{64}',sha) or type(size) is not int or size<0:
            raise ValueError('Suma o tamaño inválido en el manifiesto: '+name)
        raw=payload.get(name)
        if raw is None or len(raw)!=size or hashlib.sha256(raw).hexdigest().lower()!=sha.lower():
            raise ValueError('El archivo no coincide con el manifiesto: '+name)
        normalised.append(dict(entry,name=name,path=name))
    for name in payload:
        if name=='manifest.json':continue
        if name.casefold() not in seen and (require_complete or PurePosixPath(name).suffix.lower() in MANUFACTURING):
            raise ValueError('Archivo no declarado en el manifiesto; no se mezclan liberaciones: '+name)
    return normalised


def read_archive(path,require_complete=False):
    try:return _read_archive(path,require_complete)
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError) as error:
        raise ValueError('No se puede leer el paquete ZIP: '+str(error)) from error


def _read_archive(path,require_complete=False):
    with zipfile.ZipFile(path) as archive:
        explicit_directories=any(m.is_dir() for m in archive.infolist())
        members=[m for m in archive.infolist() if not m.is_dir()]
        if len(members)>2000 or sum(m.file_size for m in members)>200_000_000 or any(m.file_size>30_000_000 for m in members):
            raise ValueError('Paquete de fabricación demasiado grande.')
        seen=set();payload={}
        for member in members:
            name=entry_name({'path':member.filename})
            if name.casefold() in seen:raise ValueError('Archivo duplicado en el paquete: '+name)
            seen.add(name.casefold());payload[name]=archive.read(member)
    manifest=json.loads(payload['manifest.json'].decode('utf-8-sig')) if 'manifest.json' in payload else {}
    validate_manifest(payload,manifest,require_complete)
    if isinstance(manifest.get('schema'),str) and manifest['schema'].startswith('sputtering.fabrication.'):
        if explicit_directories:raise ValueError('Un paquete v1 no admite miembros directorio fuera del inventario.')
        from release_contract import validate_release
        validate_release(manifest,payload)
    return payload,manifest

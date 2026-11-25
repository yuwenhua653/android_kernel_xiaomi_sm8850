#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only ARM64 module CRC, provider, dependency and vermagic qualification.

Pass the matching kernel output and each already-built external module root.
Uses modules.order / Module.symvers; does not build, install or load modules.
This is not a signature, complete KMI, final-image or device-behavior check.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def cstring(data, offset=0):
    end = data.find(b'\0', offset)
    if end < 0:
        raise ValueError('unterminated ELF string')
    return data[offset:end].decode('utf-8')


def sections(data):
    if data[:6] != b'\x7fELF\x02\x01' or len(data) < 64:
        raise ValueError('expected little-endian ELF64')
    if struct.unpack_from('<HH', data, 16) != (1, 183):
        raise ValueError('expected relocatable ARM64 module')
    offset = struct.unpack_from('<Q', data, 40)[0]
    stride, count, strings = struct.unpack_from('<HHH', data, 58)
    if stride != 64 or offset + 64 > len(data):
        raise ValueError('invalid ELF section table')
    first = struct.unpack_from('<IIQQQQIIQQ', data, offset)
    count = count or first[5]
    strings = first[6] if strings == 0xffff else strings
    if offset + count * stride > len(data) or strings >= count:
        raise ValueError('section table outside file')
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i*stride)
               for i in range(count)]
    def contents(h):
        if h[1] == 8:  # SHT_NOBITS has no file payload.
            return b''
        start, length = h[4:6]
        if start + length > len(data):
            raise ValueError('section payload outside file')
        return data[start:start+length]
    names = contents(headers[strings])
    result = {}
    for h in headers[1:]:
        name = cstring(names, h[0])
        if name in result:
            raise ValueError('duplicate section '+name)
        result[name] = contents(h)
    return result


def versions(sec):
    result = {}
    def add(name, crc):
        if not name or name in result:
            raise ValueError('empty/duplicate version symbol '+name)
        result[name] = crc
    raw = sec.get('__versions')
    if raw is not None:
        if len(raw) % 64:
            raise ValueError('invalid ARM64 basic modversions record size')
        for i in range(0, len(raw), 64):
            crc = struct.unpack_from('<Q', raw, i)[0]
            if crc > 0xffffffff:
                raise ValueError('invalid 32-bit symbol CRC')
            add(cstring(raw[i+8:i+64]), crc)
    elif '__version_ext_crcs' in sec and '__version_ext_names' in sec:
        raw, names = sec['__version_ext_crcs'], sec['__version_ext_names']
        if len(raw) % 4 or not names.endswith(b'\0'):
            raise ValueError('invalid extended modversions sections')
        names = names[:-1].split(b'\0')
        if len(names) * 4 != len(raw):
            raise ValueError('extended modversions name/CRC count mismatch')
        for name, (crc,) in zip(names, struct.iter_unpack('<I', raw)):
            add(name.decode('utf-8'), crc)
    else:
        raise ValueError('missing symbol versions; require CONFIG_MODVERSIONS')
    if 'module_layout' not in result:
        raise ValueError('missing module_layout version')
    return result


def provider(name):
    return Path(name).name.replace('-', '_')


def audit(kernel_out, external_out):
    roots = [kernel_out, *external_out]
    exports, inputs, modules = {}, [], []
    for index, root in enumerate(roots):
        symvers = root/'Module.symvers'
        text = symvers.read_text()
        inputs.append({'root': 'kernel' if index == 0 else str(index)+':'+root.name,
                       'symvers_sha256': hashlib.sha256(text.encode()).hexdigest()})
        for row in text.splitlines():
            fields = row.split()
            if len(fields) < 4:
                raise ValueError('invalid symvers row in '+str(symvers))
            crc, name, owner = int(fields[0], 16), fields[1], provider(fields[2])
            if name in exports:
                raise ValueError('duplicate symbol provider: '+name)
            exports[name] = crc, owner
        for name in (root/'modules.order').read_text().splitlines():
            path = Path(name).with_suffix('.ko')
            path = path if path.is_absolute() else root/path
            modules.append(path)
    records, names, common_magic = [], set(), None
    for path in modules:
        data = path.read_bytes()
        sec = sections(data)
        info = {}
        for entry in sec['.modinfo'].split(b'\0'):
            if b'=' in entry:
                key, value = entry.decode().split('=', 1)
                info.setdefault(key, []).append(value)
        if len(info.get('name', [])) != 1 or len(info.get('vermagic', [])) != 1:
            raise ValueError('missing/ambiguous module identity: '+str(path))
        name, magic = info['name'][0], info['vermagic'][0]
        if name in names:
            raise ValueError('duplicate module identity '+name)
        names.add(name)
        common_magic = magic if common_magic is None else common_magic
        if magic != common_magic or ' modversions ' not in ' '+magic+' ':
            raise ValueError('module vermagic mismatch: '+name)
        imports = versions(sec)
        dependencies = {provider(dep) for dep in ','.join(info.get('depends', [])).split(',') if dep}
        required = set()
        for symbol, crc in imports.items():
            if symbol not in exports:
                raise ValueError('missing provider: '+name+' -> '+symbol)
            expected, owner = exports[symbol]
            if crc != expected:
                raise ValueError('CRC mismatch: '+name+' -> '+symbol)
            if owner not in ('vmlinux', name):
                required.add(owner)
        if not required <= dependencies:
            raise ValueError('missing declared dependencies: '+name+' -> '+str(sorted(required-dependencies)))
        records.append({'module':name, 'bytes':len(data),
                        'sha256':hashlib.sha256(data).hexdigest(),
                        'checked_versions':len(imports),
                        'dependencies':sorted(dependencies)})
    for record in records:
        missing = set(record['dependencies']) - names
        if missing:
            raise ValueError('missing built dependency: '+record['module']+' -> '+str(sorted(missing)))
    release = (kernel_out/'include/config/kernel.release').read_text().strip()
    if not common_magic or not common_magic.startswith(release+' '):
        raise ValueError('vermagic differs from kernel output release')
    return {'pass':True, 'scope':'ELF/CRC/provider/depends/vermagic only',
            'kernel_release':release, 'vermagic':common_magic,
            'module_count':len(records), 'export_count':len(exports),
            'version_records_checked':sum(r['checked_versions'] for r in records),
            'symvers_inputs':inputs, 'modules':records,
            'signature_checked':False, 'final_images_checked':False,
            'hardware_checked':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-out', required=True, type=Path)
    parser.add_argument('--external-out', action='append', default=[], type=Path)
    parser.add_argument('--json', type=Path, help='Optional report file')
    args = parser.parse_args()
    try:
        report = audit(args.kernel_out, args.external_out)
    except (OSError, ValueError, KeyError, struct.error) as exc:
        raise SystemExit('FAIL: '+str(exc))
    if args.json:
        args.json.write_text(json.dumps(report,indent=2)+'\n')
    print(f"PASS: {report['module_count']} modules, {report['version_records_checked']} symbol versions; providers, declared dependencies and vermagic match")
    print('Not a signature, complete KMI, final-image or hardware verification.')


if __name__ == '__main__':
    main()

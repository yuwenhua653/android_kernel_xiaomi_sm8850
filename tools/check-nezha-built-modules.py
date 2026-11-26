#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Audit actual ARM64 .ko dependencies/CRCs and Nezha source load lists.

Requires pyelftools. This checks a build directory, not packaged images,
module signatures, firmware, or runtime probe. No missing module is waived by
default; --host-c-binder explicitly permits only the host Rust Binder exception.
"""
import argparse
import json
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile


def norm(name):
    return Path(name).name.removesuffix('.ko').replace('-', '_')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--external', type=Path, action='append', default=[])
    ap.add_argument('--lists', type=Path, default=Path(__file__).resolve().parents[1] / 'android/nezha-native')
    ap.add_argument('--host-c-binder', action='store_true')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    errors, symbols, built, vermagics = [], {}, {}, set()
    roots = [args.out.resolve()] + [p.resolve() for p in args.external]
    paths = []
    for root in roots:
        for line in (root / 'Module.symvers').read_text().splitlines():
            crc, name, *_ = line.split()
            value = int(crc, 16)
            if name in symbols and symbols[name] != value:
                errors.append('conflicting export CRC: ' + name)
            symbols[name] = value
        for line in (root / 'modules.order').read_text().splitlines():
            p = Path(line).with_suffix('.ko')
            paths.append(p if p.is_absolute() else root / p)
    builtins = {norm(x) for x in (args.out / 'modules.builtin').read_text().splitlines()}
    checks = 0
    for path in paths:
        if not path.is_file():
            errors.append('missing build output: ' + str(path))
            continue
        with path.open('rb') as f:
            elf = ELFFile(f)
            if elf['e_machine'] != 'EM_AARCH64' or elf.elfclass != 64 or not elf.little_endian:
                errors.append('not little-endian ARM64: ' + str(path))
            sec = elf.get_section_by_name('.modinfo')
            info = dict(x.decode().split('=', 1) for x in sec.data().split(b'\0') if b'=' in x) if sec else {}
            name = info.get('name', norm(path))
            if name in built:
                errors.append('duplicate module: ' + name)
            built[name] = {'file': path.name, 'depends': info.get('depends', '').split(',')}
            vermagics.add(info.get('vermagic', ''))
            versions = elf.get_section_by_name('__versions')
            if not versions or versions.data_size % 64:
                errors.append('missing/invalid modversions: ' + path.name)
                continue
            for offset in range(0, versions.data_size, 64):
                data = versions.data()[offset:offset + 64]
                crc = struct.unpack_from('<Q', data)[0]
                symbol = data[8:].split(b'\0', 1)[0].decode()
                checks += 1
                if symbols.get(symbol) != crc:
                    errors.append(f'{path.name}: CRC/export mismatch for {symbol}')
    if len(vermagics) != 1 or '' in vermagics:
        errors.append('mixed or absent vermagic: ' + repr(sorted(vermagics)))
    for name, info in built.items():
        for dep in filter(None, info['depends']):
            if norm(dep) not in built and norm(dep) not in builtins:
                errors.append(f'{name}: missing dependency {dep}')
    lists, exceptions = {}, []
    for path in sorted(args.lists.glob('modules.*')):
        requested = [line.split('#', 1)[0].strip() for line in path.read_text().splitlines()]
        requested = [name for name in requested if name]
        missing = []
        for name in requested:
            if norm(name) in built or norm(name) in builtins:
                continue
            if args.host_c_binder and name == 'rust_binder.ko':
                exceptions.append(path.name + ':rust_binder.ko')
            else:
                missing.append(name)
        lists[path.name] = {'entries': len(requested), 'missing': missing}
        errors.extend(path.name + ': missing ' + name for name in missing)
    result = {'scope': 'build outputs only; not image/signature/runtime validation',
              'modules': len(built), 'kernel_modules': len((args.out / 'modules.order').read_text().splitlines()),
              'external_directories': len(args.external), 'crc_checks': checks,
              'vermagic': sorted(vermagics), 'load_lists': lists,
              'explicit_host_exceptions': exceptions, 'errors': errors}
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()

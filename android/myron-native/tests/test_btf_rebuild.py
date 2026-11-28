#!/usr/bin/env python3
"""Use GNU make on the production module rule to check BTF rebuild triggers."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
text = (root / 'scripts/Makefile.modfinal').read_text().replace('\\\n', ' ')
rule = next(line for line in text.splitlines() if line.startswith('%.ko:'))
with tempfile.TemporaryDirectory() as tmp:
    cwd = Path(tmp)
    (cwd / 'scripts').mkdir()
    inputs = ['test.o', 'test.mod.o', '.module-common.o', 'scripts/module.lds',
              'resolve_btfids', 'scripts/gen-btf.sh']
    for name in inputs + ['test.ko']:
        (cwd / name).touch()
        os.utime(cwd / name, (100, 100))
    os.utime(cwd / 'test.ko', (200, 200))
    for enabled in (False, True):
        (cwd / 'Makefile').write_text(
            'all: test.ko\nobjtree := .\nsrctree := .\n'
            'RESOLVE_BTFIDS := resolve_btfids\n'
            f'CONFIG_DEBUG_INFO_BTF_MODULES := {"y" if enabled else ""}\n'
            + rule + '\n\t@echo rebuilt > marker\n.PHONY: FORCE\nFORCE:\n')
        # FORCE causes the recipe to run in Kbuild, but Kbuild's newer_prereqs
        # filters it before deciding whether to relink/regenerate BTF.
        # Replace that phony sentinel with an old file for make -q scheduling.
        mf = cwd / 'Makefile'
        mf.write_text(mf.read_text().replace('.PHONY: FORCE\nFORCE:\n', ''))
        (cwd / 'FORCE').touch()
        os.utime(cwd / 'FORCE', (100, 100))
        def query():
            return subprocess.run(['make', '-q', 'all'], cwd=cwd).returncode
        assert query() == 0
        for name in ['resolve_btfids', 'scripts/gen-btf.sh']:
            os.utime(cwd / name, (300, 300))
            assert query() == int(enabled), (enabled, name)
            os.utime(cwd / name, (100, 100))
print('PASS: production module prerequisites track BTF tool/script only when BTF is enabled')

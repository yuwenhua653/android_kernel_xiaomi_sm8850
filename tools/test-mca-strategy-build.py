#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check actual Makefile selection; not a full Kconfig/ARM64 build."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[1]
mca=root/'drivers/power/supply/mca'
files=['mca_strategy/Makefile','mca_strategy/strategy_fg/Makefile','mca_strategy/strategy_charger/Makefile','mca_hardware_monitor/Makefile']
kconfig=(root/'drivers/power/supply/Kconfig').read_text();block=kconfig.split('config XIAOMI_MCA_STRATEGY_CLASS\n',1)[1].split('\nconfig ',1)[0]
assert 'depends on XIAOMI_MCA_CORE && TREE_SRCU' in block and 'default MYRON_MCA_SERVICES' in block
config=(root/'arch/arm64/configs/vendor/nezha_GKI.config').read_text()
assert 'CONFIG_XIAOMI_MCA_WIRED_STRATEGY=m' not in config
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp)/'Makefile';p.write_text(''.join('include '+str(mca/f)+'\n' for f in files)+'\nall:\n\t@echo $(obj-m)\n')
 def modules(services,complete,shared,bridge='n'):
  args=['make','-s','-f',str(p),'all','CONFIG_MYRON_MCA_SERVICES='+services,'CONFIG_MYRON_MCA_COMPLETE_SERVICES='+complete,'CONFIG_XIAOMI_MCA_STRATEGY_CLASS='+shared,'CONFIG_XIAOMI_MCA_NEZHA_FG_PSY='+bridge]
  return set(subprocess.check_output(args,text=True).split())
 regs={'mca_strategy_class.o','mca_strategy_fg_class.o'}
 guards={'mca_ibat_ocp_monitor.o','mca_vbat_ovp_monitor.o'}
 assert modules('n','n','m')==regs
 assert modules('n','n','m','m')==regs|{'mca_nezha_fg_psy.o'}
 partial=modules('m','n','m');assert regs|guards<=partial and 'mca_buckchg_jeita.o' not in partial
 full=modules('m','m','m');assert regs|guards|{'mca_buckchg_jeita.o','mca_strategy_buckchg.o','mca_strategy_fg_comp.o'}<=full
 assert not modules('n','n','n')
print('PASS: generic registry-only, legacy SERVICES-only and COMPLETE Makefile selection; Nezha policy remains gated')

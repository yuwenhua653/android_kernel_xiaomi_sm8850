#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual QC tuning/enable retry with injected backend errors and no-current case."""
from pathlib import Path
import os,runpy,subprocess,tempfile
c=runpy.run_path(str(Path(__file__).with_name('test-mca-wired-controls.py')));fn=c['fn']
extra=r'''
#define CP_MODE_FORWARD_2_1 2
#define XM_CHARGER_TYPE_HVDCP3_B 5
#define QC2_FORCE_5V 0
#define CP_PMID_ERROR_OK 0
#define CP_PMID_ERROR_LOW 1
#define CP_PMID_ERROR_HIGH 2
#define CHARGE_DFX_CP_OPEN_FAILED 1
#define QC_VBUS_TUNE_MS 3000
static int platform_class_cp_get_errorhl_stat(int r,int*out){(void)r;int ret=tick(TUNE);if(!ret)*out=CP_PMID_ERROR_OK;return ret;}
static int protocol_class_qc_set_volt_cmd(int port,int cmd){(void)port;(void)cmd;return tick(REQUEST);}
static void mca_charge_mievent_report(int e,int*p,int n){(void)e;(void)p;(void)n;}
'''
body=''.join(fn(n) for n in ['mca_quick_charge_blocked','mca_qc_quick_charge_update_ibus','mca_get_qc_vbus_tune_status','mca_qc_retry_to_enable_cp','mca_qc_quick_charge_open_path'])
test=c['test'][c['test'].index('static struct mca_votable'):c['test'].index('int main(void)')]+r'''
int main(void){struct mca_quick_charge_info i;
 setup(&i);vbus=8300;i.proc_data.adp_type=XM_CHARGER_TYPE_HVDCP3_B;assert(!mca_qc_quick_charge_open_path(&i)&&counts[ZERO]&&counts[IBUS]);int total=calls;
 for(int j=1;j<=total;j++){setup(&i);vbus=8300;fail_at=j;assert(mca_qc_quick_charge_open_path(&i)==-EIO);}
 setup(&i);vbus=8300;ibus=0;assert(mca_qc_quick_charge_open_path(&i)==-ETIMEDOUT&&counts[ENABLE]==2);
 setup(&i);i.abort_requested=true;assert(mca_qc_retry_to_enable_cp(&i)==-ECANCELED&&!calls);
 setup(&i);vbat=INT_MAX;assert(mca_qc_quick_charge_open_path(&i)==-ERANGE&&!counts[REQUEST]);
 setup(&i);fail_kind=VBUS;enum VBUS_TUNE_STAT state;assert(mca_get_qc_vbus_tune_status(&i,&state)==-EIO&&state==XM_VBUS_TUNE_INIT);
 puts("PASS: actual QC tuning/start I/O faults, sleep errno, zero-FCC before voltage, enabled-but-no-current timeout, abort, voltage overflow and tuner read failure");}
'''
with tempfile.TemporaryDirectory(prefix='mca-qc-start-') as d:
 p=Path(d);(p/'test.c').write_text(c['pre']+c['header']+c['constants']+c['stubs']+extra+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual final hardware quiesce: first errno, independent paths, no resume."""
from pathlib import Path
import os,runpy,subprocess,tempfile
c=runpy.run_path(str(Path(__file__).with_name('test-mca-wired-controls.py')))
fn=c['fn'];pre=c['pre'];header=c['header'];buck=(c['base']/'mca_strategy_buckchg.c').read_text()
stubs=r'''
#define AUX_BUCK_CHARGER 1
struct strategy_buckchg_dev {bool support_multi_buck;};
enum {FULL=1,SUSPEND,ZERO,CP0,CP1,ADC0,ADC1,FG,ICL0,ICL1,BUCK0,BUCK1,BADC0,BADC1};
static int fail1,fail2,counts[20],n;
static int tick(int k){n++;counts[k]++;return k==fail1?-EIO:k==fail2?-ETIMEDOUT:0;}
static int mca_quick_charge_stop_charging(struct mca_quick_charge_info*i){(void)i;return tick(FULL);}
static int mca_vote(struct mca_votable*v,const char*c,bool en,int val){(void)c;assert(en);return tick(val?SUSPEND:ZERO);}
static int platform_class_cp_set_charging_enable(int r,bool en){assert(!en);return tick(r?CP1:CP0);}
static int platform_class_cp_enable_adc(int r,bool en){assert(!en);return tick(r?ADC1:ADC0);}
static int strategy_class_fg_set_fastcharge(bool en){assert(!en);return tick(FG);}
static int platform_class_buckchg_ops_set_chg(int r,bool en){(void)en;return tick(r?BUCK1:BUCK0);}
static int platform_class_buckchg_ops_set_input_curr_lmt(int r,int val){assert(!val);return tick(r?ICL1:ICL0);}
static int platform_class_buckchg_ops_adc_enable(int r,bool en){assert(!en);return tick(r?BADC1:BADC0);}
'''
body=fn('mca_quick_charge_record_error')+fn('mca_quick_charge_quiesce_hardware')+fn('strategy_buckchg_quiesce_hardware',buck)+fn('strategy_class_buckchg_ops_set_chg',buck)
test=r'''
static void reset(void){fail1=fail2=n=0;memset(counts,0,sizeof(counts));}
int main(void){struct mca_quick_charge_info i={.cp_type=MCA_CP_TYPE_PARALLEL};struct strategy_buckchg_dev b={.support_multi_buck=true};
 reset();assert(!mca_quick_charge_quiesce_hardware(&i)&&counts[CP0]&&counts[CP1]&&counts[FG]&&counts[SUSPEND]&&counts[ZERO]);
 for(int k=FULL;k<=FG;k++){reset();fail1=k;assert(mca_quick_charge_quiesce_hardware(&i)==-EIO);assert(counts[CP0]&&counts[CP1]&&counts[FG]&&counts[SUSPEND]&&counts[ZERO]);if(k==CP0)assert(!counts[ADC0]);if(k==CP1)assert(!counts[ADC1]);}
 reset();fail1=FULL;fail2=CP1;assert(mca_quick_charge_quiesce_hardware(&i)==-EIO);
 for(int k=FG;k<=BADC1;k++){reset();fail1=k;assert(strategy_buckchg_quiesce_hardware(&b)==-EIO&&counts[ICL0]&&counts[ICL1]&&counts[BUCK0]&&counts[BUCK1]&&counts[FG]);}
 reset();b.support_multi_buck=false;assert(!strategy_buckchg_quiesce_hardware(&b)&&!counts[ICL1]&&!counts[BUCK1]&&!counts[BADC1]);
 b.support_multi_buck=true;reset();fail1=BUCK0;assert(strategy_class_buckchg_ops_set_chg(&b,true)==-EIO&&counts[BUCK0]==2&&counts[BUCK1]==1);
 reset();fail1=BUCK1;assert(strategy_class_buckchg_ops_set_chg(&b,true)==-EIO&&counts[BUCK0]==2&&counts[BUCK1]==2);
 reset();fail1=BUCK0;fail2=BUCK1;assert(strategy_class_buckchg_ops_set_chg(&b,false)==-EIO&&counts[BUCK0]==1&&counts[BUCK1]==1);
 puts("PASS: actual QC/Buck final quiesce across 14 failing operations, independent shutdown attempts, first errno, failed-pump ADC retained, single topology and Buck enable rollback");}
'''
with tempfile.TemporaryDirectory(prefix='mca-wired-quiesce-') as d:
 p=Path(d);(p/'test.c').write_text(pre+header+stubs+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

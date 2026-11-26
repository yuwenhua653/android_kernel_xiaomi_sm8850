#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise missing wireless profiles and FG forced-full decisions on failed reads."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root',required=True,type=Path)
p.add_argument('--wireless-source',type=Path)
p.add_argument('--fg-source',type=Path)
a=p.parse_args()
b=a.kernel_root/'drivers/power/supply/mca'
w=(a.wireless_source or b/'mca_strategy/strategy_wireless/mca_quick_wireless.c').read_text()
f=(a.fg_source or b/'mca_strategy/strategy_fg/mca_strategy_fg.c').read_text()
h=(b/'include/mca/strategy/strategy_class.h').read_text()
code=r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#define FG_IC_MASTER 0
#define STRATEGY_FG_DEFAULT_ITERM 300
#define STRATEGY_FG_DEFAULT_VTERM 4400
#define mca_log_info(...) ((void)0)
#define msecs_to_jiffies(v) (v)
'''
for n in ['mca_strategy_func_type','strategy_status_type','mca_quick_chg_status']:
    code+=re.search(r'enum '+n+r'\s*\{.*?\};',h,re.S)[0]+'\n'
code+=r'''
struct mca_wireless_quick_charge_volt_para { int voltage,current_max,current_min; };
struct mca_wireless_quick_charge_volt_para_info { int volt_para_size;struct mca_wireless_quick_charge_volt_para *volt_para; };
struct mca_wireless_quick_charge_info {
 int force_stop;
 struct { int charge_flag,enable_quickchg,cur_cp_mode,vbus,ibus;
 struct mca_wireless_quick_charge_volt_para_info *cur_volt_para[1]; } proc_data;
};
static int mca_wireless_quick_charge_select_max_ibat(struct mca_wireless_quick_charge_info *i) {(void)i;return 1000;}
'''+function(w,'mca_wireless_quick_charge_get_status')+r'''
struct strategy_fg {
 int voter_ok,iterm_voter,vterm_voter,batt_voltage,power_present,fast_charge,charging_done;
 int batt_current,start_force_full,force_report_full_work;
 struct { int terminated_by_cp; } cfg;
};
static int online=1,fail,quick_status,threshold=300,requests,work,limit=300,voltage=4400,cases;
static int mca_strategy_func_get_status(int type,int what,int *v) {
 (void)type;
 switch(what){
 case STRATEGY_STATUS_TYPE_ONLINE:*v=online;return fail==1?-EIO:0;
 case STRATEGY_STATUS_TYPE_QC_CHARGE_STS:*v=quick_status;return fail==2?-EIO:0;
 case STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM:*v=threshold;return fail==3?-ENODATA:0;
 default:assert(0);return -EINVAL;
 }
}
static int mca_get_effective_result(int voter) {return voter==1?limit:voltage;}
static void platform_fg_ops_set_force_report_full(int role) {assert(!role);requests++;}
static void schedule_delayed_work(int *w,int delay) {(void)w;assert(delay==8000);work++;}
'''+function(f,'mca_strategy_single_force_fw_report_full')+r'''
static void reset(struct strategy_fg *fg) {
 fail=1;mca_strategy_single_force_fw_report_full(fg);fail=0;requests=work=0;
 fg->start_force_full=0;
}
int main(void){
 struct mca_wireless_quick_charge_info info={0};int value=123;
 assert(mca_wireless_quick_charge_get_status(STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM,&value,&info)==-ENODATA && value==123);cases++;
 struct mca_wireless_quick_charge_volt_para_info v={0};info.proc_data.cur_volt_para[0]=&v;
 assert(mca_wireless_quick_charge_get_status(STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM,&value,&info)==-ENODATA && value==123);cases++;
 struct mca_wireless_quick_charge_volt_para rows[]={{4400,2000,300},{4500,1000,200}};
 v.volt_para=rows;v.volt_para_size=-1;
 assert(mca_wireless_quick_charge_get_status(STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM,&value,&info)==-ENODATA);cases++;
 v.volt_para_size=2;
 assert(!mca_wireless_quick_charge_get_status(STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM,&value,&info) && value==200);cases++;
 struct strategy_fg fg={.voter_ok=1,.iterm_voter=1,.vterm_voter=2,.batt_voltage=4400,
 .power_present=1,.fast_charge=1,.batt_current=-100000};
 for(online=0;online<=1;online++)for(int cp=0;cp<=1;cp++){
  fg.cfg.terminated_by_cp=cp;quick_status=cp?MCA_QUICK_CHG_STS_CHARGING:MCA_QUICK_CHG_STS_NO_CHARGING;
  for(int fault=1;fault<=(cp?3:2);fault++){
   reset(&fg);for(int n=0;n<5;n++)mca_strategy_single_force_fw_report_full(&fg);
   assert(!requests);fail=fault;
   for(int n=0;n<10;n++)mca_strategy_single_force_fw_report_full(&fg);
   assert(!requests && !fg.start_force_full);fail=0;
   for(int n=0;n<5;n++)mca_strategy_single_force_fw_report_full(&fg);
   assert(!requests);mca_strategy_single_force_fw_report_full(&fg);
   assert(requests==1 && work==1 && fg.start_force_full);cases++;
  }
 }
 fg.cfg.terminated_by_cp=1;quick_status=MCA_QUICK_CHG_STS_CHARGING;online=1;
 int invalid[]={-1,0,INT_MAX};
 for(unsigned int i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++){
  reset(&fg);threshold=invalid[i];
  for(int n=0;n<12;n++)mca_strategy_single_force_fw_report_full(&fg);
  assert(!requests);cases++;
 }
 threshold=300;
 for(int i=0;i<3;i++){
  reset(&fg);limit=invalid[i];
  for(int n=0;n<12;n++)mca_strategy_single_force_fw_report_full(&fg);
  assert(!requests);cases++;
 }
 limit=300;voltage=-EIO;reset(&fg);
 for(int n=0;n<12;n++)mca_strategy_single_force_fw_report_full(&fg);
 assert(!requests);cases++;
 printf("PASS: %d wireless profile/status and forced-full error cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src,exe=Path(tmp)/'test.c',Path(tmp)/'test'
    src.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

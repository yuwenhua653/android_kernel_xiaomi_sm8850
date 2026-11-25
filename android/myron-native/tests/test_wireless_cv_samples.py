#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Production wireless monitor/CV error paths and unchanged valid actions."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', required=True, type=Path)
p.add_argument('--monitor-source', type=Path)
p.add_argument('--cv-source', type=Path)
a = p.parse_args()
b = a.kernel_root/'drivers/power/supply/mca'
s = (b/'mca_strategy/strategy_wireless/mca_basic_wireless.c').read_text()
h = (b/'mca_strategy/strategy_wireless/inc/mca_basic_wireless.h').read_text()
code = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef int64_t s64;
#define mca_log_info(...) do { if(0) printf(__VA_ARGS__); } while(0)
#define mca_log_err(...) do { if(0) printf(__VA_ARGS__); } while(0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define MAIN_BUCK_CHARGER 0
#define STRATEGY_FUNC_TYPE_QUICK_WIRELESS 1
#define STRATEGY_STATUS_TYPE_QC_CHARGE_STS 1
#define MCA_EVENT_CHARGE_ACTION 1
#define msecs_to_jiffies(v) (v)
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; };
struct mca_hwid { const char *product_name; };
'''
for name in ['MCA_WLS_CHG_VTERM_LOW_TH','MCA_WLS_CHG_MONITOR_WORK_NORMAL_INTERVAL',
             'MCA_WLS_CHG_MONITOR_WORK_FAST_INTERVAL','CHARGE_SW_CV_WORK_NORMAL_INTERVAL',
             'CHARGE_SW_CV_WORK_FAST_INTERVAL','CHARGE_SW_CV_VBAT_ALARM_DELTA']:
    code += re.search(r'^#define '+name+r' .*$',h,re.M)[0]+'\n'
for name in ['FCC_STEP','FV_STEP']:
    code += re.search(r'^#define '+name+r' .*$',s,re.M)[0]+'\n'
for name in ['XM_WLS_CHGR_STAGE','batt_chgr_status']:
    code += re.search(r'enum '+name+r'\s*\{.*?\};',h,re.S)[0]+'\n'
code += re.search(r'enum mca_quick_chg_status\s*\{.*?\};',(b/'include/mca/strategy/strategy_class.h').read_text(),re.S)[0]
code += r'''
struct strategy_wireless_dev {
 struct delayed_work monitor_work,sw_cv_work,base_flip_sw_cv_work;
 int thermal_phone_flag,input_limit_voter,chg_enable_voter,wls_input_suspend_voter;
 int vterm_voter,iterm_voter,charge_limit_voter,sw_cv_running,support_base_flip;
 int pmic_fv_compensation,base_flip_ov_cnt;
 struct { enum XM_WLS_CHGR_STAGE chgr_stage;int vbat_cell_mv,ibat_ma; } proc_data;
};
static int qret,qstate,pmic_ret,pmic_status,disable_ret,enable_ret,voltage_ret,current_ret;
static int voltage,current,fastcharge,termination,termination_ret,votes[7],jeita_vterm;
static int toggle_calls,toggles[4],cv_start,cv_stop,ffc_calls,cv_votes,cv_value,fv_calls,fv_value,retries,interval;
static int mca_get_effective_result(int which) { assert(which>0 && which<7);return votes[which]; }
static int mca_get_client_vote(int which,const char *client) {
 if(!strcmp(client,"jeita-hot"))return 1;
 assert(!strcmp(client,"jeita"));return jeita_vterm;
}
static int strategy_class_fg_ops_get_voltage(int *v) { *v=voltage;return voltage_ret; }
static int strategy_class_fg_ops_get_current(int *v) { *v=current;return current_ret; }
static int strategy_class_fg_get_fastcharge(void) { return fastcharge; }
static int strategy_class_fg_get_first_termination(int *v) { *v=termination;return termination_ret; }
static int mca_strategy_func_get_status(int type,int what,int *v) { *v=qstate;return qret; }
static void strategy_wireless_get_qc_enable(struct strategy_wireless_dev *s,bool *v) { *v=false; }
static void mca_strategy_func_process(int type,int event,bool en) { }
static const struct mca_hwid *mca_get_hwid_info(void) { return NULL; }
static void strategy_wireless_switch_to_half_bridge(struct strategy_wireless_dev *s) { assert(0); }
static int platform_class_buckchg_ops_get_chg_status(int who,int *v) { *v=pmic_status;return pmic_ret; }
static int platform_class_buckchg_ops_set_chg(int who,bool v) {
 assert(toggle_calls<4);toggles[toggle_calls++]=v;return v?enable_ret:disable_ret;
}
static void strategy_wireless_enable_fast_charge_mode(struct strategy_wireless_dev *s) { ffc_calls++; }
static void strategy_wireless_sw_cv_stop(struct strategy_wireless_dev *s) { cv_stop++;s->sw_cv_running=0; }
static void strategy_wireless_sw_cv_start(struct strategy_wireless_dev *s) { cv_start++;s->sw_cv_running=1; }
static void mca_vote(int voter,const char *client,bool en,int val) {
 if(!strcmp(client,"sw_cv") && en){cv_votes++;cv_value=val;}
}
static void platform_class_buckchg_ops_set_term_volt(int who,int val) { fv_calls++;fv_value=val; }
static void schedule_delayed_work(struct delayed_work *w,int ms) { retries++;interval=ms; }
#define mca_queue_delayed_work schedule_delayed_work
'''
code += function(a.monitor_source.read_text() if a.monitor_source else s,'strategy_wireless_monitor_work')+'\n'
for name in ['strategy_wireless_buckchg_sw_cv_workfunc','strategy_wireless_buckchg_base_flip_sw_cv_workfunc']:
    code += function(a.cv_source.read_text() if a.cv_source else s,name)+'\n'
code += r'''
static int cases;
static void init(struct strategy_wireless_dev *s) {
 *s=(struct strategy_wireless_dev){.input_limit_voter=1,.chg_enable_voter=2,
  .wls_input_suspend_voter=3,.vterm_voter=4,.iterm_voter=5,.charge_limit_voter=6,
  .pmic_fv_compensation=20};
 s->proc_data.chgr_stage=WLS_NORMAL_MODE;s->proc_data.vbat_cell_mv=4444;s->proc_data.ibat_ma=-777777;
 votes[1]=900;votes[2]=1;votes[3]=0;votes[4]=4400;votes[5]=200;votes[6]=2000;jeita_vterm=4400;
 qret=pmic_ret=disable_ret=enable_ret=voltage_ret=current_ret=termination_ret=0;
 qstate=MCA_QUICK_CHG_STS_NO_CHARGING;pmic_status=CHARGER_STATUS_CHARGING_DISABLED;
 voltage=4500;current=-1000000;fastcharge=termination=0;
 toggle_calls=cv_start=cv_stop=ffc_calls=cv_votes=fv_calls=retries=interval=0;
}
static void cv(struct strategy_wireless_dev *s,int flip) {
 if(flip)strategy_wireless_buckchg_base_flip_sw_cv_workfunc(&s->base_flip_sw_cv_work.work);
 else strategy_wireless_buckchg_sw_cv_workfunc(&s->sw_cv_work.work);
}
int main(void) {
 struct strategy_wireless_dev s;
 /* No hardware recovery from failed or unknown quick-charge/PMIC status. */
 for(int kind=0;kind<7;kind++) {
  init(&s);
  if(kind==0)qret=-EIO;
  if(kind==1)qstate=-1;
  if(kind==2)qstate=MCA_QUICK_CHG_STS_CHARGE_FAILED+1;
  if(kind==3)pmic_ret=-EIO;
  if(kind==4)votes[2]=-EIO;
  if(kind==5)votes[3]=-EIO;
  if(kind==6)qstate=MCA_QUICK_CHG_STS_CHARGING;
  strategy_wireless_monitor_work(&s.monitor_work.work);
  assert(!toggle_calls && retries==1);cases++;
 }
 for(int fail=0;fail<3;fail++) {
  init(&s);if(fail==1)disable_ret=-EIO;if(fail==2)enable_ret=-EIO;
  strategy_wireless_monitor_work(&s.monitor_work.work);
  assert(toggle_calls==(fail==1?1:2) && toggles[0]==0);
  if(fail!=1)assert(toggles[1]==1);
  assert(retries==1);cases++;
 }
 /* CV start/stop must use a successful fresh voltage, never a stale cache. */
 init(&s);voltage=4000;strategy_wireless_monitor_work(&s.monitor_work.work);
 assert(!cv_start && !cv_stop && s.proc_data.vbat_cell_mv==4000);cases++;
 for(int running=0;running<2;running++)for(int failure=0;failure<4;failure++) {
  init(&s);s.sw_cv_running=running;
  if(failure==0)voltage_ret=-EIO;
  if(failure==1)voltage=0;
  if(failure==2)votes[4]=-EIO;
  if(failure==3)votes[2]=-EIO;
  strategy_wireless_monitor_work(&s.monitor_work.work);
  assert(!cv_start && !cv_stop && s.sw_cv_running==running && s.proc_data.vbat_cell_mv==4444);cases++;
 }
 for(int flip=0;flip<2;flip++)for(int failure=0;failure<8;failure++) {
  init(&s);
  if(failure==0)voltage_ret=-EIO;
  if(failure==1)current_ret=-EIO;
  if(failure==2)voltage=0;
  if(failure==3)current=INT_MIN;
  if(failure==4)votes[4]=jeita_vterm=-EIO;
  if(failure==5)votes[5]=-EIO;
  if(failure==6)votes[6]=-EIO;
  if(failure==7)voltage=-1;
  cv(&s,flip);
  assert(!cv_votes && !fv_calls && retries==1 && interval==CHARGE_SW_CV_WORK_NORMAL_INTERVAL);
  assert(s.proc_data.vbat_cell_mv==4444 && s.proc_data.ibat_ma==-777777);cases++;
 }
 for(int failure=0;failure<3;failure++) {
  init(&s);
  if(failure==0)fastcharge=-EIO;
  if(failure==1)termination_ret=-EIO;
  if(failure==2){termination=1;votes[4]=-EIO;}
  cv(&s,1);assert(!cv_votes && !fv_calls && retries==1);cases++;
 }
 for(int flip=0;flip<2;flip++) {
  init(&s);cv(&s,flip);
  assert(cv_votes==1 && cv_value==1000 && fv_calls==1 && fv_value==4415);
  assert(retries==1 && interval==CHARGE_SW_CV_WORK_FAST_INTERVAL);
  assert(s.proc_data.vbat_cell_mv==4500 && s.proc_data.ibat_ma==-1000000);cases++;
  init(&s);voltage=4300;cv(&s,flip);
  assert(!cv_votes && !fv_calls && retries==1);cases++;
  init(&s);votes[6]=20;cv(&s,flip);assert(!cv_votes && fv_calls==1);cases++;
  init(&s);voltage_ret=-EIO;cv(&s,flip);assert(!cv_votes && !fv_calls);
  voltage_ret=0;cv(&s,flip);assert(cv_votes==1 && fv_calls==1 && retries==2);cases++;
  init(&s);s.pmic_fv_compensation=INT_MAX;cv(&s,flip);assert(!fv_calls);cases++;
 }
 init(&s);
 for(int n=0;n<10;n++) { cv(&s,1);assert(s.base_flip_ov_cnt==(n<5?n+1:5)); }
 assert(fv_value==4395);cases++;
 init(&s);s.base_flip_ov_cnt=INT_MAX;cv(&s,1);assert(fv_value==4395);cases++;
 printf("PASS: %d wireless monitor/CV provider, recovery and bounds cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
    c.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-Wno-sign-compare','-fsanitize=undefined','-fno-sanitize-recover=undefined',
                    str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

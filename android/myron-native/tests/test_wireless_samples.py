#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute wireless monitor/property consumers with failed or invalid samples."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', type=Path, required=True)
p.add_argument('--monitor-source', type=Path)
p.add_argument('--health-source', type=Path)
a = p.parse_args()
base = a.kernel_root / 'drivers/power/supply/mca/mca_strategy/strategy_wireless'
s = (base / 'mca_basic_wireless.c').read_text()
h = (base / 'inc/mca_basic_wireless.h').read_text()
ph = (a.kernel_root / 'include/linux/power_supply.h').read_text()
code = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define mca_log_err(...) do { if (0) printf(__VA_ARGS__); } while (0)
#define mca_log_info(...) do { if (0) printf(__VA_ARGS__); } while (0)
#define WIRELESS_ROLE_MASTER 0
#define MAIN_BUCK_CHARGER 0
#define MCA_BATT_CHGR_STATUS_CHARGING_DISABLED 0
#define STRATEGY_FUNC_TYPE_QUICK_WIRELESS 1
#define STRATEGY_STATUS_TYPE_QC_START_FLAG 1
#define TRANS_DATA_FLAG_SOC 1
#define MCA_EVENT_NOTIFY_SIZE 128
struct mca_event_notify_data { char *event; int event_len; };
enum power_supply_property { POWER_SUPPLY_PROP_STATUS, POWER_SUPPLY_PROP_HEALTH };
union power_supply_propval { int intval; };
struct power_supply { int unused; };
''' + '\n'.join(re.search(r'enum\s*\{\s*'+name+r'.*?\};',ph,re.S)[0]
                   for name in ['POWER_SUPPLY_STATUS_UNKNOWN','POWER_SUPPLY_HEALTH_UNKNOWN'])
code += re.search(r'enum XM_WLS_CHGR_STAGE\s*\{.*?\};',h,re.S)[0]
code += re.search(r'enum\s*\{\s*POWER_SUPPLY_CHARGING_STATUS_UNKNOWN.*?\};',h,re.S)[0]
for name in ['EPP_DEFAULT_VOUT','START_WLS_LOOP_CHECK_CNT']:
    code += '\n'+re.search(r'^#define '+name+r' .*$',h,re.M)[0]+'\n'
code += r'''
struct strategy_wireless_dev {
 struct power_supply *batt_psy;
 int online,batt_cold,batt_overhot,audio_phone_sts;
 int input_limit_voter,charge_limit_voter,chg_enable_voter;
 struct { int batt_soc,chgr_status,vbat_cell_mv,epp,fc_flag,start_vout_check_flag;
   int start_wls_loop_cnt,magnet_tx_flag,adapter_type,qc_type;
   enum XM_WLS_CHGR_STAGE chgr_stage; } proc_data;
};
static int missing,gets,puts_count,refs,property_ret,status_sample,health_sample;
static int iout_ret,iout_sample,qc_ret,qc_sample,soc_sample;
static int votes,vote_en,vote_value,vout_writes,tx_calls,icon_calls,uevents;
static struct power_supply battery;
static struct power_supply *power_supply_get_by_name(const char *name) {
 assert(!strcmp(name,"battery"));gets++;if(missing)return NULL;refs++;return &battery;
}
static void power_supply_put(struct power_supply *p) { assert(p==&battery && refs>0);refs--;puts_count++; }
static int power_supply_get_property(struct power_supply *p,enum power_supply_property prop,union power_supply_propval *v) {
 assert(p==&battery && refs>0);
 v->intval=prop==POWER_SUPPLY_PROP_STATUS?status_sample:health_sample;
 return property_ret;
}
static int harmless(int role,int *p) { assert(role==0);*p=0;return 0; }
#define platform_class_wireless_get_vout harmless
#define platform_class_wireless_get_vrect harmless
#define platform_class_wireless_get_rx_brg_status harmless
#define platform_class_buckchg_ops_get_wls_curr harmless
#define platform_class_buckchg_ops_get_chg_status harmless
static int platform_class_wireless_get_iout(int role,int *p) { assert(role==0);*p=iout_sample;return iout_ret; }
static int strategy_class_fg_ops_get_soc(void) { return soc_sample; }
static bool strategy_class_fg_ops_get_charging_done(void) { return false; }
static int strategy_class_fg_ops_get_voltage(int *p) { *p=4000;return 0; }
static void strategy_wireless_add_trans_task_to_queue(struct strategy_wireless_dev *s,int kind,int val) {
 assert(kind==TRANS_DATA_FLAG_SOC && val==0);tx_calls++;
}
static int mca_get_effective_result(int p) { return 1; }
static int mca_strategy_func_get_status(int type,int what,int *v) { *v=qc_sample;return qc_ret; }
static void strategy_wireless_set_rx_vout(struct strategy_wireless_dev *s,int v) { assert(v==EPP_DEFAULT_VOUT);vout_writes++; }
static void strategy_wireless_soc_icl_setting(struct strategy_wireless_dev *s,bool en,int v) {
 votes++;vote_en=en;vote_value=v;
}
static void strategy_wireless_update_quick_charge_type(struct strategy_wireless_dev *s) { icon_calls++; }
static void mca_event_report_uevent(struct mca_event_notify_data *d) { uevents++; }
'''
for name in ['strategy_wireless_get_batt_property','strategy_wireless_get_batt_chgr_status','strategy_wireless_get_chgr_stage']:
    code += function(s,name)+'\n'
code += function(a.monitor_source.read_text() if a.monitor_source else s,'strategy_wireless_get_charging_info')+'\n'
code += function(a.health_source.read_text() if a.health_source else s,'strategy_wireless_process_battery_health_change')+'\n'
code += r'''
static int cases;
static void init(struct strategy_wireless_dev *s) {
 assert(!refs);
 *s=(struct strategy_wireless_dev){.online=1};
 s->proc_data.batt_soc=99;s->proc_data.chgr_status=POWER_SUPPLY_STATUS_CHARGING;
 s->proc_data.chgr_stage=WLS_TAPER_MODE;s->proc_data.epp=s->proc_data.fc_flag=1;
 s->proc_data.start_wls_loop_cnt=START_WLS_LOOP_CHECK_CNT-1;
 missing=gets=puts_count=property_ret=iout_ret=qc_ret=0;
 status_sample=POWER_SUPPLY_STATUS_CHARGING;health_sample=POWER_SUPPLY_HEALTH_GOOD;
 iout_sample=700;qc_sample=0;soc_sample=99;
 votes=tx_calls=vout_writes=icon_calls=uevents=0;vote_value=900;vote_en=1;
}
int main(void) {
 struct strategy_wireless_dev s;
 const int errors[]={0,-EIO,-ENODATA,-ENODEV};
 const int currents[]={0,1,700,-1,INT_MAX-250,INT_MAX-249,INT_MAX};
 const int flags[]={0,1,-1,2};
 for(unsigned a=0;a<4;a++)for(unsigned b=0;b<4;b++)
 for(unsigned c=0;c<7;c++)for(unsigned d=0;d<4;d++) {
  init(&s);iout_ret=errors[a];qc_ret=errors[b];iout_sample=currents[c];qc_sample=flags[d];
  strategy_wireless_get_charging_info(&s);
  bool valid_qc=!qc_ret && (qc_sample==0 || qc_sample==1);
  bool release=valid_qc && qc_sample==1;
  bool adjust=valid_qc && qc_sample==0 && !iout_ret && iout_sample>=0 && iout_sample<=INT_MAX-250;
  assert(votes==(release||adjust));
  if(release)assert(!vote_en && vote_value==0);
  else if(adjust)assert(vote_en && vote_value==iout_sample+250);
  else assert(vote_en && vote_value==900);
  assert(s.proc_data.start_wls_loop_cnt==START_WLS_LOOP_CHECK_CNT-1+valid_qc);
  assert(vout_writes==(valid_qc && !qc_sample));
  assert(gets==1 && puts_count==1 && !refs);cases++;
 }
 const int socs[]={-EIO,-1,0,98,99,100,101,INT_MAX};
 for(unsigned a=0;a<4;a++)for(unsigned b=0;b<8;b++) {
  init(&s);property_ret=errors[a];soc_sample=socs[b];status_sample=POWER_SUPPLY_STATUS_FULL;
  strategy_wireless_get_charging_info(&s);
  bool valid_soc=soc_sample>=0 && soc_sample<=100;
  assert(s.proc_data.batt_soc==(valid_soc?soc_sample:99));
  assert(tx_calls==valid_soc);
  if(property_ret)assert(s.proc_data.chgr_status==POWER_SUPPLY_STATUS_CHARGING);
  if(property_ret || !valid_soc)assert(s.proc_data.chgr_stage==WLS_TAPER_MODE);
  else if(soc_sample==100)assert(s.proc_data.chgr_stage==WLS_FULL_MODE);
  else if(soc_sample<99)assert(s.proc_data.chgr_stage==WLS_NORMAL_MODE);
  assert(gets==puts_count && !refs);cases++;
 }
 init(&s);missing=1;strategy_wireless_get_charging_info(&s);
 assert(s.proc_data.chgr_status==POWER_SUPPLY_STATUS_CHARGING && s.proc_data.chgr_stage==WLS_TAPER_MODE);
 assert(gets==1 && !puts_count && !refs);cases++;
 for(int value=-1;value<=6;value++) {
  init(&s);status_sample=value;int output=777;
  int ret=strategy_wireless_get_batt_chgr_status(&s,&output);
  if(value>=POWER_SUPPLY_STATUS_UNKNOWN && value<=POWER_SUPPLY_STATUS_FULL)assert(!ret && output==value);
  else assert(ret==-ERANGE && output==777);
  assert(gets==puts_count && !refs);cases++;
 }
 const int healths[]={POWER_SUPPLY_HEALTH_COLD,POWER_SUPPLY_HEALTH_OVERHEAT,POWER_SUPPLY_HEALTH_GOOD};
 for(unsigned a=0;a<4;a++)for(unsigned b=0;b<3;b++)for(int cold=0;cold<2;cold++)for(int hot=0;hot<2;hot++) {
  init(&s);s.batt_cold=cold;s.batt_overhot=hot;property_ret=errors[a];health_sample=healths[b];
  strategy_wireless_process_battery_health_change(&s);
  assert(s.batt_cold==(property_ret?cold:health_sample==POWER_SUPPLY_HEALTH_COLD));
  assert(s.batt_overhot==(property_ret?hot:health_sample==POWER_SUPPLY_HEALTH_OVERHEAT));
  assert(icon_calls==!property_ret && uevents==!property_ret);
  assert(gets==puts_count && !refs);cases++;
 }
 init(&s);missing=1;s.batt_overhot=1;
 strategy_wireless_process_battery_health_change(&s);
 assert(s.batt_overhot && !s.batt_cold && !icon_calls && !uevents && !refs);cases++;
 /* A valid sample recovers after failure; no synthetic limit or leaked reference. */
 init(&s);iout_ret=-EIO;strategy_wireless_get_charging_info(&s);assert(votes==0);
 iout_ret=0;strategy_wireless_get_charging_info(&s);assert(votes==1 && vote_value==950);
 assert(gets==puts_count && !refs);cases++;
 printf("PASS: %d wireless sample/error/recovery/reference cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
    c.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-fsanitize=undefined','-fno-sanitize-recover=undefined',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute production ICL ramps, bridge transitions and drawload status reads."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_sc96281_irq import function

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', required=True, type=Path)
p.add_argument('--source', type=Path)
a = p.parse_args()
s = (a.source or a.kernel_root/'drivers/power/supply/mca/mca_strategy/strategy_wireless/mca_basic_wireless.c').read_text()
code = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define READ_ONCE(x) (x)
#define min(a,b) ((a)<(b)?(a):(b))
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define WIRELESS_ROLE_MASTER 0
#define MAIN_BUCK_CHARGER 0
#define BPP_DEFAULT_VOUT 6000
#define CHARGER_STATUS_FULLON 3
#define CHARGER_STATUS_TAPER 4
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct work_struct { int unused; };
struct strategy_wireless_dev { int online,input_limit_voter;bool switching_bridge;
 struct { struct work_struct work; } wls_drawload_work;
 struct { int epp,tx_max_power; } proc_data; };
static struct strategy_wireless_dev *active;
static int calls, values[100], fail_at, sleeps, unplug_at;
static int bridge_read_ret,bridge_status,vout_ret,vout, iout_ret,iout;
static int set_ret, sets,vote_ret,release_calls,bridge_calls,bridge_ret, status_reads,status_ret;
static int strategy_wireless_icl_setting(struct strategy_wireless_dev *s,bool en,int ma) {
 assert(en && s->online && calls<100);values[calls++]=ma;
 return calls==fail_at?-EIO:0;
}
static void msleep(int ms) { assert(ms>=0);sleeps++;if(sleeps==unplug_at)active->online=0; }
static int strategy_wireless_msleep(int ms,struct strategy_wireless_dev *s) { msleep(ms);return !s->online; }
static int platform_class_wireless_get_rx_brg_status(int role,int *v) { *v=bridge_status;return bridge_read_ret; }
static int platform_class_wireless_set_vout(int role,int v) { assert(v==BPP_DEFAULT_VOUT);sets++;return set_ret; }
static int mca_vote(int v,const char *name,bool en,int ma) {
 assert(!strcmp(name,"sw_bridge"));if(!en)release_calls++;return en?vote_ret:0;
}
static int platform_class_wireless_get_vout(int role,int *v) { *v=vout;return vout_ret; }
static int platform_class_wireless_get_iout(int role,int *v) { *v=iout;return iout_ret; }
static int platform_class_wireless_switch_bridge(int role,int mode) {
 assert(mode==0 && !vout_ret && !iout_ret && vout>0 && vout<6501 && iout>=0 && iout<401);
 bridge_calls++;return bridge_ret;
}
static int platform_class_buckchg_ops_get_wls_curr(int role,int *v) { *v=0;return 0; }
static int platform_class_buckchg_ops_get_chg_status(int role,int *v) {
 status_reads++;*v=CHARGER_STATUS_FULLON;return status_ret;
}
'''
for name in ['strategy_wireless_stepper_pmic_icl','strategy_wireless_bridge_icl_setting',
             'strategy_wireless_switch_to_half_bridge','strategy_wireless_drawload_work']:
    code += function(s,name)+'\n'
code += r'''
static int cases;
static void reset(struct strategy_wireless_dev *s) {
 *s=(struct strategy_wireless_dev){.online=1};active=s;
 calls=fail_at=sleeps=unplug_at=bridge_read_ret=bridge_status=vout_ret=iout_ret=0;
 set_ret=sets=vote_ret=release_calls=bridge_calls=bridge_ret=status_reads=status_ret=0;
 vout=6000;iout=300;
}
int main(void) {
 struct strategy_wireless_dev s;
 const int ramps[][3]={{200,1300,100},{200,800,100},{250,750,100},{800,1100,100},
 {900,200,300},{200,900,300},{200,200,100},{INT_MAX-3,INT_MAX,INT_MAX},{INT_MAX,0,INT_MAX}};
 for(unsigned r=0;r<sizeof(ramps)/sizeof(ramps[0]);r++) {
  reset(&s);int start=ramps[r][0],end=ramps[r][1],step=ramps[r][2];
  assert(!strategy_wireless_stepper_pmic_icl(&s,start,end,step,20));
  assert(values[0]==start && values[calls-1]==end);
  int length=calls;
  for(int i=1;i<calls;i++) {
   if(start<end)assert(values[i]>values[i-1] && values[i]<=end);
   else assert(values[i]<values[i-1] && values[i]>=end);
  }
  for(int f=1;f<=length;f++) {
   reset(&s);fail_at=f;
   assert(strategy_wireless_stepper_pmic_icl(&s,start,end,step,20)==-EIO && calls==f);
   cases++;
  }
  for(int u=1;u<length;u++) {
   reset(&s);unplug_at=u;
   assert(strategy_wireless_stepper_pmic_icl(&s,start,end,step,20)==-ENODEV && calls==u);
   cases++;
  }
  cases++;
 }
 reset(&s);s.online=0;assert(strategy_wireless_stepper_pmic_icl(&s,200,800,100,20)==-ENODEV && !calls);cases++;
 const int bad[][4]={{-1,100,10,20},{100,-1,10,20},{100,200,0,20},{100,200,-1,20},{100,200,10,-1}};
 for(unsigned i=0;i<5;i++){reset(&s);assert(strategy_wireless_stepper_pmic_icl(&s,bad[i][0],bad[i][1],bad[i][2],bad[i][3])==-EINVAL && !calls);cases++;}
 for(int f=0;f<11;f++) {
  reset(&s);
  switch(f) {case 1:bridge_read_ret=-EIO;break;case 2:set_ret=-EIO;break;case 3:vote_ret=-EIO;break;
   case 4:vout_ret=-EIO;break;case 5:iout_ret=-EIO;break;case 6:vout=0;break;
   case 7:iout=-1;break;case 8:vout=6501;break;case 9:iout=401;break;case 10:unplug_at=1;break;}
  strategy_wireless_switch_to_half_bridge(&s);
  assert(!s.switching_bridge && bridge_calls==(f==0));
  if(f!=1 && f!=2)assert(release_calls==1);
  cases++;
 }
 reset(&s);bridge_ret=-EIO;strategy_wireless_switch_to_half_bridge(&s);
 assert(bridge_calls==1 && release_calls==1 && !s.switching_bridge);cases++;
 /* An error that leaves FULLON in the output must not shorten the polling. */
 reset(&s);status_ret=-EIO;strategy_wireless_drawload_work(&s.wls_drawload_work.work);
 assert(status_reads==51 && calls==6);cases++;
 reset(&s);strategy_wireless_drawload_work(&s.wls_drawload_work.work);
 assert(status_reads==1 && calls==6);cases++;
 printf("PASS: %d wireless ramp/bridge/status cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
    c.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-fsanitize=undefined','-fno-sanitize-recover=undefined',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run production wireless profiles against failed voltage/current commands."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', required=True, type=Path)
p.add_argument('--profile-source', type=Path)
a = p.parse_args()
b = a.kernel_root/'drivers/power/supply/mca'
s = (b/'mca_strategy/strategy_wireless/mca_basic_wireless.c').read_text()
h = (b/'mca_strategy/strategy_wireless/inc/mca_basic_wireless.h').read_text()
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define WIRELESS_ROLE_MASTER 0
#define max(a,b) ((a)>(b)?(a):(b))
struct strategy_wireless_dev {
 int input_limit_voter,charge_limit_voter,sw_qc_ichg_voter;
 struct { int target_vout,pre_vout,target_iwls,pre_iwls,qc_enable;
  int chgr_stage,batt_soc,high_soc_fcc_set,fc_flag; } proc_data;
};
static int vget_ret,vget_value,vset_fail,vset_calls,vset_values[32],sleeps,temp;
static int vote_ret[4],vote_calls[4],vote_value[4];
static int platform_class_wireless_get_vout(int role,int *v) { *v=vget_value;return vget_ret; }
static int strategy_wireless_set_rx_vout(struct strategy_wireless_dev *s,int v) {
 assert(vset_calls<32);vset_values[vset_calls++]=v;
 return vset_calls==vset_fail?-EIO:0;
}
static void msleep(int ms) { assert(ms==200);sleeps++; }
static int strategy_class_fg_ops_get_temperature(int *v) { *v=temp;return 0; }
static int mca_vote(int voter,const char *name,bool en,int v) {
 assert(voter>=1 && voter<=3 && !strcmp(name,"xm_wls"));
 vote_calls[voter]++;vote_value[voter]=v;return vote_ret[voter];
}
static void strategy_wireless_stepper_pmic_icl(struct strategy_wireless_dev *s,int start,int end,int step,int ms) { }
'''
for name in ['BPP_DEFAULT_VOUT','EPP_DEFAULT_VOUT','EPP_PLUS_VOUT']:
    code += re.search(r'^#define '+name+r' .*$', h, re.M)[0]+'\n'
code += re.search(r'enum XM_WLS_CHGR_STAGE\s*\{.*?\};', h, re.S)[0]+'\n'
for name in ['strategy_wireless_icl_setting','strategy_wireless_fcc_setting',
             'strategy_wireless_apply_profile_vout']:
    code += function(s,name)+'\n'
profiles = ['epp_plate_tx','epp_train_tx','qc2_adapter','bpp_plus','epp_standard','epp_plus','epp_musical_box']
for name in profiles:
    code += function(a.profile_source.read_text() if a.profile_source else s,'strategy_wireless_'+name+'_work')+'\n'
code += '\nstatic void (*profiles[])(struct strategy_wireless_dev *) = {'+','.join('strategy_wireless_'+n+'_work' for n in profiles)+'};\n'
code += r'''
static int cases;
static void init(struct strategy_wireless_dev *s) {
 *s=(struct strategy_wireless_dev){.input_limit_voter=1,.charge_limit_voter=2,.sw_qc_ichg_voter=3};
 s->proc_data.target_vout=s->proc_data.pre_vout=EPP_DEFAULT_VOUT;
 s->proc_data.target_iwls=900;s->proc_data.pre_iwls=700;
 s->proc_data.chgr_stage=WLS_NORMAL_MODE;s->proc_data.batt_soc=50;
 vget_ret=vset_fail=vset_calls=sleeps=0;vget_value=13500;temp=250;
 memset(vote_ret,0,sizeof(vote_ret));memset(vote_calls,0,sizeof(vote_calls));
}
int main(void) {
 struct strategy_wireless_dev s;
 /* Every profile preserves the cache on failure and submits the next retry. */
 for(int p=0;p<7;p++)for(int same=0;same<2;same++) {
  init(&s);if(same)s.proc_data.pre_iwls=900;int old=s.proc_data.pre_iwls;
  vote_ret[1]=-EIO;profiles[p](&s);
  assert(vote_calls[1]==1 && s.proc_data.pre_iwls==old);
  vote_ret[1]=0;profiles[p](&s);
  assert(vote_calls[1]==2 && vote_value[1]==900 && s.proc_data.pre_iwls==900);cases++;
 }
 /* Failed voltage changes must not be cached or followed by ordinary ICL. */
 for(int p=0;p<7;p++) {
  if(p==4)continue;
  init(&s);s.proc_data.pre_vout=EPP_PLUS_VOUT;s.proc_data.qc_enable=1;
  vset_fail=1;profiles[p](&s);
  assert(s.proc_data.pre_vout==EPP_PLUS_VOUT && s.proc_data.qc_enable && !vote_calls[1]);
  vset_fail=0;profiles[p](&s);
  assert(s.proc_data.pre_vout==EPP_DEFAULT_VOUT && vote_calls[1]==1);cases++;
 }
 for(int error=0;error<3;error++) {
  init(&s);s.proc_data.pre_vout=EPP_PLUS_VOUT;s.proc_data.qc_enable=1;
  if(error==0)vget_ret=-EIO;else vget_value=error==1?0:-1;
  assert(strategy_wireless_apply_profile_vout(&s,true)<0 && !vset_calls);
  assert(s.proc_data.pre_vout==EPP_PLUS_VOUT && s.proc_data.qc_enable);cases++;
 }
 for(int fail=0;fail<=4;fail++) {
  init(&s);s.proc_data.pre_vout=EPP_PLUS_VOUT;s.proc_data.qc_enable=1;vset_fail=fail;
  int ret=strategy_wireless_apply_profile_vout(&s,true);
  const int expected[]={12500,11500,11000,11000};
  assert(vset_calls==(fail?fail:4));
  for(int i=0;i<vset_calls;i++)assert(vset_values[i]==expected[i]);
  if(fail)assert(ret==-EIO && s.proc_data.pre_vout==EPP_PLUS_VOUT && s.proc_data.qc_enable);
  else assert(ret==1 && s.proc_data.pre_vout==EPP_DEFAULT_VOUT && !s.proc_data.qc_enable);
  vset_fail=0;assert(strategy_wireless_apply_profile_vout(&s,true)==!!fail);
  assert(s.proc_data.pre_vout==EPP_DEFAULT_VOUT && !s.proc_data.qc_enable);cases++;
 }
 init(&s);s.proc_data.target_vout=EPP_PLUS_VOUT;
 assert(strategy_wireless_apply_profile_vout(&s,true)==1 && s.proc_data.qc_enable && vset_calls==1);
 assert(!strategy_wireless_apply_profile_vout(&s,true) && vset_calls==1);cases++;
 init(&s);s.proc_data.target_vout=0;assert(strategy_wireless_apply_profile_vout(&s,false)==-EINVAL);cases++;
 init(&s);s.proc_data.target_vout=6000;assert(strategy_wireless_apply_profile_vout(&s,true)==-EINVAL);cases++;
 /* Both FCC votes are attempted; a failed leg must leave the one-shot unset. */
 for(int leg=2;leg<=3;leg++) {
  init(&s);s.proc_data.batt_soc=70;vote_ret[leg]=-EIO;
  strategy_wireless_epp_plus_work(&s);
  assert(!s.proc_data.high_soc_fcc_set && vote_calls[2]==1 && vote_calls[3]==1);
  vote_ret[leg]=0;strategy_wireless_epp_plus_work(&s);
  assert(s.proc_data.high_soc_fcc_set && vote_calls[2]==2 && vote_calls[3]==2);
  assert(vote_value[2]==6000 && vote_value[3]==6000);
  strategy_wireless_epp_plus_work(&s);assert(vote_calls[2]==2 && vote_calls[3]==2);cases++;
 }
 init(&s);assert(!strategy_wireless_fcc_setting(&s,false,999));
 assert(vote_calls[2]==1 && vote_calls[3]==1 && !vote_value[2] && !vote_value[3]);cases++;
 printf("PASS: %d wireless profile apply/retry cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
    c.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-fsanitize=undefined','-fno-sanitize-recover=undefined',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

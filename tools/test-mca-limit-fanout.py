#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual Buck/QC limit callbacks with fault-injected host backends."""
from pathlib import Path
import os, re, subprocess, tempfile

root = Path(__file__).resolve().parents[1]
base = root / 'drivers/power/supply/mca/mca_strategy/strategy_charger'

def extract(source, name):
    m = re.search(r'static\s+int\s+' + name + r'\([^;]*?\n\{', source)
    assert m, name
    p, depth = m.end(), 1
    while depth:
        depth += (source[p] == '{') - (source[p] == '}')
        p += 1
    return source[m.start():p] + '\n'

buck = (base / 'mca_strategy_buckchg.c').read_text()
qc = (base / 'mca_strategy_quickchg.c').read_text()
names = ['strategy_buckchg_process_multi_input_limit',
         'strategy_buckchg_process_multi_charge_limit',
         'strategy_buckchg_process_multi_iterm',
         'strategy_buckchg_process_multi_vterm', 'strategy_buckchg_input_limit',
         'strategy_buckchg_input_suspend', 'strategy_buckchg_set_5v_input',
         'strategy_buckchg_set_5v_ichg', 'strategy_buckchg_set_9v_input',
         'strategy_buckchg_set_9v_ichg', 'strategy_buckchg_input_voltage']
body = ''.join(extract(buck, n) for n in names)
body += ''.join(extract(qc, n) for n in [
    'mca_quick_charge_single_chg_cur_voter_cb',
    'mca_quick_charge_multi_chg_cur_voter_cb'])
assert 'mca_qcom_smem_is_zero_speed' not in body
pre = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#define READ_ONCE(x) (x)
#define mca_log_err(...) ((void)0)
#define MAIN_BUCK_CHARGER 0
#define STATEGY_CHARGE_VBUS_5V 5
#define STATEGY_CHARGE_VBUS_9V 9
#define MCA_QUICK_CHG_CH_SINGLE 0
#define MCA_QUICK_CHG_CH_MULTI 1
#define MCA_QUICK_CHG_CH_MAX 2
#define CHG_MODE_MAX 3
struct mca_votable {int id;};
struct strategy_buckchg_dev {
 bool ready,stopping,support_multi_buck; int buck_5v_in,buck_5v_ich,buck_9v_in,buck_9v_ich,hvdcp_allow_flag;
 struct {int voltage;} proc_data;
 struct mca_votable *input_limit_voter,*charge_limit_voter;
};
struct mca_quick_charge_info {
 bool ready,stopping; struct {int chg_limit[2];} sysfs_data;
 struct mca_votable *voter[6];
};
static int calls,fail_at,fail2,ids[8],values[8],enabled[8],hw_value,hw_error;
static int mca_vote(struct mca_votable *v,const char *client,bool en,int val) {
 (void)client;assert(calls<8);ids[calls]=v->id;values[calls]=val;enabled[calls]=en;calls++;
 return calls==fail_at?-EIO:calls==fail2?-ETIMEDOUT:0;
}
static int platform_class_buckchg_ops_set_input_curr_lmt(int role,int v) {
 assert(role==MAIN_BUCK_CHARGER);hw_value=v;return hw_error;
}
static void reset(int fail) {calls=0;fail_at=fail;fail2=0;}
'''
test = r'''
int main(void) {
 struct mca_votable v[6];for(int j=0;j<6;j++)v[j].id=j;
 struct strategy_buckchg_dev b={.ready=true,.input_limit_voter=&v[0],.charge_limit_voter=&v[1],
  .buck_5v_in=500,.buck_5v_ich=700,.buck_9v_in=900,.buck_9v_ich=1100};
 typedef int (*callback)(struct mca_votable *,void *,int,const char *);
 callback cb[]={strategy_buckchg_set_5v_input,strategy_buckchg_set_5v_ichg,
  strategy_buckchg_set_9v_input,strategy_buckchg_set_9v_ichg};
 for(int j=0;j<4;j++)for(int active=0;active<2;active++)for(int en=0;en<2;en++) {
  b.proc_data.voltage=((j<2)==active)?5:9;reset(1);
  assert(cb[j](NULL,&b,en?420:0,"test")== (active?-EIO:0));assert(calls==active);
  if(active){assert(ids[0]==j%2&&values[0]==(en?420:0)&&enabled[0]==en);
   reset(0);assert(!cb[j](NULL,&b,en?420:0,"test")&&calls==1);}
 }
 for(int en=0;en<2;en++){reset(1);assert(strategy_buckchg_input_suspend(NULL,&b,en,"test")==-EIO);
  assert(calls==1&&ids[0]==0&&enabled[0]==en&&values[0]==0);}
 b.buck_5v_in=500;b.buck_5v_ich=700;b.buck_9v_in=900;b.buck_9v_ich=1100;
 for(int high=0;high<2;high++)for(int fail=0;fail<=2;fail++) {
  reset(fail);assert(strategy_buckchg_input_voltage(NULL,&b,high,"test")== (fail?-EIO:0));
  assert(calls==2&&ids[0]==0&&ids[1]==1&&values[0]==(high?900:500)&&values[1]==(high?1100:700));
 }
 reset(1);fail2=2;assert(strategy_buckchg_input_voltage(NULL,&b,1,"test")==-EIO&&calls==2);
 for(int current=0;current<=1500;current+=100){hw_error=0;
  assert(!strategy_buckchg_input_limit(NULL,&b,current,"test")&&hw_value==current);}
 hw_error=-ETIMEDOUT;assert(strategy_buckchg_input_limit(NULL,&b,400,"test")==-ETIMEDOUT);
 b.support_multi_buck=true;assert(strategy_buckchg_input_limit(NULL,&b,400,"test")==-EOPNOTSUPP);
 assert(strategy_buckchg_process_multi_charge_limit(&b,400)==-EOPNOTSUPP);
 assert(strategy_buckchg_process_multi_vterm(&b,4400)==-EOPNOTSUPP);
 assert(strategy_buckchg_process_multi_iterm(&b,200)==-EOPNOTSUPP);
 struct mca_quick_charge_info q={.ready=true};for(int j=0;j<6;j++)q.voter[j]=&v[j];
 callback qcb[]={mca_quick_charge_single_chg_cur_voter_cb,mca_quick_charge_multi_chg_cur_voter_cb};
 for(int ch=0;ch<2;ch++)for(int en=0;en<2;en++)for(int fail=0;fail<=3;fail++) {
  reset(fail);assert(qcb[ch](NULL,&q,en?800:0,"test")== (fail?-EIO:0));assert(calls==3);
  for(int j=0;j<3;j++)assert(ids[j]==2*j+ch&&values[j]==(en?800:0)&&enabled[j]==en);
  assert(q.sysfs_data.chg_limit[ch]==(en?800:0));
  if(fail){reset(0);assert(!qcb[ch](NULL,&q,en?800:0,"test")&&calls==3);}
 }
 reset(1);fail2=2;assert(qcb[0](NULL,&q,600,"test")==-EIO&&calls==3);
 b.stopping=q.stopping=true;reset(0);
 assert(strategy_buckchg_input_voltage(NULL,&b,1,"test")<0&&qcb[0](NULL,&q,600,"test")<0&&!calls);
 puts("PASS: actual Buck/QC nested errors, all fanout destinations, first errno, retries, exact sub-1500mA limits and unsupported multi-buck");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-limit-fanout-') as d:
    p = Path(d)
    (p / 'test.c').write_text(pre + body + test)
    subprocess.run([os.getenv('CC', 'cc'), '-std=gnu11', '-O1', '-g',
                    '-Werror=implicit-function-declaration', '-fsanitize=address,undefined',
                    str(p/'test.c'), '-o', str(p/'test')], check=True)
    subprocess.run([str(p/'test')], check=True, timeout=30,
                   env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual smartchg DT/worker and QC private-update exclusion host regressions.
No stock BASP format or hardware behavior is inferred by these fixtures.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1];base=root/'drivers/power/supply/mca'
s=(base/'mca_smart_charge/mca_smart_charge.c').read_text();h=(base/'mca_smart_charge/inc/mca_smart_charge.h').read_text()
q=(base/'mca_strategy/strategy_charger/mca_strategy_quickchg.c').read_text()
def fn(src,n):
 m=re.search(r'static\s+(?:int|void)\s+'+n+r'\([^;]*?\n\{',src);assert m,n
 p=m.end();d=1
 while d:
  if src[p]=='{':d+=1
  elif src[p]=='}':d-=1
  p+=1
 return src[m.start():p]+'\n'
pre=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef long long ktime_t;
typedef uint32_t u32;
#define READ_ONCE(x) (x)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define NSEC_PER_SEC 1000000000LL
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define msecs_to_jiffies(x) (x)
#define CountryCN 0
struct device_node {bool cc;int cell,len,read_error;int vals[4];};
struct device {struct device_node *of_node;};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;bool pending;};
struct notifier_block {int unused;};
struct mca_votable {int unused;};
'''+h+r'''
static int read_len,fg_ret,fg_cycle,vote_ret,votes,other_work;
static int mca_parse_dts_u32(struct device_node *n,const char *p,int *out,int def) {*out=!strcmp(p,"cell_type")?n->cell:def;return 0;}
static bool of_property_read_bool(struct device_node *n,const char *p) {return !strcmp(p,"support_cc_ichg")&&n->cc;}
static int mca_parse_dts_u32_count(struct device_node *n,const char *p,int rows,int cols) {(void)p;(void)rows;(void)cols;return n->len;}
static int mca_parse_dts_u32_array(struct device_node *n,const char *p,void *out,int len) {(void)p;read_len=len;if(n->read_error)return n->read_error;assert(len>0&&len<=4);memcpy(out,n->vals,len*sizeof(int));return 0;}
struct mca_hwid {int country_version;};
static struct mca_hwid hwid={1};
static const struct mca_hwid *mca_get_hwid_info(void) {return &hwid;}
static int strategy_class_fg_ops_get_cyclecount(int *out) {if(!fg_ret)*out=fg_cycle;return fg_ret;}
static int mca_vote(struct mca_votable *v,const char *c,bool on,int val) {(void)v;(void)c;(void)on;assert(val>=0);votes++;return vote_ret;}
static void smart_charge_csd_send_pulse(struct smart_charge_info *i) {(void)i;other_work++;}
static void smart_charge_handle_bypass_chg(struct smart_charge_info *i) {(void)i;other_work++;}
static void smart_charge_handle_mishow_config(struct smart_charge_info *i) {(void)i;other_work++;}
static int schedule_delayed_work(struct delayed_work *w,int ms) {(void)ms;w->pending=true;return 1;}
'''
body=fn(s,'smart_charge_parse_dt')+fn(s,'smart_charge_workfunc')
test=r'''
int main(void) {
 struct device_node n={.cc=true,.cell=1,.len=2,.vals={100,200,500,400}};struct device dev={.of_node=&n};struct smart_charge_info i={.dev=&dev};
 assert(!smart_charge_parse_dt(&i)&&read_len==2&&i.ichg_cc_count==1&&i.ichg_cc_table[0].delta_ichg==200);
 n.len=4;assert(!smart_charge_parse_dt(&i)&&read_len==4&&i.ichg_cc_count==2);
 int bad[]={-EIO,0,1,3,5,6};
 for(int k=0;k<6;k++){n.len=bad[k];assert(smart_charge_parse_dt(&i)==(bad[k]<0?bad[k]:-EINVAL));}
 n.len=4;n.read_error=-EIO;assert(smart_charge_parse_dt(&i)==-EIO);n.read_error=0;
 for(int k=0;k<4;k++){int old=n.vals[k];n.vals[k]=-1;assert(smart_charge_parse_dt(&i)==-EINVAL);n.vals[k]=old;}
 n.vals[2]=100;assert(smart_charge_parse_dt(&i)==-EINVAL);n.vals[2]=99;assert(smart_charge_parse_dt(&i)==-EINVAL);n.vals[2]=500;
 for(int k=0;k<4;k++){n.cell=k;assert(smart_charge_parse_dt(&i)==(k==1||k==2?0:-EINVAL));}n.cell=1;
 dev.of_node=NULL;assert(smart_charge_parse_dt(&i)==-EINVAL);dev.of_node=&n;
 assert(!smart_charge_parse_dt(&i));i.online=i.ready=true;i.smart_delta_ichg=100;fg_cycle=50;fg_ret=-EIO;
 smart_charge_workfunc(&i.smart_charge_work.work);assert(!votes&&i.smart_delta_ichg==100&&other_work==2&&i.smart_charge_work.pending);
 fg_ret=0;vote_ret=-EIO;smart_charge_workfunc(&i.smart_charge_work.work);assert(votes==1&&i.smart_delta_ichg==100);
 vote_ret=0;smart_charge_workfunc(&i.smart_charge_work.work);assert(votes==2&&i.smart_delta_ichg==200);
 vote_ret=-EIO;smart_charge_workfunc(&i.smart_charge_work.work);assert(votes==3&&i.smart_delta_ichg==200);vote_ret=0;smart_charge_workfunc(&i.smart_charge_work.work);assert(votes==4&&i.smart_delta_ichg==200);fg_cycle=200;smart_charge_workfunc(&i.smart_charge_work.work);assert(votes==5&&i.smart_delta_ichg==400);
 i.stopping=true;i.smart_charge_work.pending=false;smart_charge_workfunc(&i.smart_charge_work.work);assert(votes==5&&!i.smart_charge_work.pending);
 puts("PASS: actual smartchg 1/2-row DT bounds, invalid fields, gauge failures, vote retry and stopped worker");
}
'''
qcpre=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#define READ_ONCE(x) (x)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define mca_log_err(...) ((void)0)
enum {FG_IC_MASTER,FG_IC_SLAVE,FG_SITE_MAX};
struct mca_quick_charge_info {struct {int update_batt_para_curr_batt_index[2],update_batt_para_last_batt_index[2];} runtime;bool ready,stopping;int support_base_flip,batt_type,batt_para_cc_thr[2];};
static int fg_calls,parse_calls;
static int platform_fg_ops_get_cyclecount(int role,int *out) {(void)role;fg_calls++;*out=300;return 0;}
static int mca_quick_charge_parse_batt_info(struct mca_quick_charge_info *i,int mode) {(void)i;(void)mode;parse_calls++;return 0;}
static const int batt_para_cc_thr_list[]={0,50,100,150,300,800};
'''
qcbody=fn(q,'strategy_quickchg_smartchg_update_baa_para')+fn(q,'update_batt_para')
qctest=r'''
int main(void) {
 struct mca_quick_charge_info i={.ready=true};
 assert(strategy_quickchg_smartchg_update_baa_para(&i,(char *)1,-1,2147483647)==-EOPNOTSUPP);
 assert(strategy_quickchg_smartchg_update_baa_para(NULL,(char *)1,0,0)==-ENODEV);
 i.stopping=true;assert(strategy_quickchg_smartchg_update_baa_para(&i,NULL,1,1)==-ENODEV);i.stopping=false;
 for(int n=0;n<10;n++)update_batt_para(&i);assert(!fg_calls&&!parse_calls);
 puts("PASS: actual QC rejects unverified BAA without reading input; non-foldable events do not reparse battery tables");
}
'''
for name,code in [('policy',pre+body+test),('qc',qcpre+qcbody+qctest)]:
 with tempfile.TemporaryDirectory(prefix='mca-'+name+'-') as d:
  p=Path(d);(p/'test.c').write_text(code)
  subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

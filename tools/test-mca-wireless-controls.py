#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Production wireless table parsing, current bounds and stop error paths.
ASan/UBSan with deterministic allocation, DT-read and hardware-failure injection.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1];base=root/'drivers/power/supply/mca/mca_strategy/strategy_wireless'
s=(base/'mca_quick_wireless.c').read_text();h=(base/'inc/mca_quick_wireless.h').read_text()
h=re.sub(r'#if \(LINUX_VERSION_CODE.*?#endif','',h,flags=re.S);h=re.sub(r'^#include.*\n','',h,flags=re.M)
def fn(n):
 m=re.search(r'(?:static\s+)?(?:int|void)\s+'+n+r'\([^;]*?\)\s*\n\{',s);assert m,n
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]+'\n'
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#define GFP_KERNEL 0
#define MCA_QUICK_CHG_STS_CHARGE_DONE 3
#define MCA_QUICK_CHG_STS_NO_CHARGING 0
#define FG_IC_MASTER 0
#define FG_IC_SLAVE 1
#define FG_IC_MAX 2
#define FG_SITE_MAX 2
#define WIRELESS_ROLE_MASTER 0
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define mca_log_debug(...) ((void)0)
#define min(a,b) ((a)<(b)?(a):(b))
#define max(a,b) ((a)>(b)?(a):(b))
#define clamp(v,l,h) min(max(v,l),h)
#define msecs_to_jiffies(x) (x)
#define MCA_DTPT_MOLECULE_SCALE 8
#define MCA_DTPT_DENOM_SCALE 10
#define BATT_PARA_CC_NAME_LEN 50
#define BATT_PARA_CC_TEMP_23 23
#define BATT_PARA_CC_TEMP_30 30
#define BATT_PARA_CC_TEMP_40 40
struct device {int unused;};struct mutex {int unused;};struct delayed_work {int pending;};
struct mca_charge_if_ops {void *data;};struct mca_votable {int unused;};
struct wls_adapter_power_cap {int max_fcc;};struct device_node {int unused;};
'''+h+r'''
static int allocations,alloc_steps,alloc_fail,read_steps,read_fail,of_refs;
static void *kcalloc(size_t n,size_t m,int f) {(void)f;if(++alloc_steps==alloc_fail)return NULL;void *p=calloc(n,m);assert(p);allocations++;return p;}
static void kfree(void *p) {if(p){assert(allocations>0);allocations--;free(p);}}
static int kstrtoint(const char *s,int base,int *v) {char *e;long n=strtol(s,&e,base);if(*e||n<INT_MIN||n>INT_MAX)return -EINVAL;*v=n;return 0;}
static const char *temp[]={"0","45","2","2","5000","4400","4450","volt","volt","stage","stage"};
static const char *volt[]={"4200","5000","1000","4400","3000","500"};
static int mca_parse_dts_count_strings(struct device_node *n,const char *name,int maxrow,int cols) {(void)n;(void)maxrow;(void)cols;return !strcmp(name,"temp")?ARRAY_SIZE(temp):ARRAY_SIZE(volt);}
static int mca_parse_dts_string_index(struct device_node *n,const char *name,int i,const char **v) {(void)n;if(++read_steps==read_fail)return -EINVAL;*v=!strcmp(name,"temp")?temp[i]:volt[i];return 0;}
static int mca_parse_dts_u32_array(struct device_node *n,const char *name,int *v,int count) {(void)n;(void)name;if(++read_steps==read_fail)return -EINVAL;memset(v,0,count*sizeof(*v));return 0;}
static struct device_node cc_node;
static struct device_node *of_find_node_by_name(struct device_node *n,const char *name) {(void)n;(void)name;of_refs++;return &cc_node;}
static void of_node_put(struct device_node *n) {if(n){assert(of_refs>0);of_refs--;}}
static int io_steps,io_fail,disabled[2],ucp[2],adc[2],parallel_off,fg_off,vout_off,votes,retry;
static void *system_wq;
static int io(void) {return ++io_steps==io_fail?-EIO:0;}
static int platform_class_cp_set_charging_enable(int role,bool en) {assert(!en&&role>=0&&role<2);disabled[role]++;return io();}
static int platform_class_cp_enable_busucp(int role,bool en) {assert(en);ucp[role]++;return io();}
static int platform_class_cp_enable_adc(int role,bool en) {assert(!en);adc[role]++;return io();}
static int strategy_class_wireless_ops_set_parallel_charge(bool en) {assert(!en);parallel_off++;return io();}
static int platform_class_wireless_set_vout(int role,int v) {(void)role;assert(v==MCA_WLS_QUICK_CHG_EXIT_VOUT);vout_off++;return io();}
static int strategy_class_fg_set_fastcharge(bool en) {assert(!en);fg_off++;return io();}
static void strategy_wireless_enable_cp_error_irq(bool en) {assert(!en);}
static int mod_delayed_work(void *q,struct delayed_work *w,int ms) {(void)q;(void)ms;w->pending++;retry++;return 1;}
static int mca_vote(struct mca_votable *v,const char *user,bool en,int value) {(void)v;(void)user;(void)value;assert(!en);votes++;return 0;}
static int mca_wireless_quick_charge_get_secure_cur(struct mca_wireless_quick_charge_info *i) {(void)i;return 0;}
static int mca_wireless_quick_charger_set_flip_cur(struct mca_wireless_quick_charge_info *i) {(void)i;return 0;}
static int mca_wireless_quick_get_parallel_volt_para(struct mca_wireless_quick_charge_info *i,int role) {(void)i;(void)role;return 0;}
static int mca_wireless_quick_charger_get_base_limit_cur(struct mca_wireless_quick_charge_info *i,int cur) {(void)i;return cur;}
'''
body=''.join(fn(n) for n in ['mca_wireless_quick_free_batt','mca_wireless_quick_charge_parse_stage_para','mca_wireless_quick_charge_parse_volt_para','mca_wireless_quick_charge_parse_temp_para','mca_wireless_quick_charge_jump_stage','mca_wireless_quick_charge_stop_charging','mca_wireless_quick_charge_select_max_ibat','mca_wireless_quick_charge_single_chg_cur_voter_cb','mca_wireless_quick_charge_multi_chg_cur_voter_cb'])
main=r'''
int main(void) {
 struct mca_wireless_quick_charge_info i={0};struct device_node n={0};
 int totalreads=0,totalalloc=0;
 for(int failure=0;failure<2;failure++)for(int f=0;f<64;f++){
  alloc_steps=read_steps=0;alloc_fail=read_fail=0;
  assert(!mca_wireless_quick_charge_parse_temp_para(&n,0,"temp",&i,0));
  void *old=i.batt_para[0].temp_info;int before=allocations;
  alloc_steps=read_steps=0;if(failure)read_fail=f;else alloc_fail=f;
  int ret=mca_wireless_quick_charge_parse_temp_para(&n,0,"temp",&i,0);
  if(!f){assert(!ret);totalreads=read_steps;totalalloc=alloc_steps;}
  else if(f<=(failure?totalreads:totalalloc)){assert(ret<0&&i.batt_para[0].temp_info==old&&allocations==before);}
  else assert(!ret);
  mca_wireless_quick_free_batt(&i.batt_para[0]);assert(!allocations&&!of_refs);
 }
 assert(mca_wireless_quick_charge_parse_temp_para(&n,-1,"temp",&i,0)==-EINVAL);
 alloc_fail=read_fail=0;assert(!mca_wireless_quick_charge_parse_temp_para(&n,0,"temp",&i,0));
 struct mca_wireless_quick_charge_volt_para_info *v=&i.batt_para[0].temp_info[0].volt_info;
 assert(mca_wireless_quick_charge_jump_stage(-1,v)==0);assert(mca_wireless_quick_charge_jump_stage(100,v)==3);for(int k=0;k<4;k++)v->stage_para[k]=1;assert(mca_wireless_quick_charge_jump_stage(0,v)==3);
 assert(mca_wireless_quick_charge_select_max_ibat(&i)==0);
 i.proc_data.cur_volt_para[0]=v;i.proc_data.wls_power.max_fcc=9000;i.proc_data.single_curr=6000;i.proc_data.max_curr=9000;i.proc_data.temp_max_cur[0]=9000;i.proc_data.sw_qc_ichg=9000;i.proc_data.sw_thermal_ichg=9000;
 assert(!mca_wireless_quick_charge_single_chg_cur_voter_cb(NULL,&i,2500,NULL));assert(!mca_wireless_quick_charge_multi_chg_cur_voter_cb(NULL,&i,3500,NULL));assert(mca_wireless_quick_charge_select_max_ibat(&i)==2500);i.proc_data.cur_work_cp=MCA_WLS_QUICK_CHG_CP_DUAL;assert(mca_wireless_quick_charge_select_max_ibat(&i)==3500);i.proc_data.debug_qc_ichg=8000;assert(mca_wireless_quick_charge_select_max_ibat(&i)==3500);i.proc_data.cur_stage[0]=100;assert(!mca_wireless_quick_charge_select_max_ibat(&i));
 mca_wireless_quick_free_batt(&i.batt_para[0]);assert(!allocations);
 for(int f=1;f<=9;f++) {
  memset(&i,0,sizeof(i));i.hardware_active=true;i.cp_type=MCA_CP_TYPE_PARALLEL;i.online=true;i.proc_data.enable_quickchg=1;io_fail=f;io_steps=retry=0;memset(disabled,0,sizeof(disabled));memset(adc,0,sizeof(adc));
  assert(mca_wireless_quick_charge_stop_charging(&i)==-EIO);assert(i.stop_pending&&i.hardware_active&&i.proc_data.enable_quickchg&&retry==1);assert(disabled[0]&&disabled[1]);if(f==1)assert(!adc[0]);if(f==4)assert(!adc[1]);
  io_fail=0;assert(!mca_wireless_quick_charge_stop_charging(&i));assert(!i.stop_pending&&!i.hardware_active&&!i.proc_data.enable_quickchg);
 }
 memset(&i,0,sizeof(i));io_steps=0;assert(!mca_wireless_quick_charge_stop_charging(&i)&&!io_steps);
 i.hardware_active=true;i.stopping=true;io_fail=1;retry=0;assert(mca_wireless_quick_charge_stop_charging(&i)==-EIO&&!retry);
 printf("PASS: %d allocations/%d table reads faulted, transactional replacement, stage/current bounds, nine stop I/O failures and retry\n",totalalloc,totalreads);
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+body+main)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
# Reverse exit has different rail ownership: exercise all attempted sources.
s=(base/'mca_wireless_revchg.c').read_text()
revpre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
#define PMIC_REV_BOOST 0
#define PMIC_HBOOST 1
#define EXTERNAL_BOOST 2
#define CHARGER_ADAPTER 3
#define REV_EN_BOOST 2
#define WLS_PEN_CHARGE_TYPE 1
#define WRITE_ONCE(x,v) ((x)=(v))
#define WIRELESS_ROLE_MASTER 0
#define MAIN_BUCK_CHARGER 0
#define READ_ONCE(x) (x)
#define set_bit(b,p) (*(p)|=1UL<<(b))
#define min(a,b) ((a)<(b)?(a):(b))
#define CP_ROLE_MASTER 0
#define REVCHG_TYPE 1
#define mca_log_err(...) ((void)0)
#define test_bit(b,p) ((*(p))&(1UL<<(b)))
struct mca_wireless_revchg {bool tx_attempted,stopping,stop_pending,ovp_blocked,external_boost_attempted,support_tx_only;int rev_boost_voltage;unsigned long boost_attempted,pmic_boost_attempted;struct {bool reverse_chg_en;} proc_data;};
static int step,fail,tx,hboost,external,pmic[3];
static int live_src,gate_off,persistent_i2c,rx_present;
static int io(void){return ++step==fail?-EIO:0;}
static int platform_class_wireless_enable_reverse_chg(int role,bool en){(void)role;(void)en;tx++;return io();}
static int platform_class_wireless_set_charge_type(int role,int type){(void)role;assert(type==1);return io();}
static int platform_class_wireless_set_hboost_enable(int role,bool en){(void)role;hboost++;return io();}
static int platform_class_wireless_set_external_boost_enable(int role,bool en){(void)role;external++;int rc=io();if(!rc){if(en)live_src|=4;else live_src&=~4;}return rc;}
static int platform_class_buckchg_ops_set_boost_enable(int role,int cmd){(void)role;assert((cmd>>16)==REV_EN_BOOST);int src=(cmd>>8)&255;assert(src<3);pmic[src]++;int rc=io();if(!rc){if(cmd&1)live_src|=1<<src;else live_src&=~(1<<src);}return rc;}
'''
revpre += r'''
static void msleep(int ms){(void)ms;}
static int platform_class_cp_enable_ovpgate_with_check(int role,int type,bool enable){(void)role;(void)type;int rc=io();if(!rc)gate_off=!enable;return rc;}
static int platform_class_buckchg_ops_set_boost_voltage(int role,int cmd){(void)role;assert((cmd&65535)>=5000&&(cmd&65535)<=6000);return io();}
static int platform_class_wireless_is_present(int role,int *v){(void)role;*v=rx_present;return io();}
static int platform_class_wireless_check_i2c_is_ok(int role){(void)role;int rc=io();return persistent_i2c?-EIO:rc;}
'''
revmain=r'''
int main(void){
 struct mca_wireless_revchg i={0};assert(!mca_wireless_rev_quiesce(&i)&&!step);
 for(int f=1;f<=5;f++){
  i=(struct mca_wireless_revchg){.tx_attempted=true,.boost_attempted=7,.pmic_boost_attempted=3,.external_boost_attempted=true,.proc_data.reverse_chg_en=true};step=tx=hboost=external=pmic[0]=pmic[1]=0;fail=f;
  assert(mca_wireless_rev_quiesce(&i)==-EIO);assert(step==5&&tx==1&&hboost==1&&external==1&&pmic[0]==1&&pmic[1]==1);assert(i.tx_attempted&&i.boost_attempted==7&&i.proc_data.reverse_chg_en);
  fail=0;assert(!mca_wireless_rev_quiesce(&i));assert(!i.tx_attempted&&!i.boost_attempted&&!i.proc_data.reverse_chg_en);
 }
 for(int f=1;f<=8;f++){
  i=(struct mca_wireless_revchg){.rev_boost_voltage=6000};step=live_src=gate_off=0;fail=f;
  assert(mca_wireless_rev_enable_boost(&i,PMIC_REV_BOOST,false)==-EIO);assert(!live_src&&!gate_off&&!i.boost_attempted);
 }
 i=(struct mca_wireless_revchg){.rev_boost_voltage=6000};step=0;fail=9;assert(!mca_wireless_rev_enable_boost(&i,PMIC_REV_BOOST,false));assert(live_src==1&&gate_off);fail=0;assert(!mca_wireless_rev_quiesce(&i)&&!live_src&&!gate_off);
 persistent_i2c=1;step=0;assert(mca_wireless_rev_enable_boost(&i,EXTERNAL_BOOST,false)==-EIO&&!live_src&&!gate_off);persistent_i2c=0;
 step=0;assert(!mca_wireless_rev_enable_boost(&i,EXTERNAL_BOOST,true));assert(live_src==4&&i.pmic_boost_attempted==4&&!i.external_boost_attempted);assert(!mca_wireless_rev_quiesce(&i)&&!live_src);
 for(int f=1;f<=2;f++){
  i=(struct mca_wireless_revchg){.support_tx_only=true};step=0;fail=f;
  assert(mca_wireless_rev_start_tx(&i)==-EIO);assert(!i.tx_attempted&&!i.stop_pending);
 }
 fail=0;i=(struct mca_wireless_revchg){.support_tx_only=true};step=0;assert(!mca_wireless_rev_start_tx(&i)&&i.tx_attempted);assert(!mca_wireless_rev_quiesce(&i));
 i.stop_pending=true;step=0;assert(mca_wireless_rev_start_tx(&i)==-EBUSY&&!step);i.stop_pending=false;
 i.rev_boost_voltage=6000;i.stopping=true;step=0;assert(mca_wireless_rev_enable_boost(&i,0,false)==-ESHUTDOWN&&!step);
 puts("PASS: checked boost start/rollback, I2C retry, firmware PMIC route, runtime OVP restore and shutdown rejection");
 puts("PASS: reverse TX and all attempted boost rails, five independent failures, first-error retention, retry, idle ownership");
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(revpre+fn('mca_wireless_rev_quiesce')+fn('mca_wireless_rev_enable_boost')+fn('mca_wireless_rev_start_tx')+revmain)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fault injection into actual Buck/QC ownership, probe and stop functions.
Kernel registries/workqueues and hardware are modeled, not kernel-runtime tested.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
base=root/'drivers/power/supply/mca/mca_strategy/strategy_charger'
def fn(s,n):
 m=re.search(r'static\s+(?:int|void)\s+'+n+r'\([^;]*?\n\{',s);assert m,n
 p=m.end();d=1
 while d:
  if s[p]=='{':d+=1
  elif s[p]=='}':d-=1
  p+=1
 return s[m.start():p]+'\n'
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#define GFP_KERNEL 0
#define EPROBE_DEFER 517
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define IS_ERR(x) ((uintptr_t)(x)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(x) (!(x)||IS_ERR(x))
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define MCA_VOTE_MIN 0
#define MCA_VOTE_MAX 1
#define MCA_VOTE_AND 2
#define MCA_VOTE_OR 3
#define MCA_EVENT_TYPE_PANEL 0
#define MCA_EVENT_TYPE_THERMAL_TEMP 1
#define MCA_EVENT_TYPE_CHARGER_CONNECT 2
#define MCA_EVENT_USB_CONNECT 1
#define MCA_SMARTCHG_IF_CHG_TYPE_BUCK 0
#define MCA_SMARTCHG_IF_CHG_TYPE_QC 1
#define STRATEGY_FUNC_TYPE_BUCK_CHARGE 0
#define STRATEGY_FUNC_TYPE_QUICK_CHARGE 1
#define MAIN_BUCK_CHARGER 0
#define CP_ROLE_MASTER 0
#define CP_ROLE_SLAVE 1
#define MCA_CP_TYPE_PARALLEL 1
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
struct device { void *data; };
struct platform_device { struct device dev; };
struct notifier_block { void *notifier_call; int priority; };
struct mca_charge_if_ops { void *data; };
struct mca_smartchg_if_ops { void *data; };
struct delayed_work { bool initialized,disabled,pending; };
struct mutex { int unused; };
static void mutex_init(struct mutex *m) {(void)m;}
static void mutex_lock(struct mutex *m) {(void)m;}
static void mutex_unlock(struct mutex *m) {(void)m;}
static struct delayed_work *works[16];static int nworks;
static void init_work(struct delayed_work *w) {assert(!w->initialized);w->initialized=true;works[nworks++]=w;}
#define INIT_DELAYED_WORK(w,fn) init_work(w)
static int disable_count,stop_io,steps,fail_at,active_slots,registered[6],sysfs_created;
static bool folded,borrowed_flip=true;
static void *allocated;
static int table_allocations;
static void *table_alloc(size_t n) {void *p=calloc(1,n);assert(p);table_allocations++;return p;}
static void kfree(void *p) {if(p){assert(table_allocations>0);table_allocations--;free(p);}}
static int step(void) {return ++steps==fail_at?-EIO:0;}
static void *devm_kzalloc(struct device *dev,size_t n,int flag) {(void)dev;(void)flag;assert(!allocated);return allocated=calloc(1,n);}
static void platform_set_drvdata(struct platform_device *p,void *i) {p->dev.data=i;}
static void *platform_get_drvdata(struct platform_device *p) {return p->dev.data;}
static int schedule(struct delayed_work *w) {if(w->disabled)return 0;w->pending=true;return 1;}
static void late_enqueue(void) {for(int i=0;i<nworks;i++)schedule(works[i]);}
static int disable_delayed_work_sync(struct delayed_work *w) {
 assert(w->initialized&&!w->disabled);w->disabled=true;w->pending=false;disable_count++;
 late_enqueue(); /* model another producer racing each individual drain */
 return 1;
}
struct mca_votable { void *owner; char name[40]; };
static struct mca_votable slots[32],borrowed;
static int nslots;
static struct mca_votable *mca_create_owned_votable(const char *name,int type,
 int (*cb)(struct mca_votable *,void *,int,const char *),int def,void *owner) {
 (void)type;(void)cb;(void)def;int ret=step();if(ret)return ERR_PTR(ret);
 int i;for(i=0;i<nslots;i++)if(!strcmp(slots[i].name,name))break;
 if(i==nslots){assert(nslots<32);strcpy(slots[nslots++].name,name);}
 assert(!slots[i].owner);slots[i].owner=owner;active_slots++;return &slots[i];
}
static int mca_detach_owned_votable(struct mca_votable *v,void *owner) {
 assert(v->owner==owner);v->owner=NULL;active_slots--;late_enqueue();return 0;
}
static struct mca_votable *mca_find_votable(const char *name) {
 if(!strcmp(name,"smartchg_delta_ichg"))return NULL;
 if(!strcmp(name,"flip_charge_curr")&&!borrowed_flip)return NULL;
 return &borrowed;
}
static int mca_get_effective_result(struct mca_votable *v) {(void)v;return -ENODEV;}
static int mca_vote(struct mca_votable *v,const char *who,bool en,int value) {
 (void)who;(void)en;(void)value;assert(v&&!IS_ERR(v));return step();
}
static int registration(int slot) {int ret=step();if(ret)return ret;assert(!registered[slot]);registered[slot]=1;late_enqueue();return 0;}
static void unregistration(int slot) {assert(registered[slot]);registered[slot]=0;late_enqueue();}
static int mca_strategy_ops_register(int type,void *event,void *get,void *set,void *data) {
 (void)type;(void)event;(void)get;(void)set;assert(data);return registration(0);
}
static int mca_strategy_ops_unregister(int type,void *data) {(void)type;assert(data);unregistration(0);return 0;}
static struct mca_charge_if_ops *charge_ops;
static int mca_charge_if_ops_register(struct mca_charge_if_ops *ops) {int ret=registration(1);if(!ret)charge_ops=ops;return ret;}
static int mca_charge_if_ops_unregister(struct mca_charge_if_ops *ops) {assert(charge_ops==ops);unregistration(1);charge_ops=NULL;return 0;}
static void *smart_data;
static int mca_smartchg_if_ops_register(struct mca_smartchg_if_ops *ops) {int ret=registration(2);if(!ret)smart_data=ops->data;return ret;}
static int mca_smartchg_if_ops_unregister(unsigned int type,void *data) {(void)type;assert(smart_data==data);unregistration(2);smart_data=NULL;return 0;}
static int mca_event_block_notify_register(int type,struct notifier_block *nb) {(void)nb;return registration(3+type);}
static int mca_event_block_notify_unregister(int type,struct notifier_block *nb) {(void)nb;unregistration(3+type);return 0;}
static void mca_event_block_notify(int type,int event,void *v) {(void)type;(void)event;(void)v;late_enqueue();}
static int register_reboot_notifier(struct notifier_block *nb) {(void)nb;return registration(5);}
static int unregister_reboot_notifier(struct notifier_block *nb) {(void)nb;unregistration(5);return 0;}
static void check_drained(void) {
 assert(!active_slots&&!sysfs_created&&!charge_ops&&!smart_data);
 for(int i=0;i<6;i++)assert(!registered[i]);
 for(int i=0;i<nworks;i++)assert(works[i]->disabled&&!works[i]->pending);
}
static void reset(int fail) {
 assert(!active_slots&&!table_allocations);free(allocated);allocated=NULL;nworks=0;disable_count=stop_io=steps=sysfs_created=0;
 fail_at=fail;memset(registered,0,sizeof(registered));folded=false;borrowed_flip=true;
}
'''
for kind in ('buck','qc'):
 s=(base/('mca_strategy_buckchg.c' if kind=='buck' else 'mca_strategy_quickchg.c')).read_text()
 names=('strategy_buckchg_init_voter','strategy_buckchg_stop','strategy_buckchg_class_probe','strategy_buckchg_class_remove','strategy_buckchg_class_shutdown') if kind=='buck' else ('mca_quick_charge_create_voter','mca_quick_charge_stop','mca_quick_charge_probe','mca_quick_charge_remove','mca_quick_charge_platform_shutdown')
 init=fn(s,names[0]);stop=fn(s,names[1]);probe=fn(s,names[2]);body=init+stop+probe+fn(s,names[3])+fn(s,names[4])
 cbs=set(re.findall(r'mca_create_owned_votable\(\s*"[^"]+",\s*\w+,\s*(\w+)',init))
 callbacks=''.join('static int '+n+'(struct mca_votable *v,void *d,int x,const char *s){(void)v;(void)d;(void)x;(void)s;return 0;}\n' for n in sorted(cbs))
 if kind=='buck':
  h=(base/'inc/mca_strategy_buckchg.h').read_text();defs='\n'.join(re.findall(r'^#define STATEGY_\w+[^\n]*',h,re.M))+'\n'
  voters=['chg_enable_voter','input_suppend_voter','input_limit_voter','charge_limit_voter','iterm_voter','vterm_voter','input_voltage_voter','buck_5v_in_voter','buck_5v_ich_voter','buck_9v_in_voter','buck_9v_ich_voter']
  ws=re.findall(r'INIT_DELAYED_WORK\(&info->(\w+),',probe)
  decl='struct strategy_buckchg_dev {struct device *dev; bool stopping,ready,strategy_registered,charge_if_registered,smartchg_registered,panel_registered,thermal_registered; struct mca_charge_if_ops charge_if_ops;struct notifier_block panel_nb,thermal_board_nb;int strategy_init_done,chg_batt_auth_failed;struct {int voltage;} proc_data;'+''.join('struct mca_votable *'+v+';' for v in voters)+''.join('struct delayed_work '+w+';' for w in ws)+'};\n'
  stubs=r'''
static const struct mca_charge_if_ops g_strategy_buckchg_if_ops={0};
static const struct mca_smartchg_if_ops g_buck_smartchg_if_ops={0};
static void strategy_buckchg_parse_dt(struct strategy_buckchg_dev *i) {i->chg_batt_auth_failed=2000;}
static int strategy_buckchg_quiesce_hardware(struct strategy_buckchg_dev *i) {
 assert(i->stopping);check_drained();stop_io++;return 0;
}
static int platform_class_buckchg_ops_get_online(int role,int *v) {(void)role;*v=1;return 0;}
static void strategy_buckchg_process_event(void) {}
static void strategy_buckchg_get_status(void) {}
static void strategy_buckchg_set_config(void) {}
static void strategy_buckchg_thermal_notifier_cb(void) {}
static void strategy_buckchg_panel_notifier_cb(void) {}
'''
 else:
  body=fn(s,'mca_quick_charge_free_batt_para')+body
  defs='';ws=['monitor_work','pps_ptf_work','vfc_work'];voters=['input_suspend_voter','buck_input_voter','buck_charge_curr_voter','term_volt_voter','flip_charge_curr_voter','thermal_flip_voter','chg_disable_voter','chg_en_voter','single_chg_cur_voter','multi_chg_cur_voter']
  decl='struct mca_quick_charge_volt_para_info {void *stage_para,*volt_para;};struct mca_quick_charge_temp_para_info {struct mca_quick_charge_volt_para_info volt_info,volt_ffc_info;};struct mca_quick_charge_batt_para_info {int temp_para_size;struct mca_quick_charge_temp_para_info *temp_info;};struct mca_quick_charge_info {struct device *dev;bool hardware_ready,teardown_done,ready,stopping,strategy_registered,charge_if_registered,smartchg_registered,sysfs_created,reboot_registered;struct mca_charge_if_ops charge_if_ops;struct notifier_block shutdown_notifier;struct mutex data_lock,buck_parallel_lock;int cp_chip_vendor,support_base_flip,cp_type;struct {int delta_ichg;} smartchg_data;struct mca_votable *voter[6];struct mca_quick_charge_batt_para_info batt_para[3],base_flip_para[2];'+''.join('struct mca_votable *'+v+';' for v in voters)+''.join('struct delayed_work '+w+';' for w in ws)+'};\n'
  stubs=r'''
static const struct mca_charge_if_ops g_strategy_quickchg_if_ops={0};
static const struct mca_smartchg_if_ops g_quickchg_smartchg_if_ops={0};
static void mca_quick_charge_diag_begin(void) {}
static void mca_quick_charge_diag_attach(struct mca_quick_charge_info *i) {(void)i;}
static int mca_quick_charge_diag_finish(const char *s,int ret,int dep) {(void)s;(void)dep;return ret;}
static int strategy_class_fg_ops_is_init_ok(void) {return 1;}
static int platform_class_cp_get_chip_vendor(int role,int *vendor) {(void)role;*vendor=1;return 0;}
static int platform_class_cp_get_probe_ok(int role) {(void)role;return 0;}
static int mca_quick_charge_parse_dt(struct mca_quick_charge_info *i) {
 i->support_base_flip=folded;i->cp_type=MCA_CP_TYPE_PARALLEL;
 for(int a=0;a<5;a++) {
  struct mca_quick_charge_batt_para_info *p=a<3?&i->batt_para[a]:&i->base_flip_para[a-3];
  p->temp_para_size=2;p->temp_info=table_alloc(2*sizeof(*p->temp_info));
  for(int j=0;j<2;j++) {
   p->temp_info[j].volt_info.stage_para=table_alloc(8);
   p->temp_info[j].volt_info.volt_para=table_alloc(16);
   p->temp_info[j].volt_ffc_info.stage_para=table_alloc(8);
   p->temp_info[j].volt_ffc_info.volt_para=table_alloc(16);
  }
 }
 return step();
}
static void mca_quick_charge_init_data(struct mca_quick_charge_info *i) {(void)i;}
static int mca_quick_charge_create_group(struct device *d) {(void)d;int ret=step();if(!ret)sysfs_created=1;return ret;}
static void mca_quick_charge_remove_group(struct device *d) {(void)d;assert(sysfs_created);sysfs_created=0;late_enqueue();}
static int platform_class_cp_set_charging_enable(int role,bool enable) {(void)role;assert(!enable);check_drained();stop_io++;return 0;}
static int mca_quick_charge_quiesce_hardware(struct mca_quick_charge_info *i) {
 assert(i->stopping&&!i->ready);check_drained();stop_io++;
 /* Actual hardware stop is exercised by test-mca-wired-stop.py. */
 return 0;
}
static void mca_quick_charge_process_event(void) {}
static void mca_quick_charge_get_status(void) {}
static void mca_quick_charge_shutdown(void) {}
'''
 test='''int main(void){struct platform_device p={0};reset(0);assert(!'''+names[2]+'''(&p));int total=steps;assert(active_slots==11);'''+names[3]+'''(&p);check_drained();assert(disable_count=='''+str(len(ws))+''');'''+names[4]+'''(&p);assert(disable_count=='''+str(len(ws))+''');
 for(int n=1;n<=total;n++){reset(n);int ret='''+names[2]+'''(&p);assert(ret==-EIO);if(nworks&&disable_count)check_drained();else assert(!active_slots);}
 reset(0);assert(!'''+names[2]+'''(&p));'''+names[3]+'''(&p);check_drained();
'''
 if kind=='qc':test+=''' reset(0);borrowed_flip=false;assert(!mca_quick_charge_probe(&p));mca_quick_charge_remove(&p);check_drained();reset(0);folded=true;borrowed_flip=false;assert(mca_quick_charge_probe(&p)==-EPROBE_DEFER&&!active_slots);'''
 test+=' reset(0);puts("PASS: actual '+kind+' probe fault injection, 11 owned voters, registry unwind, disabled work and re-probe");}\n'
 with tempfile.TemporaryDirectory(prefix='mca-provider-'+kind+'-') as d:
  p=Path(d);(p/'test.c').write_text(pre+defs+decl+callbacks+stubs+body+test)
  subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

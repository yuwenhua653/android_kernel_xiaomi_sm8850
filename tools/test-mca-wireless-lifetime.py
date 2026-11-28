#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual wireless probe/unwind/stop code, with registry/workqueue fault models.
Every registration/allocation failure, duplicate ownership, retained handles and
reprobe are exercised; hardware quiesce is tested separately, not asserted here.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1];base=root/'drivers/power/supply/mca/mca_strategy/strategy_wireless'
def fn(s,n):
 m=re.search(r'(?:static\s+)?(?:struct\s+\w+\s*\*\s*|(?:int|void)\s+)'+n+r'\([^;]*?\)\s*\n\{',s);assert m,n
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
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
#define MCA_VOTE_OR 3
#define MCA_WLS_CHARGE_INPUT_SUSPEND 0
#define MAIN_BUCK_CHARGER 0
#define AUX_BUCK_CHARGER 1
#define WIRELESS_ROLE_MASTER 0
#define CP_ROLE_MASTER 0
#define CP_ROLE_SLAVE 1
#define MCA_EVENT_TYPE_CHARGER_CONNECT 2
#define MCA_EVENT_WIRELESS_CONNECT 1
#define MCA_SMARTCHG_IF_CHG_TYPE_WL_BUCK 0
#define MCA_SMARTCHG_IF_CHG_TYPE_WL_QC 0
#define STRATEGY_FUNC_TYPE_BASIC_WIRELESS 0
#define STRATEGY_FUNC_TYPE_QUICK_WIRELESS 0
#define STRATEGY_FUNC_TYPE_REV_WIRELESS 0
#define PMIC_REV_BOOST 0
#define CHARGER_ADAPTER 3
#define POWER_ON_UPDATE_TIMER 10000
#define IS_ENABLED(x) 0
#define msecs_to_jiffies(x) (x)
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
struct device {void *data;};struct platform_device {struct device dev;};
struct notifier_block {void *notifier_call;int priority;};
struct mca_charge_if_ops {void *data;};struct mca_smartchg_if_ops {void *data;};
struct delayed_work {bool initialized,disabled,pending;};struct mutex {int unused;};
static void mutex_init(struct mutex *m) {(void)m;}static void mutex_lock(struct mutex *m) {(void)m;}static void mutex_unlock(struct mutex *m) {(void)m;}
#define rcu_access_pointer(x) (x)
#define RCU_INIT_POINTER(x,v) ((x)=(v))
#define rcu_assign_pointer(x,v) ((x)=(v))
static void synchronize_srcu(int *s) {(void)s;}
struct list_head {struct list_head *next,*prev;};
static void INIT_LIST_HEAD(struct list_head *l) {l->next=l->prev=l;}
static void spin_lock_init(int *s) {*s=0;}static void init_waitqueue_head(int *s) {*s=0;}
static int steps,fail_at,nworks,ndisabled,active[4],wakeup,psy_refs,tables;
static void *allocated,*owners[4];static struct delayed_work *works[32];
static int step(void) {return ++steps==fail_at?-EIO:0;}
static void *devm_kzalloc(struct device *d,size_t n,int f) {(void)d;(void)f;if(step())return NULL;assert(!allocated);return allocated=calloc(1,n);}
static void platform_set_drvdata(struct platform_device *p,void *i) {p->dev.data=i;}
static void *platform_get_drvdata(struct platform_device *p) {return p->dev.data;}
static void init_work(struct delayed_work *w) {assert(!w->initialized);w->initialized=true;works[nworks++]=w;}
#define INIT_DELAYED_WORK(w,f) init_work(w)
static int schedule_delayed_work(struct delayed_work *w,int ms) {(void)ms;assert(w->initialized);if(w->disabled)return 0;w->pending=true;return 1;}
static int disable_delayed_work_sync(struct delayed_work *w) {assert(w->initialized&&!w->disabled);w->disabled=true;w->pending=false;ndisabled++;assert(!schedule_delayed_work(w,0));return 1;}
static int strategy_class_fg_ops_is_init_ok(void) {return 1;}
static int device_init_wakeup(struct device *d,bool en) {(void)d;if(en){int r=step();if(r)return r;assert(!wakeup);wakeup=1;}else{assert(wakeup);wakeup=0;}return 0;}
static void pm_relax(struct device *d) {(void)d;}
static void *power_supply_get_by_name(const char *s) {(void)s;psy_refs++;return &psy_refs;}
static void power_supply_put(void *p) {assert(p==&psy_refs&&psy_refs);psy_refs--;}
static int reg(int idx,void *owner) {int r=step();if(r)return r;if(active[idx])return -EBUSY;active[idx]=1;owners[idx]=owner;return 0;}
static void unreg(int idx,void *owner) {assert(active[idx]&&owners[idx]==owner);active[idx]=0;owners[idx]=NULL;}
static int mca_strategy_ops_register(int t,void *f,void *g,void *set,void *data) {(void)t;(void)f;(void)g;(void)set;return reg(0,data);}
static int mca_strategy_ops_unregister(int t,void *data) {(void)t;unreg(0,data);return 0;}
static int mca_charge_if_ops_register(struct mca_charge_if_ops *o) {return reg(1,o->data);}
static int mca_charge_if_ops_unregister(struct mca_charge_if_ops *o) {unreg(1,o->data);return 0;}
static int mca_smartchg_if_ops_register(struct mca_smartchg_if_ops *o) {return reg(2,o->data);}
static int mca_smartchg_if_ops_unregister(int t,void *data) {(void)t;unreg(2,data);return 0;}
static int register_reboot_notifier(struct notifier_block *n) {return reg(1,n);}
static int unregister_reboot_notifier(struct notifier_block *n) {unreg(1,n);return 0;}
static int sysfs_create(struct device *d) {return reg(3,d);}
static void sysfs_remove(struct device *d) {unreg(3,d);}
static int platform_class_buckchg_ops_set_wls_hiz(int role,bool en) {(void)role;assert(en);return 0;}
static int platform_class_wireless_is_present(int role,int *online) {(void)role;*online=0;return step();}
static int mca_event_block_notify(int t,int e,void *p) {(void)t;(void)e;(void)p;return 0;}
struct mca_votable {const char *name;void *owner;};static struct mca_votable slots[24];static int nslots;
static struct mca_votable *mca_create_owned_votable(const char *name,int t,void *cb,int v,void *owner) {
 (void)t;(void)cb;(void)v;int r=step();if(r)return ERR_PTR(r);
 for(int i=0;i<nslots;i++)if(!strcmp(slots[i].name,name)){if(slots[i].owner)return ERR_PTR(-EBUSY);slots[i].owner=owner;return &slots[i];}
 assert(nslots<24);slots[nslots]=(struct mca_votable){name,owner};return &slots[nslots++];
}
static int mca_detach_owned_votable(struct mca_votable *v,void *owner) {assert(v->owner==owner);v->owner=NULL;return 0;}
static struct mca_votable borrowed;static struct mca_votable *mca_find_votable(const char *name) {(void)name;return &borrowed;}
static int mca_get_effective_result(struct mca_votable *v) {(void)v;return 0;}
static int platform_class_cp_get_chip_vendor(int r,int *v) {(void)r;*v=1;return 0;}
static int platform_class_cp_get_probe_ok(int r) {(void)r;return 0;}
static void dummy(void) {}
static int dummy_voter(struct mca_votable *v,void *d,int e,const char *c) {(void)v;(void)d;(void)e;(void)c;return 0;}
'''
for kind,typ,prefix,probe,stop,init in [
 ('basic','strategy_wireless_dev','basic_wls','basic_wireless_class_probe','basic_wireless_stop','strategy_wireless_init_work'),
 ('quick','mca_wireless_quick_charge_info','quick','mca_wireless_quick_charge_probe','mca_wireless_quick_stop',None),
 ('revchg','mca_wireless_revchg','wls_rev','mca_wireless_revchg_probe','mca_wireless_rev_stop','mca_wireless_rev_init_work')]:
 s=(base/('mca_'+('wireless_revchg' if kind=='revchg' else kind+'_wireless')+'.c')).read_text()
 worknames=re.findall(r'INIT_DELAYED_WORK\(&info->(\w+),',fn(s,init) if init else fn(s,probe))
 setup='';body='';fields='struct device *dev;bool ready,stopping,strategy_registered,charge_if_registered,smartchg_registered,hardware_ready,sysfs_created,wakeup_enabled,notifier_registered;struct mca_charge_if_ops charge_if_ops;struct mutex data_lock;'+''.join('struct delayed_work '+w+';' for w in worknames)
 if kind=='basic':
  owned=re.findall(r'&info->(\w+)',fn(s,'strategy_wireless_destroy_voters'))
  fields+=''.join('struct mca_votable *'+v+';' for v in owned)+'struct list_head header,irq_header;int list_lock,wait_que,strategy_init_done,support_multi_buck;bool wl_irq_running;void *batt_psy;'
  setup+='static struct '+typ+' *g_basic_wls_info;static struct mutex basic_wls_publish_lock;static int basic_wls_srcu;\n'
  setup+='static int strategy_wireless_parse_dt(struct '+typ+' *i) {(void)i;tables++;return step();}\n'
  setup+='static void strategy_wireless_free_cmd_tables(struct '+typ+' *i) {(void)i;assert(tables);tables--;}\n'
  setup+='static void strategy_wireless_free_queues(struct '+typ+' *i) {assert(i->header.next==&i->header&&i->irq_header.next==&i->irq_header);}\n'
  setup+='#define strategy_wireless_create_group sysfs_create\n#define strategy_wireless_remove_group sysfs_remove\n#define strategy_wireless_process_event dummy\n#define strategy_wireless_get_status dummy\n'
  setup+='static const struct mca_charge_if_ops g_strategy_wireless_if_ops={0};static const struct mca_smartchg_if_ops g_basic_smartchg_if_ops={0};\n'
  initv=fn(s,'strategy_wireless_init_voter');callbacks=re.findall(r'\b(strategy_wireless_\w+)\s*,',initv)
  setup+=''.join('#define '+cb+' dummy_voter\n' for cb in set(callbacks))
  body=''.join(fn(s,n) for n in ['strategy_wireless_create_voter','strategy_wireless_destroy_voters','strategy_wireless_init_voter',init,stop,probe])
 elif kind=='quick':
  fields+='struct mca_votable *chg_disable_voter,*single_chg_cur_voter,*multi_chg_cur_voter,*thermal_flip_voter,*input_limit_voter,*chg_enable_voter,*charge_limit_voter,*flip_charge_curr_voter;int cp_chip_vendor,online;struct {int delta_ichg;} smartchg_data;struct {int sw_qc_ichg,sw_thermal_ichg;} proc_data;int batt_para[2],base_flip_para[2];'
  setup+='static int mca_wireless_quick_charge_parse_dt(struct '+typ+' *i) {for(int n=0;n<2;n++){i->batt_para[n]=i->base_flip_para[n]=1;tables+=2;}return step();}\n'
  setup+='static void mca_wireless_quick_free_batt(int *i) {if(*i){tables--;*i=0;}}\nstatic int mca_wireless_quick_charge_stop_charging(struct '+typ+' *i){(void)i;return 0;}\n'
  for n in ['mca_wireless_quick_charge_process_event','mca_wireless_quick_charge_get_status','mca_wireless_quick_charge_chg_disable_voter_cb','mca_wireless_quick_charge_single_chg_cur_voter_cb','mca_wireless_quick_charge_multi_chg_cur_voter_cb','mca_wireless_quick_charge_thermal_flip_voter_cb']:setup+='#define '+n+' dummy\n'
  setup+='static const struct mca_charge_if_ops g_quick_wireless_if_ops={0};static const struct mca_smartchg_if_ops g_quick_wireless_smartchg_if_ops={0};\n'
  body=''.join(fn(s,n) for n in ['mca_wireless_quick_charge_create_voter',stop,probe])
 else:
  fields+='struct mca_votable *usbin_rev_disable_voter;struct notifier_block shutdown_notifier;int rev_boost_default,rev_boost_src;struct {bool user_reverse_chg;} proc_data;'
  setup+='static struct '+typ+' *g_wls_rev_info;static struct mutex wls_rev_publish_lock;static int wls_rev_srcu;\n'
  setup+='static int mca_wireless_rev_parse_dt(struct '+typ+' *i) {i->rev_boost_default=0;return step();}\nstatic int mca_wireless_rev_quiesce(struct '+typ+' *i) {(void)i;return 0;}\n'
  setup+='#define strategy_wireless_rev_create_group sysfs_create\n#define strategy_wireless_rev_remove_group sysfs_remove\n'
  for n in ['mca_wireless_rev_process_event','mca_wireless_rev_get_status','mca_wireless_usbin_rev_disable_voter_cb','mca_wireless_rev_shutdown_cb']:setup+='#define '+n+' dummy\n'
  body=''.join(fn(s,n) for n in [init,stop,probe])
 stopcall=stop+'(p.dev.data'+(', false' if kind=='revchg' else '')+')'
 main='''int main(void) {
 int maxsteps=0;
 for(int fail=0;fail<=maxsteps+1;fail++) {
  struct platform_device p={0};steps=0;fail_at=fail;nworks=ndisabled=0;
  int ret='''+probe+'''(&p);
  if(!fail){assert(!ret);maxsteps=steps;assert(active[0]);}
  else if(fail<=maxsteps)assert(ret<0);
  if(p.dev.data) {'''+stopcall+';'+stopcall+''';assert(ndisabled==nworks);}
  for(int n=0;n<4;n++)assert(!active[n]);for(int n=0;n<nslots;n++)assert(!slots[n].owner);
  assert(!tables&&!wakeup&&!psy_refs);free(allocated);allocated=NULL;
  if(fail==maxsteps+1)break;
 }
 /* A provider that already owns a name survives a failed second probe. */
 if(nslots){void *other=&slots;slots[0].owner=other;struct platform_device p={0};fail_at=0;steps=0;nworks=ndisabled=0;assert('''+probe+'''(&p)<0);assert(slots[0].owner==other);slots[0].owner=NULL;free(allocated);allocated=NULL;for(int n=0;n<4;n++)assert(!active[n]);assert(!tables&&!wakeup&&!psy_refs);}
 printf("PASS: '''+kind+''' wireless probe/unwind/reprobe, %d failure steps, '''+str(len(worknames))+''' work drains, stable owned handles\\n",maxsteps);
}'''
 with tempfile.TemporaryDirectory() as d:
  c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+'struct '+typ+'{'+fields+'};\n'+setup+body+main)
  subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})

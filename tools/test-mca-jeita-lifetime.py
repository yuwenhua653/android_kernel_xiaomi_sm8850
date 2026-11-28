#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual JEITA probe/dispatch/stop C with modeled registries and workqueue.

Covers provider publication, error unwind, non-foldable behavior and re-probe.
Does not validate temperature hardware or the full charging policy.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1];mca=root/'drivers/power/supply/mca'
s=(mca/'mca_strategy/strategy_charger/mca_buckchg_jeita.c').read_text()
h=(mca/'mca_strategy/strategy_charger/inc/mca_buckchg_jeita.h').read_text().replace('#include <linux/mutex.h>','')
smart=(mca/'include/mca/smartchg/smart_chg_class.h').read_text().replace('#include <linux/types.h>','')
events=(mca/'include/mca/common/mca_event.h').read_text().replace('#include <linux/notifier.h>','struct notifier_block;')
def fn(name):
 m=re.search(r'static (?:int|void) '+name+r'\([^;]+?\n\{',s);assert m,name
 pos=m.end();level=1
 while level:
  if s[pos]=='{':level+=1
  elif s[pos]=='}':level-=1
  pos+=1
 return s[m.start():pos]+'\n'
head=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
#define GFP_KERNEL 0
#define EPROBE_DEFER 517
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define IS_ENABLED(x) (x)
#ifndef CONFIG_TARGET_PRODUCT_NEZHA
#define CONFIG_TARGET_PRODUCT_NEZHA 1
#endif
#define MCA_VOTE_MIN 0
#define LOADSW_ROLE_MASTER 0
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define dev_err_probe(dev,ret,...) (ret)
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define IS_ERR(x) ((uintptr_t)(x)>=(uintptr_t)-4095)
#define msecs_to_jiffies(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
enum { STRATEGY_FUNC_TYPE_JEITA, STRATEGY_FUNC_TYPE_BUCK_CHARGE, STRATEGY_FUNC_TYPE_BASIC_WIRELESS };
enum { STRATEGY_STATUS_TYPE_ONLINE, STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM,
 STRATEGY_STATUS_TYPE_JEITA_NORMAL_VTERM, STRATEGY_STATUS_TYPE_JEITA_FFC_VTERM, STRATEGY_STATUS_TYPE_JEITA_COLD_ZONE };
struct mutex { bool locked; };
static void mutex_init(struct mutex *m) { m->locked=false; }
static void mutex_lock(struct mutex *m) { assert(!m->locked); m->locked=true; }
static void mutex_unlock(struct mutex *m) { assert(m->locked); m->locked=false; }
struct device { void *data; };
struct platform_device { struct device dev; };
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; bool initialized,pending; void (*fn)(struct work_struct *); };
#define INIT_DELAYED_WORK(w,f) do { (w)->initialized=true; (w)->fn=(f); } while(0)
static int schedules,cancels,sequence,unreg_seq,cancel_seq,detach_seq;
static int schedule_delayed_work(struct delayed_work *w,int delay) { (void)delay;assert(w->initialized);w->pending=true;schedules++;return 1; }
#define system_wq NULL
#define mod_delayed_work(wq, work, delay) schedule_delayed_work(work, delay)
static int cancel_delayed_work_sync(struct delayed_work *w) { assert(w->initialized);w->pending=false;cancels++;cancel_seq=++sequence;return 1; }
static void *allocations[32];static int nalloc;
static void *devm_kzalloc(struct device *d,size_t n,int flags) { (void)d;(void)flags;void *p=calloc(1,n);assert(p&&nalloc<32);allocations[nalloc++]=p;return p; }
static void platform_set_drvdata(struct platform_device *p,void *data) {p->dev.data=data;}
static void *platform_get_drvdata(struct platform_device *p) {return p->dev.data;}
struct mca_votable { void *owner; int (*cb)(struct mca_votable *,void *,int,const char *); };
''' + h+smart+events+r'''
static int parse_error,foldable,available=1,hw_error,smart_error,reg_error;
static int create_error,hw_calls,creates,detaches,updates,disable_votes,buck_online,wls_online,buck_error,wls_error;
static int reg_event=-1,smart_event=-1;
static struct mca_votable shared[4],flip_slot;
static struct mca_buckchg_jeita_dev *strategy_owner;
static struct mca_smartchg_if_ops smart_entry;
static int mca_buckchg_jeita_parse_dt(struct mca_buckchg_jeita_dev *i) {i->support_base_flip=foldable;return parse_error;}
static void mca_buckchg_jeita_update(struct mca_buckchg_jeita_dev *i) {(void)i;updates++;}
static void mca_buckchg_base_jeita_update(struct mca_buckchg_jeita_dev *i) {(void)i;}
static void mca_buckchg_flip_jeita_update(struct mca_buckchg_jeita_dev *i) {(void)i;}
static int mca_strategy_buckchg_jeita_get_normal_vterm(struct mca_buckchg_jeita_dev *i) {(void)i;return 4400;}
static int mca_strategy_buckchg_jeita_get_ffc_iterm(struct mca_buckchg_jeita_dev *i) {(void)i;return 100;}
static int mca_strategy_buckchg_jeita_get_ffc_vterm(struct mca_buckchg_jeita_dev *i) {(void)i;return 4500;}
static struct mca_votable *mca_find_votable(const char *name) {
 if(!available)return NULL;
 const char *names[]={"chg_enable","buck_charge_curr","term_volt","term_curr"};
 for(int n=0;n<4;n++)if(!strcmp(name,names[n]))return &shared[n];
 assert(0);return NULL;
}
static int platform_class_loadsw_set_ibat_limit(int role,int value) {(void)role;assert(value==2950);hw_calls++;return hw_error;}
static struct mca_votable *mca_create_owned_votable(const char *name,int type,
 int (*cb)(struct mca_votable *,void *,int,const char *),int def,void *owner) {
 (void)type;assert(!strcmp(name,"flip_charge_curr")&&def==2950);creates++;
 if(create_error)return ERR_PTR(create_error);
 if(flip_slot.owner)return ERR_PTR(-EBUSY);
 flip_slot.owner=owner;flip_slot.cb=cb;return &flip_slot;
}
static int mca_rerun_election(struct mca_votable *v) {assert(v->owner);return v->cb(v,v->owner,2950,NULL);}
static int mca_detach_owned_votable(struct mca_votable *v,void *owner) {
 assert(v->owner==owner);v->owner=NULL;v->cb=NULL;detaches++;detach_seq=++sequence;return 0;
}
static int mca_vote(struct mca_votable *v,const char *who,bool enabled,int value) {
 assert(v==&shared[0]&&!strcmp(who,"jeita")&&enabled&&value==0);disable_votes++;return 0;
}
static int mca_strategy_func_get_status(int type,int status,void *out) {
 assert(status==STRATEGY_STATUS_TYPE_ONLINE);
 *(int *)out=type==STRATEGY_FUNC_TYPE_BUCK_CHARGE?buck_online:wls_online;
 return type==STRATEGY_FUNC_TYPE_BUCK_CHARGE?buck_error:wls_error;
}
static int (*dispatch)(int,int,void *);
static int mca_strategy_ops_register(unsigned int type,int (*f)(int,int,void *),
 int (*get)(int,void *,void *),void *set,void *data) {
 (void)get;(void)set;assert(type==STRATEGY_FUNC_TYPE_JEITA);
 if(reg_error)return reg_error;
 if(strategy_owner)return -EBUSY;
 strategy_owner=data;dispatch=f;
 assert(strategy_owner->monitor_work.initialized);
 if(reg_event>=0)assert(!dispatch(reg_event,0,data));
 return 0;
}
static int mca_strategy_ops_unregister(unsigned int type,void *data) {
 assert(type==STRATEGY_FUNC_TYPE_JEITA&&strategy_owner==data&&strategy_owner->stopping);
 assert(dispatch(MCA_EVENT_USB_CONNECT,0,data)==-ENODEV);
 strategy_owner=NULL;unreg_seq=++sequence;return 0;
}
int mca_smartchg_if_ops_register(struct mca_smartchg_if_ops *ops) {
 if(smart_event>=0&&strategy_owner)assert(!dispatch(smart_event,0,strategy_owner));
 if(smart_error)return smart_error;
 assert(!smart_entry.data);smart_entry=*ops;return 0;
}
int mca_smartchg_if_ops_unregister(unsigned int type,void *data) {
 assert(type==MCA_SMARTCHG_IF_CHG_TYPE_JEITA&&smart_entry.data==data);
 assert(smart_entry.set_delta_fv(data,10)==-ENODEV);
 memset(&smart_entry,0,sizeof(smart_entry));unreg_seq=++sequence;return 0;
}
'''
for name in ['mca_buckchg_jeita_flip_charge_limit','mca_buckchg_jeita_init_voter','mca_buckchg_jeita_monitor_work','mca_nezha_jeita_process_event','mca_buckchg_jeita_process_event','mca_strategy_buckchg_jeita_get_status','mca_jeita_smartchg_delta_fv_callback','mca_buckchg_jeita_smartchg_baa_update_jeita_data','mca_buckchg_jeita_smartchg_update_baa_para']:
 head+=fn(name)
head+=s[s.index('static const struct mca_smartchg_if_ops g_jeita_smartchg_if_ops'):s.index('static const struct of_device_id match_table[]')]
test=r'''
static void reset(void) {
 assert(!strategy_owner&&!smart_entry.data&&!flip_slot.owner);
 while(nalloc)free(allocations[--nalloc]);
 parse_error=foldable=hw_error=smart_error=reg_error=0;available=1;
 schedules=cancels=sequence=unreg_seq=cancel_seq=detach_seq=0;
 create_error=hw_calls=creates=detaches=updates=disable_votes=buck_online=wls_online=buck_error=wls_error=0;
 reg_event=smart_event=-1;
}
int main(void) {
 struct platform_device p={0},other={0};
 reset();parse_error=-EPROBE_DEFER;assert(mca_buckchg_jeita_probe(&p)==-EPROBE_DEFER);assert(!creates&&!schedules&&!strategy_owner);
 reset();reg_error=-EBUSY;assert(mca_buckchg_jeita_probe(&p)==-EBUSY);assert(!strategy_owner&&!disable_votes&&!creates);
 reset();smart_error=-ENOMEM;smart_event=MCA_EVENT_USB_CONNECT;
 assert(mca_buckchg_jeita_probe(&p)==-ENOMEM);
 struct mca_buckchg_jeita_dev *i=p.dev.data;
 assert(i->stopping&&!i->monitor_work.pending&&!strategy_owner&&!smart_entry.data);
 assert(cancel_seq>unreg_seq&&disable_votes==1);
 reset();buck_online=1;reg_event=MCA_EVENT_USB_DISCONNECT;
 assert(!mca_buckchg_jeita_probe(&p));i=p.dev.data;
 assert(!i->online&&!i->monitor_work.pending&&!creates);
 assert(!smart_entry.set_delta_fv(i,15)&&i->smartchg_data.delta_fv==15);
 assert(g_jeita_smartchg_if_ops.data==NULL); /* immutable template */
 assert(mca_buckchg_jeita_probe(&other)==-EBUSY&&strategy_owner==i);
 mca_buckchg_jeita_remove(&p);assert(cancel_seq>unreg_seq&&disable_votes==1);
 int saved=schedules; mca_buckchg_jeita_monitor_work(&i->monitor_work.work);
 assert(schedules==saved);int output=77;
 assert(mca_strategy_buckchg_jeita_get_status(STRATEGY_STATUS_TYPE_JEITA_COLD_ZONE,&output,i)==-ENODEV&&output==77);
 mca_buckchg_jeita_shutdown(&p);assert(disable_votes==1);
 assert(!mca_buckchg_jeita_probe(&p));mca_buckchg_jeita_remove(&p);
 reset();available=0;assert(!mca_buckchg_jeita_probe(&p));i=p.dev.data;
 assert(i->monitor_work.pending&&!i->voter_ok);
 available=1;buck_online=1;assert(!dispatch(MCA_EVENT_USB_CONNECT,0,i));
 mca_buckchg_jeita_monitor_work(&i->monitor_work.work);assert(i->voter_ok&&updates==1);
 mca_buckchg_jeita_shutdown(&p);assert(!i->monitor_work.pending);
 reset();foldable=1;create_error=-ENOMEM;
 assert(mca_buckchg_jeita_probe(&p)==-ENOMEM&&creates==1&&!detaches&&!flip_slot.owner&&!strategy_owner);
 reset();foldable=1;hw_error=-EIO;
 assert(!mca_buckchg_jeita_probe(&p)&&!hw_calls); /* never write a default before temperature sampling */
 mca_buckchg_jeita_remove(&p);assert(detach_seq>cancel_seq);
 reset();foldable=1;assert(!mca_buckchg_jeita_probe(&p));i=p.dev.data;
 assert(flip_slot.owner==i&&creates==1);
 assert(mca_buckchg_jeita_probe(&other)==-EBUSY&&flip_slot.owner==i&&!detaches);
 mca_buckchg_jeita_remove(&p);assert(detaches==1&&detach_seq>cancel_seq);
 assert(!mca_buckchg_jeita_probe(&p));mca_buckchg_jeita_shutdown(&p);assert(detaches==2);
 reset();buck_online=wls_online=1;buck_error=wls_error=-EIO;
 assert(!mca_buckchg_jeita_probe(&p));i=p.dev.data;assert(!i->online&&!i->monitor_work.pending);
 mca_buckchg_jeita_remove(&p);reset();
 puts("PASS: actual JEITA publication/unwind, non-foldable path, stopped callbacks, retained limits and provider re-probe");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-jeita-lifetime-') as d:
 p=Path(d);(p/'test.c').write_text(head+test)
 for product in (0,1):
  subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Werror=implicit-function-declaration',f'-DCONFIG_TARGET_PRODUCT_NEZHA={product}','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual smartchg publication/stop/event functions with host API models.
SRCU is a pthread model; this does not validate kernel scheduling or hardware.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1];base=root/'drivers/power/supply/mca/mca_smart_charge'
s=(base/'mca_smart_charge.c').read_text();h=(base/'inc/mca_smart_charge.h').read_text()
def fn(n):
 m=re.search(r'(?:static\s+)?(?:int|void)\s+'+n+r'\([^;]*?\n\{',s);assert m,n
 p=m.end();d=1
 while d:
  if s[p]=='{':d+=1
  elif s[p]=='}':d-=1
  p+=1
 return s[m.start():p]+'\n'
assert 'cdev_add(' not in s and '.mmap =' not in s and 'smart_charge_handle_baa_data(' not in s
# All references outside publication/exports must be explicit device arguments.
assert len(re.findall(r'global_smartchg_info',s))==11
pre=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#include <limits.h>
typedef long long ktime_t;
#define NSEC_PER_SEC 1000000000LL
#define GFP_KERNEL 0
#define __rcu
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define IS_ERR(x) ((uintptr_t)(x)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(x) (!(x)||IS_ERR(x))
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define DEFINE_MUTEX(x) pthread_mutex_t x=PTHREAD_MUTEX_INITIALIZER
#define DEFINE_STATIC_SRCU(x) static pthread_rwlock_t x=PTHREAD_RWLOCK_INITIALIZER
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define srcu_dereference(x,s) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define rcu_access_pointer(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define rcu_assign_pointer(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define RCU_INIT_POINTER(x,v) rcu_assign_pointer(x,v)
#define check_mul_overflow(a,b,c) __builtin_mul_overflow(a,b,c)
static atomic_int syncing,entered,release_cb,block_report,unpublished;
static int srcu_read_lock(pthread_rwlock_t *s) {pthread_rwlock_rdlock(s);return 0;}
static void srcu_read_unlock(pthread_rwlock_t *s,int idx) {(void)idx;pthread_rwlock_unlock(s);}
static void synchronize_srcu(pthread_rwlock_t *s) {atomic_store(&syncing,1);pthread_rwlock_wrlock(s);pthread_rwlock_unlock(s);}
#define msecs_to_jiffies(x) (x)
#define SMART_CHARGE_FAKE_SCENE_DEFAULT -1
#define SMART_CHARGE_DELTA_FV_DEFAULT_VALUE 0
#define SMART_CHARGE_DELTA_ICHG_DEFAULT_VALUE 0
#define SMART_CHARGE_DTPT_DELTA_VALUE 15
#define MCA_VOTE_MAX 1
#define MCA_VOTE_MIN 0
enum {STRATEGY_FUNC_TYPE_SMARTCHG,STRATEGY_FUNC_TYPE_BUCK_CHARGE,STRATEGY_FUNC_TYPE_BASIC_WIRELESS,STRATEGY_STATUS_TYPE_ONLINE,MCA_EVENT_TYPE_PANEL,MCA_EVENT_TYPE_THERMAL_TEMP};
enum {MCA_EVENT_USB_CONNECT,MCA_EVENT_WIRELESS_CONNECT,MCA_EVENT_USB_DISCONNECT,MCA_EVENT_WIRELESS_DISCONNECT,MCA_EVENT_BATTERY_DTPT};
struct device {void *data;};
struct platform_device {struct device dev;};
struct notifier_block {void *notifier_call;};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;bool initialized,disabled,pending;};
static struct delayed_work *works[3];static int nworks,disables,cancels;
static void init_work(struct delayed_work *w) {assert(nworks<3);w->initialized=true;works[nworks++]=w;}
#define INIT_DELAYED_WORK(w,f) init_work(w)
static int schedule_delayed_work(struct delayed_work *w,int delay) {(void)delay;assert(w->initialized);if(w->disabled)return 0;w->pending=true;return 1;}
static int cancel_delayed_work_sync(struct delayed_work *w) {assert(w->initialized);w->pending=false;cancels++;return 0;}
static void late_enqueue(void) {for(int i=0;i<nworks;i++)schedule_delayed_work(works[i],0);}
static int disable_delayed_work_sync(struct delayed_work *w) {assert(w->initialized&&!w->disabled);w->disabled=true;w->pending=false;disables++;late_enqueue();return 1;}
struct mca_votable {void *owner;char name[32];};
''' +h+r'''
static int steps,fail_at,active[4],slots_used,active_slots,vote_ret,votes,resets,soc_changes,usb_status,wls_status;
static void *allocation,*strategy_owner;
static struct mca_votable slots[3];
static int step(void) {return ++steps==fail_at?-EIO:0;}
static void *devm_kzalloc(struct device *d,size_t n,int f) {(void)d;(void)f;assert(!allocation);return allocation=calloc(1,n);}
static void platform_set_drvdata(struct platform_device *p,void *d) {p->dev.data=d;}
static void *platform_get_drvdata(struct platform_device *p) {return p->dev.data;}
static int smart_charge_parse_dt(struct smart_charge_info *i) {i->cell_type=2;return step();}
static struct mca_votable *mca_create_owned_votable(const char *name,int type,void *cb,int def,void *owner) {
 (void)type;(void)cb;(void)def;int ret=step();if(ret)return ERR_PTR(ret);
 int n;for(n=0;n<slots_used;n++)if(!strcmp(slots[n].name,name))break;
 if(n==slots_used){assert(slots_used<3);strcpy(slots[slots_used++].name,name);}
 assert(!slots[n].owner);slots[n].owner=owner;active_slots++;return &slots[n];
}
static int mca_detach_owned_votable(struct mca_votable *v,void *owner) {assert(v->owner==owner);v->owner=NULL;active_slots--;late_enqueue();return 0;}
static int mca_vote(struct mca_votable *v,const char *client,bool enable,int value) {(void)client;(void)enable;(void)value;assert(v&&!IS_ERR(v));votes++;return vote_ret;}
static int mca_strategy_func_get_status(int type,int status,int *value) {(void)status;*value=type==STRATEGY_FUNC_TYPE_BUCK_CHARGE?usb_status:wls_status;return 0;}
static int mca_strategy_ops_register(int t,void *f,void *g,void *set,void *data) {(void)t;(void)f;(void)g;(void)set;assert(((struct smart_charge_info *)data)->ready);int ret=step();if(!ret){assert(!active[0]);active[0]=1;strategy_owner=data;late_enqueue();}return ret;}
static int mca_strategy_ops_unregister(int t,void *data) {(void)t;assert(active[0]&&data==strategy_owner);active[0]=0;strategy_owner=NULL;late_enqueue();return 0;}
static int mca_event_block_notify_register(int type,struct notifier_block *n) {(void)n;int i=type==MCA_EVENT_TYPE_PANEL?1:2;int ret=step();if(!ret){assert(!active[i]);active[i]=1;late_enqueue();}return ret;}
static int mca_event_block_notify_unregister(int type,struct notifier_block *n) {(void)n;int i=type==MCA_EVENT_TYPE_PANEL?1:2;assert(active[i]);active[i]=0;late_enqueue();return 0;}
static int smart_charge_sysfs_create_group(struct device *d) {(void)d;int ret=step();if(!ret){assert(!active[3]);active[3]=1;}return ret;}
static void smart_charge_sysfs_remove_group(struct device *d) {(void)d;assert(active[3]);active[3]=0;late_enqueue();}
static void smart_charge_report_scene(struct smart_charge_info *i,int scene) {(void)i;(void)scene;if(atomic_load(&block_report)){atomic_store(&entered,1);while(!atomic_load(&release_cb))sched_yield();}}
static int strategy_class_fg_ops_get_rsoc(int *rsoc) {*rsoc=50;return 0;}
static int smart_charge_plugin_or_plugout_reset(struct smart_charge_info *i) {(void)i;resets++;return vote_ret;}
static void smart_charge_set_soc_limit(bool value) {assert(!value);soc_changes++;}
static void smart_charge_fv_control(void) {}
static void smart_charge_ichg_control(void) {}
static void smart_charge_set_fcc_control(void) {}
static void smart_charge_panel_notifier_cb(void) {}
static void smart_charge_thermal_notifier_cb(void) {}
'''
body=s[s.index('static struct smart_charge_info __rcu'):s.index('static struct mca_smartchg_if_ops __rcu')]
body+=''.join(fn(n) for n in ['smart_charge_set_scene','mca_smartchg_set_scene','mca_smartchg_get_scene','mca_smartchg_set_board_temp','mca_smartchg_get_board_temp','mca_smartchg_is_extreme_cold_enabled','mca_smartchg_get_limit_soc','handle_smart_batt_message','mca_smart_charge_process_event','smart_charge_init_voter','smart_charge_stop','smart_charge_probe','smart_charge_remove','smart_charge_shutdown'])
test=r'''
static void check_drained(void) {
 for(int i=0;i<4;i++)assert(!active[i]);assert(!active_slots);
 for(int i=0;i<nworks;i++)assert(works[i]->disabled&&!works[i]->pending);
}
static void reset(int fail) {
 check_drained();assert(!rcu_access_pointer(global_smartchg_info));free(allocation);allocation=NULL;
 steps=0;fail_at=fail;nworks=disables=cancels=votes=resets=soc_changes=vote_ret=usb_status=wls_status=0;
}
static void *reader(void *p) {(void)p;mca_smartchg_set_scene(5);return NULL;}
static void *unpublish(void *p) {smart_charge_unpublish(p);atomic_store(&unpublished,1);return NULL;}
int main(void) {
 struct platform_device p={0};reset(0);
 assert(!mca_smartchg_get_scene()&&!mca_smartchg_get_board_temp()&&!mca_smartchg_get_limit_soc()&&!mca_smartchg_is_extreme_cold_enabled());
 assert(!smart_charge_probe(&p));int total=steps;struct smart_charge_info *i=p.dev.data;
 assert(active_slots==3&&rcu_access_pointer(global_smartchg_info)==i);
 mca_smartchg_set_scene(5);assert(mca_smartchg_get_scene()==5);mca_smartchg_set_board_temp(123);assert(mca_smartchg_get_board_temp()==123);
 i->soc_limit_enable=true;i->soc_limit=80;assert(mca_smartchg_get_limit_soc()==80);
 i->smart_chg_data.smart_chgcfg[SMART_CHG_EXTREME_COLD].enable=1;assert(mca_smartchg_is_extreme_cold_enabled());
 assert(!handle_smart_batt_message(i,10)&&i->smart_batt_val==10);
 int before=votes;assert(handle_smart_batt_message(i,INT_MAX)==-ERANGE&&votes==before);
 vote_ret=-EIO;assert(handle_smart_batt_message(i,20)==-EIO&&i->smart_batt_val==10);vote_ret=0;
 assert(!mca_smart_charge_process_event(MCA_EVENT_USB_CONNECT,1,i)&&i->online&&i->usb_online);
 before=resets;assert(!mca_smart_charge_process_event(MCA_EVENT_USB_CONNECT,1,i)&&resets==before);
 assert(!mca_smart_charge_process_event(MCA_EVENT_WIRELESS_CONNECT,1,i));
 assert(!mca_smart_charge_process_event(MCA_EVENT_USB_DISCONNECT,0,i)&&i->online&&!i->usb_online&&i->wls_online&&i->soc_limit_enable);
 assert(!mca_smart_charge_process_event(MCA_EVENT_WIRELESS_DISCONNECT,0,i)&&!i->online&&!i->soc_limit_enable&&soc_changes==1);
 before=resets;assert(!mca_smart_charge_process_event(MCA_EVENT_WIRELESS_DISCONNECT,0,i)&&resets==before);
 assert(!mca_smart_charge_process_event(MCA_EVENT_WIRELESS_CONNECT,1,i));
 assert(!mca_smart_charge_process_event(MCA_EVENT_USB_CONNECT,1,i));
 assert(!mca_smart_charge_process_event(MCA_EVENT_WIRELESS_DISCONNECT,0,i)&&i->online);
 assert(!mca_smart_charge_process_event(MCA_EVENT_USB_DISCONNECT,0,i)&&!i->online);
 vote_ret=-EIO;assert(mca_smart_charge_process_event(MCA_EVENT_BATTERY_DTPT,1,i)==-EIO);assert(mca_smart_charge_process_event(MCA_EVENT_USB_CONNECT,1,i)==-EIO&&i->online&&i->smart_charge_work.pending);vote_ret=0;
 atomic_store(&block_report,1);pthread_t r,u;pthread_create(&r,NULL,reader,NULL);while(!atomic_load(&entered))sched_yield();
 atomic_store(&syncing,0);pthread_create(&u,NULL,unpublish,i);while(!atomic_load(&syncing))sched_yield();assert(!atomic_load(&unpublished));
 assert(!mca_smartchg_get_scene());atomic_store(&release_cb,1);pthread_join(r,NULL);pthread_join(u,NULL);atomic_store(&block_report,0);
 assert(atomic_load(&unpublished));smart_charge_remove(&p);check_drained();assert(disables==3);
 assert(mca_smart_charge_process_event(MCA_EVENT_USB_CONNECT,1,i)==-ENODEV);smart_charge_shutdown(&p);assert(disables==3);reset(0);
 for(int n=1;n<=total;n++){reset(n);assert(smart_charge_probe(&p)==-EIO);check_drained();assert(!rcu_access_pointer(global_smartchg_info));}
 reset(0);struct smart_charge_info old={0};assert(!smart_charge_publish(&old));assert(smart_charge_probe(&p)==-EBUSY);check_drained();assert(rcu_access_pointer(global_smartchg_info)==&old);smart_charge_unpublish(&old);reset(0);
 for(int n=0;n<20;n++){usb_status=1;assert(!smart_charge_probe(&p));i=p.dev.data;assert(i->online&&i->smart_charge_work.pending&&i->smart_soc_limit_work.pending);smart_charge_remove(&p);reset(0);}
 assert(slots_used==3);puts("PASS: actual smartchg probe faults, 3 owned voters, all global exports/SRCU drain, dual-source events, overflow/errors and 20 rebinds");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-smart-lifetime-') as d:
 p=Path(d);(p/'test.c').write_text(pre+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

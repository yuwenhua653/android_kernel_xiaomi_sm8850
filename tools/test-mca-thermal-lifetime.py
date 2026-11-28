#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual thermal global dispatch, cooling bounds and probe/stop fault paths.
Uses pthread SRCU and kernel API models; not a kernel/thermal-hardware test.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1];base=root/'drivers/power/supply/mca/mca_strategy/strategy_charger'
s=(base/'mca_charger_thermal.c').read_text();h=(base/'inc/mca_charger_thermal.h').read_text()
def fn(n):
 m=re.search(r'(?:static\s+)?(?:int|void)\s+'+n+r'\([^;]*?\n\{',s);assert m,n
 p=m.end();d=1
 while d:
  if s[p]=='{':d+=1
  elif s[p]=='}':d-=1
  p+=1
 return s[m.start():p]+'\n'
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
#define GFP_KERNEL 0
#define __rcu
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define IS_ERR(x) ((uintptr_t)(x)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(x) (!(x)||IS_ERR(x))
#define min(a,b) ((a)<(b)?(a):(b))
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
static atomic_int syncing,entered,release_cb,block_vote,unpublished;
static int srcu_read_lock(pthread_rwlock_t *s) {pthread_rwlock_rdlock(s);return 0;}
static void srcu_read_unlock(pthread_rwlock_t *s,int idx) {(void)idx;pthread_rwlock_unlock(s);}
static void synchronize_srcu(pthread_rwlock_t *s) {atomic_store(&syncing,1);pthread_rwlock_wrlock(s);pthread_rwlock_unlock(s);}
#define msecs_to_jiffies(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
enum {XM_CHARGER_TYPE_UNKNOW,STRATEGY_FUNC_TYPE_THERMAL,STRATEGY_FUNC_TYPE_QUICK_WIRELESS,STRATEGY_FUNC_TYPE_BASIC_WIRELESS,MCA_EVENT_WIRELESS_THERMAL_PHONE_FLAG,MCA_SMARTCHG_IF_CHG_TYPE_THERMAL,MCA_CHARGE_LOG_ID_THERMAL};
struct device_node {int unused;};
struct device {void *data;struct device_node *of_node;};
struct platform_device {struct device dev;};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;bool initialized,disabled,pending;};
#define INIT_DELAYED_WORK(w,f) ((w)->initialized=true)
static int schedule_delayed_work(struct delayed_work *w,int delay) {(void)delay;assert(w->initialized);if(w->disabled)return 0;w->pending=true;return 1;}
static int disable_delayed_work_sync(struct delayed_work *w) {assert(w->initialized&&!w->disabled);w->disabled=true;w->pending=false;assert(!schedule_delayed_work(w,0));return 1;}
struct thermal_cooling_device {void *devdata;};
struct thermal_cooling_device_ops {int (*get_max_state)(struct thermal_cooling_device *,unsigned long *);int (*get_cur_state)(struct thermal_cooling_device *,unsigned long *);int (*set_cur_state)(struct thermal_cooling_device *,unsigned long);};
struct mca_smartchg_if_ops {void *data;};
struct mca_log_charge_log_ops {int unused;};
struct mca_votable {int unused;};
''' +h+r'''
static int steps,fail_at,active[5],limit_calls,votes,wired_missing,wireless_missing;
static void *allocation,*smart_owner,*strategy_owner,*log_owner;
static struct thermal_cooling_device cooling;
static int step(void) {return ++steps==fail_at?-EIO:0;}
static void *devm_kzalloc(struct device *d,size_t n,int f) {(void)d;(void)f;assert(!allocation);return allocation=calloc(1,n);}
static void platform_set_drvdata(struct platform_device *p,void *d) {p->dev.data=d;}
static void *platform_get_drvdata(struct platform_device *p) {return p->dev.data;}
static int mca_vote(struct mca_votable *v,const char *who,bool en,int value) {
 (void)v;(void)who;(void)en;assert(value>=0);votes++;
 if(atomic_load(&block_vote)) {atomic_store(&entered,1);while(!atomic_load(&release_cb))sched_yield();}
 return 0;
}
static int mca_rerun_election(struct mca_votable *v) {(void)v;return 0;}
static int mca_strategy_func_process(int t,int e,int v) {(void)t;(void)e;(void)v;return 0;}
static int mca_charger_thermal_handle_limit(struct mca_thermal_info *i,struct mca_thermal_ctrl_info *c,struct mca_thermal_data *d,struct mca_votable **v) {(void)i;(void)c;(void)d;(void)v;limit_calls++;return 0;}
static int mca_charger_thermal_flip_handle_limit(struct mca_thermal_info *i,struct mca_thermal_ctrl_info *c,int *d,struct mca_votable *v) {(void)i;(void)c;(void)d;(void)v;limit_calls++;return 0;}
static int mca_charger_thermal_parse_dt(struct mca_thermal_info *i) {i->support_wireless=1;i->wired_ctrl_info.max_level=i->wireless_ctrl_info.max_level=2;return step();}
static int mca_charger_thermal_sic_initial_chg_curr(struct mca_thermal_info *i) {(void)i;return 0;}
static int mca_charger_thermal_init_wired_voter(struct mca_thermal_info *i) {i->wired_ctrl_info.voter_ok=!wired_missing;return wired_missing?-EAGAIN:0;}
static int mca_charger_thermal_init_wireless_voter(struct mca_thermal_info *i) {i->wireless_ctrl_info.voter_ok=!wireless_missing;return wireless_missing?-EAGAIN:0;}
static int mca_strategy_ops_register(int t,void *f,void *g,void *set,void *data) {(void)t;(void)f;(void)g;(void)set;int ret=step();if(!ret){assert(!active[0]);active[0]=1;strategy_owner=data;}return ret;}
static int mca_strategy_ops_unregister(int t,void *data) {(void)t;assert(active[0]&&data==strategy_owner);active[0]=0;strategy_owner=NULL;return 0;}
static int mca_smartchg_if_ops_register(struct mca_smartchg_if_ops *o) {int ret=step();if(!ret){assert(!active[1]);active[1]=1;smart_owner=o->data;}return ret;}
static int mca_smartchg_if_ops_unregister(unsigned int t,void *data) {(void)t;assert(active[1]&&smart_owner==data);active[1]=0;smart_owner=NULL;return 0;}
static struct thermal_cooling_device *thermal_of_cooling_device_register(struct device_node *n,const char *s,void *data,const struct thermal_cooling_device_ops *ops) {
 (void)n;(void)s;int ret=step();if(ret)return ERR_PTR(ret);assert(!active[2]);active[2]=1;cooling.devdata=data;unsigned long state;assert(!ops->get_max_state(&cooling,&state)&&state==2);return &cooling;
}
static void thermal_cooling_device_unregister(struct thermal_cooling_device *t) {assert(t==&cooling&&active[2]);active[2]=0;}
static int mca_charger_thermal_create_group(struct device *d) {(void)d;int ret=step();if(!ret){assert(!active[3]);active[3]=1;}return ret;}
static void mca_charger_thermal_remove_group(struct device *d) {(void)d;assert(active[3]);active[3]=0;}
static void mca_log_charge_log_register(int t,struct mca_log_charge_log_ops *o,void *data) {
 (void)t;if(o){assert(!active[4]);active[4]=1;log_owner=data;}else{assert(active[4]);active[4]=0;log_owner=NULL;}
}
static void mca_charger_thermal_process_event(void) {}
static const struct mca_smartchg_if_ops g_thermal_smartchg_if_ops={0};
static struct mca_log_charge_log_ops g_mca_thermal_log_ops;
'''
reg=s[s.index('static struct mca_thermal_info __rcu'):s.index('static void mca_charger_thermal_update_chg_curr')]
body=reg+''.join(fn(n) for n in ['mca_thermal_record_error','mca_thermal_retry','mca_charger_thermal_poweroff_clear_voter','mca_wireless_charger_thermal_poweroff_clear_voter','mca_wireless_charger_thermal_flip_handle_limit','mca_wireless_charger_thermal_handle_limit','mca_set_wls_charger_thermal_remove','mca_get_wls_charger_thermal_remove','mca_charger_thermal_init_voter_work','mca_charger_thermal_get_max_level','mca_charger_thermal_get_cur_level','mca_charger_thermal_set_cur_level'])
body+=s[s.index('static const struct thermal_cooling_device_ops g_mca_charger_tcd_ops'):s.index('static int mca_charger_thermal_wls_super_sts_callback')]
body+=''.join(fn(n) for n in ['mca_charger_thermal_stop','mca_charger_thermal_probe','mca_charger_thermal_remove','mca_charger_thermal_shutdown'])
test=r'''
static void reset(int fail) {
 for(int i=0;i<5;i++)assert(!active[i]);assert(!rcu_access_pointer(g_wlscharger_thermal_info));
 free(allocation);allocation=NULL;steps=0;fail_at=fail;wired_missing=wireless_missing=limit_calls=votes=0;
}
static void *reader(void *p) {(void)p;assert(!mca_set_wls_charger_thermal_remove(true));return NULL;}
static void *unpublish(void *p) {mca_thermal_unpublish(p);atomic_store(&unpublished,1);return NULL;}
int main(void) {
 struct platform_device p={0};reset(0);assert(!mca_charger_thermal_probe(&p));int total=steps;
 struct mca_thermal_info *i=p.dev.data;unsigned long level=99;
 assert(!mca_charger_thermal_get_max_level(i->tcd,&level)&&level==2);
 assert(!mca_charger_thermal_set_cur_level(i->tcd,2)&&i->wired_ctrl_info.limit_level==2);
 assert(mca_charger_thermal_set_cur_level(i->tcd,3)==-EINVAL);
 assert(mca_charger_thermal_set_cur_level(i->tcd,ULONG_MAX)==-EINVAL&&i->wired_ctrl_info.limit_level==2);
 assert(mca_get_wls_charger_thermal_remove(NULL)==-EINVAL);
 i->wireless_ctrl_info.limit_level=MAX_THERMAL_LEVEL+1;i->wls_online=1;
 assert(mca_set_wls_charger_thermal_remove(false)==-EINVAL&&!votes); /* no out-of-range table read */
 i->wireless_ctrl_info.limit_level=-1;assert(mca_set_wls_charger_thermal_remove(false)==-EINVAL&&!votes);
 i->wireless_ctrl_info.limit_level=1;i->wireless_ctrl_info.chg_curr=1000;
 atomic_store(&block_vote,1);pthread_t r,u;pthread_create(&r,NULL,reader,NULL);
 while(!atomic_load(&entered))sched_yield();
 atomic_store(&syncing,0);pthread_create(&u,NULL,unpublish,i);
 while(!atomic_load(&syncing))sched_yield();assert(!atomic_load(&unpublished));
 bool old=true;assert(mca_get_wls_charger_thermal_remove(&old)==-ENODEV&&old);
 atomic_store(&release_cb,1);pthread_join(r,NULL);pthread_join(u,NULL);atomic_store(&block_vote,0);
 assert(atomic_load(&unpublished));mca_charger_thermal_remove(&p);assert(i->init_voter_work.disabled);
 mca_charger_thermal_shutdown(&p);reset(0);
 for(int n=1;n<=total;n++){reset(n);assert(mca_charger_thermal_probe(&p)==-EIO);for(int j=0;j<5;j++)assert(!active[j]);assert(!rcu_access_pointer(g_wlscharger_thermal_info));}
 reset(0);wired_missing=1;assert(!mca_charger_thermal_probe(&p));i=p.dev.data;
 assert(i->wireless_ctrl_info.voter_ok&&i->init_voter_work.pending);
 i->init_voter_work.pending=false;mca_charger_thermal_init_voter_work(&i->init_voter_work.work);assert(i->init_voter_work.pending);
 wired_missing=0;mca_charger_thermal_init_voter_work(&i->init_voter_work.work);assert(i->wired_ctrl_info.voter_ok);
 mca_charger_thermal_remove(&p);assert(!i->init_voter_work.pending);reset(0);
 struct mca_thermal_info other={0};assert(!mca_thermal_publish(&other));
 assert(mca_charger_thermal_probe(&p)==-EBUSY&&rcu_access_pointer(g_wlscharger_thermal_info)==&other);
 for(int j=0;j<5;j++)assert(!active[j]);mca_thermal_unpublish(&other);reset(0);
 puts("PASS: actual thermal SRCU drain, ownership, all probe failures, cooling/wireless bounds and wired supplier retry");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-thermal-lifetime-') as d:
 p=Path(d);(p/'test.c').write_text(pre+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

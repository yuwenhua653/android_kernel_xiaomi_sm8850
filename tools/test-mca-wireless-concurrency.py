#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual reverse global/worker/event entry wrappers with pthread SRCU/mutexes.
Checks serialization and in-flight global dispatch against unpublication. Kernel
workqueues/lockdep and device timing still need kernel/runtime validation.
"""
from pathlib import Path
import os,re,subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'drivers/power/supply/mca/mca_strategy/strategy_wireless/mca_wireless_revchg.c').read_text()
def fn(n):
 m=re.search(r'(?:static\s+)?(?:int|void)\s+'+n+r'\([^;]*?\)\s*\n\{',s);assert m,n
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]+'\n'
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <pthread.h>
#include <sched.h>
#include <errno.h>
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define srcu_dereference(x,s) READ_ONCE(x)
#define mca_log_info(...) ((void)0)
struct work_struct {int unused;};struct delayed_work {struct work_struct work;};
struct mca_wireless_revchg {bool ready,stopping;pthread_mutex_t data_lock;struct delayed_work monitor_work;struct {bool user_reverse_chg;} proc_data;};
static struct mca_wireless_revchg *g_wls_rev_info;
static pthread_rwlock_t wls_rev_srcu=PTHREAD_RWLOCK_INITIALIZER;
static int srcu_read_lock(pthread_rwlock_t *s){pthread_rwlock_rdlock(s);return 0;}
static void srcu_read_unlock(pthread_rwlock_t *s,int idx){(void)idx;pthread_rwlock_unlock(s);}
static atomic_int active,total,hold,entered,release_call,draining,drained;
static void action(void){assert(atomic_fetch_add(&active,1)==0);total++;if(hold){entered=1;while(!release_call)sched_yield();}sched_yield();assert(atomic_fetch_sub(&active,1)==1);}
static int mca_wireless_rev_enable_reverse_charge_held(struct mca_wireless_revchg *i,bool en){(void)i;(void)en;action();return 0;}
static void mca_wireless_rev_monitor_work_locked(struct work_struct *w){(void)w;action();}
static int mca_wireless_rev_process_event_locked(int e,int v,void *p){(void)e;(void)v;(void)p;action();return 0;}
'''
body=''.join(fn(n) for n in ['mca_wireless_rev_enable_reverse_charge','mca_wireless_rev_monitor_work','mca_wireless_rev_process_event','mca_wireless_rev_get_user_reverse_chg_held','mca_wireless_rev_get_user_reverse_chg'])
main=r'''
static void *runner(void *p){struct mca_wireless_revchg *i=p;for(int n=0;n<1000;n++){assert(!mca_wireless_rev_enable_reverse_charge(true));mca_wireless_rev_monitor_work(&i->monitor_work.work);assert(!mca_wireless_rev_process_event(0,0,i));}return NULL;}
static void *one_call(void *p){(void)p;assert(!mca_wireless_rev_enable_reverse_charge(true));return NULL;}
static void *unpublish(void *p){struct mca_wireless_revchg *i=p;WRITE_ONCE(i->stopping,true);WRITE_ONCE(i->ready,false);WRITE_ONCE(g_wls_rev_info,NULL);draining=1;pthread_rwlock_wrlock(&wls_rev_srcu);pthread_rwlock_unlock(&wls_rev_srcu);drained=1;return NULL;}
int main(void){
 bool out=true;assert(mca_wireless_rev_get_user_reverse_chg(NULL)==-EINVAL);assert(mca_wireless_rev_get_user_reverse_chg(&out)==-ENODEV&&out);assert(mca_wireless_rev_enable_reverse_charge(true)==-ENODEV);
 struct mca_wireless_revchg *i=calloc(1,sizeof(*i));assert(i);pthread_mutex_init(&i->data_lock,NULL);i->ready=true;WRITE_ONCE(g_wls_rev_info,i);assert(!mca_wireless_rev_get_user_reverse_chg(&out)&&!out);
 pthread_t ts[4];for(int n=0;n<4;n++)pthread_create(&ts[n],NULL,runner,i);for(int n=0;n<4;n++)pthread_join(ts[n],NULL);assert(total==12000&&!active);
 hold=1;pthread_t call,stop;pthread_create(&call,NULL,one_call,NULL);while(!entered)sched_yield();pthread_create(&stop,NULL,unpublish,i);while(!draining)sched_yield();assert(!drained);assert(mca_wireless_rev_enable_reverse_charge(true)==-ENODEV);release_call=1;pthread_join(call,NULL);pthread_join(stop,NULL);assert(drained&&!active);int before=total;mca_wireless_rev_monitor_work(&i->monitor_work.work);assert(mca_wireless_rev_process_event(0,0,i)==-ENODEV&&total==before);free(i);
 puts("PASS: 12000 serialized reverse entries, stopped worker/event rejection, SRCU drain of blocked global caller and NULL output");
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+body+main)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined','-pthread',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})

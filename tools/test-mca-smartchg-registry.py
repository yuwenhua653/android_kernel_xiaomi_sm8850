#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual smartchg registry/dispatch tests, including a concurrent drain model.

SRCU is modeled by pthread rwlocks; this is not an in-kernel concurrency test.
The unverified BASP dispatcher is deliberately absent.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
mca=root/'drivers/power/supply/mca'
s=(mca/'mca_smart_charge/mca_smart_charge.c').read_text()
h=(mca/'include/mca/smartchg/smart_chg_class.h').read_text().replace('#include <linux/types.h>','')
reg=s[s.index('static struct mca_smartchg_if_ops __rcu'):s.index('static ssize_t smart_charge_sysfs_show')]
reg=re.sub(r'static void smart_charge_report_scene\([^;]+;', '', reg)
names=['smart_charge_set_soc_limit','smartcharging_handle_wls_super','smartcharging_handle_power_boost','smartcharging_handle_wls_quiet','smart_charge_fv_control','smart_charge_ichg_control','smart_charge_set_fcc_control']
funcs=[]
for name in names:
    m=re.search(r'static (?:int|void) '+name+r'\([^;]+?\n\{',s)
    assert m,name
    end=m.end(); depth=1
    while depth:
        if s[end]=='{': depth+=1
        elif s[end]=='}': depth-=1
        end+=1
    block=s[m.start():end]
    assert block.count('srcu_read_lock(')==1 and block.count('srcu_read_unlock(')==1,name
    assert 'static struct mca_smartchg_if_ops *' not in block,name
    funcs.append(block)
# Ensure every active lookup remains in the protected functions or getter.
active=re.sub(r'//[^\n]*','',s)
assert active.count('mca_smartchg_if_get_ops(')==sum(x.count('mca_smartchg_if_get_ops(') for x in funcs)+1
c=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
typedef uint32_t u32;
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define __rcu
#define GFP_KERNEL 0
#define EXPORT_SYMBOL(x)
#define DEFINE_MUTEX(x) pthread_mutex_t x = PTHREAD_MUTEX_INITIALIZER
#define DEFINE_STATIC_SRCU(x) static pthread_rwlock_t x = PTHREAD_RWLOCK_INITIALIZER
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define srcu_dereference(x,s) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define rcu_access_pointer(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define rcu_assign_pointer(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define RCU_INIT_POINTER(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
static atomic_int allocations, fail_alloc, syncing;
static _Thread_local int read_depth;
static void *kmemdup(const void *p,size_t n,int flags) {
    (void)flags;
    if(atomic_load(&fail_alloc)) return NULL;
    void *out=malloc(n); assert(out); memcpy(out,p,n); atomic_fetch_add(&allocations,1); return out;
}
static void kfree(void *p) { if(p) { atomic_fetch_sub(&allocations,1); free(p); } }
static int srcu_read_lock(pthread_rwlock_t *x) { pthread_rwlock_rdlock(x); read_depth++; return 0; }
static void srcu_read_unlock(pthread_rwlock_t *x,int idx) { (void)idx; read_depth--; pthread_rwlock_unlock(x); }
static void synchronize_srcu(pthread_rwlock_t *x) {
    atomic_store(&syncing,1); pthread_rwlock_wrlock(x); pthread_rwlock_unlock(x);
}
enum { SMART_CHG_WLS_SUPER, SMART_CHG_OUTDOOR, SMART_CHG_TRAVELWAIT, SMART_CHG_WLS_QUIET,
       SMART_CHG_OUTDOOR_PWR_BOOST, SMART_CHG_TRAVELWAIT_PWR_BOOST };
struct smart_charge_info {
    struct { struct { int enable; } smart_chgcfg[4]; } smart_chg_data;
    int delta_fv, delta_ichg;
    bool ready,stopping;
};
struct mca_votable;
''' + h + reg + '\n'.join(funcs) + r'''
static atomic_int entered, release_cb, unregistered, calls;
static int payload=123;
static int fail_value;
static int cb(void *data,int value) {
    assert(read_depth>0 && data==&payload && value==1);
    atomic_fetch_add(&calls,1); return fail_value;
}
static int blocking_cb(void *data,int value) {
    assert(read_depth>0 && data==&payload && value==1);
    atomic_store(&entered,1);
    while(!atomic_load(&release_cb)) sched_yield();
    assert(*(int *)data==123); return 0;
}
static void *reader(void *p) { (void)p; smart_charge_set_soc_limit(true); return NULL; }
static void *unregister_thread(void *p) {
    (void)p;
    assert(!mca_smartchg_if_ops_unregister(MCA_SMARTCHG_IF_CHG_TYPE_BUCK,&payload));
    atomic_store(&unregistered,1); return NULL;
}
static void *cleanup_thread(void *p) { (void)p; mca_smartchg_if_cleanup(); atomic_store(&unregistered,1); return NULL; }
static void drain_test(bool cleanup) {
    struct mca_smartchg_if_ops ops={.type=MCA_SMARTCHG_IF_CHG_TYPE_BUCK,.data=&payload,.set_soc_limit_sts=blocking_cb};
    atomic_store(&entered,0); atomic_store(&release_cb,0); atomic_store(&unregistered,0); atomic_store(&syncing,0);
    assert(!mca_smartchg_if_ops_register(&ops));
    pthread_t r,u;
    assert(!pthread_create(&r,NULL,reader,NULL));
    while(!atomic_load(&entered)) sched_yield();
    assert(!pthread_create(&u,NULL,cleanup?cleanup_thread:unregister_thread,NULL));
    while(!atomic_load(&syncing)) sched_yield();
    assert(!atomic_load(&unregistered) && atomic_load(&allocations)==1);
    atomic_store(&release_cb,1);
    pthread_join(r,NULL); pthread_join(u,NULL);
    assert(atomic_load(&unregistered) && !atomic_load(&allocations));
    smart_charge_set_soc_limit(true); /* no old callback remains */
}
int main(void) {
    struct mca_smartchg_if_ops ops={.type=MCA_SMARTCHG_IF_CHG_TYPE_BUCK,.data=&payload,
        .set_soc_limit_sts=cb,.set_wls_super_sts=cb,.set_wls_quiet_sts=cb,.set_pwr_boost_sts=cb,
        .set_delta_fv=cb,.set_delta_ichg=cb,.set_fcc=cb};
    assert(mca_smartchg_if_ops_register(NULL)==-EINVAL);
    ops.type=-1; assert(mca_smartchg_if_ops_register(&ops)==-EINVAL);
    ops.type=MCA_SMARTCHG_IF_CHG_TYPE_END; assert(mca_smartchg_if_ops_register(&ops)==-EINVAL);
    ops.type=MCA_SMARTCHG_IF_CHG_TYPE_BUCK;
    assert(mca_smartchg_if_ops_unregister(-1,&payload)==-EINVAL);
    assert(mca_smartchg_if_ops_unregister(ops.type,&payload)==-ENOENT);
    atomic_store(&fail_alloc,1); assert(mca_smartchg_if_ops_register(&ops)==-ENOMEM); atomic_store(&fail_alloc,0);
    assert(!mca_smartchg_if_ops_register(&ops));
    assert(mca_smartchg_if_ops_register(&ops)==-EBUSY && atomic_load(&allocations)==1);
    assert(mca_smartchg_if_ops_unregister(ops.type,(void *)1)==-ENOENT);
    /* Mutating the caller's table after publication cannot alter the entry. */
    ops.data=(void *)1; ops.set_soc_limit_sts=NULL;
    smart_charge_set_soc_limit(true); assert(atomic_load(&calls)==1);
    assert(!mca_smartchg_if_ops_unregister(ops.type,&payload) && !atomic_load(&allocations));
    ops.data=&payload; ops.set_soc_limit_sts=cb;
    for(int i=0;i<MCA_SMARTCHG_IF_CHG_TYPE_END;i++) { ops.type=i; assert(!mca_smartchg_if_ops_register(&ops)); }
    struct smart_charge_info info={.ready=true};
    for(int i=0;i<4;i++) info.smart_chg_data.smart_chgcfg[i].enable=1;
    atomic_store(&calls,0);
    smart_charge_set_soc_limit(true);
    smartcharging_handle_wls_super(&info); smartcharging_handle_wls_quiet(&info);
    smartcharging_handle_power_boost(&info,SMART_CHG_OUTDOOR_PWR_BOOST);
    smartcharging_handle_power_boost(&info,SMART_CHG_TRAVELWAIT_PWR_BOOST);
    assert(!smart_charge_fv_control(NULL,&info,1,NULL) && info.delta_fv==1);
    assert(!smart_charge_ichg_control(NULL,&info,1,NULL) && info.delta_ichg==1);
    assert(!smart_charge_set_fcc_control(NULL,&info,1,NULL));
    assert(atomic_load(&calls)==8*MCA_SMARTCHG_IF_CHG_TYPE_END && !read_depth);
    assert(smart_charge_fv_control(NULL,NULL,1,NULL)==-ENODEV);
    assert(smart_charge_ichg_control(NULL,NULL,1,NULL)==-ENODEV);
    assert(smart_charge_set_fcc_control(NULL,NULL,1,NULL)==-ENODEV);
    fail_value=-EIO;info.delta_fv=7;info.delta_ichg=9;atomic_store(&calls,0);
    assert(smart_charge_fv_control(NULL,&info,1,NULL)==-EIO&&info.delta_fv==7);
    assert(smart_charge_ichg_control(NULL,&info,1,NULL)==-EIO&&info.delta_ichg==9);
    assert(smart_charge_set_fcc_control(NULL,&info,1,NULL)==-EIO);
    assert(atomic_load(&calls)==3*MCA_SMARTCHG_IF_CHG_TYPE_END);fail_value=0;
    info.stopping=true;assert(smart_charge_fv_control(NULL,&info,1,NULL)==-ENODEV);info.stopping=false;
    mca_smartchg_if_cleanup(); assert(!atomic_load(&allocations));
    assert(smart_charge_fv_control(NULL,&info,1,NULL)==-ENODEV);
    assert(smart_charge_ichg_control(NULL,&info,1,NULL)==-ENODEV);
    assert(smart_charge_set_fcc_control(NULL,&info,1,NULL)==-ENODEV);
    drain_test(false); drain_test(true);
    puts("PASS: actual smartchg copied registry, allocation failure, identity, seven dispatchers, backend failures and concurrent unregister/cleanup drain model");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-smartchg-registry-') as d:
    p=Path(d); (p/'test.c').write_text(c)
    subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Wall','-Werror=implicit-function-declaration','-pthread','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

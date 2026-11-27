#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual strategy dispatch under host sanitizers and a pthread SRCU model.
This tests ownership/error paths; it is not an in-kernel SRCU or hardware test.
"""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'drivers/power/supply/mca/mca_strategy/mca_strategy_class.c').read_text()
s=s[s.index('struct mca_strategy_func_data {'):s.index('static struct platform_driver')]
h=(root/'drivers/power/supply/mca/include/mca/strategy/strategy_class.h').read_text().replace('#include <linux/types.h>','')
pre=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#define __rcu
#define GFP_KERNEL 0
#define EXPORT_SYMBOL(x)
#define DEFINE_MUTEX(x) pthread_mutex_t x=PTHREAD_MUTEX_INITIALIZER
#define DEFINE_STATIC_SRCU(x) static pthread_rwlock_t x=PTHREAD_RWLOCK_INITIALIZER
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define srcu_dereference(p,s) __atomic_load_n(&(p),__ATOMIC_ACQUIRE)
#define rcu_access_pointer(p) __atomic_load_n(&(p),__ATOMIC_ACQUIRE)
#define rcu_assign_pointer(p,v) __atomic_store_n(&(p),(v),__ATOMIC_RELEASE)
#define RCU_INIT_POINTER(p,v) rcu_assign_pointer(p,v)
static int srcu_read_lock(pthread_rwlock_t *p){pthread_rwlock_rdlock(p);return 0;}
static void srcu_read_unlock(pthread_rwlock_t *p,int i){pthread_rwlock_unlock(p);}
static void synchronize_srcu(pthread_rwlock_t *p){pthread_rwlock_wrlock(p);pthread_rwlock_unlock(p);}
static atomic_int live;
static int fail_alloc;
static void *kzalloc(size_t n,int flags){if(fail_alloc)return NULL;void *p=calloc(1,n);assert(p);atomic_fetch_add(&live,1);return p;}
static void kfree(void *p){if(p){atomic_fetch_sub(&live,1);free(p);}}
'''
test=r'''
static int a=7,b=9;
static atomic_int entered,leave,removed;
static int status(int key,void *v,void *d){*(int*)v=*(int*)d;return 0;}
static int config(int key,int v,void *d){return -EIO;}
static int process(int key,int v,void *d){return *(int*)d;}
static int block(int key,int v,void *d){atomic_store(&entered,1);while(!atomic_load(&leave))sched_yield();return *(int*)d;}
static void *reader(void *p){assert(mca_strategy_func_process(0,0,0)==7);return NULL;}
static void *unregister(void *p){assert(!mca_strategy_ops_unregister(0,&a));atomic_store(&removed,1);return NULL;}
int main(void){
 int v=123;pthread_t rd,wr;
 assert(mca_strategy_func_get_status(-1,0,&v)==-EINVAL);
 assert(mca_strategy_func_get_status(0,0,NULL)==-EINVAL);
 assert(mca_strategy_func_get_status(0,0,&v)==-ENODEV && v==123);
 assert(mca_strategy_func_process(STRATEGY_FUNC_TYPE_MAX,0,0)==-EINVAL);
 assert(mca_strategy_func_set_config(-1,0,0)==-EINVAL);
 assert(mca_strategy_ops_register(0,NULL,NULL,NULL,&a)==-EINVAL);
 assert(mca_strategy_ops_register(0,process,NULL,NULL,NULL)==-EINVAL);
 fail_alloc=1;assert(mca_strategy_ops_register(0,process,NULL,NULL,&a)==-ENOMEM);fail_alloc=0;
 assert(!mca_strategy_ops_register(0,NULL,status,config,&a));
 assert(mca_strategy_ops_register(0,process,NULL,NULL,&b)==-EBUSY);
 assert(!mca_strategy_func_get_status(0,0,&v)&&v==7);
 assert(mca_strategy_func_set_config(0,0,0)==-EIO);
 assert(mca_strategy_func_process(0,0,0)==-EOPNOTSUPP);
 assert(mca_strategy_ops_unregister(0,&b)==-ENOENT);
 assert(!mca_strategy_ops_unregister(0,&a));assert(!atomic_load(&live));
 assert(!mca_strategy_ops_register(0,block,NULL,NULL,&a));
 pthread_create(&rd,NULL,reader,NULL);while(!atomic_load(&entered))sched_yield();
 pthread_create(&wr,NULL,unregister,NULL);
 while(rcu_access_pointer(g_mca_stg_func[0]))sched_yield();
 assert(!atomic_load(&removed));assert(atomic_load(&live)==1);
 /* Replacement registration cannot invalidate the old callback's data. */
 assert(!mca_strategy_ops_register(0,process,NULL,NULL,&b));
 atomic_store(&leave,1);pthread_join(rd,NULL);pthread_join(wr,NULL);
 assert(mca_strategy_func_process(0,0,0)==9);
 assert(!mca_strategy_ops_unregister(0,&b));assert(!atomic_load(&live));
 assert(mca_strategy_ops_unregister(0,&b)==-ENOENT);
 puts("PASS: actual strategy dispatch errors, duplicate registration, allocation failure, synchronized unregister and concurrent replacement");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(pre+h+s+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-O1','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(c),'-o',str(exe)],check=True)
 env=dict(os.environ);env.setdefault('ASAN_OPTIONS','detect_leaks=0');subprocess.run([str(exe)],check=True,env=env,timeout=30)

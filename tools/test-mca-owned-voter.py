#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise production voter code with pthread/list/debugfs host models.

Checks retained handles, rebind, allocation errors and a blocked callback during
provider detach. Does not establish in-kernel lockdep or hardware correctness.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'drivers/power/supply/mca/mca_common/mca_voter.c').read_text()
s=re.sub(r'^#include[^\n]*\n','',s,flags=re.M)
h=(root/'drivers/power/supply/mca/include/mca/common/mca_voter.h').read_text().replace('#include <linux/types.h>','')
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
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#include <sys/stat.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define GFP_KERNEL 0
#define THIS_MODULE NULL
#define __exit
#define MODULE_DESCRIPTION(x)
#define MODULE_AUTHOR(x)
#define MODULE_LICENSE(x)
#define module_exit(x)
#define EXPORT_SYMBOL(x)
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define mca_log_debug(...) ((void)0)
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define IS_ERR(x) ((uintptr_t)(x)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(x) (!(x)||IS_ERR(x))
static atomic_int live_allocations, fail_after;
static bool fail_alloc(void) {
    int n=atomic_load(&fail_after);
    if(n<0) return false;
    if(!n) return true;
    atomic_fetch_sub(&fail_after,1); return false;
}
static void *kzalloc(size_t n,int flags) {
    (void)flags; if(fail_alloc()) return NULL;
    void *p=calloc(1,n); assert(p); atomic_fetch_add(&live_allocations,1); return p;
}
static char *kstrdup(const char *s,int flags) {
    (void)flags; if(fail_alloc()) return NULL;
    char *p=strdup(s); assert(p); atomic_fetch_add(&live_allocations,1); return p;
}
static void kfree(const void *p) { if(p) { atomic_fetch_sub(&live_allocations,1); free((void *)p); } }
static int strscpy(char *d,const char *s,size_t n) { snprintf(d,n,"%s",s); return strlen(d); }
struct mutex { pthread_mutex_t lock; };
#define DEFINE_MUTEX(x) struct mutex x = { PTHREAD_MUTEX_INITIALIZER }
#define DEFINE_SPINLOCK(x) pthread_mutex_t x = PTHREAD_MUTEX_INITIALIZER
#define spin_lock_irqsave(x,f) do { (f)=0; pthread_mutex_lock(x); } while(0)
#define spin_unlock_irqrestore(x,f) do { (void)(f); pthread_mutex_unlock(x); } while(0)
static _Thread_local bool detaching;
static atomic_int detach_waiting;
static void mutex_init(struct mutex *m) { assert(!pthread_mutex_init(&m->lock,NULL)); }
static void mutex_lock(struct mutex *m) {
    if(detaching) atomic_store(&detach_waiting,1);
    assert(!pthread_mutex_lock(&m->lock));
}
static void mutex_unlock(struct mutex *m) { assert(!pthread_mutex_unlock(&m->lock)); }
struct list_head { struct list_head *next,*prev; };
#define LIST_HEAD(n) struct list_head n={&(n),&(n)}
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_entry(p,t,m) container_of(p,t,m)
#define list_empty(h) ((h)->next==(h))
#define list_for_each_entry(p,h,m) \
 for(p=list_entry((h)->next,__typeof__(*p),m); &(p)->m!=(h); p=list_entry((p)->m.next,__typeof__(*p),m))
#define list_for_each_entry_safe(p,n,h,m) \
 for(p=list_entry((h)->next,__typeof__(*p),m),n=list_entry(p->m.next,__typeof__(*p),m); \
 &(p)->m!=(h); p=n,n=list_entry(n->m.next,__typeof__(*n),m))
static void list_add(struct list_head *n,struct list_head *h) {
    n->next=h->next; n->prev=h; h->next->prev=n; h->next=n;
}
static void list_del(struct list_head *n) { n->prev->next=n->next; n->next->prev=n->prev; }
struct dentry { int unused; };
struct seq_file { void *private; };
struct inode { void *i_private; };
struct file { void *private_data; };
struct file_operations {
    void *owner; int (*open)(struct inode *,struct file *);
    void *read,*llseek,*release;
};
#define seq_printf(...) ((void)0)
#define seq_read NULL
#define seq_lseek NULL
#define single_release NULL
static int single_open(struct file *f,int (*show)(struct seq_file *,void *),void *p) {
    (void)f; (void)show; (void)p; return 0;
}
#define DEFINE_DEBUGFS_ATTRIBUTE(name,get,set,fmt) static const struct file_operations name={0}
static struct dentry dummy_dentry;
static struct dentry *debugfs_create_dir(const char *s,struct dentry *p) { (void)s;(void)p;return &dummy_dentry; }
static struct dentry *debugfs_create_file(const char *s,int mode,struct dentry *p,void *data,const struct file_operations *ops) {
    (void)s;(void)mode;(void)p;(void)data;(void)ops;return &dummy_dentry;
}
static void debugfs_create_u32(const char *s,int mode,struct dentry *p,u32 *v) { (void)s;(void)mode;(void)p;(void)v; }
static void debugfs_remove_recursive(struct dentry *d) { (void)d; }
'''
test=r'''
struct owner { int magic; bool block; atomic_int calls; int last; };
static atomic_int entered,release_cb,detach_done;
static int callback(struct mca_votable *v,void *data,int val,const char *client) {
    (void)v;(void)client;
    struct owner *o=data; assert(o->magic==123);
    atomic_fetch_add(&o->calls,1); o->last=val;
    if(o->block) {
        atomic_store(&entered,1);
        while(!atomic_load(&release_cb)) sched_yield();
        assert(o->magic==123);
    }
    return 0;
}
struct invocation { struct mca_votable *v; struct owner *o; };
static void *reader(void *arg) {
    struct invocation *i=arg; assert(!mca_vote(i->v,"thermal",true,200)); return NULL;
}
static void *detach(void *arg) {
    struct invocation *i=arg; detaching=true;
    assert(!mca_detach_owned_votable(i->v,i->o));
    atomic_store(&detach_done,1); return NULL;
}
static pthread_barrier_t creators;
struct creation { struct owner *o; struct mca_votable *v; };
static void *create_racing(void *arg) {
    struct creation *c=arg; pthread_barrier_wait(&creators);
    c->v=mca_create_owned_votable("race",MCA_VOTE_MIN,callback,500,c->o);return NULL;
}
int main(void) {
    atomic_store(&fail_after,-1);
    struct owner a={.magic=123}, b={.magic=123};
    assert(PTR_ERR(mca_create_owned_votable(NULL,0,callback,1,&a))==-EINVAL);
    assert(PTR_ERR(mca_create_owned_votable("bad",-1,callback,1,&a))==-EINVAL);
    assert(PTR_ERR(mca_create_owned_votable("bad",0,NULL,1,&a))==-EINVAL);
    assert(PTR_ERR(mca_create_owned_votable("bad",0,callback,1,NULL))==-EINVAL);
    for(int n=0;n<2;n++) {
        atomic_store(&fail_after,n);
        assert(PTR_ERR(mca_create_owned_votable("oom",0,callback,1,&a))==-ENOMEM);
        assert(!mca_find_votable("oom") && !atomic_load(&live_allocations));
    }
    atomic_store(&fail_after,-1);
    struct mca_votable *v=mca_create_owned_votable("owned",MCA_VOTE_MIN,callback,500,&a);
    assert(!IS_ERR(v) && v==mca_find_votable("owned"));
    assert(!atomic_load(&a.calls)); /* attach never programs half-built providers */
    assert(PTR_ERR(mca_create_owned_votable("owned",MCA_VOTE_MIN,callback,500,&b))==-EBUSY);
    assert(PTR_ERR(mca_create_votable("owned",MCA_VOTE_MIN,callback,500,&b))==-EBUSY);
    assert(mca_detach_owned_votable(v,&b)==-ENOENT);
    assert(!mca_vote(v,"thermal",true,100) && a.last==100);
    assert(!mca_detach_owned_votable(v,&a));
    assert(mca_vote(v,"thermal",false,0)==-ENODEV);
    assert(mca_vote_override(v,"test",true,1)==-ENODEV);
    assert(mca_rerun_election(v)==-ENODEV && mca_force_active_set(v,1)==-ENODEV);
    assert(mca_get_effective_result(v)==-ENODEV && !mca_get_effective_client(v));
    u64 force=77; assert(mca_force_active_get(v,&force)==-ENODEV && force==77);
    assert(mca_detach_owned_votable(v,&a)==-ENOENT);
    int retained=atomic_load(&live_allocations);
    mca_destroy_votable(v); assert(mca_find_votable("owned")==v && retained==atomic_load(&live_allocations));
    assert(PTR_ERR(mca_create_owned_votable("owned",MCA_VOTE_MAX,callback,500,&b))==-EINVAL);
    assert(PTR_ERR(mca_create_owned_votable("owned",MCA_VOTE_MIN,callback,600,&b))==-EINVAL);
    for(int n=0;n<20;n++) {
        assert(mca_create_owned_votable("owned",MCA_VOTE_MIN,callback,500,&b)==v);
        assert(mca_detach_owned_votable(v,&a)==-ENOENT);
        assert(!mca_rerun_election(v) && b.last==100);
        assert(!mca_detach_owned_votable(v,&b));
    }
    assert(retained==atomic_load(&live_allocations));
    struct owner *heap=calloc(1,sizeof(*heap)); heap->magic=123; heap->block=true;
    assert(mca_create_owned_votable("owned",MCA_VOTE_MIN,callback,500,heap)==v);
    struct invocation invocation={v,heap}; pthread_t r,u;
    assert(!pthread_create(&r,NULL,reader,&invocation));
    while(!atomic_load(&entered)) sched_yield();
    assert(!pthread_create(&u,NULL,detach,&invocation));
    while(!atomic_load(&detach_waiting)) sched_yield();
    assert(!atomic_load(&detach_done));
    atomic_store(&release_cb,1); pthread_join(r,NULL); pthread_join(u,NULL);
    assert(atomic_load(&detach_done)); free(heap);
    assert(mca_vote(v,"thermal",true,50)==-ENODEV); /* cached pointer after owner free */
    struct mca_votable *legacy=mca_create_votable("legacy",MCA_VOTE_MIN,callback,500,&a);
    assert(!IS_ERR(legacy));
    assert(PTR_ERR(mca_create_owned_votable("legacy",MCA_VOTE_MIN,callback,500,&b))==-EBUSY);
    assert(mca_detach_owned_votable(legacy,&a)==-EINVAL);
    mca_destroy_votable(legacy); assert(!mca_find_votable("legacy"));
    struct creation c1={.o=&a},c2={.o=&b};
    pthread_barrier_init(&creators,NULL,2);
    pthread_create(&r,NULL,create_racing,&c1); pthread_create(&u,NULL,create_racing,&c2);
    pthread_join(r,NULL); pthread_join(u,NULL);
    assert(IS_ERR(c1.v)!=IS_ERR(c2.v));
    struct creation *winner=IS_ERR(c1.v)?&c2:&c1,*loser=IS_ERR(c1.v)?&c1:&c2;
    assert(PTR_ERR(loser->v)==-EBUSY && !mca_detach_owned_votable(winner->v,winner->o));
    mca_voter_exit(); assert(list_empty(&votable_list) && !atomic_load(&live_allocations));
    puts("PASS: actual owned voter stable handles, callback drain, duplicate/legacy rejection, rebind, allocation failures and module cleanup");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-owned-voter-') as d:
 p=Path(d);(p/'test.c').write_text(pre+h+s+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

/* SPDX-License-Identifier: GPL-2.0-only */
/* Sleepable host primitives for extracted production-function tests. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define __rcu
#define __packed __attribute__((packed))
#define EXPORT_SYMBOL(x)
#define EXPORT_SYMBOL_GPL(x)
#define GFP_KERNEL 0
#define ARRAY_SIZE(a) (sizeof(a)/sizeof(a[0]))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define EPROBE_DEFER 517
#define kmalloc(n,f) malloc(n)
#define kzalloc(n,f) calloc(1,n)
#define kfree(p) free(p)
#define mutex pthread_mutex_t
#define DEFINE_MUTEX(n) pthread_mutex_t n=PTHREAD_MUTEX_INITIALIZER
#define mutex_init(p) pthread_mutex_init(p,NULL)
#define mutex_lock(p) assert(!pthread_mutex_lock(p))
#define mutex_unlock(p) assert(!pthread_mutex_unlock(p))
typedef pthread_mutex_t spinlock_t;
#define spin_lock_init mutex_init
#define spin_lock_irqsave(p,f) do { (f)=0; mutex_lock(p); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f); mutex_unlock(p); } while(0)
struct host_srcu { pthread_mutex_t lock;pthread_cond_t cond;unsigned int readers; };
#define DEFINE_STATIC_SRCU(n) static struct host_srcu n={PTHREAD_MUTEX_INITIALIZER,PTHREAD_COND_INITIALIZER,0}
static int srcu_read_lock(struct host_srcu *s) {mutex_lock(&s->lock);s->readers++;mutex_unlock(&s->lock);return 0;}
static void srcu_read_unlock(struct host_srcu *s,int i) {mutex_lock(&s->lock);assert(s->readers);s->readers--;pthread_cond_broadcast(&s->cond);mutex_unlock(&s->lock);}
static void synchronize_srcu(struct host_srcu *s) {mutex_lock(&s->lock);while(s->readers)pthread_cond_wait(&s->cond,&s->lock);mutex_unlock(&s->lock);}
#define srcu_dereference(p,s) __atomic_load_n(&(p),__ATOMIC_ACQUIRE)
#define rcu_dereference_protected(p,c) (p)
#define rcu_access_pointer(p) __atomic_load_n(&(p),__ATOMIC_ACQUIRE)
#define rcu_assign_pointer(p,v) __atomic_store_n(&(p),(v),__ATOMIC_RELEASE)
#define RCU_INIT_POINTER rcu_assign_pointer
#define rcu_replace_pointer(p,v,c) __atomic_exchange_n(&(p),(v),__ATOMIC_ACQ_REL)
#define lockdep_is_held(p) 1
#define srcu_read_lock_held(p) 1
struct list_head {struct list_head *next,*prev;};
#define LIST_HEAD(n) struct list_head n={&(n),&(n)}
#define INIT_LIST_HEAD(p) do {(p)->next=(p);(p)->prev=(p);} while(0)
static void list_add_rcu(struct list_head *n,struct list_head *h) {
 n->next=h->next;n->prev=h;h->next->prev=n;__atomic_store_n(&h->next,n,__ATOMIC_RELEASE);
}
static void list_del_rcu(struct list_head *n) {n->next->prev=n->prev;__atomic_store_n(&n->prev->next,n->next,__ATOMIC_RELEASE);}
#define list_del list_del_rcu
#define list_for_each_entry_rcu(p,h,m,...) \
 for(p=container_of(__atomic_load_n(&(h)->next,__ATOMIC_ACQUIRE),__typeof__(*p),m);&(p)->m!=(h);p=container_of(__atomic_load_n(&(p)->m.next,__ATOMIC_ACQUIRE),__typeof__(*p),m))
#define list_for_each_entry(p,h,m) list_for_each_entry_rcu(p,h,m)
#define list_for_each_entry_safe(p,t,h,m) \
 for(p=container_of((h)->next,__typeof__(*p),m),t=container_of(p->m.next,__typeof__(*p),m);&(p)->m!=(h);p=t,t=container_of(t->m.next,__typeof__(*t),m))
typedef uint32_t u32;
typedef uint8_t u8;

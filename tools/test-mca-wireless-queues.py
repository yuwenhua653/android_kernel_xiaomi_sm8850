#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise production wireless IRQ/TX queues with concurrent producers and ASan.
The workqueue and hardware handlers are host models; this is not a device test.
"""
import os,re,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/'drivers/power/supply/mca/mca_strategy/strategy_wireless/mca_basic_wireless.c').read_text()
def fn(n):
 m=re.search(r'(?:static\s+)?(?:int|void)\s+'+n+r'\([^;]*?\)\s*\n\{',s);assert m,n
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]+'\n'
pre=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <stdatomic.h>
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define GFP_KERNEL 0
#define GFP_ATOMIC 0
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define spin_lock pthread_mutex_lock
#define spin_unlock pthread_mutex_unlock
#define __ffs(x) __builtin_ctz((unsigned)(x))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct list_head {struct list_head *next,*prev;};
static void INIT_LIST_HEAD(struct list_head *h) {h->next=h->prev=h;}
static bool list_empty(struct list_head *h) {return h->next==h;}
static void list_add_tail(struct list_head *n,struct list_head *h) {n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n;}
static void list_del(struct list_head *n) {n->prev->next=n->next;n->next->prev=n->prev;}
#define list_first_entry(h,t,m) container_of((h)->next,t,m)
#define list_for_each_entry_safe(p,tmp,h,m) for(p=container_of((h)->next,__typeof__(*p),m),tmp=container_of(p->m.next,__typeof__(*p),m); &p->m!=(h);p=tmp,tmp=container_of(tmp->m.next,__typeof__(*tmp),m))
struct delayed_work {atomic_int pending;};
typedef int TRANS_DATA_FLAG;
struct trans_data_lis_node {struct list_head lnode;TRANS_DATA_FLAG data_flag;int value;};
struct strategy_wireless_irq_node {struct list_head node;int int_mask;};
struct strategy_wireless_dev {
 bool ready,stopping,online,wl_irq_running,mutex_lock_sts;
 struct list_head header,irq_header;
 pthread_mutex_t list_lock;
 int head_cnt,irq_node_cnt;
 struct delayed_work process_irq_work,trans_data_work;
 struct {int int_flag;} proc_data;
};
static atomic_int allocations,allocation_calls,fail_alloc;
static void *kmalloc(size_t n,int f) {(void)f;if(atomic_fetch_add(&allocation_calls,1)+1==atomic_load(&fail_alloc))return NULL;void *p=malloc(n);assert(p);allocations++;return p;}
static void kfree(void *p) {if(p){allocations--;free(p);}}
static int schedule_delayed_work(struct delayed_work *w,int delay) {(void)delay;atomic_fetch_add(&w->pending,1);return 1;}
static int irq_calls,tx_calls,last_tx=-1;
static bool check_fifo;
static void strategy_wireless_chg_handler(struct strategy_wireless_dev *i) {assert(i->proc_data.int_flag>=0&&i->proc_data.int_flag<32);irq_calls++;}
static void strategy_wireless_process_trans_func(struct strategy_wireless_dev *i,struct trans_data_lis_node *n) {(void)i;assert(n->data_flag==7);assert(n->value>=0&&n->value<4000);if(check_fifo)assert(n->value==++last_tx);tx_calls++;}
'''
body=''.join(fn(n) for n in ['strategy_wireless_add_trans_task_to_queue','strategy_wireless_split_irq_index','strategy_wireless_process_trans','strategy_wireless_process_irq','strategy_wireless_free_queues'])
main=r'''
struct producer {struct strategy_wireless_dev *i;int start;};
static void *produce(void *a) {struct producer *p=a;for(int j=0;j<1000;j++){strategy_wireless_split_irq_index(p->i,(int)0x80000001u);strategy_wireless_add_trans_task_to_queue(p->i,7,p->start+j);}return NULL;}
int main(void) {
 struct strategy_wireless_dev i={.ready=true,.online=true,.wl_irq_running=true,.list_lock=PTHREAD_MUTEX_INITIALIZER};INIT_LIST_HEAD(&i.header);INIT_LIST_HEAD(&i.irq_header);
 for(int n=0;n<10;n++){strategy_wireless_split_irq_index(&i,1<<n);strategy_wireless_add_trans_task_to_queue(&i,7,n);}
 assert(i.head_cnt==10&&i.irq_node_cnt==10);assert(i.header.next!=i.irq_header.next);
 i.mutex_lock_sts=true;strategy_wireless_process_trans(&i);assert(!tx_calls&&i.head_cnt==10);
 strategy_wireless_process_irq(&i);assert(irq_calls==10&&i.irq_node_cnt==0&&i.head_cnt==10);
 i.mutex_lock_sts=false;check_fifo=true;strategy_wireless_process_trans(&i);assert(tx_calls==10&&!allocations);
 check_fifo=false;pthread_t th[4];struct producer ps[4];for(int n=0;n<4;n++){ps[n]=(struct producer){&i,1000*n};assert(!pthread_create(&th[n],NULL,produce,&ps[n]));}for(int n=0;n<4;n++)pthread_join(th[n],NULL);
 assert(i.irq_node_cnt==8000&&i.head_cnt==4000);strategy_wireless_process_irq(&i);strategy_wireless_process_trans(&i);assert(irq_calls==8010&&tx_calls==4010&&!allocations);
 fail_alloc=allocation_calls+1;strategy_wireless_split_irq_index(&i,3);assert(i.irq_node_cnt==1);strategy_wireless_free_queues(&i);assert(!allocations);
 strategy_wireless_add_trans_task_to_queue(&i,7,0);i.online=false;strategy_wireless_process_trans(&i);assert(i.head_cnt==1);i.stopping=true;strategy_wireless_add_trans_task_to_queue(&i,7,0);strategy_wireless_split_irq_index(&i,-1);assert(i.head_cnt==1&&!i.irq_node_cnt);strategy_wireless_free_queues(&i);assert(!allocations&&list_empty(&i.header)&&list_empty(&i.irq_header));
 puts("PASS: distinct IRQ/TX queues, FIFO, 4 producers/12000 nodes, bit31, allocation failure, paused/offline TX, late enqueue and drain");
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+body+main)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Wextra','-Werror','-g','-fsanitize=address,undefined','-pthread',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})

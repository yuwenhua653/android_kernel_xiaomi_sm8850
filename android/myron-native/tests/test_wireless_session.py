#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise production RX queue/session functions with deterministic host mocks.

This checks event ordering, not I2C, firmware, negotiation or battery charging.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_sc96281_irq import function


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-root', type=Path, required=True)
    parser.add_argument('--strategy', type=Path)
    args = parser.parse_args()
    source = (args.strategy or args.kernel_root / 'drivers/power/supply/mca/'
              'mca_strategy/strategy_wireless/mca_basic_wireless.c').read_text()
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define GFP_KERNEL 0
#define GFP_ATOMIC 0
static int allocations;
static void *alloc_node(size_t size) { void *p=malloc(size); assert(p); allocations++; return p; }
static void free_node(void *p) { if(p) allocations--; free(p); }
#define kmalloc(n,f) alloc_node(n)
#define kfree(p) free_node(p)
#define __ffs(n) __builtin_ctzl(n)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define wake_up(p) (++*(p))
#define wake_up_interruptible(p) wake_up(p)
struct list_head { struct list_head *next,*prev; };
static void list_add(struct list_head *n, struct list_head *h) {
    n->next=h->next; n->prev=h; h->next->prev=n; h->next=n;
}
static void list_add_tail(struct list_head *n, struct list_head *h) { list_add(n,h->prev); }
static void list_del(struct list_head *n) { n->prev->next=n->next; n->next->prev=n->prev; }
#define list_empty(h) ((h)->next==(h))
#define list_first_entry(h,t,m) container_of((h)->next,t,m)
#define list_next_entry(p,m) container_of((p)->m.next,__typeof__(*(p)),m)
#define list_for_each_entry_safe(p,n,h,m) \
    for(p=list_first_entry(h,__typeof__(*p),m),n=list_next_entry(p,m); \
        &(p)->m!=(h); p=n,n=list_next_entry(n,m))
static void mutex_lock(int *p) { assert(!*p); ++*p; }
static void mutex_unlock(int *p) { assert(*p==1); --*p; }
#define spin_lock mutex_lock
#define spin_unlock mutex_unlock
typedef int TRANS_DATA_FLAG;
struct trans_data_lis_node { struct list_head lnode; TRANS_DATA_FLAG data_flag; int value; };
struct strategy_wireless_irq_node { struct list_head node; int int_mask; };
struct strategy_wireless_dev {
    struct list_head header, irq_header;
    int irq_list_lock, irq_wait_que, head_cnt, mutex_lock_sts;
    int online, session_lock, list_lock, wait_que, irq_node_cnt, wl_irq_running;
    struct { int int_flag; } proc_data;
};
static int icl, events[16], count, connects, disconnects, tx_count;
static void strategy_wireless_process_trans_func(struct strategy_wireless_dev *s,
                                                 struct trans_data_lis_node *node) {
    (void)s; assert(node->data_flag==5 && node->value==1234); tx_count++;
}
static void strategy_wireless_power_good_on(struct strategy_wireless_dev *s) {
    assert(s->online); connects++; icl=0;
}
static void strategy_wireless_power_good_off(struct strategy_wireless_dev *s) {
    assert(!s->online); disconnects++; icl=-1;
}
static void strategy_wireless_chg_handler(struct strategy_wireless_dev *s) {
    assert(count<16); events[count++]=s->proc_data.int_flag;
    /* Model the existing LDO_ON ICL ramp; no new charge setpoint is introduced. */
    if (s->proc_data.int_flag==1) icl=750;
}
'''
    for name in ('strategy_wireless_add_trans_task_to_queue',
                 'strategy_wireless_process_trans',
                 'strategy_wireless_process_online_change',
                 'strategy_wireless_split_irq_index',
                 'strategy_wireless_process_irq'):
        code += function(source, name) + '\n'
    code += r'''
static void init(struct strategy_wireless_dev *s) {
    *s=(struct strategy_wireless_dev){.wl_irq_running=1};
    s->header.next=s->header.prev=&s->header;
    s->irq_header.next=s->irq_header.prev=&s->irq_header;
    icl=-1; count=connects=disconnects=tx_count=0; assert(!allocations);
}
static void idle(struct strategy_wireless_dev *s) {
    assert(!s->session_lock && !s->list_lock && !s->irq_list_lock);
    assert(!s->irq_node_cnt && !s->head_cnt);
    assert(list_empty(&s->header) && list_empty(&s->irq_header) && !allocations);
}
int main(void) {
    struct strategy_wireless_dev s;
    /* RX and TX have separate ownership: neither worker may consume the other's node. */
    for(int tx_first=0;tx_first<2;tx_first++) {
        init(&s); strategy_wireless_process_online_change(1,&s);
        strategy_wireless_split_irq_index(&s,1<<1);
        strategy_wireless_add_trans_task_to_queue(&s,5,1234);
        if(tx_first) {
            strategy_wireless_process_trans(&s);
            assert(tx_count==1 && count==0 && s.irq_node_cnt==1);
            strategy_wireless_process_irq(&s);
        } else {
            strategy_wireless_process_irq(&s);
            assert(count==1 && tx_count==0 && s.head_cnt==1);
            strategy_wireless_process_trans(&s);
        }
        assert(count==1 && tx_count==1 && icl==750); idle(&s);
    }
    /* LDO_ON before delayed CONNECT: keep it queued until zero-ICL init finishes. */
    init(&s);
    strategy_wireless_split_irq_index(&s,1<<1);
    assert(!strategy_wireless_process_irq(&s));
    assert(count==0 && s.irq_node_cnt==1 && icl==-1);
    strategy_wireless_process_online_change(1,&s);
    assert(icl==0 && s.irq_wait_que>=2);
    strategy_wireless_process_irq(&s);
    assert(icl==750 && count==1 && connects==1); idle(&s);
    strategy_wireless_process_online_change(1,&s);
    assert(icl==750 && connects==1); idle(&s);
    /* Normal CONNECT-first path still reaches the existing current ramp. */
    init(&s);
    strategy_wireless_process_online_change(1,&s);
    strategy_wireless_split_irq_index(&s,1<<1);
    strategy_wireless_process_irq(&s);
    assert(icl==750); idle(&s);
    /* Preserve arrival order across separate IRQs and within a queued bitmask. */
    count=0;
    strategy_wireless_split_irq_index(&s,1<<5);
    strategy_wireless_split_irq_index(&s,(1<<1)|(1<<3));
    strategy_wireless_process_irq(&s);
    assert(count==3 && events[0]==5 && events[1]==1 && events[2]==3); idle(&s);
    /* Drop already queued events at disconnect instead of replaying them later. */
    strategy_wireless_split_irq_index(&s,1<<1);
    strategy_wireless_process_online_change(0,&s);
    assert(icl==-1 && disconnects==1); idle(&s);
    count=0;
    strategy_wireless_process_online_change(1,&s);
    strategy_wireless_process_irq(&s);
    assert(count==0 && icl==0); idle(&s);
    /* A fresh early IRQ for the next session must survive while offline. */
    strategy_wireless_process_online_change(0,&s);
    strategy_wireless_split_irq_index(&s,1<<1);
    strategy_wireless_process_irq(&s);
    assert(s.irq_node_cnt==1);
    strategy_wireless_process_online_change(1,&s);
    strategy_wireless_process_irq(&s);
    assert(count==1 && icl==750); idle(&s);
    /* Stopping the worker while offline must still satisfy wait_event. */
    strategy_wireless_process_online_change(0,&s);
    s.wl_irq_running=0;
    assert(strategy_wireless_process_irq(&s)); idle(&s);
    puts("PASS: RX/TX queue isolation, early/late RX, initialization, duplicate CONNECT, FIFO, disconnect, reconnect, stop");
}
'''
    with tempfile.TemporaryDirectory(prefix='wireless-session-') as temp:
        path = Path(temp)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', '-fsanitize=undefined',
                        str(path / 'test.c'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


if __name__ == '__main__':
    main()

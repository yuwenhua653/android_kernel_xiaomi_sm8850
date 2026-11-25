#!/usr/bin/env python3
"""Execute extracted production IRQ dispatch and RX queue functions with host mocks.

Usage: python3 test_sc96281_irq.py --kernel-root /path/to/kernel
Requires a host C compiler. This is not a kernel build or hardware test.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(text, name):
    match = re.search(r"static\s+(?:void|int)\s+" + name + r"\s*\(", text)
    if not match:
        raise ValueError("Missing function: " + name)
    start = text.index("{", match.end())
    depth = 1
    end = start + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[match.start():end]


def enum(text, symbol):
    return re.search(r"typedef enum " + symbol + r"\s*\{.*?\}\s*" + symbol + r";", text, re.S)[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel-root", required=True, type=Path)
    ap.add_argument("--driver", type=Path, help="Optional replacement driver for regression testing")
    ap.add_argument("--strategy", type=Path, help="Optional replacement strategy for regression testing")
    a = ap.parse_args()
    mca = a.kernel_root / "drivers/power/supply/mca"
    drv = mca / "mca_hardware_ic/wireless_ic/sc96281"
    strategy = mca / "mca_strategy/strategy_wireless"
    source = (a.driver or drv / "sc96281_core.c").read_text()
    header = (drv / "inc/sc96281_reg.h").read_text()
    consumer = (a.strategy or strategy / "mca_basic_wireless.c").read_text()
    sh = (strategy / "inc/mca_basic_wireless.h").read_text()
    rx_names = re.findall(r"RX_INT_\w+", enum(header, "rx_irq_flag_t"))
    assert rx_names == re.findall(r"RX_INT_\w+", sh), "Driver/strategy RX enum mismatch"
    maps = "\n".join(re.search(r"static int_map_t " + name + r"\[\] = \{.*?\};", source, re.S)[0]
                     for name in ("rx_irq_map", "tx_irq_map"))
    preamble = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#define BIT(n) (1UL << (n))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define READ_ONCE(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define GFP_KERNEL 0
#define kmalloc(n,f) malloc(n)
#define kfree(p) free(p)
#define __ffs(n) __builtin_ctzl(n)
#define wake_up(p) ((void)0)
#define RTX_MODE 1
#define STRATEGY_FUNC_TYPE_REV_WIRELESS 1
#define STRATEGY_FUNC_TYPE_BASIC_WIRELESS 2
#define MCA_EVENT_WIRELESS_INT_CHANGE 8
struct work_struct { int unused; };
struct sc96281 { struct { struct work_struct work; } interrupt_work;
    bool ready; int wireless_chg_int_lock;
    struct { int int_trx_mode, int_flag; } proc_data; };
struct list_head { struct list_head *next, *prev; };
static void list_add(struct list_head *n, struct list_head *h) {
    n->next=h->next; n->prev=h; h->next->prev=n; h->next=n;
}
static inline void list_add_tail(struct list_head *n, struct list_head *h) { list_add(n,h->prev); }
static void list_del(struct list_head *n) { n->prev->next=n->next; n->next->prev=n->prev; }
#define list_empty(h) ((h)->next==(h))
#define list_first_entry(h,t,m) container_of((h)->next,t,m)
struct strategy_wireless_irq_node { struct list_head node; int int_mask; };
struct strategy_wireless_dev { struct list_head header, irq_header; int irq_list_lock, irq_wait_que, list_lock, wait_que, irq_node_cnt, wl_irq_running, online, session_lock;
    struct { int int_flag; } proc_data; };
static int decoded[128], count, mode, failure, cleared;
static uint32_t raw;
static struct strategy_wireless_dev info;
static void mutex_lock(int *p) { assert(!*p); ++*p; }
static void mutex_unlock(int *p) { assert(*p==1); --*p; }
#define spin_lock mutex_lock
#define spin_unlock mutex_unlock
static void strategy_wireless_chg_handler(struct strategy_wireless_dev *s) {
    assert(count<128); decoded[count++]=s->proc_data.int_flag;
}
static int sc96281_get_rx_rtx_mode(int *m, struct sc96281 *c) { (void)c; *m=mode; return failure==1?-1:0; }
static int sc96281_rx_get_int(struct sc96281 *c, uint32_t *v) { (void)c; *v=raw; return failure==2?-1:0; }
#define sc96281_tx_get_int sc96281_rx_get_int
static int sc96281_rx_clr_int(struct sc96281 *c, uint32_t v) { (void)c; assert(v==raw); cleared=1; return failure==3?-1:0; }
#define sc96281_tx_clr_int sc96281_rx_clr_int
typedef struct { uint32_t irq_regval; int irq_flag; } int_map_t;
#define DECL_INTERRUPT_MAP(reg,flag) {reg,flag}
'''
    bridge = r'''
static void mca_strategy_func_process(int type, int event, int value) {
    assert(cleared && event==MCA_EVENT_WIRELESS_INT_CHANGE);
    if (type==STRATEGY_FUNC_TYPE_BASIC_WIRELESS) strategy_wireless_split_irq_index(&info,value);
    else { assert(type==STRATEGY_FUNC_TYPE_REV_WIRELESS); decoded[count++]=value; }
}
'''
    tests = r'''
static int cases;
static void check(uint32_t bits, int tx, int fail, bool ready) {
    struct sc96281 chip={.ready=ready};
    int expected[128]={0}, actual[128]={0}, sequence[128]={0}, n=0;
    int_map_t *map=tx?tx_irq_map:rx_irq_map;
    unsigned len=tx?ARRAY_SIZE(tx_irq_map):ARRAY_SIZE(rx_irq_map);
    mode=tx; raw=bits; failure=fail; count=cleared=0;
    info=(struct strategy_wireless_dev){.online=1}; info.header.next=info.header.prev=&info.header;
    info.irq_header.next=info.irq_header.prev=&info.irq_header;
    sc96281_interrupt_work(&chip.interrupt_work.work);
    strategy_wireless_process_irq(&info);
    assert(!chip.wireless_chg_int_lock && !chip.proc_data.int_flag);
    assert(!info.irq_node_cnt && !info.list_lock && list_empty(&info.irq_header));
    if (!fail && ready) for(unsigned i=0;i<len;i++) if(bits & map[i].irq_regval) {expected[map[i].irq_flag]++; sequence[n++]=map[i].irq_flag;}
    for(int i=0;i<count;i++) {assert(decoded[i]>=0 && decoded[i]<128); actual[decoded[i]]++;}
    if(n!=count) {fprintf(stderr,"event count mismatch tx=%d bits=%x expected=%d actual=%d\n",tx,bits,n,count); exit(1);}
    for(int i=0;i<128;i++) if(expected[i]!=actual[i]) {
        fprintf(stderr,"wrong decoded event tx=%d bits=%x index=%d expected=%d actual=%d\n",tx,bits,i,expected[i],actual[i]); exit(1);
    }
    for(int i=0;i<n;i++) assert(decoded[i]==sequence[i]);
    cases++;
}
int main(void) {
    /* LDO is the regression: raw index 1 must not decode as UNKNOWN (0). */
    check(WP_IRQ_RX_LDO_ON,0,0,true);
    for(int tx=0;tx<2;tx++) {
        int_map_t *map=tx?tx_irq_map:rx_irq_map;
        unsigned len=tx?ARRAY_SIZE(tx_irq_map):ARRAY_SIZE(rx_irq_map);
        for(unsigned subset=0;subset<(1U<<len);subset++) {
            uint32_t bits=0;
            for(unsigned i=0;i<len;i++) if(subset & (1U<<i)) bits|=map[i].irq_regval;
            check(bits,tx,0,true);
        }
        check(UINT32_MAX,tx,0,true);
        check(UINT32_MAX,tx,0,false);
        for(int fail=1;fail<=3;fail++) check(UINT32_MAX,tx,fail,true);
    }
    printf("PASS: %d IRQ cases; actual RX FIFO/decoder; TX indices; read/clear failures; ready guard\n",cases);
}
'''
    code = preamble + "\n".join(enum(header, n) for n in ("wp_irq_t", "rx_irq_flag_t", "tx_irq_flag_t"))
    code += maps + function(consumer, "strategy_wireless_split_irq_index")
    code += function(consumer, "strategy_wireless_process_irq") + bridge
    code += function(source, "sc96281_interrupt_work") + tests
    with tempfile.TemporaryDirectory(prefix="sc96281-irq-test-") as tmp:
        path = Path(tmp)
        (path / "test.c").write_text(code)
        subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-sign-compare", "-fsanitize=undefined", str(path / "test.c"), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True)


if __name__ == "__main__":
    main()

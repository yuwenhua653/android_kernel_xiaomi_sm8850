#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual log registration/dump C under host ASan/UBSan + pthread mutexes."""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
mca=root/'drivers/power/supply/mca'
s=(mca/'mca_common/mca_log.c').read_text()
h=(mca/'include/mca/common/mca_log.h').read_text();h=h[h.index('enum mca_charge_log_id_ele'):h.index('__printf')]
entry=re.search(r'struct mca_charge_log_ops_data \{.*?\n\};',s,re.S)[0]
reg=s[s.index('void mca_log_charge_log_register('):s.index('EXPORT_SYMBOL(mca_log_charge_log_register);')]
dump=s[s.index('static int mca_log_charge_log_dump('):s.index('static ssize_t mca_log_sysfs_store(',s.index('static int mca_log_charge_log_dump('))]
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>
#define PAGE_SIZE 64
#define min(a,b) ((a)<(b)?(a):(b))
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
static pthread_mutex_t g_mca_charge_log_lock=PTHREAD_MUTEX_INITIALIZER;
'''
globals='static struct mca_charge_log_ops_data g_mca_charge_log_data[MCA_CHARGE_LOG_ID_MAX];\n'
test=r'''
static int calls;
static int text(void*d,char*b,int n){calls++;return snprintf(b,n,"%s",(char*)d);}
static int error(void*d,char*b,int n){return -EIO;}
static int long_text(void*d,char*b,int n){assert(n>0&&n<PAGE_SIZE);memset(b,'x',n-1);b[n-1]=0;return INT_MAX;}
static atomic_int entered,leave,removing,removed;
static int blocking(void*d,char*b,int n){atomic_store(&entered,1);while(!atomic_load(&leave))sched_yield();return text(d,b,n);}
static void *reader(void*p){char b[PAGE_SIZE];assert(mca_log_charge_log_dump_log_context(b)==8);assert(!strcmp(b,"battery\n"));return NULL;}
static void *remover(void*p){atomic_store(&removing,1);mca_log_charge_log_register(0,NULL,NULL);atomic_store(&removed,1);return NULL;}
int main(void){
 char b[PAGE_SIZE];pthread_t rd,wr;
 struct mca_log_charge_log_ops ops={.dump_log_context=text};
 assert(mca_log_charge_log_dump_log_context(b)==1&&!strcmp(b,"\n"));
 mca_log_charge_log_register(-1,&ops,"bad");mca_log_charge_log_register(MCA_CHARGE_LOG_ID_MAX,&ops,"bad");assert(!calls);
 mca_log_charge_log_register(0,&ops,"battery");
 assert(mca_log_charge_log_dump_log_head(b)==1&&!calls);
 assert(mca_log_charge_log_dump_log_context(b)==8&&calls==1&&!strcmp(b,"battery\n"));
 mca_log_charge_log_register(0,NULL,NULL);
 assert(mca_log_charge_log_dump_log_context(b)==1&&calls==1);
 ops.dump_log_context=error;mca_log_charge_log_register(0,&ops,NULL);assert(mca_log_charge_log_dump_log_context(b)==-EIO);mca_log_charge_log_register(0,NULL,NULL);
 ops.dump_log_context=long_text;mca_log_charge_log_register(0,&ops,NULL);assert(mca_log_charge_log_dump_log_context(b)==PAGE_SIZE-1&&b[PAGE_SIZE-2]=='\n'&&b[PAGE_SIZE-1]==0);mca_log_charge_log_register(0,NULL,NULL);
 ops.dump_log_context=blocking;mca_log_charge_log_register(0,&ops,"battery");
 pthread_create(&rd,NULL,reader,NULL);while(!atomic_load(&entered))sched_yield();
 assert(pthread_mutex_trylock(&g_mca_charge_log_lock)==EBUSY);
 pthread_create(&wr,NULL,remover,NULL);while(!atomic_load(&removing))sched_yield();
 assert(!atomic_load(&removed));atomic_store(&leave,1);pthread_join(rd,NULL);pthread_join(wr,NULL);
 assert(atomic_load(&removed)&&!g_mca_charge_log_data[0].ops);
 assert(mca_log_charge_log_dump_log_context(b)==1);
 puts("PASS: log NULL/missing callbacks, invalid slot, negative/oversized returns, newline bounds and synchronized unregister");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(pre+h+entry+globals+reg+dump+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-O1','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

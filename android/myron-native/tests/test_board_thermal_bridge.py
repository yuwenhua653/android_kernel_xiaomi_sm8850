#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Production board-temperature sysfs, MCA delivery and init/unwind checks."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(text, name):
    match = re.search(r'(?:static\s+)?(?:ssize_t|void|int)\s+(?:__init\s+|__exit\s+)?' +
                      name + r'\s*\([^;{}]*\)\s*\{', text)
    if not match:
        raise ValueError(name)
    end, depth = match.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', type=Path, required=True)
p.add_argument('--source', type=Path)
a = p.parse_args()
s = (a.source or a.kernel_root / 'drivers/thermal/xiaomi/mi_thermal_interface.c').read_text()
events = (a.kernel_root / 'drivers/power/supply/mca/include/mca/common/mca_event.h').read_text()
consumer = (a.kernel_root / 'drivers/power/supply/mca/mca_hardware_monitor/mca_connector_antiburn.c').read_text()
code = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#define __init
#define __exit
#define GFP_KERNEL 0
#define NOTIFY_DONE 0
#define NTC_SCALE_TEMP 1000
#define mca_log_info(...) ((void)0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define sysfs_emit(b,...) snprintf(b,4096,__VA_ARGS__)
struct mutex { pthread_mutex_t p; };
static void mutex_init(struct mutex *m) { assert(!pthread_mutex_init(&m->p,0)); }
static void mutex_lock(struct mutex *m) { assert(!pthread_mutex_lock(&m->p)); }
static void mutex_unlock(struct mutex *m) { assert(!pthread_mutex_unlock(&m->p)); }
struct device { void *data; };
struct device_attribute { int unused; };
struct attribute_group { int unused; };
static const struct attribute_group **mi_board_thermal_groups;
struct device_node { int unused; };
struct notifier_block { int unused; };
struct connector_antiburn { struct notifier_block thermal_board_nb; int thermal_board_temp; };
static struct connector_antiburn conn;
static void *dev_get_drvdata(struct device *d) { return d->data; }
static int kstrtoint(const char *b,unsigned base,int *v) {
 char *end;long val;
 if(!*b || *b==' ' || *b=='\t' || *b=='\n')return -EINVAL;
 errno=0;val=strtol(b,&end,base);
 if(errno==ERANGE || val>INT_MAX || val<INT_MIN)return -ERANGE;
 if(end==b)return -EINVAL;
 if(*end=='\n')end++;
 if(*end)return -EINVAL;
 *v=val;return 0;
}
''' + '\n'.join(re.search(r'enum '+name+r'\s*\{.*?\};', events, re.S)[0]
                 for name in ['mca_event_type', 'mca_event_code']) + '\n' + function(consumer, 'connector_antiburn_thermal_notifier_event') + r'''
static int delivered[4096], deliveries;
static void mca_event_block_notify(unsigned type,unsigned long event,void *data) {
 assert(type==MCA_EVENT_TYPE_THERMAL_TEMP && event==MCA_EVENT_THERMAL_BOARD_TEMP_CHANGE);
 assert(deliveries<4096);
 delivered[deliveries++]=*(int *)data;
 connector_antiburn_thermal_notifier_event(&conn.thermal_board_nb,event,data);
}
''' + re.search(r'struct mi_board_thermal\s*\{.*?\};', s, re.S)[0] + r'''
static struct mi_board_thermal board_thermal;
static struct device *thermal_message;
static struct device dev;
static struct device_node node;
static int missing, disabled, read_error, alloc_fail, create_error, node_puts, allocs, frees, creates, removes;
static const char *name="VIRTUAL-SENSOR0";
static struct device_node *of_find_node_by_path(const char *path) {
 assert(!strcmp(path,"/soc/thermal-message"));return missing?NULL:&node;
}
static bool of_device_is_available(struct device_node *n) { return !disabled; }
static int of_property_read_string(struct device_node *n,const char *key,const char **v) {
 assert(n==&node && !strcmp(key,"board-sensor"));if(read_error)return read_error;*v=name;return 0;
}
static char *kstrdup(const char *s,int flags) { if(alloc_fail)return NULL;allocs++;return strdup(s); }
static void of_node_put(struct device_node *n) { assert(n==&node);node_puts++; }
static void kfree(const void *p) { assert(p && allocs>frees);frees++;free((void *)p); }
static struct device *thermal_auxiliary_device_create(const char *n,void *data,const struct attribute_group **groups) {
 assert(!strcmp(n,"thermal_message") && data==&board_thermal);creates++;
 if(create_error)return ERR_PTR(create_error);dev.data=data;return &dev;
}
static void device_unregister(struct device *d) { assert(d==&dev && allocs>frees);removes++; }
''' + '\n'.join(function(s, n) for n in ['board_sensor_show','board_sensor_temp_show',
    'board_sensor_temp_store','mi_board_thermal_init','mi_board_thermal_exit']) + r'''
static int cases;
static void reset(void) {
 memset(&board_thermal,0,sizeof(board_thermal));missing=disabled=read_error=alloc_fail=create_error=0;
 node_puts=allocs=frees=creates=removes=deliveries=0;name="VIRTUAL-SENSOR0";
}
static void init_tests(void) {
 reset();missing=1;assert(mi_board_thermal_init()==-ENODEV && !node_puts && !allocs && !creates);cases++;
 reset();disabled=1;assert(mi_board_thermal_init()==-ENODEV && node_puts==1 && !allocs && !creates);cases++;
 reset();read_error=-EINVAL;assert(mi_board_thermal_init()==-EINVAL && node_puts==1 && !allocs && !creates);cases++;
 reset();name="";assert(mi_board_thermal_init()==-EINVAL && node_puts==1 && !allocs && !creates);cases++;
 reset();alloc_fail=1;assert(mi_board_thermal_init()==-ENOMEM && node_puts==1 && !allocs && !creates);cases++;
 reset();create_error=-EEXIST;assert(mi_board_thermal_init()==-EEXIST && node_puts==1 && allocs==1 && frees==1 && !removes);
 pthread_mutex_destroy(&board_thermal.lock.p);cases++;
 reset();assert(!mi_board_thermal_init() && node_puts==1 && allocs==1 && !frees && creates==1);
 char b[4096];assert(board_sensor_show(&dev,0,b)>0 && !strcmp(b,"VIRTUAL-SENSOR0\n"));
 assert(board_sensor_temp_show(&dev,0,b)==-ENODATA && !deliveries);cases++;
}
static void *writer(void *arg) {
 intptr_t base=(intptr_t)arg;
 for(int i=0;i<500;i++) { char b[32];snprintf(b,sizeof(b),"%ld\n",(long)(base+i));
  assert(board_sensor_temp_store(&dev,0,b,strlen(b))==(ssize_t)strlen(b)); }
 return NULL;
}
int main(void) {
 init_tests();
 char empty_read[4096];
 assert(board_sensor_temp_store(&dev,0,"invalid",7)==-EINVAL);
 assert(!board_thermal.valid && !deliveries);
 assert(board_sensor_temp_show(&dev,0,empty_read)==-ENODATA);cases++;
 int valid[]={INT_MIN,-40000,-1001,-1,0,1,37000,55000,125000,INT_MAX};
 char b[4096],out[4096];
 for(unsigned i=0;i<sizeof(valid)/sizeof(valid[0]);i++) {
  snprintf(b,sizeof(b),"%d\n",valid[i]);int old=deliveries;
  assert(board_sensor_temp_store(&dev,0,b,strlen(b))==(ssize_t)strlen(b));
  assert(deliveries==old+1 && delivered[old]==valid[i]);
  assert(conn.thermal_board_temp==valid[i]/1000);
  assert(board_sensor_temp_show(&dev,0,out)==(ssize_t)strlen(b) && !strcmp(b,out));cases++;
 }
 const char *bad[]={"","\n","x","1x","1\n2","2147483648","-2147483649","99999999999999999999999999"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
  int before=deliveries,temperature=board_thermal.temperature;
  assert(board_sensor_temp_store(&dev,0,bad[i],strlen(bad[i]))<0);
  assert(deliveries==before && board_thermal.temperature==temperature);cases++;
 }
 pthread_t t[4];
 for(int i=0;i<4;i++)assert(!pthread_create(&t[i],NULL,writer,(void *)(intptr_t)(i*1000)));
 for(int i=0;i<4;i++)assert(!pthread_join(t[i],NULL));
 assert(deliveries==2010 && board_thermal.temperature==delivered[deliveries-1]);
 assert(conn.thermal_board_temp==board_thermal.temperature/1000);cases++;
 int before=deliveries;
 snprintf(b,sizeof(b),"%d\n",board_thermal.temperature);
 assert(board_sensor_temp_store(&dev,0,b,strlen(b))==(ssize_t)strlen(b));
 assert(deliveries==before+1 && delivered[before]==board_thermal.temperature);cases++;
 mi_board_thermal_exit();assert(removes==1 && frees==1);pthread_mutex_destroy(&board_thermal.lock.p);cases++;
 printf("PASS: %d board-temperature ABI/init/unwind cases and 2000 concurrent writes\n",cases);
}
'''
with tempfile.TemporaryDirectory() as t:
    c, exe = Path(t)/'test.c', Path(t)/'test'
    c.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                    '-Wno-unused-parameter','-Wno-misleading-indentation',
                    '-fsanitize=undefined','-fno-sanitize-recover=undefined','-pthread',
                    str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

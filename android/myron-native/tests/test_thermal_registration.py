#!/usr/bin/env python3
"""Exercise production CPU cooling registration retry and duplicate work."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(s, name):
    m = re.search(r'static\s+(?:void|int|unsigned int)\s+'+name+r'\(', s)
    start = s.index('{', m.end())
    i, depth = start+1, 1
    while depth:
        depth += (s[i]=='{')-(s[i]=='}')
        i += 1
    return s[m.start():i]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel-root',type=Path,required=True)
    p.add_argument('--source',type=Path)
    a=p.parse_args()
    s=(a.source or a.kernel_root/'drivers/thermal/qcom/qti_cpufreq_cdev.c').read_text()
    body='\n'.join(function(s,n) for n in ['compare_frequency','state_to_cpufreq','cpufreq_cdev_register'])
    pre=r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct work_struct {int unused;};
struct cpufreq_frequency_table {unsigned int frequency;};
struct cpufreq_policy {struct cpufreq_frequency_table *freq_table;int constraints;};
struct thermal_cooling_device {int registered;};
struct cpufreq_cdev_device {
 struct work_struct reg_work;struct thermal_cooling_device *cdev;
 int cpu,qos_max_freq_req;unsigned long max_state,cur_state;
 unsigned int *freq_table;struct cpufreq_policy *policy;char cdev_name[16];
};
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define pr_err(...) ((void)0)
#define pr_debug(...) ((void)0)
#define GFP_KERNEL 0
#define FREQ_QOS_MAX 0
#define IS_ERR(p) ((intptr_t)(p)<0)
#define PTR_ERR(p) ((intptr_t)(p))
#define cpufreq_for_each_valid_entry(p,t) for(p=t;p->frequency;p++)
static struct cpufreq_frequency_table table[]={{100},{300},{200},{0}};
static struct cpufreq_policy policy={table,0};
static struct thermal_cooling_device cooling;
static int refs,allocs,qos,cdevs,fail,cases,cpufreq_cdev_ops;
static struct cpufreq_policy *cpufreq_cpu_get(int cpu){
 (void)cpu;if(fail==1)return NULL;refs++;return &policy;
}
static void cpufreq_cpu_put(struct cpufreq_policy *p){assert(p==&policy && refs>0);refs--;}
static int cpufreq_table_count_valid_entries(struct cpufreq_policy *p){(void)p;return fail==2?0:3;}
static void *kmalloc_array(size_t n,size_t z,int f){
 (void)f;if(fail==3)return NULL;void *p=calloc(n,z);assert(p);allocs++;return p;
}
static void kfree(void *p){if(p){allocs--;free(p);}}
static void sort(void *a,size_t n,size_t z,int (*cmp)(const void *,const void *),void *swap){
 (void)swap;qsort(a,n,z,cmp);
}
static int freq_qos_add_request(int *c,int *r,int t,unsigned int freq){
 (void)c;(void)t;assert(freq==300);if(fail==4)return -1;
 assert(!*r);*r=1;qos++;return 0;
}
static void freq_qos_remove_request(int *r){assert(*r);*r=0;qos--;}
static struct thermal_cooling_device *thermal_cooling_device_register(const char *n,void *d,int *o){
 (void)n;(void)d;(void)o;if(fail==5)return (void *)(intptr_t)-1;cdevs++;return &cooling;
}
'''
    tests=r'''
static void cleanup(struct cpufreq_cdev_device *d){
 assert(d->cdev==&cooling && cdevs==1 && refs==1 && allocs==1 && qos==1);
 cdevs--;freq_qos_remove_request(&d->qos_max_freq_req);
 cpufreq_cpu_put(d->policy);kfree(d->freq_table);
}
int main(void){
 for(int n=0;n<=5;n++){
  struct cpufreq_cdev_device d={0};fail=n;
  cpufreq_cdev_register(&d.reg_work);
  if(n){
   assert(!d.cdev && !d.freq_table && !d.policy && !refs && !qos && !allocs && !cdevs);
   fail=0;cpufreq_cdev_register(&d.reg_work);
  }
  assert(d.max_state==2 && d.freq_table[0]==300 && d.freq_table[2]==100);
  unsigned int *original=d.freq_table;
  for(int repeat=0;repeat<16;repeat++){
   cpufreq_cdev_register(&d.reg_work);
   assert(d.freq_table==original && refs==1 && allocs==1 && qos==1 && cdevs==1);cases++;
  }
  cleanup(&d);cases++;
 }
 printf("PASS: %d CPU cooling registration cases; retries and duplicate work retain one owner\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c,exe=Path(tmp)/'test.c',Path(tmp)/'test'
        c.write_text(pre+body+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':
    main()

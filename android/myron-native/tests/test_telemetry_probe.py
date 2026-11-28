#!/usr/bin/env python3
"""Execute the production CPUSS probe against failing firmware/mapping backends."""
import argparse
from pathlib import Path
import subprocess
import tempfile

def function(src, name):
    at = src.index('static int ' + name + '(')
    start = src.index('{', at)
    end, depth = start + 1, 1
    while depth:
        depth += (src[end] == '{') - (src[end] == '}')
        end += 1
    return src[at:end]

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', type=Path, required=True)
p.add_argument('--source', type=Path)
a = p.parse_args()
src = (a.source or a.kernel_root / 'drivers/soc/qcom/cpuss_telemetry.c').read_text()
pre = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
#define TELEMETRY_MAX_COUNTERS 4096
#define SCMI_TELEMETRY_ALGO_STR 0x454c454d45545259ULL
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR_OR_NULL(p) (!(p) || IS_ERR(p))
#define IS_ALIGNED(x,n) (!((x) & ((n)-1)))
typedef uint64_t u64;
struct device { void *data; };
struct scmi_protocol_handle { int unused; };
struct qcom_scmi_vendor_ops {
 int (*get_param)(void *,void *,u64,int,int,size_t);
};
struct handle {
 struct qcom_scmi_vendor_ops *(*devm_protocol_get)(void *,int,void *);
};
struct scmi_device { struct device dev; struct handle *handle; int protocol_id; };
struct telemetry_global_param_t { uint32_t num_max_counters; u64 pname, pvalue; };
struct telemetry_counter_attributes_name_t { char name[32]; };
struct telemetry_counter_attributes_value_t { u64 value; };
struct cpuss_telemetry { void *header,*names,*values,*ph,*dir; unsigned count;
 struct qcom_scmi_vendor_ops *ops; };
static struct cpuss_telemetry instance, *active;
static struct telemetry_global_param_t header;
static int fail, response, maps, unmapped, requested, files, telemetry_lock;
static int counter_info_fops, update_fops;
static u64 address;
static void *devm_kzalloc(void *d,size_t n,int f) {
 (void)d;(void)f; assert(n==sizeof(instance));memset(&instance,0,n);
 return fail==1?NULL:&instance;
}
static int get_param(void *ph,void *buf,u64 algo,int id,int tx,size_t rx) {
 (void)ph;assert(algo==SCMI_TELEMETRY_ALGO_STR && !id && !tx && rx==8);
 requested++;*(u64 *)buf=address;return response;
}
static struct qcom_scmi_vendor_ops ops={get_param};
static struct qcom_scmi_vendor_ops *get_protocol(void *s,int id,void *ph) {
 (void)s;(void)id;(void)ph;return fail==2?(void *)(intptr_t)-EOPNOTSUPP:&ops;
}
static int dev_err_probe(void *d,int ret,const char *s) {(void)d;(void)s;return ret;}
static void *ioremap_cache(u64 addr,size_t len) {
 maps++;if (fail==maps+2)return NULL;
 if(maps==1){assert(addr==address && len==sizeof(header));return &header;}
 assert(len==header.num_max_counters*(maps==2?32:8));
 return (void *)(uintptr_t)addr;
}
static uint32_t readl(void *p){uint32_t v;memcpy(&v,p,4);return v;}
static u64 readq(void *p){u64 v;memcpy(&v,p,8);return v;}
static void mutex_lock(int *p){assert(!*p);*p=1;}
static void mutex_unlock(int *p){assert(*p);*p=0;}
static void telemetry_unmap(struct cpuss_telemetry *t){
 unmapped=!!t->header+!!t->names+!!t->values;
}
static void *debugfs_create_dir(const char *n,void *p){
 (void)n;(void)p;return fail==6?(void *)(intptr_t)-ENOMEM:(void *)0x2000;
}
static void debugfs_create_file(const char *n,int mode,void *dir,void *t,int *f){
 (void)n;(void)mode;(void)dir;(void)t;(void)f;files++;
}
static void dev_set_drvdata(struct device *d,void *t){d->data=t;}
'''
post = r'''
int main(void) {
 struct handle h={get_protocol};struct scmi_device s={.handle=&h};
 int cases=0;
 for(int i=0;i<12;i++) {
  response=0;fail=0;maps=unmapped=requested=files=0;active=NULL;s.dev.data=NULL;
  address=0x1000;header=(struct telemetry_global_param_t){2,0x3000,0x4000};
  int expected;
  if(i<4) {int codes[]={-ETIMEDOUT,-EIO,-EOPNOTSUPP,-EACCES};response=codes[i];expected=i?-codes[i]:EPROBE_DEFER;expected=-expected;}
  else if(i<10){fail=i-3;expected=fail==2?-EOPNOTSUPP:-ENOMEM;}
  else if(i==10){address=0;expected=-EINVAL;}
  else {header.num_max_counters=0;expected=-EINVAL;}
  int ret=scmi_cpuss_telemetry_probe(&s);
  assert(ret==expected && !active && !s.dev.data && !files && !telemetry_lock);
  if(response)assert(requested==1 && !maps);
  cases++;
 }
 response=0;fail=0;maps=unmapped=requested=files=0;address=0x1000;
 header=(struct telemetry_global_param_t){2,0x3000,0x4000};
 assert(!scmi_cpuss_telemetry_probe(&s));
 assert(active==&instance && s.dev.data==active && maps==3 && files==2);
 printf("PASS: %d probe failures plus successful retry; no premature mappings/publication\n",cases);
}
'''
with tempfile.TemporaryDirectory() as t:
    c,exe=Path(t)/'probe.c',Path(t)/'probe'
    c.write_text(pre+function(src,'scmi_cpuss_telemetry_probe')+post)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

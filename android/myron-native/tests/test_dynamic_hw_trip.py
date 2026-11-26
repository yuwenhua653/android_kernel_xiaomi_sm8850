#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute production dynamic-trip initialization with DT and SCMI failures."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_sc96281_irq import function

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', required=True, type=Path)
p.add_argument('--source', type=Path)
a = p.parse_args()
s = (a.source or a.kernel_root/'drivers/thermal/qcom/qti_dynamic_hw_trip.c').read_text()
code = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
struct device_node { int present, error; u32 value; };
struct device { struct device_node *of_node; };
struct thermal_trip { int temperature; };
struct dyn_hw_trip { struct device *dev; int last_thresh_req; uint64_t last_req_ts; };
static int get_error,set_error,gets,sets,written;
static void *of_find_property(struct device_node *n,const char *p,void *len) {
 assert(!strcmp(p,"qcom,trip-temperature") && !len);return n->present?n:NULL;
}
static int of_property_read_u32(struct device_node *n,const char *p,u32 *v) {
 assert(!strcmp(p,"qcom,trip-temperature"));*v=n->value;return n->error;
}
static int qcom_scmi_vp_get_trip_temp(struct dyn_hw_trip *d,int *v) {
 (void)d;gets++;if(!get_error)*v=87000;return get_error;
}
static int qcom_scmi_vp_set_trip_temp(struct dyn_hw_trip *d,int v) {
 (void)d;sets++;written=v;return set_error;
}
static uint64_t sched_clock(void) { return 12345; }
'''+function(s,'qcom_dynamic_hw_init_trip')+r'''
int main(void) {
 int cases=0;
 for(int present=0;present<2;present++)for(int fail=0;fail<4;fail++){
  struct device_node np={present,fail==1?-EINVAL:0,fail==2?UINT32_MAX:95000};
  struct device dev={&np};struct dyn_hw_trip d={&dev,123,456};struct thermal_trip t={321};
  gets=sets=0;get_error=set_error=fail==3?-EIO:0;
  int r=qcom_dynamic_hw_init_trip(&d,&t);
  if(present){
   assert(!gets);
   if(fail){assert(r<0 && t.temperature==321 && d.last_thresh_req==123 && d.last_req_ts==456);}
   else{assert(!r && t.temperature==95000 && d.last_thresh_req==95000 && d.last_req_ts==12345);}
   assert(sets==(fail==0||fail==3));if(sets)assert(written==95000);
  }else{
   assert(gets==1 && !sets && r==get_error);
   assert(t.temperature==(get_error?321:87000));assert(d.last_thresh_req==123 && d.last_req_ts==456);
  }
  cases++;
 }
 /* DT initialization must work with a write-capable, read-unsupported firmware. */
 struct device_node np={1,0,95000};struct device dev={&np};
 struct dyn_hw_trip d={.dev=&dev};struct thermal_trip t={0};
 get_error=-EOPNOTSUPP;set_error=0;gets=sets=0;
 assert(!qcom_dynamic_hw_init_trip(&d,&t) && !gets && sets==1 && t.temperature==95000);cases++;
 printf("PASS: %d dynamic-trip DT/SCMI initialization cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src, exe = Path(tmp)/'test.c', Path(tmp)/'test'
    src.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

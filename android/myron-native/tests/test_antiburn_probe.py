#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise production antiburn probe ordering and GPIO failure ownership."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_sc96281_irq import function
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root',type=Path,required=True)
p.add_argument('--source',type=Path)
a=p.parse_args()
s=(a.source or a.kernel_root/'drivers/power/supply/mca/mca_hardware_monitor/mca_connector_antiburn.c').read_text()
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
#define EXTERNAL_BOOST 1
#define MCA_EVENT_TYPE_THERMAL_TEMP 0
#define MCA_EVENT_TYPE_SUBPMIC_INFO 1
#define MCA_CHARGE_LOG_ID_USCP 0
#define mca_log_info(...) do { if(0) printf(__VA_ARGS__); } while(0)
#define mca_log_err(...) do { if(0) printf(__VA_ARGS__); } while(0)
#define mca_log_charge_log_register(...) ((void)0)
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define ERR_PTR(v) ((void *)(intptr_t)(v))
#define INIT_DELAYED_WORK(...) ((void)0)
#define msecs_to_jiffies(v) (v)
#define gpio_to_desc(n) (n)
struct device { void *of_node; };
struct platform_device { struct device dev; void *data; };
struct notifier { void *notifier_call; };
struct connector_antiburn {
 struct device *dev; int support_hw_antiburn,mos_ctrl_gpio,use_double_ntc,monitor_interval;
 int otg_boost_src,triggered,disable_antiburn,monitor_work;
 const char *thermal_zone_name,*thermal_zone_name2;
 void *tzd_conn,*tzd_conn2; struct notifier thermal_board_nb,debug_nb;
};
struct mca_hwid { int platform_version,major_version,minor_version; const char *product_name; };
static struct mca_hwid hwid={2,1,0,"myron"};
static struct connector_antiburn *g_conn;
static int have_hwid=1,hardware=1,double_ntc=1,names=1,zone_error,zone_index;
static int gpio_number=42,request_error,direction_error,owned,requests,directions,frees,queued;
static void *allocation;
static const struct mca_hwid *mca_get_hwid_info(void) { return have_hwid?&hwid:0; }
static void *devm_kzalloc(struct device *d,size_t n,int f) { (void)d;(void)f; allocation=calloc(1,n);return allocation; }
static void devm_kfree(struct device *d,void *p) { (void)d;free(p);allocation=0; }
static void platform_set_drvdata(struct platform_device *p,void *d) { p->data=d; }
static void connector_antiburn_parse_dt(struct connector_antiburn *c) {
 c->support_hw_antiburn=hardware;c->use_double_ntc=double_ntc;
 c->thermal_zone_name=names?"conn_therm":0;c->thermal_zone_name2="conn_therm2";
}
static int of_get_named_gpio(void *p,const char *n,int i) { (void)p;(void)n;(void)i;return gpio_number; }
static bool gpio_is_valid(int n) { return n>=0; }
static int gpio_request(int n,const char *s) { (void)n;(void)s;requests++;if(request_error)return request_error;assert(!owned);owned=1;return 0; }
static void gpio_free(int n) { (void)n;assert(owned);owned=0;frees++; }
static int gpiod_direction_output_raw(int g,int v) { (void)g;assert(owned&&!v);directions++;return direction_error; }
static void *thermal_zone_get_zone_by_name(const char *n) { assert(n);zone_index++;return zone_index==zone_error?ERR_PTR(-ENODEV):&hwid; }
static int dev_err_probe(struct device *d,int err,const char *s,...) { (void)d;(void)s;return err; }
static int connector_antiburn_thermal_notifier_event,connector_antiburn_debug_notifier_cb;
#define mca_event_block_notify_register(...) ((void)0)
static void mca_queue_delayed_work(int *w,int n) { (void)w;(void)n;queued++; }
static void antiburn_sysfs_create_group(struct device *d) { (void)d; }
'''
# Callback symbols need addresses, as actual notifier functions decay to pointers.
code=code.replace('static int connector_antiburn_thermal_notifier_event,connector_antiburn_debug_notifier_cb;',
 'static void connector_antiburn_thermal_notifier_event(void) {}\nstatic void connector_antiburn_debug_notifier_cb(void) {}')
for n in ['connector_antiburn_mos_ctrl_gpio_init','connector_antiburn_gpio_init','connector_antiburn_probe']:
 code+=function(s,n)+'\n'
code+=r'''
static void reset(void) {
 free(allocation);allocation=0;g_conn=0;
 have_hwid=hardware=double_ntc=names=1;
 zone_error=zone_index=request_error=direction_error=owned=requests=directions=frees=queued=0;
 gpio_number=42;
}
int main(void) {
 struct platform_device p={0};int cases=0;
 for(int zone=1;zone<=2;zone++) {
  reset();zone_error=zone;
  assert(connector_antiburn_probe(&p)==-EPROBE_DEFER);
  assert(!requests&&!directions&&!frees&&!owned&&!queued);cases++;
 }
 reset();have_hwid=0;assert(connector_antiburn_probe(&p)==-EPROBE_DEFER);assert(!requests);cases++;
 reset();names=0;assert(connector_antiburn_probe(&p)==-EINVAL);assert(!requests);cases++;
 reset();gpio_number=-EPROBE_DEFER;
 assert(connector_antiburn_probe(&p)==-EPROBE_DEFER);assert(!requests&&!frees);cases++;
 reset();request_error=-EBUSY;
 assert(connector_antiburn_probe(&p)==-EBUSY);assert(requests==1&&!frees&&!directions&&!owned);cases++;
 reset();direction_error=-EIO;
 assert(connector_antiburn_probe(&p)==-EIO);assert(requests==1&&directions==1&&frees==1&&!owned);cases++;
 reset();assert(!connector_antiburn_probe(&p));assert(owned&&queued==1&&g_conn==p.data);cases++;
 reset();hardware=0;
 assert(!connector_antiburn_probe(&p));assert(!requests&&!directions&&!frees&&queued==1);cases++;
 reset();double_ntc=0;zone_error=2;
 assert(!connector_antiburn_probe(&p));assert(zone_index==1&&owned&&queued==1);cases++;
 reset();printf("PASS: %d antiburn sensor-before-GPIO, deferral and ownership cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';e=Path(d)/'test';c.write_text(code)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=undefined',str(c),'-o',str(e)],check=True)
 subprocess.run([str(e)],check=True)

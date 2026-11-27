#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual BMD resource/probe/work/teardown C with mocked kernel APIs.

Host ASan/UBSan regression test; not an IIO/GPIO or kernel workqueue test.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'drivers/power/supply/mca/mca_hardware_monitor/mca_bmd.c').read_text()
core = source[source.index('#define BTB_OPEN_MAX_VOL'):source.index('enum btb_attr_list')]
lifecycle = source[source.index('static void mca_bmd_stop('):source.index('static const struct of_device_id')]
header = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
#define GPIOF_IN 1
#define MAIN_BUCK_CHARGER 0
#define WIRELESS_ROLE_MASTER 0
#define STRATEGY_FUNC_TYPE_BMD 0
#define STRATEGY_STATUS_TYPE_BMD_BATT_MISSING 0
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define IS_ERR(x) ((uintptr_t)(x) >= (uintptr_t)-4095)
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define msecs_to_jiffies(x) (x)
enum { MASTER_BTB, SLAVE_BTB, MAX_BTB };
enum { MCA_EVENT_TYPE_HW_INFO, MCA_EVENT_TYPE_BATTERY_INFO,
       MCA_EVENT_BATT_BTB_CHANGE, MCA_EVENT_BATTERY_FAKE_POWER,
       MCA_EVENT_USB_CONNECT, MCA_EVENT_WIRELESS_CONNECT,
       MCA_EVENT_USB_DISCONNECT, MCA_EVENT_WIRELESS_DISCONNECT,
       MIEVENT_STATE_END, CHARGE_DFX_BATTERY_MISSING, CHARGE_DFX_DUAL_BATTERY_MISSING };
struct device_node { int unused; };
struct device { struct device_node *of_node; void *data; };
struct platform_device { struct device dev; };
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; int initialized, pending; void (*fn)(struct work_struct *); };
struct iio_channel { int unused; };
static struct iio_channel channel;
static int scheme_values[2], parse_error, adc_error, gpio_number, gpio_error;
static int gpio_requests, adc_reads, adc_read_error, adc_value, gpio_value, fg_result;
static int register_error, sysfs_error, reg_calls, unreg_calls, sysfs_removes;
static int buck_error, buck_online, wireless_error, wireless_online;
static int schedule_count, cancel_count, notifications, sequence, unreg_sequence, last_cancel;
static int dispatch_on_register, dispatch_on_unregister;
static void *registered_data, *allocation;
static void init_work(struct delayed_work *w, void (*fn)(struct work_struct *)) {
    assert(!w->initialized); w->initialized=1; w->fn=fn;
}
#define INIT_DELAYED_WORK(w,fn) init_work(w,fn)
static int schedule_delayed_work(struct delayed_work *w, int delay) {
    (void)delay; assert(w->initialized); w->pending=1; schedule_count++; return 1;
}
static int cancel_delayed_work_sync(struct delayed_work *w) {
    assert(w->initialized); w->pending=0; cancel_count++; last_cancel=++sequence; return 1;
}
static void *devm_kzalloc(struct device *dev, size_t size, int flags) {
    (void)dev; (void)flags; assert(!allocation); return allocation=calloc(1,size);
}
static void platform_set_drvdata(struct platform_device *p, void *data) { p->dev.data=data; }
static void *platform_get_drvdata(struct platform_device *p) { return p->dev.data; }
static int mca_parse_dts_u32_array(struct device_node *n,const char *s,int *v,int count) {
    (void)n; (void)s; assert(count==2); memcpy(v,scheme_values,sizeof(scheme_values)); return parse_error;
}
static void mca_parse_dts_u32(struct device_node *n,const char *s,int *v,int def) {
    (void)n; (void)s; *v=def;
}
static struct iio_channel *devm_iio_channel_get(struct device *d,const char *s) {
    (void)d; (void)s; return adc_error ? ERR_PTR(adc_error) : &channel;
}
static int of_get_named_gpio(struct device_node *n,const char *s,int i) {
    (void)n; (void)s; assert(i==0); return gpio_number;
}
static int devm_gpio_request_one(struct device *d,int gpio,int flags,const char *s) {
    (void)d; (void)s; assert(gpio>=0 && flags==GPIOF_IN); gpio_requests++; return gpio_error;
}
static int iio_read_channel_processed(struct iio_channel *ch,int *v) {
    assert(ch==&channel); adc_reads++; *v=adc_value; return adc_read_error;
}
static int gpio_get_value_cansleep(int gpio) { assert(gpio>=0); return gpio_value; }
static int strategy_class_fg_dual_is_chip_ok(int index) { assert(index<2); return fg_result; }
static int strategy_class_fg_is_chip_ok(void) { return fg_result; }
static void mca_event_block_notify(int type,int event,void *data) {
    (void)type; (void)event; assert(data); notifications++;
}
static void mca_charge_mievent_set_state(int state,int event) { (void)state; (void)event; }
static void mca_charge_mievent_report(int event,void *data,int count) { (void)event; (void)data; (void)count; }
static int platform_class_buckchg_ops_get_online(int role,int *value) {
    (void)role; *value=buck_online; return buck_error;
}
static int platform_class_wireless_is_present(int role,int *value) {
    (void)role; *value=wireless_online; return wireless_error;
}
static int btb_sysfs_create_group(struct device *dev) { (void)dev; return sysfs_error; }
static void btb_sysfs_remove_group(struct device *dev) { (void)dev; sysfs_removes++; }
static int (*dispatch)(int,int,void *);
static int mca_strategy_ops_register(unsigned int type,int (*fn)(int,int,void *),
                                    int (*get)(int,void *,void *),void *set,void *data) {
    (void)type; (void)get; (void)set; reg_calls++;
    if(register_error) return register_error;
    assert(!registered_data); registered_data=data; dispatch=fn;
    if(dispatch_on_register) assert(!fn(MCA_EVENT_USB_DISCONNECT,0,data));
    return 0;
}
static int mca_strategy_ops_unregister(unsigned int type,void *data) {
    (void)type; assert(registered_data==data); unreg_calls++; unreg_sequence=++sequence;
    if(dispatch_on_unregister) assert(dispatch(MCA_EVENT_USB_DISCONNECT,0,data)==-ENODEV);
    registered_data=NULL; return 0;
}
''' + core + lifecycle + r'''
static struct device_node node;
static struct platform_device pdev;
static void reset(void) {
    assert(!registered_data);
    free(allocation); allocation=NULL;
    memset(&pdev,0,sizeof(pdev)); pdev.dev.of_node=&node;
    scheme_values[0]=ADC_SCHEME; scheme_values[1]=IIC_SCHEME;
    parse_error=adc_error=gpio_error=register_error=sysfs_error=0; gpio_number=42;
    gpio_requests=adc_reads=adc_read_error=0; adc_value=1600; gpio_value=0; fg_result=1;
    reg_calls=unreg_calls=sysfs_removes=0;
    buck_error=wireless_error=buck_online=wireless_online=0;
    schedule_count=cancel_count=notifications=sequence=unreg_sequence=last_cancel=0;
    dispatch_on_register=dispatch_on_unregister=0;
}
static void failed_probe(int expected) {
    assert(mca_bmd_probe(&pdev)==expected);
    assert(!registered_data && !schedule_count);
}
int main(void) {
    reset(); pdev.dev.of_node=NULL; failed_probe(-EINVAL);
    reset(); parse_error=-EIO; failed_probe(-EIO);
    reset(); adc_error=-EPROBE_DEFER; failed_probe(-EPROBE_DEFER); assert(!reg_calls && !adc_reads);
    reset(); adc_error=-ENODEV; failed_probe(-ENODEV);
    reset(); scheme_values[0]=GPIO_SCHEME; gpio_number=-EPROBE_DEFER;
    failed_probe(-EPROBE_DEFER); assert(!gpio_requests);
    reset(); scheme_values[0]=GPIO_SCHEME; gpio_error=-EBUSY; failed_probe(-EBUSY);
    reset(); scheme_values[0]=INT_SCHEME; failed_probe(-EOPNOTSUPP);
    reset(); scheme_values[0]=-1; failed_probe(-EINVAL);
    reset(); scheme_values[0]=MAX_SCHEME; failed_probe(-EINVAL);
    reset(); register_error=-EBUSY; failed_probe(-EBUSY); assert(!unreg_calls && !cancel_count);
    reset(); sysfs_error=-ENOMEM; dispatch_on_register=1; dispatch_on_unregister=1;
    assert(mca_bmd_probe(&pdev)==-ENOMEM);
    struct mca_bmd_dev *info=pdev.dev.data;
    assert(!registered_data && unreg_calls==1 && !sysfs_removes);
    assert(!info->monitor_bmd_work.pending && !info->delay_report_bmd_sts_work.pending);
    assert(last_cancel>unreg_sequence && !mca_bmd_get_btb_status(NULL,0));
    reset(); scheme_values[0]=GPIO_SCHEME; scheme_values[1]=GPIO_SCHEME;
    assert(!mca_bmd_probe(&pdev) && gpio_requests==1);
    info=pdev.dev.data;
    assert(info->batt_missing);  /* unknown must not be advertised healthy */
    assert(!mca_bmd_get_btb_status(info,-1) && !mca_bmd_get_btb_status(info,MAX_BTB));
    assert(mca_bmd_get_btb_status(info,0));
    gpio_value=1; assert(!mca_bmd_get_btb_status(info,0));
    gpio_value=-EIO; assert(!mca_bmd_get_btb_status(info,0));
    dispatch_on_unregister=1;
    mca_bmd_shutdown(&pdev); mca_bmd_remove(&pdev);
    assert(unreg_calls==1 && sysfs_removes==1 && cancel_count==2 && last_cancel>unreg_sequence);
    int old_schedule=schedule_count, old_notifications=notifications;
    mca_bmd_monitor_workfunc(&info->monitor_bmd_work.work);
    mca_bmd_delay_report_bmd_sts_work(&info->delay_report_bmd_sts_work.work);
    assert(schedule_count==old_schedule && notifications==old_notifications);
    u32 status=77;
    assert(mca_bmd_get_status(0,&status,info)==-ENODEV && status==77);
    reset(); assert(!mca_bmd_probe(&pdev)); info=pdev.dev.data;
    assert(mca_bmd_get_btb_status(info,0));
    adc_value=1800; assert(!mca_bmd_get_btb_status(info,0));
    adc_value=1700; assert(mca_bmd_get_btb_status(info,0));
    adc_value=1900; assert(mca_bmd_get_btb_status(info,0));
    adc_read_error=-EIO; assert(!mca_bmd_get_btb_status(info,0)); adc_read_error=0;
    fg_result=-EIO; assert(!mca_bmd_get_btb_status(info,1)); fg_result=1;
    mca_bmd_delay_report_bmd_sts_work(&info->delay_report_bmd_sts_work.work);
    assert(!info->batt_missing && !mca_bmd_get_status(0,&status,info) && status==0);
    adc_value=1800; mca_bmd_monitor_workfunc(&info->monitor_bmd_work.work);
    assert(info->batt_missing && info->monitor_bmd_work.pending);
    mca_bmd_remove(&pdev);
    reset(); buck_online=1; wireless_error=-ENODEV;
    assert(!mca_bmd_probe(&pdev)); info=pdev.dev.data; assert(info->monitor_bmd_work.pending);
    mca_bmd_remove(&pdev);
    reset(); buck_online=wireless_online=1; buck_error=wireless_error=-EIO;
    assert(!mca_bmd_probe(&pdev)); info=pdev.dev.data; assert(!info->monitor_bmd_work.pending);
    mca_bmd_remove(&pdev); reset();
    puts("PASS: actual BMD supplier errors, managed GPIO, callback publication/unwind, stop ordering and conservative samples");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-bmd-') as d:
    c=Path(d)/'test.c'; exe=Path(d)/'test'; c.write_text(header)
    subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Wall','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

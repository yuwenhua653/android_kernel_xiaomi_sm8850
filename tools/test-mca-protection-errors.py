#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual protection sampling/worker/stop paths with fault injection.
No claim about calibrated limits, physical charging or actual workqueue behavior.
"""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]/'drivers/power/supply/mca/mca_hardware_monitor'
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#include <limits.h>
typedef int64_t s64;
#define abs(x) ((x)<0?-(x):(x))
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define MAIN_BUCK_CHARGER 0
#define WIRELESS_ROLE_MASTER 0
#define LOADSW_ROLE_MASTER 0
#define FG_IC_MASTER 0
#define FG_IC_SLAVE 1
#define CHARGE_DFX_LOAD_SWITCH_I2C_ERR 0
#define MCA_EVENT_TYPE_HW_INFO 0
#define MCA_EVENT_IBAT_OCP_CHANGE 1
#define MCA_EVENT_VBAT_OVP_CHANGE 2
#define SYSFS_DEV_5 "charger"
#define FAST_HEARTBEAT_TIMER_MS 10000
#define NORMAL_HEARTBEAT_TIMER_MS 60000
struct device {int unused;};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;};
static int buck_error,wireless_error=-EOPNOTSUPP,temp_error,volt_error,current_error,fast=1;
static int usb=1,wireless_reads,current[2]={200,0},voltage=5000,temperature=250;
static int notifications,schedules,last_interval,removes,cancels;
static int platform_class_buckchg_ops_get_online(int id,int *v){if(buck_error)return buck_error;*v=usb;return 0;}
static int platform_class_wireless_is_present(int id,int *v){wireless_reads++;if(wireless_error)return wireless_error;*v=0;return 0;}
static int platform_class_loadsw_get_present(int id,bool *v){*v=true;return 0;}
static int strategy_class_fg_get_fastcharge(void){return fast;}
static int strategy_class_fg_ops_get_temperature(int *v){if(temp_error)return temp_error;*v=temperature;return 0;}
static int strategy_class_fg_ops_get_voltage(int *v){if(volt_error)return volt_error;*v=voltage;return 0;}
static int platform_fg_ops_get_curr(int id,int *v){if(current_error==id+1)return -EIO;*v=current[id];return 0;}
static void mca_charge_mievent_report(int id,void *p,int n){}
static void mca_event_block_notify(int kind,int event,void *v){assert(*(int*)v>=0);notifications++;}
static int msecs_to_jiffies(int ms){return ms;}
static void schedule_delayed_work(struct delayed_work *p,int delay){schedules++;last_interval=delay;}
static void mca_sysfs_remove_link_group(const char *parent,const char *name,struct device *d,void *group){assert(!cancels);removes++;}
static void cancel_delayed_work_sync(struct delayed_work *p){cancels++;}
'''
for tag,kind in [('ibat','ocp'),('vbat','ovp')]:
 s=(root/f'mca_{tag}_{kind}_monitor.c').read_text()
 a=s.index(f'static int mca_{tag}_mon_get_');b=s.index(f'static int mca_{tag}_{kind}_mon_parse_dt',a)
 body=s[a:b];a=s.index(f'static void mca_{tag}_{kind}_mon_stop');b=s.index(f'static int mca_{tag}_{kind}_mon_probe',a);body+=s[a:b]
 h=(root/f'inc/mca_{tag}_{kind}_monitor.h').read_text()
 setup='struct mca_'+tag+'_'+kind+'_mon_dev info={0},other={0};struct device d={0};info.dev=&d;'
 if tag=='ibat':
  tests=r'''
 info.fg_type=other.fg_type=MCA_FG_TYPE_PARALLEL;
 info.ocp_threshold[0]=info.ocp_threshold[1]=other.ocp_threshold[0]=other.ocp_threshold[1]=100;
 assert(mca_ibat_mon_get_ibat_ocp_status(&info)==2 && !wireless_reads);
 assert(info.triggered && !other.triggered);
 current_error=1;assert(mca_ibat_mon_get_ibat_ocp_status(&info)==-EIO);
 info.batt_ocp_status=2;mca_ibat_ocp_monitor_workfunc(&info.monitor_ibat_ocp_work.work);
 assert(info.batt_ocp_status==2 && !notifications && schedules==1 && last_interval==10000);
 current_error=2;assert(mca_ibat_mon_get_ibat_ocp_status(&info)==-EIO);current_error=0;
 current[0]=INT_MIN;assert(mca_ibat_mon_get_ibat_ocp_status(&info)==2);
 current[0]=0;assert(!mca_ibat_mon_get_ibat_ocp_status(&info) && !info.triggered);
 fast=-EIO;assert(mca_ibat_mon_get_ibat_ocp_status(&info)==-EIO);fast=1;
 usb=0;assert(mca_ibat_mon_get_ibat_ocp_status(&info)==-EOPNOTSUPP);usb=1;
 buck_error=-EIO;assert(mca_ibat_mon_get_ibat_ocp_status(&info)==-EIO);buck_error=0;
 info.fg_type=MCA_FG_TYPE_SINGLE;assert(mca_ibat_mon_get_ibat_ocp_status(&info)==-EOPNOTSUPP);
'''
 else:
  tests=r'''
 info.fg_type=MCA_FG_TYPE_SINGLE;info.vbat_ovp_thr_ffr_mv=info.vbat_ovp_thr_nor_mv=4500;
 info.vbat_ovp_thr_hys_mv=50;info.vbat_ovp_recharge_delta_mv=100;
 assert(mca_vbat_mon_get_vbat_ovp_status(&info)==1 && !wireless_reads);
 assert(info.triggered && !other.triggered);
 temp_error=-EIO;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==-EIO);temp_error=0;
 volt_error=-EIO;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==-EIO);
 info.batt_ovp_status=1;mca_vbat_ovp_monitor_workfunc(&info.monitor_vbat_ovp_work.work);
 assert(info.batt_ovp_status==1 && !notifications && schedules==1 && last_interval==10000);volt_error=0;
 fast=-EIO;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==-EIO);fast=1;
 voltage=4450;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==1);
 voltage=4400;assert(!mca_vbat_mon_get_vbat_ovp_status(&info) && !info.triggered);
 voltage=5000;info.fg_type=MCA_FG_TYPE_SINGLE_SERIES;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==1);
 usb=0;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==-EOPNOTSUPP);usb=1;
 buck_error=-EIO;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==-EIO);buck_error=0;
 info.fg_type=MCA_FG_TYPE_PARALLEL;assert(mca_vbat_mon_get_vbat_ovp_status(&info)==-EOPNOTSUPP);
'''
 test='int main(void){'+setup+tests+f'''
 info.sysfs_created=true;mca_{tag}_{kind}_mon_stop(&info);assert(!info.sysfs_created && removes==1 && cancels==1);
 mca_{tag}_{kind}_mon_stop(&info);assert(removes==1 && cancels==2);
 puts("PASS: {tag} wired-only sampling, provider failures, fault preservation, per-instance state, topology and stop ordering");return 0;
}}'''
 with tempfile.TemporaryDirectory() as tmp:
  c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(pre+h+f'\nstatic int {tag}_{kind}_sysfs_attr_group;\n'+body+test)
  subprocess.run([os.getenv('CC','cc'),'-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(c),'-o',str(exe)],check=True)
  env=dict(os.environ);env.setdefault('ASAN_OPTIONS','detect_leaks=0');subprocess.run([str(exe)],check=True,env=env)

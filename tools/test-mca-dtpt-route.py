#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test actual FG -> business -> Nezha JEITA DTPT functions with synchronous stubs.
The real notifier queue, gauge and charging hardware are not exercised.
"""
from pathlib import Path
import os,subprocess,tempfile
base=Path(__file__).resolve().parents[1]/'drivers/power/supply/mca'
def region(path,start,end):
 s=(base/path).read_text();return s[s.index(start):s.index(end,s.index(start))]
jeita=region('mca_strategy/strategy_charger/mca_buckchg_jeita.c','static int mca_nezha_jeita_process_event','static int mca_buckchg_jeita_process_event')
route=region('mca_business/business_charger/mca_business_charger.c','static void\nbusiness_charger_process_dtpt_change','static void business_charger_process_fg_ota')
fg=region('mca_strategy/strategy_fg/mca_strategy_fg.c','static void strategy_fg_dtpt_monitor_work','static void strategy_fl4p0_calibration_work')
events=(base/'include/mca/common/mca_event.h').read_text().replace('#include <linux/notifier.h>','struct notifier_block;')
strategy=(base/'include/mca/strategy/strategy_class.h').read_text().replace('#include <linux/types.h>','')
pre=r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <assert.h>
#include <errno.h>
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define mca_log_info(...) ((void)0)
#define max(a,b) ((a)>(b)?(a):(b))
#define FG_IC_MASTER 0
#define FG_IC_SLAVE 1
#define MCA_FG_TYPE_SINGLE_NUM_MAX 0
#define STRATEGY_FG_WORK_INTERVAL_DTPT 1000
struct proc {int cur_jeita_index,temp_hys_en,max_chg_curr;};
struct mca_buckchg_jeita_dev {bool stopping,usb_online,wireless_online;int event_lock,monitor_work,online,dtpt_status;struct proc proc_data,flip_proc_data,base_proc_data;};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;};
struct strategy_fg {struct {int fg_type;} cfg;struct delayed_work dtpt_monitor_work;};
struct business_charger {int unused;};
static int bad_gauge,alert,notifications,schedules;
static struct mca_buckchg_jeita_dev ji;
static struct business_charger business;
static void mutex_lock(int *p){assert(!*p);*p=1;}
static void mutex_unlock(int *p){assert(*p);*p=0;}
static void cancel_delayed_work_sync(void *w){}
static void schedule_delayed_work(void *w,int delay){schedules++;}
static int msecs_to_jiffies(int n){return n;}
static int platform_fg_ops_get_isc_alert_level(int id,int *v){if(bad_gauge)return -EIO;*v=alert;return 0;}
static int platform_fg_ops_get_soa_alert_level(int id,int *v){if(bad_gauge)return -EIO;*v=0;return 0;}
'''
bridge=r'''
int mca_strategy_func_process(unsigned int type,int event,int value){
 if(type==STRATEGY_FUNC_TYPE_JEITA)return mca_nezha_jeita_process_event(&ji,event,value);
 return -ENODEV;
}
'''
notify=r'''
void mca_event_block_notify(unsigned int type,unsigned long event,void *data){
 assert(type==MCA_EVENT_CHARGE_STATUS && event==MCA_EVENT_BATTERY_DTPT);
 notifications++;business_charger_process_dtpt_change(&business,event,data);
}
'''
test=r'''
int main(void){
 struct strategy_fg gauge={0};alert=3;
 strategy_fg_dtpt_monitor_work(&gauge.dtpt_monitor_work.work);assert(ji.dtpt_status==1&&notifications==1);
 bad_gauge=1;alert=0;strategy_fg_dtpt_monitor_work(&gauge.dtpt_monitor_work.work);assert(ji.dtpt_status==1&&notifications==1);
 bad_gauge=0;strategy_fg_dtpt_monitor_work(&gauge.dtpt_monitor_work.work);assert(!ji.dtpt_status&&notifications==2&&schedules==3);
 mca_nezha_jeita_process_event(&ji,MCA_EVENT_PLATE_SHOCK,1);assert(!ji.dtpt_status);
 ji.stopping=true;assert(mca_nezha_jeita_process_event(&ji,MCA_EVENT_BATTERY_DTPT,1)==-ENODEV&&!ji.dtpt_status);
 puts("PASS: actual FG/business/JEITA DTPT route, failed sample preserves protection, unrelated event rejected");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(pre+events+strategy+jeita+bridge+route+notify+fg+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(c),'-o',str(exe)],check=True)
 env=dict(os.environ);env.setdefault('ASAN_OPTIONS','detect_leaks=0');subprocess.run([str(exe)],check=True,env=env)

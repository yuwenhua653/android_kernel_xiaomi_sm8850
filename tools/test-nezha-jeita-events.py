#!/usr/bin/env python3
"""Exercise actual Nezha JEITA source handover; no hardware/voter claims."""
from pathlib import Path
import os,subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'drivers/power/supply/mca/mca_strategy/strategy_charger/mca_buckchg_jeita.c').read_text();a=s.index('static int mca_nezha_jeita_process_event');b=s.index('static int mca_buckchg_jeita_process_event',a)
pre=r'''
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
/* Event values are taken from the production header below. */
#define WRITE_ONCE(x,v) ((x)=(v))
struct proc {int cur_jeita_index,temp_hys_en,max_chg_curr;};
struct mca_buckchg_jeita_dev {bool usb_online,wireless_online;int event_lock,monitor_work,online,dtpt_status;struct proc proc_data,flip_proc_data,base_proc_data;};
static int starts,cancels;
static void mutex_lock(int *p){assert(!*p);*p=1;}
static void mutex_unlock(int *p){assert(*p);*p=0;}
static void cancel_delayed_work_sync(int *w){cancels++;*w=0;}
static void schedule_delayed_work(int *w,int delay){starts++;*w=1;}
'''
events=(Path(__file__).resolve().parents[1]/'drivers/power/supply/mca/include/mca/common/mca_event.h').read_text().replace('#include <linux/notifier.h>','struct notifier_block;')
test=r'''
int main(void){
 struct mca_buckchg_jeita_dev s={0};
 assert(!mca_nezha_jeita_process_event(&s,1,0));assert(s.online && s.monitor_work && starts==1);
 mca_nezha_jeita_process_event(&s,3,0);assert(starts==1 && cancels==1);
 mca_nezha_jeita_process_event(&s,0,0);assert(s.online && s.monitor_work && starts==1 && cancels==1);
 mca_nezha_jeita_process_event(&s,0,0);assert(s.online && cancels==1);
 mca_nezha_jeita_process_event(&s,MCA_EVENT_BATTERY_DTPT,9);assert(s.dtpt_status==9 && s.monitor_work);
 mca_nezha_jeita_process_event(&s,MCA_EVENT_PLATE_SHOCK,5);assert(s.dtpt_status==9);
 mca_nezha_jeita_process_event(&s,2,0);assert(!s.online && !s.monitor_work && cancels==2);
 assert(s.base_proc_data.max_chg_curr==-1 && s.flip_proc_data.max_chg_curr==-1);
 mca_nezha_jeita_process_event(&s,3,0);mca_nezha_jeita_process_event(&s,1,0);
 mca_nezha_jeita_process_event(&s,2,0);assert(s.online && s.monitor_work && starts==2);
 mca_nezha_jeita_process_event(&s,1,0);assert(starts==2);
 mca_nezha_jeita_process_event(&s,0,0);assert(!s.online && cancels==4);
 puts("PASS: actual Nezha JEITA wired/wireless handover, repeated events, final disconnect and shared OSS DTPT event (no OEM ID alias)");
}
'''
with tempfile.TemporaryDirectory(prefix='jeita-event-test-') as d:
 p=Path(d);(p/'test.c').write_text(pre+events+s[a:b]+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),check=True)

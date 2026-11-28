#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual thermal apply/entry/retry functions under host fault injection.
Uses API models, not hardware writes or in-kernel workqueue concurrency.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1];base=root/'drivers/power/supply/mca/mca_strategy/strategy_charger'
s=(base/'mca_charger_thermal.c').read_text();h=(base/'inc/mca_charger_thermal.h').read_text()
def fn(n):
 m=re.search(r'static\s+(?:int|void|ssize_t)\s+'+n+r'\([^;]*?\n\{',s);assert m,n
 p=m.end();d=1
 while d:
  if s[p]=='{':d+=1
  elif s[p]=='}':d-=1
  p+=1
 return s[m.start():p]+'\n'
apply=['mca_charger_thermal_handle_limit','mca_wireless_charger_thermal_handle_limit','mca_charger_thermal_flip_handle_limit','mca_wireless_charger_thermal_flip_handle_limit']
assert all('mca_qcom_smem_is_zero_speed' not in fn(n) for n in apply)
pre=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <sys/types.h>
#define READ_ONCE(x) (x)
#define min(a,b) ((a)<(b)?(a):(b))
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define msecs_to_jiffies(x) (x)
#define FG_IC_MASTER 0
#define MCA_CHARGER_THERMAL_SYSFS_ATTRS_SIZE 8
enum {XM_CHARGER_TYPE_UNKNOW,XM_CHARGER_TYPE_HVDCP3_B,XM_CHARGER_TYPE_HVDCP3P5,XM_CHARGER_TYPE_PPS,XM_CHARGER_TYPE_PD_VERIFY};
enum {STRATEGY_FUNC_TYPE_QUICK_WIRELESS,STRATEGY_FUNC_TYPE_BASIC_WIRELESS,MCA_EVENT_WIRELESS_THERMAL_PHONE_FLAG};
enum {MCA_EVENT_USB_CONNECT,MCA_EVENT_USB_DISCONNECT,MCA_EVENT_WIRELESS_CONNECT,MCA_EVENT_WIRELESS_DISCONNECT,MCA_EVENT_WIRELESS_EPP_MODE,MCA_EVENT_CHARGE_TYPE_CHANGE};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;bool pending;};
struct device {void *data;};
struct thermal_cooling_device {void *devdata;};
struct device_attribute {struct {const char *name;} attr;};
struct mca_sysfs_attr_info {int sysfs_attr_name;};
struct mca_votable {int id;};
''' +h+r'''
static int calls,fail_at,fail_at2,wireless_calls,clears,last_value[21],last_enable[21],missing_wired,missing_wls;
static struct mca_votable voter[21],flip={.id=0};
static int mca_vote(struct mca_votable *v,const char *client,bool en,int value) {
 (void)client;assert(v&&v->id>=0&&v->id<21);calls++;wireless_calls+=v->id>=10;clears+=!en;
 if(calls==fail_at)return -EIO;if(calls==fail_at2)return -ETIMEDOUT;
 last_value[v->id]=value;last_enable[v->id]=en;return 0;
}
static int mca_rerun_election(struct mca_votable *v) {(void)v;calls++;return calls==fail_at?-EIO:calls==fail_at2?-ETIMEDOUT:0;}
static int schedule_delayed_work(struct delayed_work *w,int ms) {(void)ms;w->pending=true;return 1;}
static int mca_strategy_func_process(int type,int event,int val) {(void)type;(void)event;(void)val;return 0;}
static int mca_charger_thermal_init_wired_voter(struct mca_thermal_info *i) {i->wired_ctrl_info.voter_ok=!missing_wired;return missing_wired?-EAGAIN:0;}
static int mca_charger_thermal_init_wireless_voter(struct mca_thermal_info *i) {i->wireless_ctrl_info.voter_ok=!missing_wls;return missing_wls?-EAGAIN:0;}
static int mca_charger_thermal_sic_initial_chg_curr(struct mca_thermal_info *i) {(void)i;return 0;}
static void *dev_get_drvdata(struct device *d) {return d->data;}
static struct mca_sysfs_attr_info mca_charger_thermal_sysfs_field_tbl[1],attribute;
static struct mca_sysfs_attr_info *mca_sysfs_lookup_attr(const char *n,void *table,int count) {(void)n;(void)table;(void)count;return &attribute;}
static int platform_fg_ops_get_batt_cell_info(int role,const char **out) {(void)role;*out="atl";return 0;}
static int kstrtoint(const char *s,int base,int *out) {char *e;errno=0;long v=strtol(s,&e,base);if(errno==ERANGE||v>INT_MAX||v<INT_MIN)return -ERANGE;if(e==s||(*e&&strcmp(e,"\n")))return -EINVAL;*out=v;return 0;}
'''
names=['mca_thermal_record_error','mca_thermal_retry']+apply+['mca_charger_thermal_update_chg_curr','mca_charger_thermal_poweroff_clear_voter','mca_wireless_charger_thermal_poweroff_clear_voter','mca_charger_thermal_init_voter_work','mca_charger_thermal_set_cur_level','mca_charger_thermal_wls_super_sts_callback','mca_charger_thermal_process_event','mca_charger_thermal_sysfs_store']
body=''.join(fn(n) for n in names)
test=r'''
static struct device dev;
static void reset_calls(int fail) {calls=wireless_calls=clears=0;fail_at=fail;fail_at2=0;}
static void setup(struct mca_thermal_info *i) {
 memset(i,0,sizeof(*i));dev.data=i;i->dev=&dev;i->online=i->wls_online=i->support_wireless=1;
 i->wired_ctrl_info.voter_ok=i->wireless_ctrl_info.voter_ok=true;
 i->wired_ctrl_info.max_level=i->wireless_ctrl_info.max_level=2;
 i->wired_ctrl_info.limit_level=i->wireless_ctrl_info.limit_level=1;
 i->wired_ctrl_info.chg_curr=i->wireless_ctrl_info.chg_curr=1000;
 for(int j=0;j<10;j++){voter[j].id=j;voter[j+10].id=j+10;i->wired_voter[j]=&voter[j];i->wireless_voter[j]=&voter[j+10];}
 for(int j=0;j<2;j++){int *w=&i->wired_thermal_data[j].buck_5v_in,*wl=&i->wireless_thermal_data[j].wireless_bpp_in;for(int k=0;k<10;k++){w[k]=500-j*100;wl[k]=600-j*100;}}
 i->flip_voter=i->wls_flip_voter=&flip;i->wired_flip_thermal_data[1]=500;i->wireless_flip_thermal_data[1]=500;
 missing_wired=missing_wls=0;reset_calls(0);
}
static void replay(struct mca_thermal_info *i) {i->init_voter_work.pending=false;mca_charger_thermal_init_voter_work(&i->init_voter_work.work);}
int main(void) {
 struct mca_thermal_info i;setup(&i);
 assert(!mca_charger_thermal_handle_limit(&i,&i.wired_ctrl_info,i.wired_thermal_data,i.wired_voter)&&calls==10&&last_value[0]==500);
 for(int n=1;n<=10;n++) {
  setup(&i);reset_calls(n);assert(mca_charger_thermal_handle_limit(&i,&i.wired_ctrl_info,i.wired_thermal_data,i.wired_voter)==-EIO&&calls==10&&i.init_voter_work.pending);
  reset_calls(0);replay(&i);assert(!i.init_voter_work.pending&&calls==30);
 }
 setup(&i);reset_calls(1);fail_at2=2;assert(mca_charger_thermal_handle_limit(&i,&i.wired_ctrl_info,i.wired_thermal_data,i.wired_voter)==-EIO&&calls==10);
 for(int n=1;n<=20;n++) {
  setup(&i);reset_calls(n);assert(mca_wireless_charger_thermal_handle_limit(&i,&i.wireless_ctrl_info,i.wireless_thermal_data,i.wireless_voter)==-EIO&&calls==20&&i.init_voter_work.pending);
  reset_calls(0);replay(&i);assert(!i.init_voter_work.pending);
 }
 setup(&i);i.wired_ctrl_info.wired_thermal_remove=1;reset_calls(1);
 assert(mca_charger_thermal_handle_limit(&i,&i.wired_ctrl_info,i.wired_thermal_data,i.wired_voter)==-EIO&&!i.wired_thermal_removed);
 reset_calls(0);replay(&i);assert(i.wired_thermal_removed&&!i.init_voter_work.pending);
 setup(&i);i.wireless_ctrl_info.wls_thermal_remove=1;reset_calls(1);
 assert(mca_wireless_charger_thermal_handle_limit(&i,&i.wireless_ctrl_info,i.wireless_thermal_data,i.wireless_voter)==-EIO&&!i.wireless_thermal_removed);
 reset_calls(0);replay(&i);assert(i.wireless_thermal_removed&&!i.init_voter_work.pending);
 setup(&i);missing_wired=1;replay(&i);assert(wireless_calls==10&&i.init_voter_work.pending);
 missing_wired=0;reset_calls(0);replay(&i);assert(calls==30&&!i.init_voter_work.pending);
 setup(&i);i.wired_ctrl_info.limit_level=-1;assert(mca_charger_thermal_handle_limit(&i,&i.wired_ctrl_info,i.wired_thermal_data,i.wired_voter)==-EINVAL&&!calls&&!i.init_voter_work.pending);
 setup(&i);struct thermal_cooling_device c={.devdata=&i};reset_calls(1);
 assert(mca_charger_thermal_set_cur_level(&c,1)==-EIO&&i.init_voter_work.pending);
 reset_calls(0);assert(!mca_charger_thermal_set_cur_level(&c,2));replay(&i);assert(last_value[0]==400&&!i.init_voter_work.pending);
 assert(mca_charger_thermal_set_cur_level(&c,ULONG_MAX)==-EINVAL&&i.wired_ctrl_info.limit_level==2);
 setup(&i);reset_calls(1);assert(mca_charger_thermal_process_event(MCA_EVENT_USB_DISCONNECT,999,&i)==-EIO&&!i.online&&i.wired_clear_pending&&i.init_voter_work.pending);
 reset_calls(0);replay(&i);assert(!i.wired_clear_pending&&!i.init_voter_work.pending&&!last_enable[0]);
 setup(&i);reset_calls(1);assert(mca_charger_thermal_process_event(MCA_EVENT_WIRELESS_DISCONNECT,999,&i)==-EIO&&!i.wls_online&&i.wireless_clear_pending);
 reset_calls(0);assert(!mca_charger_thermal_process_event(MCA_EVENT_WIRELESS_CONNECT,0,&i)&&i.wls_online&&!i.wireless_clear_pending);replay(&i);assert(last_enable[10]&&!i.init_voter_work.pending);
 setup(&i);i.online=0;i.wired_ctrl_info.sic_chg_curr=900;missing_wls=1;replay(&i);assert(i.wired_ctrl_info.sic_chg_curr==900); /* offline lookup cannot erase request */
 setup(&i);struct device_attribute attr={.attr={.name="test"}};
 attribute.sysfs_attr_name=MCA_THERMAL_WIRED_CTRL_LIMIT;
 const char *invalid[]={"-1","3","1junk","2147483648"};
 for(int n=0;n<4;n++){int old=i.wired_ctrl_info.limit_level;assert(mca_charger_thermal_sysfs_store(&dev,&attr,invalid[n],strlen(invalid[n]))<0&&i.wired_ctrl_info.limit_level==old);}
 reset_calls(1);assert(mca_charger_thermal_sysfs_store(&dev,&attr,"2",1)==-EIO&&i.wired_ctrl_info.limit_level==2&&i.init_voter_work.pending);
 reset_calls(0);replay(&i);assert(!i.init_voter_work.pending&&last_value[0]==400);
 attribute.sysfs_attr_name=MCA_THERMAL_WIRED_THERMAL_REMOVE;assert(mca_charger_thermal_sysfs_store(&dev,&attr,"2",1)==-EINVAL&&!i.wired_ctrl_info.wired_thermal_remove);
 attribute.sysfs_attr_name=MCA_THERMAL_WIRELESS_CTRL_LIMIT;i.support_wireless=0;assert(mca_charger_thermal_sysfs_store(&dev,&attr,"1",1)==-EOPNOTSUPP);
 setup(&i);i.wired_ctrl_info.sic_chg_curr=i.wired_ctrl_info.sic_init_fcc=0;mca_charger_thermal_update_chg_curr(&i);assert(!i.wired_ctrl_info.chg_curr);
 setup(&i);reset_calls(1);assert(mca_charger_thermal_wls_super_sts_callback(&i,1)==-EIO&&i.init_voter_work.pending);
 setup(&i);reset_calls(1);assert(mca_charger_thermal_flip_handle_limit(&i,&i.wired_ctrl_info,i.wired_flip_thermal_data,&flip)==-EIO&&i.init_voter_work.pending);
 setup(&i);i.stopping=true;assert(mca_charger_thermal_handle_limit(&i,&i.wired_ctrl_info,i.wired_thermal_data,i.wired_voter)==-ENODEV&&!calls);replay(&i);assert(!calls&&!i.init_voter_work.pending);
 setup(&i);i.wireless_car_column=true;i.wireless_voter[10]=&voter[20];voter[20].id=20;i.wireless_thermal_data[0].wireless_xiaomi_car=440;
 assert(!mca_wireless_charger_thermal_handle_limit(&i,&i.wireless_ctrl_info,i.wireless_thermal_data,i.wireless_voter));
 assert(last_enable[20]&&last_value[20]==440);
 i.wireless_ctrl_info.limit_level=0;i.wireless_ctrl_info.chg_curr=330;reset_calls(0);
 assert(!mca_wireless_charger_thermal_handle_limit(&i,&i.wireless_ctrl_info,i.wireless_thermal_data,i.wireless_voter)&&last_value[20]==330);
 reset_calls(11);assert(mca_charger_thermal_process_event(MCA_EVENT_WIRELESS_DISCONNECT,0,&i)==-EIO&&i.wireless_clear_pending);
 reset_calls(0);replay(&i);assert(!i.wireless_clear_pending&&!last_enable[20]);
 puts("PASS: actual thermal 30 apply failure points, first errors, retry/new requests, release retry, independent suppliers, sysfs/cooling bounds and disconnect cleanup");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-thermal-errors-') as d:
 p=Path(d);(p/'test.c').write_text(pre+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

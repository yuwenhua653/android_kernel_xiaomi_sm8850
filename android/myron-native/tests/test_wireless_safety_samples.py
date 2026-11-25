#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute production wireless alarm and FFC decisions with failed sensors."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', type=Path, required=True)
p.add_argument('--alarm-source', type=Path)
p.add_argument('--ffc-source', type=Path)
p.add_argument('--profile-source', type=Path)
a = p.parse_args()
b = a.kernel_root / 'drivers/power/supply/mca'
s = (b/'mca_strategy/strategy_wireless/mca_basic_wireless.c').read_text()
h = (b/'mca_strategy/strategy_wireless/inc/mca_basic_wireless.h').read_text()
code = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
typedef int64_t s64;
#define div_s64(a,b) ((s64)(a)/(b))
#define mca_log_err(...) do { if(0) printf(__VA_ARGS__); } while(0)
#define mca_log_info(...) do { if(0) printf(__VA_ARGS__); } while(0)
#define WIRELESS_ROLE_MASTER 0
#define WLS_CHIP_VENDOR_SC96281 1
#define STRATEGY_FUNC_TYPE_QUICK_WIRELESS 1
#define STRATEGY_FUNC_TYPE_JEITA 2
#define STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM 1
#define STRATEGY_STATUS_TYPE_JEITA_NORMAL_VTERM 2
#define STRATEGY_STATUS_TYPE_QC_CHARGE_STS 3
#define STRATEGY_STATUS_TYPE_QC_IBAT_MAX 4
#define ADAPTER_AUTH_FAILED 5
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; };
'''
for name in ['MCA_WLS_CHG_RX_MAX_TEMP','MCA_WLS_CHG_RX_MAX_TEMP_SC96281','MCA_WLS_CHG_RX_OTP_DELTA_TEMP',
             'BPP_DEFAULT_VOUT','EPP_DEFAULT_VOUT','EPP_PLUS_VOUT','CHARGE_SW_CV_VBAT_ALARM_DELTA','MCA_WLS_CHG_ENABLE_FASTCHG_CNT']:
    code += re.search(r'^#define '+name+r' .*$',h,re.M)[0]+'\n'
for name in ['XM_WLS_CHGR_STAGE','WLS_FORWARD_CHARGER_MODE','mca_wireless_basic_chg_mode']:
    code += re.search(r'enum '+name+r'\s*\{.*?\};',h,re.S)[0]+'\n'
code += re.search(r'enum mca_quick_chg_status\s*\{.*?\};',(b/'include/mca/strategy/strategy_class.h').read_text(),re.S)[0]
code += r'''
struct strategy_wireless_dev {
 struct delayed_work rx_alarm_work;
 int rx_max_iout[2],rx_temp,project_vendor,charge_limit_voter,input_limit_voter;
 int sw_cv_running,ffc_temp_low,ffc_temp_high;
 struct { int forward_charger_mode,adapter_type;enum XM_WLS_CHGR_STAGE chgr_stage;
  int target_vout,pre_vout,target_iwls,pre_iwls,fc_flag,qc_enable; } proc_data;
 struct { int delta_fv; } smartchg_data;
};
static int iout_ret,temp_ret,rx_iout,rx_temp,retries,otp_calls,otp_en,otp_value,fcc_calls,fcc_value;
static int fail_at,quick_ret,quick_state,ibat_ret,ibat_value,icl_value,fcc_sample;
static int temp_sample,vbat_sample,vout_sample,fast_mode,ffc_calls,ffc_value,icl_calls,vout_calls;
static int platform_class_wireless_get_iout(int r,int *v) { *v=rx_iout;return iout_ret; }
static int platform_class_wireless_get_temp(int r,int *v) { *v=rx_temp;return temp_ret; }
static int platform_class_wireless_get_vout(int r,int *v) { *v=vout_sample;return fail_at==3?-EIO:0; }
static int strategy_class_fg_ops_get_temperature(int *v) { *v=temp_sample;return fail_at==4?-EIO:0; }
static int strategy_class_fg_ops_get_voltage(int *v) { *v=vbat_sample;return fail_at==5?-EIO:0; }
static int strategy_class_fg_get_fastcharge(void) { return fail_at==6?-EIO:fast_mode; }
static void strategy_class_fg_set_fastcharge(bool v) { ffc_calls++;ffc_value=v; }
static void strategy_wireless_get_chgr_stage(struct strategy_wireless_dev *s,enum XM_WLS_CHGR_STAGE *st) { }
static int mca_strategy_func_get_status(int type,int what,int *v) {
 switch(what) {
 case STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM:*v=300;return fail_at==1?-EIO:0;
 case STRATEGY_STATUS_TYPE_JEITA_NORMAL_VTERM:*v=4400;return fail_at==2?-EIO:0;
 case STRATEGY_STATUS_TYPE_QC_CHARGE_STS:*v=quick_state;return quick_ret;
 case STRATEGY_STATUS_TYPE_QC_IBAT_MAX:*v=ibat_value;return ibat_ret;
 default:assert(0);return -EINVAL;
 }
}
static int mca_get_effective_result(int voter) {
 if(voter==1)return fail_at==7?-EIO:icl_value;
 assert(voter==2);return fail_at==8?-EIO:fcc_sample;
}
static void msleep(int ms) { assert(ms==200); }
static void strategy_wireless_set_rx_vout(struct strategy_wireless_dev *s,int v) { vout_calls++; }
static void strategy_wireless_icl_setting(struct strategy_wireless_dev *s,bool en,int v) { assert(en);icl_calls++; }
static void strategy_wireless_otp_fcc_setting(struct strategy_wireless_dev *s,bool en,int value) {
 otp_calls++;otp_en=en;otp_value=value;
}
static void strategy_wireless_fcc_setting(struct strategy_wireless_dev *s,bool en,int value) {
 assert(en);fcc_calls++;fcc_value=value;
}
#define msecs_to_jiffies(v) (v)
static void schedule_delayed_work(struct delayed_work *w,int ms) { assert(ms==4000);retries++; }
'''
alarm = a.alarm_source.read_text() if a.alarm_source else s
for name in ['strategy_wireless_check_rx_alarm','strategy_wireless_rx_alarm_work']:
    code += function(alarm,name)+'\n'
code += function(a.ffc_source.read_text() if a.ffc_source else s,'strategy_wireless_enable_fast_charge_mode')+'\n'
for name in ['strategy_wireless_epp_train_tx_work','strategy_wireless_epp_musical_box_work']:
    code += function(a.profile_source.read_text() if a.profile_source else s,name)+'\n'
code += r'''
static int cases;
static void init(struct strategy_wireless_dev *s) {
 *s=(struct strategy_wireless_dev){.rx_max_iout={1000,1500},.rx_temp=95,
  .project_vendor=WLS_CHIP_VENDOR_SC96281,.input_limit_voter=1,.charge_limit_voter=2,
  .ffc_temp_low=0,.ffc_temp_high=50};
 s->proc_data.forward_charger_mode=FORWARD_2_1_CHARGER_MODE;
 s->proc_data.adapter_type=ADAPTER_AUTH_FAILED+1;
 s->proc_data.chgr_stage=WLS_NORMAL_MODE;
 iout_ret=temp_ret=retries=otp_calls=fcc_calls=fail_at=quick_ret=ibat_ret=ffc_calls=0;
 icl_calls=vout_calls=0;
 s->proc_data.target_vout=s->proc_data.pre_vout=EPP_DEFAULT_VOUT;
 s->proc_data.target_iwls=s->proc_data.pre_iwls=900;
 s->proc_data.fc_flag=1;
 rx_iout=200;rx_temp=70;otp_en=1;otp_value=1200;fcc_value=1600;
 quick_state=MCA_QUICK_CHG_STS_NO_CHARGING;ibat_value=2000;icl_value=1000;fcc_sample=2000;
 temp_sample=250;vbat_sample=4000;vout_sample=11000;fast_mode=0;
}
int main(void) {
 struct strategy_wireless_dev s;
 for(int vendor=0;vendor<2;vendor++)for(int mode=0;mode<2;mode++)
 for(int ierr=0;ierr<2;ierr++)for(int terr=0;terr<2;terr++)
 for(int current=-1;current<3;current++)for(int delta=-11;delta<=1;delta++) {
  init(&s);s.project_vendor=vendor;
  s.proc_data.forward_charger_mode=mode?FORWARD_4_1_CHARGER_MODE:FORWARD_2_1_CHARGER_MODE;
  int threshold=vendor?MCA_WLS_CHG_RX_MAX_TEMP_SC96281:MCA_WLS_CHG_RX_MAX_TEMP;
  rx_iout=current<0?-1:current*1000;rx_temp=threshold+delta;
  iout_ret=ierr?-EIO:0;temp_ret=terr?-EIO:0;
  bool ocp=!ierr && rx_iout>=s.rx_max_iout[mode];
  bool otp=!terr && rx_temp>=threshold;
  bool recover=!ierr && rx_iout>=0 && !terr && rx_temp<=threshold-MCA_WLS_CHG_RX_OTP_DELTA_TEMP;
  strategy_wireless_rx_alarm_work(&s.rx_alarm_work.work);
  if(!ocp && !otp && recover)assert(otp_calls==1 && !otp_en && !retries && !fcc_calls);
  else {
   assert(retries==1 && fcc_calls==ocp && otp_calls==otp);
   if(ocp)assert(fcc_value==1900);
   if(otp)assert(otp_en && otp_value==1500);
   else assert(otp_en && otp_value==1200);
  }
  assert(s.rx_temp==(terr?95:rx_temp));cases++;
 }
 for(int kind=0;kind<4;kind++) {
  init(&s);rx_iout=2000;rx_temp=95;
  if(kind==0)quick_ret=-EIO;
  if(kind==1){quick_state=MCA_QUICK_CHG_STS_CHARGING;ibat_ret=-EIO;}
  if(kind==2)fcc_sample=INT_MIN;
  if(kind==3){quick_state=MCA_QUICK_CHG_STS_CHARGING;ibat_value=INT_MIN;}
  strategy_wireless_rx_alarm_work(&s.rx_alarm_work.work);
  assert(!otp_calls && !fcc_calls && retries==1 && otp_en && otp_value==1200);cases++;
 }
 for(int stage=1;stage<=8;stage++) {
  init(&s);fail_at=stage;
  assert(strategy_wireless_enable_fast_charge_mode(&s)<0);
  assert(!ffc_calls);cases++;
 }
 const int volts[]={0,-1,INT_MIN};
 for(unsigned i=0;i<3;i++) {
  init(&s);vbat_sample=volts[i];
  assert(strategy_wireless_enable_fast_charge_mode(&s)==-ENODATA && !ffc_calls);cases++;
 }
 init(&s);assert(!strategy_wireless_enable_fast_charge_mode(&s));
 assert(ffc_calls==1 && ffc_value==1);cases++;
 init(&s);temp_sample=550;assert(!strategy_wireless_enable_fast_charge_mode(&s));
 assert(!ffc_calls);cases++;
 init(&s);temp_sample=550;fast_mode=1;assert(!strategy_wireless_enable_fast_charge_mode(&s));
 assert(ffc_calls==1 && !ffc_value);cases++;
 init(&s);vbat_sample=4400;icl_value=INT_MAX;fcc_sample=2000;
 assert(!strategy_wireless_enable_fast_charge_mode(&s) && !ffc_calls);cases++;
 init(&s);fail_at=4;assert(strategy_wireless_enable_fast_charge_mode(&s)<0 && !ffc_calls);
 fail_at=0;assert(!strategy_wireless_enable_fast_charge_mode(&s) && ffc_calls==1 && ffc_value);cases++;
 for(int profile=0;profile<2;profile++) {
  init(&s);fail_at=4;s.proc_data.target_vout=EPP_PLUS_VOUT;
  if(profile)strategy_wireless_epp_musical_box_work(&s);else strategy_wireless_epp_train_tx_work(&s);
  assert(!fcc_calls && !icl_calls && !vout_calls && s.proc_data.fc_flag);
  assert(s.proc_data.pre_vout==EPP_DEFAULT_VOUT && s.proc_data.pre_iwls==900);cases++;
 }
 const int voice_fcc[]={6000,2500,2300,2100,1900,1700,1500,1300,1100,1000};
 for(int temp=35;temp<=44;temp++) {
  init(&s);temp_sample=temp*10;strategy_wireless_epp_musical_box_work(&s);
  assert(fcc_calls==1 && fcc_value==voice_fcc[temp-35]);cases++;
  init(&s);temp_sample=temp*10;strategy_wireless_epp_train_tx_work(&s);
  assert(fcc_calls==(temp>=38));
  if(temp>=38)assert(fcc_value==1990 && s.proc_data.target_iwls==(temp<=40?700:500));
  cases++;
 }
 printf("PASS: %d wireless alarm/FFC/profile failure, hysteresis and recovery cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
    c.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-fsanitize=undefined','-fno-sanitize-recover=undefined',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

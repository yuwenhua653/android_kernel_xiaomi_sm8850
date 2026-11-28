#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual SIC rating selection and pending retry with host provider models."""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
b=root/'drivers/power/supply/mca/mca_strategy/strategy_charger'
s=(b/'mca_charger_thermal.c').read_text();h=(b/'inc/mca_charger_thermal.h').read_text()
def fn(n):
 m=re.search(r'static\s+(?:int|void)\s+'+n+r'\([^;]*?\n\{',s);assert m,n
 p=m.end();d=1
 while d:
  d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]+'\n'
pre=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <limits.h>
#define READ_ONCE(x) (x)
#define min(a,b) ((a)<(b)?(a):(b))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define mca_log_info(...) ((void)0)
#define msecs_to_jiffies(x) (x)
#define QC_27W_SIC_INIT_FCC 6000
#define SIC_PWR_MAX_POWER_THR 68
enum {XM_CHARGER_TYPE_UNKNOW,XM_CHARGER_TYPE_PPS,XM_CHARGER_TYPE_PD_VERIFY,XM_CHARGER_TYPE_HVDCP3P5,XM_CHARGER_TYPE_HVDCP3_B,XM_CHARGER_TYPE_HVDCP3};
enum {STRATEGY_FUNC_TYPE_QUICK_CHARGE,STRATEGY_STATUS_TYPE_POWER_MAX,ADAPTER_PROTOCOL_PPS};
struct work_struct {int unused;};struct delayed_work {struct work_struct work;bool pending;};
'''+h+r'''
static int status_ret,status_power,power_ret,queries,pwr_queries,max_queries,apply_ret,wired_applies,wls_applies;
static unsigned int rating;
static int wired_init_ret;
static int schedule_delayed_work(struct delayed_work*w,int ms){(void)ms;w->pending=true;return 1;}
static int mca_strategy_func_get_status(int type,int state,int *v){(void)type;(void)state;*v=status_power;return status_ret;}
static int protocol_class_get_adapter_pwr_max_power(int type,unsigned int*v){(void)type;queries++;pwr_queries++;*v=rating;return power_ret;}
static int protocol_class_get_adapter_max_power(int type,unsigned int*v){(void)type;queries++;max_queries++;*v=rating;return power_ret;}
static int mca_charger_thermal_handle_limit(struct mca_thermal_info*i,struct mca_thermal_ctrl_info*c,struct mca_thermal_data*d,struct mca_votable**v){(void)i;(void)c;(void)d;(void)v;wired_applies++;return apply_ret;}
static int mca_wireless_charger_thermal_handle_limit(struct mca_thermal_info*i,struct mca_thermal_ctrl_info*c,struct mca_wireless_thermal_data*d,struct mca_votable**v){(void)i;(void)c;(void)d;(void)v;wls_applies++;return 0;}
static int mca_charger_thermal_init_wired_voter(struct mca_thermal_info*i){(void)i;return wired_init_ret;}
static int mca_charger_thermal_init_wireless_voter(struct mca_thermal_info*i){(void)i;return 0;}
static int mca_charger_thermal_poweroff_clear_voter(struct mca_thermal_info*i){(void)i;return 0;}
static int mca_wireless_charger_thermal_poweroff_clear_voter(struct mca_thermal_info*i){(void)i;return 0;}
static int mca_charger_thermal_flip_handle_limit(struct mca_thermal_info*i,struct mca_thermal_ctrl_info*c,int*d,struct mca_votable*v){(void)i;(void)c;(void)d;(void)v;return 0;}
static int mca_wireless_charger_thermal_flip_handle_limit(struct mca_thermal_info*i,struct mca_thermal_ctrl_info*c,int*d,struct mca_votable*v){(void)i;(void)c;(void)d;(void)v;return 0;}
'''
body=''.join(fn(n) for n in ['mca_thermal_record_error','mca_thermal_retry','mca_charger_thermal_update_chg_curr','mca_charger_thermal_sic_initial_chg_curr','mca_charger_thermal_init_voter_work'])
test=r'''
static void reset(struct mca_thermal_info*i){memset(i,0,sizeof(*i));i->online=i->wls_online=i->support_wireless=1;i->real_type=XM_CHARGER_TYPE_PPS;i->wired_ctrl_info.sic_init_fcc=6000;i->wired_ctrl_info.chg_curr=6000;status_ret=power_ret=queries=pwr_queries=max_queries=apply_ret=wired_applies=wls_applies=0;status_power=67;rating=67;wired_init_ret=0;}
int main(void){struct mca_thermal_info i;
 for(int fail=0;fail<2;fail++){reset(&i);if(fail)power_ret=-ETIMEDOUT;else status_ret=-ENODEV;
  assert(mca_charger_thermal_sic_initial_chg_curr(&i)==(fail?-ETIMEDOUT:-ENODEV));
  assert(i.wired_ctrl_info.sic_init_fcc==6000&&i.wired_ctrl_info.chg_curr==6000&&i.sic_power_pending&&i.init_voter_work.pending&&!wired_applies);
  assert(queries==fail);status_ret=power_ret=0;i.init_voter_work.pending=false;
  mca_charger_thermal_init_voter_work(&i.init_voter_work.work);
  assert(!i.sic_power_pending&&i.wired_ctrl_info.sic_init_fcc==12400&&wls_applies==1&&!i.init_voter_work.pending);
 }
 int ratings[]={1,33,34,67,68,90,91,120};int caps[]={6600,6600,12400,12400,15600,15600,22000,22000};
 for(int j=0;j<8;j++){reset(&i);rating=ratings[j];status_power=68;assert(!mca_charger_thermal_sic_initial_chg_curr(&i)&&i.wired_ctrl_info.sic_init_fcc==caps[j]&&max_queries==1&&!pwr_queries);}
 reset(&i);rating=0;assert(mca_charger_thermal_sic_initial_chg_curr(&i)==-EAGAIN&&i.wired_ctrl_info.sic_init_fcc==6000&&i.init_voter_work.pending);
 reset(&i);rating=UINT_MAX;assert(mca_charger_thermal_sic_initial_chg_curr(&i)==-ERANGE&&i.wired_ctrl_info.sic_init_fcc==6000&&!wired_applies&&!i.init_voter_work.pending);
 reset(&i);rating=UINT_MAX;wired_init_ret=-ENODEV;i.sic_power_pending=true;mca_charger_thermal_init_voter_work(&i.init_voter_work.work);assert(i.init_voter_work.pending&&wls_applies==1);
 reset(&i);status_power=-1;assert(mca_charger_thermal_sic_initial_chg_curr(&i)==-EINVAL&&!queries);
 reset(&i);power_ret=-EIO;i.sic_power_pending=true;mca_charger_thermal_init_voter_work(&i.init_voter_work.work);assert(wls_applies==1&&i.init_voter_work.pending&&i.wired_ctrl_info.chg_curr==6000);
 reset(&i);i.wired_ctrl_info.sic_chg_curr=4000;assert(!mca_charger_thermal_sic_initial_chg_curr(&i)&&i.wired_ctrl_info.chg_curr==4000);
 i.real_type=XM_CHARGER_TYPE_UNKNOW;assert(!mca_charger_thermal_sic_initial_chg_curr(&i)&&!i.wired_ctrl_info.sic_init_fcc&&i.wired_ctrl_info.chg_curr==4000&&!i.sic_power_pending);
 reset(&i);i.sic_power_pending=true;i.real_type=XM_CHARGER_TYPE_HVDCP3;assert(!mca_charger_thermal_sic_initial_chg_curr(&i)&&!i.sic_power_pending&&i.wired_ctrl_info.sic_init_fcc==6000&&!queries);
 reset(&i);i.online=0;i.sic_power_pending=true;mca_charger_thermal_init_voter_work(&i.init_voter_work.work);assert(!queries);
 reset(&i);i.stopping=true;i.sic_power_pending=true;mca_charger_thermal_init_voter_work(&i.init_voter_work.work);assert(!queries&&!wired_applies&&!wls_applies);
 puts("PASS: actual SIC query errors, retained limits, both rating APIs, all rating boundaries, retry, source changes and independent wireless replay");}
'''
with tempfile.TemporaryDirectory(prefix='mca-sic-power-') as d:
 p=Path(d);(p/'test.c').write_text(pre+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

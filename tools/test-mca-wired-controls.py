#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual wired controls with the production data layout and faulting I/O.
Host ASan/UBSan coverage; not an electrical or Linux workqueue qualification.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
base=root/'drivers/power/supply/mca/mca_strategy/strategy_charger'
s=(base/'mca_strategy_quickchg.c').read_text()
h=(base/'inc/mca_quick_charger.h').read_text()
def fn(name,source=s):
 m=re.search(r'static\s+(?:int|void|bool|ssize_t)\s+'+name+r'\([^;]*?\n\{',source);assert m,name
 end=m.end();depth=1
 while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[m.start():end]+'\n'
header=h[h.index('/* default value*/'):h.rindex('#endif')]
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
#include <ctype.h>
#include <pthread.h>
#include <unistd.h>
typedef int64_t s64;typedef uint64_t u64;typedef int64_t ktime_t;
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_RELAXED)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELAXED)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define DIV_ROUND_UP_ULL(a,b) (((a)+(b)-1)/(b))
#define BIT(x) (1U<<(x))
#define min(a,b) ((a)<(b)?(a):(b))
#define max(a,b) ((a)>(b)?(a):(b))
#define min_t(t,a,b) min((t)(a),(t)(b))
#define max_t(t,a,b) max((t)(a),(t)(b))
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define msecs_to_jiffies(x) (x)
#define MAIN_BUCK_CHARGER 0
#define FG_IC_MASTER 0
#define FG_IC_SLAVE 1
#define FG_IC_MAX 3
#define FG_SITE_MAX 2
#define CP_ROLE_MASTER 0
#define CP_ROLE_SLAVE 1
#define CP_ROLE_MAX 2
#define ADAPTER_CAP_MAX_NR 10
#define TYPEC_PORT_0 0
#define STRATEGY_FUNC_TYPE_JEITA 1
#define STRATEGY_STATUS_TYPE_JEITA_FFC_VTERM 1
#define MCA_QUICK_CHG_STS_NO_CHARGING 0
#define MCA_QUICK_CHG_STS_CHARGING 1
#define MCA_QUICK_CHG_STS_CHARGE_DONE 2
#define XM_CHARGER_TYPE_PD_VERIFY 4
#define XM_CHARGER_TYPE_PPS 3
struct adapter_power_cap {int min_voltage,max_voltage,max_current;};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;bool pending;};
struct mutex {pthread_mutex_t raw;};
struct notifier_block {int unused;};
struct mca_charge_if_ops {void *data;};
struct mca_votable {int id;};
static void mutex_lock(struct mutex*m){assert(!pthread_mutex_lock(&m->raw));}
static void mutex_unlock(struct mutex*m){assert(!pthread_mutex_unlock(&m->raw));}
static int mutex_trylock(struct mutex*m){return !pthread_mutex_trylock(&m->raw);}
static int kstrtoint(const char*s,unsigned base,int*out){char*end;errno=0;long n=strtol(s,&end,base);if(errno||end==s||n<INT_MIN||n>INT_MAX)return -EINVAL;while(isspace(*end))end++;if(*end)return -EINVAL;*out=n;return 0;}
'''
# The constants are taken from production rather than duplicated.
constants='\n'.join(re.findall(r'^#define (?:SINGLE_CP_|PMIC_SINGLE_CP_|MCA_QUICK_CHG_CP_DEFAULT_FSW)[^\n]*',s,re.M))+'\n'
stubs=r'''
enum {ADC=1,MODE,BATTERY,SUSPEND,ICL,FCC,ZERO,RELEASE,RESUME,REQUEST,SLEEP,TUNE,ENABLE,ENABLED,IBUS,VBUS,UCP,FSW,FAST,GAUGE,JEITA,PACK,VTERM,AICL,READ_FSW,WRITE_FSW,STOP};
static int calls,fail_at,fail_kind,trace[4096],counts[64],vote_error;
static bool enabled=true,suspended=true,zero=true,fsw_stuck;static int fsw_step;
static int ibus=2000,vbus=9000,vbat=4000,fast=1,pack=4300,jeita=4400,fsw[2]={500,500},applied_icl,applied_fcc,applied_vterm;
static int tick(int kind){assert(calls<4096);trace[calls++]=kind;counts[kind]++;return (calls==fail_at||kind==fail_kind)?-EIO:0;}
static int platform_class_cp_enable_adc(int r,bool on){(void)r;(void)on;return tick(ADC);}
static int platform_class_cp_set_mode(int r,int mode){(void)r;(void)mode;return tick(MODE);}
static int platform_class_cp_get_battery_voltage(int r,int*out){(void)r;int ret=tick(BATTERY);if(!ret)*out=vbat;return ret;}
static int platform_class_cp_get_bus_current(int r,int*out){(void)r;int ret=tick(IBUS);if(!ret)*out=ibus;return ret;}
static int platform_class_cp_get_bus_voltage(int r,int*out){(void)r;int ret=tick(VBUS);if(!ret)*out=vbus;return ret;}
static int platform_class_cp_get_charging_enabled(int r,bool*out){(void)r;int ret=tick(ENABLED);if(!ret)*out=enabled;return ret;}
static int platform_class_cp_set_charging_enable(int r,bool on){(void)r;(void)on;return tick(ENABLE);}
static int platform_class_cp_enable_busucp(int r,bool en){(void)r;(void)en;return tick(UCP);}
static int platform_class_cp_set_default_fsw(int r){(void)r;return tick(FSW);}
static int platform_class_cp_set_fsw(int r,int val){int ret=tick(WRITE_FSW);if(!ret&&!fsw_stuck)fsw[r]=val;return ret;}
static int platform_class_cp_get_fsw_step(int r,int*out){(void)r;int ret=tick(READ_FSW);if(!ret)*out=fsw_step;return ret;}
static int platform_class_cp_get_fsw(int r,int*out){int ret=tick(READ_FSW);if(!ret)*out=fsw[r];return ret;}
static int mca_quick_charge_req_adp_volt_and_cur(struct mca_quick_charge_info*i){assert(!i->pd_switch_to_pmic);return tick(REQUEST);}
static int mca_quick_charge_msleep(int ms,struct mca_quick_charge_info*i){(void)ms;(void)i;return tick(SLEEP);}
static int mca_quick_charge_tune_vbus(struct mca_quick_charge_info*i,int*out){(void)i;int ret=tick(TUNE);if(!ret)*out=XM_VBUS_TUNE_OK;return ret;}
static int64_t ktime_get_boottime_seconds(void){return 123;}
static int strategy_class_fg_get_fastcharge(void){int ret=tick(FAST);return ret?ret:fast;}
static int strategy_class_fg_ops_get_voltage(int*out){int ret=tick(GAUGE);if(!ret)*out=vbat;return ret;}
static int mca_strategy_func_get_status(int t,int cmd,int*out){assert(t==STRATEGY_FUNC_TYPE_JEITA);(void)cmd;int ret=tick(JEITA);if(!ret)*out=jeita;return ret;}
static int platform_class_buckchg_ops_get_pack_vbat(int r,int*out){assert(!r);int ret=tick(PACK);if(!ret)*out=pack;return ret;}
static int platform_class_buckchg_ops_set_restart_aicl(int r,bool on){assert(!r&&on&&!suspended);return tick(AICL);}
static int mca_vote(struct mca_votable*v,const char*client,bool en,int val){
 int kind=v->id==0?(en?SUSPEND:RESUME):v->id==1?ICL:v->id==2?(!strcmp(client,"wire_qc")?(en?ZERO:RELEASE):FCC):VTERM;
 int ret=tick(kind);if(ret)return ret;if(vote_error)return vote_error;
 if(kind==SUSPEND)suspended=true;
 if(kind==ZERO)zero=true;
 if(kind==RELEASE)zero=false;
 if(kind==RESUME){assert(!zero);suspended=false;}
 if(kind==ICL)applied_icl=en?min(val,700):0;
 if(kind==FCC)applied_fcc=en?min(val,1200):0;
 if(kind==VTERM)applied_vterm=en?min(val,4350):0;
 return 0;
}
static int mca_quick_charge_force_stop_charging(struct mca_quick_charge_info*i){int ret=tick(STOP);if(!ret)i->proc_data.charge_flag=0;return ret;}
static void msleep(int ms){(void)ms;}
static void usleep_range(int a,int b){(void)a;(void)b;}
'''
names=['mca_quick_charge_record_error','mca_quick_charge_blocked','mca_quick_charge_busucp','mca_quick_charge_open_path','strategy_quickchg_adjust_vterm','strategy_quickchg_single_cp_cleanup','strategy_quickchg_pmic_single_cp_charging','strategy_quickchg_map_ibus_to_fsw','strategy_quickchg_update_cp_fsw','mca_quick_charge_set_chg_enable','mca_quick_charge_set_cp_path_enable']
body=''.join(fn(n) for n in names)
body+='static int mca_qc_quick_charge_open_path(struct mca_quick_charge_info*i){return mca_quick_charge_open_path(i);}\n'+fn('mca_quick_charge_open_selected')
start_stubs=r'''
static bool temp_selected;
static int mca_quick_charge_judge_soc(struct mca_quick_charge_info*i){(void)i;return tick(FAST);}
static int mca_quick_charge_judge_vbat(struct mca_quick_charge_info*i){(void)i;return tick(GAUGE);}
static int mca_quick_charge_judge_temp(struct mca_quick_charge_info*i){(void)i;int r=tick(JEITA);if(!r)temp_selected=true;return r;}
static int mca_quick_charge_select_stage(struct mca_quick_charge_info*i){(void)i;assert(temp_selected);return tick(PACK);}
static void mca_cp_check_initial_mode(struct mca_quick_charge_info*i){i->cur_cp_work_mode=1;}
static int mca_quick_charge_judge_thermal_vote(struct mca_quick_charge_info*i,bool init){assert(init&&i->cur_cp_work_mode==1);return tick(TUNE);}
static int mca_quick_charge_select_cp(struct mca_quick_charge_info*i){assert(i->cur_cp_work_mode==1);return tick(MODE);}
static int strategy_class_fg_set_fastcharge(bool en){(void)en;return tick(FAST);}
static int mca_quick_charge_stop_charging(struct mca_quick_charge_info*i){i->proc_data.charge_flag=0;return tick(STOP);}
static int schedule_delayed_work(struct delayed_work*w,int delay){(void)delay;w->pending=true;return 1;}
'''
body+=start_stubs+fn('mca_quick_charge_start_charging')
test=r'''
static struct mca_votable voters[4]={{0},{1},{2},{3}};
static void setup(struct mca_quick_charge_info*i){memset(i,0,sizeof(*i));calls=fail_at=fail_kind=vote_error=0;memset(counts,0,sizeof(counts));enabled=true;suspended=zero=true;ibus=2000;vbus=9000;vbat=4000;fast=1;pack=4300;jeita=4400;fsw[0]=fsw[1]=500;fsw_stuck=false;fsw_step=0;applied_icl=applied_fcc=applied_vterm=0;i->online=i->ready=i->sysfs_data.chg_enable=true;i->cp_type=MCA_CP_TYPE_PARALLEL;i->proc_data.ratio=2;i->proc_data.open_path=300;i->proc_data.max_adp_volt=21000;i->proc_data.delta_volt=300;i->proc_data.ibus=2000;i->input_suspend_voter=&voters[0];i->buck_input_voter=&voters[1];i->buck_charge_curr_voter=&voters[2];i->term_volt_voter=&voters[3];i->vbat_threshold=4400;for(int j=0;j<PMIC_SINGLE_CP_FCC_NR;j++)i->pmih_fcc_value[j]=2000;i->support_mode=i->cur_support_mode=7;}
int main(void){struct mca_quick_charge_info i;
 setup(&i);assert(!mca_quick_charge_open_selected(&i));int total=calls;assert(counts[ENABLE]==1&&counts[UCP]>=3);
 for(int j=1;j<=total;j++){setup(&i);fail_at=j;assert(mca_quick_charge_open_selected(&i)==-EIO);}
 setup(&i);enabled=false;i.proc_data.max_adp_volt=INT_MAX;assert(mca_quick_charge_open_path(&i)==-ETIMEDOUT&&counts[ENABLE]==MCA_QUICK_CHG_OPEN_PATH_COUNT);
 setup(&i);i.abort_requested=true;assert(mca_quick_charge_open_selected(&i)==-ECANCELED&&!calls);
 setup(&i);vbat=0;assert(mca_quick_charge_open_path(&i)==-ERANGE&&!counts[REQUEST]);
 setup(&i);i.proc_data.cur_work_cp=2;assert(mca_quick_charge_open_path(&i)==-EINVAL&&!calls);
 setup(&i);assert(!strategy_quickchg_pmic_single_cp_charging(&i,10000));total=calls;assert(!suspended&&!zero&&applied_icl==700&&applied_fcc==1200&&applied_vterm==4350&&i.last_pmih_fcc==2000);
 for(int j=1;j<=total;j++){setup(&i);fail_at=j;assert(strategy_quickchg_pmic_single_cp_charging(&i,10000)==-EIO&&i.last_pmih_fcc==0);if(counts[ICL])assert(suspended&&zero);}
 setup(&i);fail_kind=VTERM;i.ffc_final_vterm=4200;i.last_override_vterm=4100;assert(strategy_quickchg_adjust_vterm(&i)==-EIO&&i.ffc_final_vterm==4200&&i.last_override_vterm==4100);
 setup(&i);i.vterm_adjust_count=10;i.pmic_fv_compensation=100;pack=4500;assert(!strategy_quickchg_adjust_vterm(&i)&&i.last_override_vterm<=4400);
 setup(&i);vbat=4500;assert(!strategy_quickchg_pmic_single_cp_charging(&i,10000)&&i.single_cp_buck_disabled&&suspended&&zero&&!counts[RESUME]);
 setup(&i);fsw_step=100;assert(!strategy_quickchg_update_cp_fsw(&i,800)&&fsw[0]==800);
 setup(&i);i.proc_data.cur_work_cp=2;fsw_step=100;assert(!strategy_quickchg_update_cp_fsw(&i,800)&&fsw[0]==800&&fsw[1]==800);total=calls;
 for(int j=1;j<=total;j++){setup(&i);i.proc_data.cur_work_cp=2;fsw_step=100;fail_at=j;assert(strategy_quickchg_update_cp_fsw(&i,800)==-EIO);}
 setup(&i);assert(strategy_quickchg_update_cp_fsw(&i,800)==-ERANGE&&!counts[WRITE_FSW]);
 setup(&i);fsw_step=100;fsw_stuck=true;assert(strategy_quickchg_update_cp_fsw(&i,800)==-EIO);
 setup(&i);int target; i.proc_data.ibus_queue.avg=INT_MAX;i.proc_data.ratio=4;assert(strategy_quickchg_map_ibus_to_fsw(&i,&target)==-ERANGE);
 setup(&i);i.proc_data.charge_flag=1;i.proc_data.work_mode=4;fail_kind=STOP;assert(mca_quick_charge_set_chg_enable("div4 0",&i)==-EIO&&i.cur_support_mode==7);fail_kind=0;assert(!mca_quick_charge_set_chg_enable("div4 0",&i)&&i.cur_support_mode==3);
 const char*bad[]={"div4 2","div4 -1","div4 999999999999999999999999","toolongnameabcdefghijklmnopqrstuvwxyz 1","div4 1 extra","div4","garbage 1"};
 for(unsigned j=0;j<ARRAY_SIZE(bad);j++){setup(&i);assert(mca_quick_charge_set_chg_enable(bad[j],&i)==-EINVAL&&!calls&&i.cur_support_mode==7);}
 setup(&i);assert(mca_quick_charge_set_cp_path_enable("div4_master 1 div2_bad 0",&i)==-EINVAL&&!i.sysfs_data.cp_path_enable[2][0]);
 assert(!mca_quick_charge_set_cp_path_enable("div4_master 1\tdiv2_slave 0\n",&i)&&i.sysfs_data.cp_path_enable[2][0]);
 i.cp_type=0;assert(mca_quick_charge_set_cp_path_enable("div4_slave 1",&i)==-EOPNOTSUPP);
 setup(&i);temp_selected=false;i.proc_data.adp_type=XM_CHARGER_TYPE_PPS;i.proc_data.max_power=65;i.proc_data.adp_mode=7;mca_quick_charge_start_charging(&i);assert(i.proc_data.charge_flag==1&&i.monitor_work.pending);total=calls;
 for(int j=1;j<=total;j++){setup(&i);temp_selected=false;i.proc_data.adp_type=XM_CHARGER_TYPE_PPS;i.proc_data.max_power=65;i.proc_data.adp_mode=7;fail_at=j;mca_quick_charge_start_charging(&i);assert(!i.proc_data.charge_flag&&!i.monitor_work.pending);if(counts[ADC])assert(counts[STOP]);}
 puts("PASS: production-layout PPS start fault injection, timeout/abort, UCP restoration, PMIC/VTERM MIN caps and rollback, VFC writes/readback/bounds, transactional mode/path parsing");
}
'''
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='mca-wired-controls-') as d:
  p=Path(d);(p/'test.c').write_text(pre+header+constants+stubs+body+test)
  subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

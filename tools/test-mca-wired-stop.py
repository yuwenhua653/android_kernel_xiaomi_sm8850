#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual wired stop/request/voter functions under host hardware fault injection.
The model checks ordering/error behavior, not electrical safety or kernel races.
"""
from pathlib import Path
import re,os,subprocess,tempfile
root=Path(__file__).resolve().parents[1];b=root/'drivers/power/supply/mca/mca_strategy/strategy_charger'
s=(b/'mca_strategy_quickchg.c').read_text();h=(b/'inc/mca_quick_charger.h').read_text()
def fn(n):
 m=re.search(r'static\s+(?:int|void|bool)\s+'+n+r'\([^;]*?\n\{',s);assert m,n
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]+'\n'
consts=['MCA_QUICK_CHG_ADP_DEFAULT_VOLT','MCA_QUICK_CHG_VBUS_OK_HIGH_TH','MCA_QUICK_QC_CHG_ADP_DEFAULT_VOLT','MCA_QUICK_PD_FIXED_CHG_ADP_DEFAULT_VOLT','MCA_QUICK_CHG_ADP_DEFAULT_CURR','MCA_QUICK_CHG_BASE_CLOSE_VTERM_OFFSET']
macros=''.join(re.search(r'^#define '+n+r' .+$',h,re.M)[0]+'\n' for n in consts)
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
#define READ_ONCE(x) (x)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define min(a,b) ((a)<(b)?(a):(b))
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define msecs_to_jiffies(x) (x)
#define PDO_9V_VOLATGE 9000
#define CP_ROLE_MASTER 0
#define CP_ROLE_SLAVE 1
#define MAIN_BUCK_CHARGER 0
#define TYPEC_PORT_0 0
#define ADAPTER_PROTOCOL_PD 0
#define CP_MODE_FORWARD_2_1 0
#define MCA_CP_TYPE_PARALLEL 1
#define MCA_QUICK_CHG_STS_CHARGING 1
#define MCA_QUICK_CHG_STS_NO_CHARGING 0
#define MCA_QUICK_CHG_STS_CHARGE_DONE 2
enum {XM_CHARGER_TYPE_UNKNOW,XM_CHARGER_TYPE_PD,XM_CHARGER_TYPE_PPS,XM_CHARGER_TYPE_PD_VERIFY,XM_CHARGER_TYPE_HVDCP3_B,XM_CHARGER_TYPE_HVDCP3P5};
struct adapter_power_cap_info {int nums;struct {int max_voltage,min_voltage;} cap[7];};
struct delayed_work {bool pending;};struct mca_votable {int id;};
struct process {int adp_type,cur_adp_cur,max_adp_curr,cur_adp_volt,min_adp_volt,max_adp_volt,cur_protocol,dual_cp_count,charge_flag,type_chg,sw_ocp_curr,total_err,error_num[2],cur_work_cp;bool cp_iic_ok,stop_charging,ffc_flag;int cur_stage[2],secure_info;struct {int data[4],index,count,sum,avg;} ibus_queue;};
struct mca_quick_charge_info {bool ready,stopping,stop_pending,online,pd_switch_to_pmic,trigger_antr_burn,pmic_chg_need_fixed_volt,en_buck_parallel_chg,pmic_single_cp_chg,support_base_flip,master_batt_close,check_vbat_ov;int batt_type;int force_normal_volt_para,parall_force_normal_volt_para[2],batt_auth,init_volt_para,parall_init_volt_para,is_platform_qc,fake_pps_ptf,is_eu_model,data_lock,dtpt_status,pps_ptf;int mult_to_single_cnt,cp_type,ffc_final_vterm,last_override_vterm,base_close_curr,force_stop;struct {int chg_enable;} sysfs_data;struct process proc_data;struct delayed_work vfc_work,monitor_work,pps_ptf_work;struct mca_votable *input_suspend_voter,*buck_charge_curr_voter,*term_volt_voter,*flip_charge_curr_voter,*chg_disable_voter,*chg_en_voter;};
enum {OFF0=1,OFF1,FG,FSW0,FSW1,REQUEST,READBACK,MODE0,MODE1,VOTE0,VOTE1,ADC0,ADC1,OVERRIDE,RERUN,TERM,ADC_ON};
static int trace[256],count,fail_op,fail_op2,error1,error2,readback,request_volt,request_cur,request_kind,request_count,read_count,cap_ret,cap_num,parallel_calls;
static bool pdo9;
static int op(int id){assert(count<256);trace[count++]=id;return id==fail_op?error1:id==fail_op2?error2:0;}
static int platform_class_cp_set_charging_enable(int role,bool en){assert(!en);return op(role?OFF1:OFF0);}
static int strategy_class_fg_set_fastcharge(bool en){assert(!en);return op(FG);}
static int platform_class_cp_set_default_fsw(int role){return op(role?FSW1:FSW0);}
static int platform_class_cp_set_mode(int role,int mode){(void)mode;return op(role?MODE1:MODE0);}
static int platform_class_cp_enable_adc(int role,bool en){if(en){assert(!role);return op(ADC_ON);}return op(role?ADC1:ADC0);}
static int platform_class_cp_get_bus_voltage(int role,int*v){assert(!role);read_count++;*v=readback;return op(READBACK);}
static int protocol_class_get_adapter_power_cap(int protocol,struct adapter_power_cap_info*c){(void)protocol;memset(c,0,sizeof(*c));c->nums=cap_num;if(pdo9)c->cap[0].min_voltage=c->cap[0].max_voltage=9000;return cap_ret;}
static int protocol_class_pd_set_fixed_volt(int port,int v){assert(!port);request_kind=1;request_volt=v;request_count++;return op(REQUEST);}
static int protocol_class_set_adapter_volt_and_curr(int protocol,int v,int c){(void)protocol;request_kind=2;request_volt=v;request_cur=c;request_count++;return op(REQUEST);}
static int protocol_class_qc_set_volt(int port,int v){assert(!port);request_kind=3;request_volt=v;request_count++;return op(REQUEST);}
static void cancel_delayed_work_sync(struct delayed_work*w){w->pending=false;}
static int schedule_delayed_work(struct delayed_work*w,int delay){(void)delay;w->pending=true;return 1;}
static void msleep(int ms){assert(ms==300);}
static int mca_vote(struct mca_votable*v,const char*c,bool en,int val){assert(v);(void)c;(void)en;(void)val;return op(v->id?VOTE1:VOTE0);}
static int mca_vote_override(struct mca_votable*v,const char*c,bool en,int val){(void)v;(void)c;(void)en;(void)val;return op(OVERRIDE);}
static int mca_rerun_election(struct mca_votable*v){assert(v);return op(RERUN);}
static int mca_get_client_vote(struct mca_votable*v,const char*c){(void)v;(void)c;return 4400;}
static int platform_class_buckchg_ops_set_term_volt(int r,int v){(void)r;(void)v;return op(TERM);}
static void strategy_quickchg_enable_buck_charging(struct mca_quick_charge_info*i,int a,int b,bool en){(void)i;(void)a;(void)b;(void)en;parallel_calls++;}
static void mca_eu_pps_anti_disconnection_strategy(struct mca_quick_charge_info*i){(void)i;}
'''
names=['mca_quick_charge_is_charge_abnormal','mca_qc_quick_charge_is_charge_abnormal','stategy_quickchg_is_pdo_9v','mca_quick_charge_req_adp_volt_and_cur','mca_quick_charge_record_error','mca_quick_charge_stop_charging','mca_quick_charge_force_stop_charging','mca_quick_charge_exit_charging','mca_quick_charge_chg_disable_voter_cb','mca_quick_charge_chg_en_voter_cb']
events=fn('mca_quick_charge_process_event')
event_names=sorted(set(re.findall(r'\bMCA_EVENT_\w+',events)))
pre+='enum {'+','.join(event_names)+'};\n'
pre+=r'''
#define FG_IC_MASTER 0
#define FG_IC_SLAVE 1
#define ADAPTER_PROTOCOL_PPS 1
#define ADAPTER_PROTOCOL_QC 3
#define MCA_QUICK_CHG_BASE_CLOSE_CURR_NUM 1
#define MCA_QUICK_CHG_BASE_CLOSE_CURR_DEN 1
#define MCA_QUICK_CHG_PPS_PTF_INTERVAL 1000
#define USBPD_QUICK_DPM_PORT_PPS_PTF_NOT_OVERTEMP 1
#define OCP_THRESHOLD_MAINT 10000
#define OCP_THRESHOLD_FLIP 10000
static void mutex_lock(int*p){(void)p;}
static void mutex_unlock(int*p){(void)p;}
static int mca_quick_charge_can_tbat_do_charge(int role,struct mca_quick_charge_info*i,bool init){(void)role;(void)i;(void)init;return 0;}
static int mca_quick_charge_parallel_judge_temp(struct mca_quick_charge_info*i){(void)i;return 0;}
static void update_batt_para(struct mca_quick_charge_info*i){(void)i;}
static void mca_quick_charge_pre_charge_check(struct mca_quick_charge_info*i){(void)i;}
static void mca_quick_charge_reset_charge_para(struct mca_quick_charge_info*i){(void)i;}
'''
pre+=r'''
#define MCA_QUICK_CHG_CP_DUAL 2
#define MCA_QUICK_CHG_CP_MASTER 0
#define MCA_QUICK_CHG_CP_SLAVE 1
#define MCA_BATTERY_TYPE_SINGLE_NUM_MAX 1
static int cp_read_error[2],fg_read_error[2],fg_reads;
static bool cp_enabled[2],fg_fault[2];
static int platform_class_cp_get_charging_enabled(int r,bool*v){assert(r>=0&&r<2);*v=cp_enabled[r];return cp_read_error[r];}
static int platform_fg_ops_get_error_state(int r,bool*v){assert(r>=0&&r<2);fg_reads++;*v=fg_fault[r];return fg_read_error[r];}
static void platform_class_cp_dump_register(int r){(void)r;}
'''
body=''.join(fn(n) for n in names)+events
# These actual entry functions must service pending stop before normal charging.
monitor=fn('mca_quick_charge_monitor_work');precheck=fn('mca_quick_charge_pre_charge_check')
assert monitor.index('if (info->stop_pending)')<monitor.index('strategy_class_fg_is_chip_ok')
assert precheck.index('if (info->stop_pending)')<precheck.index('MCA_QUICK_CHG_STS_CHARGING')
test=r'''
static struct mca_votable v[3]={{0},{1},{2}};
static bool seen(int id){for(int j=0;j<count;j++)if(trace[j]==id)return true;return false;}
static void reset_trace(void){count=request_count=read_count=fail_op=fail_op2=parallel_calls=0;error1=-EIO;error2=-ENODEV;readback=9000;cap_num=1;cap_ret=0;pdo9=true;}
static void setup(struct mca_quick_charge_info*i){memset(i,0,sizeof(*i));reset_trace();i->ready=i->online=true;i->cp_type=MCA_CP_TYPE_PARALLEL;i->proc_data.adp_type=XM_CHARGER_TYPE_PPS;i->proc_data.cur_adp_volt=16000;i->proc_data.min_adp_volt=11000;i->proc_data.max_adp_volt=21000;i->proc_data.cur_adp_cur=2000;i->proc_data.max_adp_curr=3000;i->proc_data.ffc_flag=true;i->proc_data.charge_flag=MCA_QUICK_CHG_STS_CHARGING;i->input_suspend_voter=&v[0];i->buck_charge_curr_voter=&v[1];i->term_volt_voter=&v[2];i->chg_disable_voter=&v[0];i->chg_en_voter=&v[1];}
int main(void){struct mca_quick_charge_info i;
 setup(&i);assert(!mca_quick_charge_stop_charging(&i));assert(!i.stop_pending&&!i.proc_data.stop_charging&&i.proc_data.charge_flag==MCA_QUICK_CHG_STS_NO_CHARGING&&request_kind==1&&request_volt==9000);assert(trace[0]==OFF0&&trace[1]==OFF1&&trace[2]==FG&&seen(VOTE0)&&seen(VOTE1));
 int critical[]={OFF0,OFF1,FG,FSW0,FSW1,ADC_ON,REQUEST,READBACK,MODE0,MODE1};
 for(unsigned j=0;j<ARRAY_SIZE(critical);j++){setup(&i);fail_op=critical[j];
  assert(mca_quick_charge_stop_charging(&i)==-EIO&&i.stop_pending&&i.proc_data.stop_charging&&i.monitor_work.pending);
  assert(!seen(VOTE0)&&!seen(VOTE1));assert(seen(FG));
  if(fail_op==REQUEST||fail_op==READBACK)assert(request_count==10&&read_count==10);
  reset_trace();i.monitor_work.pending=false;assert(!mca_quick_charge_stop_charging(&i)&&!i.stop_pending&&!i.monitor_work.pending);
 }
 for(int val=0;val<3;val++){setup(&i);readback=val==0?0:val==1?-1:MCA_QUICK_CHG_VBUS_OK_HIGH_TH;
  assert(mca_quick_charge_stop_charging(&i)==-ETIMEDOUT&&request_count==10&&!seen(VOTE0));}
 setup(&i);fail_op=REQUEST;error1=-ETIMEDOUT;fail_op2=READBACK;assert(mca_quick_charge_stop_charging(&i)==-ETIMEDOUT);
 setup(&i);fail_op=OFF0;fail_op2=FG;assert(mca_quick_charge_stop_charging(&i)==-EIO&&seen(OFF1)&&seen(FG)&&!request_count);
 int tail[]={VOTE0,VOTE1,ADC0,ADC1};for(unsigned j=0;j<ARRAY_SIZE(tail);j++){setup(&i);fail_op=tail[j];assert(mca_quick_charge_stop_charging(&i)==-EIO&&i.stop_pending&&i.monitor_work.pending);}
 setup(&i);i.pmic_single_cp_chg=true;i.ffc_final_vterm=4400;i.last_override_vterm=4300;fail_op=OVERRIDE;
 assert(mca_quick_charge_stop_charging(&i)==-EIO&&i.ffc_final_vterm==4400&&i.last_override_vterm==4300&&!seen(VOTE0));
 setup(&i);i.cp_type=0;assert(!mca_quick_charge_stop_charging(&i)&&!seen(OFF1)&&!seen(FSW1)&&!seen(MODE1)&&!seen(ADC1));
 setup(&i);i.online=false;assert(!mca_quick_charge_exit_charging(&i)&&!request_count&&!read_count&&!i.proc_data.adp_type);
 setup(&i);i.online=false;fail_op=FG;assert(mca_quick_charge_exit_charging(&i)==-EIO&&i.proc_data.adp_type==XM_CHARGER_TYPE_PPS&&i.stop_pending);
 setup(&i);fail_op=OFF0;i.stopping=true;assert(mca_quick_charge_stop_charging(&i)==-EIO&&!i.monitor_work.pending);
 setup(&i);fail_op=FG;assert(mca_quick_charge_chg_disable_voter_cb(NULL,&i,1,"test")==-EIO&&i.force_stop&&i.stop_pending);
 reset_trace();assert(!mca_quick_charge_chg_disable_voter_cb(NULL,&i,1,"test")&&!i.stop_pending);
 setup(&i);fail_op=FG;assert(mca_quick_charge_chg_en_voter_cb(NULL,&i,0,"test")==-EIO&&!i.sysfs_data.chg_enable);
 setup(&i);i.trigger_antr_burn=true;assert(!mca_quick_charge_stop_charging(&i)&&request_volt==5000);
 setup(&i);i.pmic_chg_need_fixed_volt=true;assert(!mca_quick_charge_stop_charging(&i)&&request_volt==5000);
 setup(&i);i.pd_switch_to_pmic=true;cap_num=8;assert(!mca_quick_charge_req_adp_volt_and_cur(&i)&&request_volt==5000);cap_num=-1;assert(!stategy_quickchg_is_pdo_9v(&i));
 int types[]={XM_CHARGER_TYPE_PD,XM_CHARGER_TYPE_PPS,XM_CHARGER_TYPE_PD_VERIFY,XM_CHARGER_TYPE_HVDCP3_B,XM_CHARGER_TYPE_HVDCP3P5};
 for(unsigned j=0;j<ARRAY_SIZE(types);j++){setup(&i);i.proc_data.adp_type=types[j];fail_op=REQUEST;error1=-EAGAIN;assert(mca_quick_charge_req_adp_volt_and_cur(&i)==-EAGAIN&&request_count==1);}
 setup(&i);i.proc_data.cur_adp_volt=22000;i.proc_data.cur_adp_cur=4000;assert(!mca_quick_charge_req_adp_volt_and_cur(&i)&&request_volt==21000&&request_cur==3000);
 setup(&i);i.proc_data.cur_adp_cur=-1;assert(mca_quick_charge_req_adp_volt_and_cur(&i)==-ERANGE&&!request_count);
 setup(&i);i.proc_data.adp_type=XM_CHARGER_TYPE_UNKNOW;assert(mca_quick_charge_req_adp_volt_and_cur(&i)==-EOPNOTSUPP&&!request_count);
 int protection[]={MCA_EVENT_CONN_ANTIBURN_CHANGE,MCA_EVENT_BATT_BTB_CHANGE,MCA_EVENT_LPD_STATUS_CHANGE,MCA_EVENT_WIRELESS_REVCHG,MCA_EVENT_CC_SHORT_VBUS,MCA_EVENT_VBAT_OVP_CHANGE,MCA_EVENT_CP_CBOOT_FAIL,MCA_EVENT_PPS_PTF,MCA_EVENT_PLATE_SHOCK,MCA_EVENT_CSD_SEND_PULSE};
 for(unsigned j=0;j<ARRAY_SIZE(protection);j++){setup(&i);fail_op=VOTE0;fail_op2=VOTE1;error2=-EIO;
  assert(mca_quick_charge_process_event(protection[j],1,&i)==-EIO);}
 setup(&i);fail_op=OFF0;fail_op2=VOTE0;error2=-ETIMEDOUT;assert(mca_quick_charge_process_event(MCA_EVENT_SINK_PWR_SUSPEND_CHANGE,1,&i)==-EIO&&seen(OFF1)&&seen(VOTE0));
 setup(&i);fail_op=FG;assert(mca_quick_charge_process_event(MCA_EVENT_CHARGE_ABNORMAL,1,&i)==-EIO&&i.stop_pending);
 setup(&i);fail_op=FG;assert(mca_quick_charge_process_event(MCA_EVENT_USB_DISCONNECT,1,&i)==-EIO&&!i.online&&i.proc_data.adp_type==XM_CHARGER_TYPE_PPS&&!request_count);
 setup(&i);cp_enabled[0]=cp_enabled[1]=true;fg_fault[0]=fg_fault[1]=false;
 i.proc_data.cur_work_cp=MCA_QUICK_CHG_CP_DUAL;i.batt_type=2;fg_reads=0;
 assert(!mca_quick_charge_is_charge_abnormal(&i)&&fg_reads==2);
 for(int role=0;role<2;role++){cp_read_error[role]=-ETIMEDOUT;assert(mca_quick_charge_is_charge_abnormal(&i)==-ETIMEDOUT);cp_read_error[role]=0;
 fg_read_error[role]=-ENODEV;assert(mca_quick_charge_is_charge_abnormal(&i)==-ENODEV);fg_read_error[role]=0;
 fg_fault[role]=true;assert(mca_quick_charge_is_charge_abnormal(&i)==-EIO);fg_fault[role]=false;}
 i.proc_data.cur_work_cp=0;i.batt_type=0;fg_reads=0;assert(!mca_quick_charge_is_charge_abnormal(&i)&&fg_reads==1);
 i.proc_data.cur_work_cp=-1;assert(mca_quick_charge_is_charge_abnormal(&i)==-EINVAL);
 cp_read_error[0]=-EAGAIN;assert(mca_qc_quick_charge_is_charge_abnormal(&i)==-EAGAIN);cp_read_error[0]=0;cp_enabled[0]=false;assert(mca_qc_quick_charge_is_charge_abnormal(&i)==-EIO);
 puts("PASS: actual single/dual CP and gauge read errors; dual-CP path no longer skips gauge checks");
 puts("PASS: actual protection events propagate vote/stop errors, attempt both CPs and preserve the first failure");
 puts("PASS: actual wired CP/FG/adapter/readback stop ordering, blocked release, retry state, detach preservation, single/dual CP, voter errors and PD/PPS/QC request failures");}
'''
with tempfile.TemporaryDirectory(prefix='mca-wired-stop-') as d:
 p=Path(d);(p/'test.c').write_text(pre+macros+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

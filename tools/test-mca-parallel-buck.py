#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute production parallel Buck and CP transitions with fault injection.
Hardware and voter aggregation are modeled; mutexes use pthreads. Not Kbuild or
in-kernel workqueue/lockdep validation.
"""
from pathlib import Path
import os, re, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
s = (root/'drivers/power/supply/mca/mca_strategy/strategy_charger/mca_strategy_quickchg.c').read_text()
def fn(name):
    m = re.search(r'static\s+(?:int|void|bool)\s+'+name+r'\([^;]*?\n\{', s)
    assert m, name
    end, depth = m.end(), 1
    while depth:
        depth += (s[end] == '{') - (s[end] == '}')
        end += 1
    return s[m.start():end]+'\n'
pre = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>
typedef int64_t s64;
#define READ_ONCE(x) (x)
#define CP_ROLE_MASTER 0
#define CP_ROLE_SLAVE 1
#define CP_ROLE_MAX 2
#define MCA_QUICK_CHG_CP_MASTER 0
#define MCA_QUICK_CHG_CP_SLAVE 1
#define MCA_QUICK_CHG_CP_DUAL 2
#define MAIN_BUCK_CHARGER 0
#define MCA_CP_TYPE_PARALLEL 1
#define MCA_QUICK_CHG_SINGLE_MAX_ERR_COUNT 5
#define MCA_QUICK_CHG_OPEN_PATH_IBUS_TH 100
#define mca_log_err(...) ((void)0)
struct mca_votable {int id;};
struct mca_quick_charge_process_data {
 int cur_work_cp,error_num[2],ibus,multi_ibus_th,again_multi_ibus_th,ibus_dec,ibus_inc,dual_cp_count,cur_cp_mode;
 bool stop_charging,cp_path_enable[2];
};
struct mca_quick_charge_info {
 bool online,abort_requested,force_stop; struct {bool chg_enable;} sysfs_data;
 bool ready,stopping,stop_pending,en_buck_parallel_chg,buck_parallel_active,buck_parallel_dirty,is_platform_qc;
 int buck_parallel_icl,buck_parallel_fcc,mult_to_single_cnt,mult_to_single_count,cp_type;
 pthread_mutex_t buck_parallel_lock;
 struct mca_votable *input_suspend_voter,*buck_input_voter,*buck_charge_curr_voter;
 struct mca_quick_charge_process_data proc_data;
};
static void mutex_lock(pthread_mutex_t*m){assert(!pthread_mutex_lock(m));}
static void mutex_unlock(pthread_mutex_t*m){assert(!pthread_mutex_unlock(m));}
enum {SUSPEND=1,RESUME,FREQ_HIGH,FREQ_LOW,ICL_SET,FCC_SET,ICL_CLEAR,FCC_CLEAR,AICL,STATE0,STATE1,READ0,READ1,BUCK_READ,ADC_ON0,ADC_ON1,ADC_OFF0,ADC_OFF1,MODE0,MODE1,ENABLE0,ENABLE1,DISABLE0,DISABLE1,SLEEP,CP_ZERO,CP_RELEASE};
static int trace[1024],count,fail_op,fail_op2,fail_code=-EIO,read0=1800,read1=1800,buck_read=200000;
static int icl,fcc,thermal_icl=700,thermal_fcc=1000,seen_icl,seen_fcc,delay_us;
static bool cp_zero=true;
static bool suspended,enabled[2]={true,true};
static int op(int id){assert(count<1024);trace[count++]=id;if(delay_us)usleep(delay_us);return id==fail_op?fail_code:id==fail_op2?-ENODEV:0;}
static bool seen(int id){for(int n=0;n<count;n++)if(trace[n]==id)return true;return false;}
static int mca_vote(struct mca_votable*v,const char*client,bool en,int val){
 int id=v->id==0?(en?SUSPEND:RESUME):v->id==1?(en?ICL_SET:ICL_CLEAR):(en?FCC_SET:FCC_CLEAR);
 if(v->id==2&&!strcmp(client,"wire_qc")){int ret=op(en?CP_ZERO:CP_RELEASE);if(!ret)cp_zero=en;return ret;}
 assert(!strcmp(client,v->id?"parallel_qc":"wire_qc"));
 if(id==ICL_SET||id==FCC_SET)assert(suspended);
 int ret=op(id);if(ret)return ret;
 if(v->id==0){if(!en){assert(icl>0&&fcc>0&&!cp_zero);seen_icl=icl<thermal_icl?icl:thermal_icl;seen_fcc=fcc<thermal_fcc?fcc:thermal_fcc;}suspended=en;}
 else if(v->id==1)icl=en?val:0;else fcc=en?val:0;
 return 0;
}
static int platform_class_buckchg_ops_set_buck_fsw(int r,int f){assert(!r&&suspended);return op(f==18000?FREQ_HIGH:FREQ_LOW);}
static int platform_class_buckchg_ops_set_restart_aicl(int r,bool b){assert(!r&&b&&!suspended);return op(AICL);}
static int platform_class_cp_get_charging_enabled(int r,bool*v){assert(r==0||r==1);int ret=op(r?STATE1:STATE0);if(!ret)*v=enabled[r];return ret;}
static int platform_class_cp_get_bus_current(int r,int*v){assert(r==0||r==1);int ret=op(r?READ1:READ0);if(!ret)*v=r?read1:read0;return ret;}
static int platform_class_buckchg_ops_get_bus_curr(int r,int*v){assert(!r);int ret=op(BUCK_READ);if(!ret)*v=buck_read;return ret;}
static int platform_class_cp_enable_adc(int r,bool en){assert(r==0||r==1);return op(en?(r?ADC_ON1:ADC_ON0):(r?ADC_OFF1:ADC_OFF0));}
static int platform_class_cp_set_mode(int r,int m){(void)m;assert(r==0||r==1);return op(r?MODE1:MODE0);}
static int platform_class_cp_set_charging_enable(int r,bool en){assert(r==0||r==1);int ret=op(en?(r?ENABLE1:ENABLE0):(r?DISABLE1:DISABLE0));if(!ret)enabled[r]=en;return ret;}
static int mca_quick_charge_msleep(int ms,struct mca_quick_charge_info*i){assert(ms==500);(void)i;return op(SLEEP);}
'''
names = ['mca_quick_charge_blocked', 'mca_quick_charge_record_error', 'mca_quick_charge_update_ibus',
         'strategy_quickchg_disable_buck_parallel', 'strategy_quickchg_enable_buck_charging',
         'mca_quick_charge_try2_single_path', 'mca_quick_charge_try2_multi_path',
         'mca_quick_charge_change_path']
body = ''.join(fn(n) for n in names)
test = r'''
static struct mca_votable v[3]={{0},{1},{2}};
static void clear_trace(void){count=fail_op=fail_op2=0;fail_code=-EIO;}
static void init(struct mca_quick_charge_info*i){memset(i,0,sizeof(*i));assert(!pthread_mutex_init(&i->buck_parallel_lock,NULL));i->online=i->sysfs_data.chg_enable=i->ready=i->en_buck_parallel_chg=true;i->cp_type=MCA_CP_TYPE_PARALLEL;i->proc_data.cur_work_cp=2;i->input_suspend_voter=&v[0];i->buck_input_voter=&v[1];i->buck_charge_curr_voter=&v[2];}
static void reset(struct mca_quick_charge_info*i){assert(!pthread_mutex_destroy(&i->buck_parallel_lock));init(i);clear_trace();suspended=cp_zero=true;icl=fcc=0;read0=read1=1800;buck_read=200000;enabled[0]=enabled[1]=true;}
static void *enable_thread(void*p){assert(!strategy_quickchg_enable_buck_charging(p,900,2000,true));return NULL;}
int main(void){struct mca_quick_charge_info i,j;init(&i);reset(&i);
 assert(!strategy_quickchg_enable_buck_charging(&i,900,2000,true));assert(i.buck_parallel_active&&!i.buck_parallel_dirty&&!suspended&&seen_icl==700&&seen_fcc==1000);
 clear_trace();assert(!strategy_quickchg_enable_buck_charging(&i,900,2000,true)&&!seen(FREQ_HIGH));
 assert(!strategy_quickchg_enable_buck_charging(&i,1000,2500,true)&&i.buck_parallel_icl==1000&&i.buck_parallel_fcc==2500);
 int failures[]={STATE0,STATE1,READ0,READ1,BUCK_READ,SUSPEND,FREQ_HIGH,ICL_SET,FCC_SET,CP_RELEASE,RESUME,AICL};
 for(unsigned n=0;n<sizeof(failures)/sizeof(failures[0]);n++){
  reset(&i);fail_op=failures[n];assert(strategy_quickchg_enable_buck_charging(&i,900,2000,true)==-EIO&&!i.buck_parallel_active);
  if(fail_op!=SUSPEND)assert(suspended);
  clear_trace();assert(!strategy_quickchg_enable_buck_charging(&i,900,2000,true)&&i.buck_parallel_active&&!i.buck_parallel_dirty);
 }
 reset(&i);fail_op=AICL;fail_op2=ICL_CLEAR;assert(strategy_quickchg_enable_buck_charging(&i,900,2000,true)==-EIO&&i.buck_parallel_dirty&&suspended);
 clear_trace();assert(!strategy_quickchg_enable_buck_charging(&i,900,2000,true)&&!i.buck_parallel_dirty);
 int cleanup[]={SUSPEND,CP_ZERO,FREQ_LOW,ICL_CLEAR,FCC_CLEAR};
 for(unsigned n=0;n<sizeof(cleanup)/sizeof(cleanup[0]);n++){
  reset(&i);assert(!strategy_quickchg_enable_buck_charging(&i,900,2000,true));i.stop_pending=true;clear_trace();fail_op=cleanup[n];
  assert(strategy_quickchg_enable_buck_charging(&i,0,0,false)==-EIO&&i.buck_parallel_dirty&&i.buck_parallel_active);
  assert(!seen(STATE0)&&!seen(READ0));clear_trace();assert(!strategy_quickchg_enable_buck_charging(&i,0,0,false)&&!i.buck_parallel_active&&!i.buck_parallel_dirty&&suspended);
 }
 reset(&i);assert(!strategy_quickchg_enable_buck_charging(&i,900,2000,true));i.stop_pending=true;read0=read1=0;buck_read=0;enabled[0]=enabled[1]=false;fail_op=STATE0;assert(!strategy_quickchg_enable_buck_charging(&i,0,0,false)&&!i.buck_parallel_active);
 reset(&i);i.proc_data.cur_work_cp=9;assert(strategy_quickchg_enable_buck_charging(&i,900,2000,true)==-EINVAL&&!count);
 reset(&i);i.stopping=true;assert(strategy_quickchg_enable_buck_charging(&i,900,2000,true)==-ESHUTDOWN&&!count);
 reset(&i);assert(strategy_quickchg_enable_buck_charging(&i,-1,2000,true)==-EINVAL&&!count);
 reset(&i);enabled[1]=false;assert(strategy_quickchg_enable_buck_charging(&i,900,2000,true)==-EAGAIN&&!seen(RESUME));
 reset(&i);i.proc_data.ibus=777;fail_op=BUCK_READ;assert(mca_quick_charge_update_ibus(&i)==-EIO&&i.proc_data.ibus==777);
 clear_trace();read0=INT_MAX;read1=INT_MAX;assert(mca_quick_charge_update_ibus(&i)==-ERANGE&&i.proc_data.ibus==777);
 read0=-1;read1=1;assert(mca_quick_charge_update_ibus(&i)==-ERANGE&&i.proc_data.ibus==777);
 reset(&i);init(&j);assert(!strategy_quickchg_enable_buck_charging(&i,900,2000,true));suspended=true;clear_trace();assert(!strategy_quickchg_enable_buck_charging(&j,900,2000,true)&&seen(FREQ_HIGH));pthread_mutex_destroy(&j.buck_parallel_lock);
 /* Concurrent requests for one instance serialize into one transition. */
 reset(&i);delay_us=1000;pthread_t a,b;assert(!pthread_create(&a,NULL,enable_thread,&i));assert(!pthread_create(&b,NULL,enable_thread,&i));pthread_join(a,NULL);pthread_join(b,NULL);delay_us=0;
 int enables=0;for(int n=0;n<count;n++)enables+=trace[n]==FREQ_HIGH;assert(enables==1);
 /* Dual -> single: both disable and ADC acknowledgments precede publication. */
 int single_fail[]={READ0,READ1,BUCK_READ,DISABLE1,ADC_OFF1};
 for(unsigned n=0;n<sizeof(single_fail)/sizeof(single_fail[0]);n++){
  reset(&i);i.proc_data.cp_path_enable[0]=true;i.proc_data.multi_ibus_th=5000;fail_op=single_fail[n];
  assert(mca_quick_charge_change_path(&i)==-EIO&&i.proc_data.cur_work_cp==2);
  clear_trace();assert(!mca_quick_charge_change_path(&i)&&i.proc_data.cur_work_cp==0&&!enabled[1]);
 }
 /* Single -> dual: every failed operation rolls back the added CP. */
 int multi_fail[]={ADC_ON1,MODE1,ENABLE1,SLEEP,READ1};
 for(unsigned n=0;n<sizeof(multi_fail)/sizeof(multi_fail[0]);n++){
  reset(&i);i.proc_data.cur_work_cp=0;enabled[1]=false;fail_op=multi_fail[n];
  assert(mca_quick_charge_change_path(&i)==-EIO&&i.proc_data.cur_work_cp==0&&!i.proc_data.dual_cp_count&&seen(DISABLE1)&&!enabled[1]);
  clear_trace();assert(!mca_quick_charge_change_path(&i)&&i.proc_data.cur_work_cp==2&&i.proc_data.dual_cp_count==1);
 }
 reset(&i);i.proc_data.cur_work_cp=0;read1=0;assert(mca_quick_charge_change_path(&i)==-EAGAIN&&!enabled[1]&&i.proc_data.cur_work_cp==0);
 reset(&i);i.proc_data.cur_work_cp=0;fail_op=MODE1;fail_op2=DISABLE1;assert(mca_quick_charge_change_path(&i)==-EIO&&i.stop_pending&&i.proc_data.stop_charging);
 pthread_mutex_destroy(&i.buck_parallel_lock);
 puts("PASS: actual Buck transitions, MIN caps, 12 enable failures, 5 cleanup failures, rollback retry, instance isolation and pthread serialization");
 puts("PASS: actual complete-current samples, invalid/overflow input, single/dual CP transitions, rollback and failure state");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-parallel-') as d:
    p=Path(d)
    (p/'test.c').write_text(pre+body+test)
    subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread',
                    '-Werror=implicit-function-declaration','-fsanitize=address,undefined',
                    str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=30,
                   env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

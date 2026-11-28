#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual dynamic mode handover, atomic sample publication and stage bounds."""
from pathlib import Path
import os,runpy,subprocess,tempfile,re
c=runpy.run_path(str(Path(__file__).with_name('test-mca-wired-controls.py')));fn=c['fn'];s=c['s']
pre=c['pre']
stubs=r'''
enum {STOP=1,SELECT,OPEN,FAST,TABLE,STAGE,VBAT,IBAT,V0,V1,I0,I1};
static int calls,fail_at,chosen=1,trace[100],vbat=4000,current=-1500000;
static int tick(int id){trace[calls++]=id;return calls==fail_at?-EIO:0;}
static int mca_get_cpmode_unrelated_fcc(struct mca_quick_charge_info*i){(void)i;return 5000;}
static int mca_select_cp_work_mode_by_current(struct mca_quick_charge_info*i,int fcc){(void)i;(void)fcc;return chosen;}
static int mca_quick_charge_stop_charging(struct mca_quick_charge_info*i){int r=tick(STOP);if(!r){i->pd_switch_to_pmic=true;i->proc_data.ffc_flag=false;i->proc_data.charge_flag=0;}return r;}
static void mca_quick_charge_update_work_mode_para(struct mca_quick_charge_info*i){(void)i;}
static int mca_quick_charge_select_cp(struct mca_quick_charge_info*i){(void)i;return tick(SELECT);}
static int mca_quick_charge_open_selected(struct mca_quick_charge_info*i){assert(!i->pd_switch_to_pmic&&!i->proc_data.charge_flag);return tick(OPEN);}
static int strategy_class_fg_set_fastcharge(bool en){assert(en);return tick(FAST);}
static int mca_quick_charge_select_volt_para(struct mca_quick_charge_info*i){(void)i;return tick(TABLE);}
static int mca_quick_charge_select_stage(struct mca_quick_charge_info*i){(void)i;return tick(STAGE);}
static int schedule_delayed_work(struct delayed_work*w,int delay){(void)delay;w->pending=true;return 1;}
static int strategy_class_fg_ops_get_voltage(int*out){int r=tick(VBAT);if(!r)*out=vbat;return r;}
static int strategy_class_fg_ops_get_current(int*out){int r=tick(IBAT);if(!r)*out=current;return r;}
static int platform_fg_ops_get_volt(int role,int*out){int r=tick(role?V1:V0);if(!r)*out=4000+role;return r;}
static int platform_fg_ops_get_curr(int role,int*out){int r=tick(role?I1:I0);if(!r)*out=-1000000-role*1000;return r;}
'''
body=''.join(fn(n) for n in ['mca_check_cp_work_mode','mca_quick_charge_update_vbat','mca_quick_charge_update_ibat','mca_quick_charge_jump_stage','mca_quick_charge_check_chg_done'])
test=r'''
static struct mca_quick_charge_volt_para table[3];static int stages[6];static struct mca_quick_charge_volt_para_info vp={.volt_para_size=3,.volt_para=table,.stage_para=stages};
static void setup(struct mca_quick_charge_info*i){memset(i,0,sizeof(*i));calls=fail_at=0;chosen=1;vbat=4000;current=-1500000;i->support_mode_switch=true;i->cur_cp_work_mode=i->cp_default_work_mode=2;i->cur_support_mode=7;i->proc_data.cur_volt_para[0]=&vp;i->proc_data.ffc_flag=true;i->proc_data.charge_flag=1;}
int main(void){struct mca_quick_charge_info i;
 setup(&i);assert(!mca_check_cp_work_mode(&i)&&i.cur_cp_work_mode==1&&i.proc_data.charge_flag==1&&i.proc_data.ffc_flag&&!i.pd_switch_to_pmic);assert(calls==6&&trace[0]==STOP&&trace[2]==OPEN&&trace[5]==STAGE);
 for(int j=1;j<=6;j++){setup(&i);fail_at=j;assert(mca_check_cp_work_mode(&i)==-EIO&&i.cur_cp_work_mode==2);if(j>1)assert(!i.proc_data.charge_flag);}
 setup(&i);i.support_mode_switch=false;i.proc_data.cur_volt_para[0]=NULL;assert(!mca_check_cp_work_mode(&i)&&!calls);
 setup(&i);i.cur_support_mode=4;assert(mca_check_cp_work_mode(&i)==-EINVAL&&!calls);
 setup(&i);i.batt_type=3;i.proc_data.vbat[0]=99;i.proc_data.parall_vbat[0]=98;i.proc_data.parall_vbat[1]=97;fail_at=3;assert(mca_quick_charge_update_vbat(&i)==-EIO&&i.proc_data.vbat[0]==99&&i.proc_data.parall_vbat[0]==98&&i.proc_data.parall_vbat[1]==97);
 calls=fail_at=0;assert(!mca_quick_charge_update_vbat(&i)&&i.proc_data.vbat[0]==4000&&i.proc_data.parall_vbat[1]==4001);
 calls=0;fail_at=3;i.proc_data.ibat_total=99;i.proc_data.parall_ibat[0]=98;assert(mca_quick_charge_update_ibat(&i)==-EIO&&i.proc_data.ibat_total==99&&i.proc_data.parall_ibat[0]==98);
 calls=fail_at=0;current=INT_MIN;assert(!mca_quick_charge_update_ibat(&i)&&i.proc_data.ibat_total==2147483&&i.proc_data.parall_ibat[1]==1001);
 setup(&i);i.proc_data.charge_flag=MCA_QUICK_CHG_STS_CHARGE_DONE;i.recharge_vbat=4300;assert(!mca_quick_charge_check_chg_done(&i));vbat=4400;assert(mca_quick_charge_check_chg_done(&i)==1);calls=0;fail_at=1;assert(mca_quick_charge_check_chg_done(&i)==-EIO);
 memset(stages,0,sizeof(stages));assert(mca_quick_charge_jump_stage(6,&vp)==5);vp.stage_para=NULL;assert(mca_quick_charge_jump_stage(6,&vp)==5);vp.stage_para=stages;for(int j=0;j<6;j++)stages[j]=1;assert(mca_quick_charge_jump_stage(0,&vp)==5);assert(mca_quick_charge_jump_stage(-1,&vp)==-EINVAL);vp.volt_para_size=0;assert(mca_quick_charge_jump_stage(0,&vp)==-EINVAL);
 puts("PASS: actual CP mode stop-before-open and six faults, fixed-PDO flag reset, unsupported modes, complete sample publication, INT_MIN conversion, end-stage bounds with/without skip tables");}
'''
with tempfile.TemporaryDirectory(prefix='mca-wired-mode-') as d:
 p=Path(d);(p/'test.c').write_text(pre+c['header']+stubs+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

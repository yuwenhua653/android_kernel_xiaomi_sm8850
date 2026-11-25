#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the production battery getter against independent/missing/failing inputs."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', type=Path, required=True)
p.add_argument('--source', type=Path)
a = p.parse_args()
s = (a.source or a.kernel_root / 'drivers/power/supply/mca/mca_business/business_battery/mca_battery_psy.c').read_text()
getter = function(s, 'batt_psy_get_prop')
helper = function(s, 'battery_psy_get_input_online') if 'static int battery_psy_get_input_online(' in s else ''
props = sorted(set(re.findall(r'POWER_SUPPLY_PROP_\w+', getter + helper)))
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#define mca_log_err(...) ((void)0)
#define MAIN_BUCK_CHARGER 0
#define POWER_SUPPLY_STATUS_CHARGING 1
#define POWER_SUPPLY_STATUS_DISCHARGING 2
#define POWER_SUPPLY_STATUS_FULL 4
#define POWER_SUPPLY_TECHNOLOGY_LIPO 3
union power_supply_propval { int intval; const char *strval; };
struct power_supply { int kind; };
struct batt_psy_info { struct power_supply *batt_psy,*usb_psy,*wls_psy; void *input_suppend_voter; bool fake_power; };
static struct power_supply battery={0},usb={1},wls={2};
static struct batt_psy_info info={&battery,&usb,&wls,0,false};
static int ustate,wstate,vote,soc=50,fg_error,fg_ready=1,usb_reads,wls_reads;
static bool done;
static struct batt_psy_info *power_supply_get_drvdata(struct power_supply *p) { (void)p;return &info; }
static bool battery_psy_is_usb_available(struct batt_psy_info *p) { return p->usb_psy!=0; }
static bool battery_psy_is_wls_available(struct batt_psy_info *p) { return p->wls_psy!=0; }
static int strategy_class_fg_ops_is_init_ok(void) { return fg_ready; }
static int strategy_class_fg_ops_get_soc(void) { return soc; }
static bool strategy_class_fg_ops_get_charging_done(void) { return done; }
static void *mca_find_votable(const char *name) { (void)name; return &vote; }
static int mca_get_client_vote(void *v,const char *name) { (void)v;(void)name;return vote; }
static int sample(int *v) { *v=4200; return fg_error; }
#define strategy_class_fg_ops_get_voltage sample
#define strategy_class_fg_ops_get_current sample
#define strategy_class_fg_ops_get_temperature sample
#define strategy_class_fg_get_rm sample
#define strategy_class_fg_ops_get_cyclecount sample
#define strategy_class_fg_get_fcc sample
#define strategy_class_fg_get_dc sample
static int strategy_class_fg_get_model_name(const char **s) { *s="test"; return fg_error; }
static int get_prop_batt_health(struct batt_psy_info *p,union power_supply_propval *v) { (void)p;return sample(&v->intval); }
#define get_prop_batt_capacity_level get_prop_batt_health
static int platform_class_buckchg_ops_get_chg_type(int r,int *v) { (void)r;return sample(v); }
'''
code += 'enum power_supply_property {' + ','.join(props) + '};\n'
code += r'''
static int fake_batt_psy_get_prop(struct batt_psy_info *p,enum power_supply_property n,union power_supply_propval *v) { (void)p;(void)n;return sample(&v->intval); }
static int power_supply_get_property(struct power_supply *p,enum power_supply_property prop,union power_supply_propval *v) {
    assert(p); int state=p->kind==1?ustate:wstate;
    if(p->kind==1)usb_reads++;else wls_reads++;
    v->intval=12345;
    if(state==2)return -EIO;
    v->intval=prop==POWER_SUPPLY_PROP_ONLINE?state:5000;
    return 0;
}
'''
code += helper + getter + r'''
int main(void) {
    union power_supply_propval v;
    int cases=0;
    /* Independent FG readings must work before either input provider binds. */
    info.usb_psy=info.wls_psy=0;
    const int independent[]={POWER_SUPPLY_PROP_CAPACITY,POWER_SUPPLY_PROP_VOLTAGE_NOW,
        POWER_SUPPLY_PROP_CURRENT_NOW,POWER_SUPPLY_PROP_TEMP,POWER_SUPPLY_PROP_CHARGE_COUNTER,
        POWER_SUPPLY_PROP_CYCLE_COUNT,POWER_SUPPLY_PROP_CHARGE_FULL,POWER_SUPPLY_PROP_CHARGE_FULL_DESIGN};
    for(unsigned i=0;i<sizeof(independent)/sizeof(*independent);i++) {
        v.intval=-777;
        assert(!batt_psy_get_prop(&battery,independent[i],&v));
        assert(v.intval!=-777);cases++;
    }
    assert(!usb_reads&&!wls_reads);
    /* -1=missing, 0=offline, 1=online, 2=read error. */
    const int votes[]={-EINVAL,0,1};
    for(int u=-1;u<=2;u++)for(int w=-1;w<=2;w++)for(int n=0;n<3;n++) {
        info.usb_psy=u<0?0:&usb;info.wls_psy=w<0?0:&wls;
        ustate=u;wstate=w;vote=votes[n];v.intval=-777;
        int rc=batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_STATUS,&v);
        if(vote>0)assert(!rc && v.intval==POWER_SUPPLY_STATUS_DISCHARGING);
        else if(u==1||w==1)assert(!rc && v.intval==POWER_SUPPLY_STATUS_CHARGING);
        else if(u==0&&w==0)assert(!rc && v.intval==POWER_SUPPLY_STATUS_DISCHARGING);
        else assert(rc<0 && v.intval==-777);
        cases++;
    }
    info.usb_psy=0;info.wls_psy=&wls;wstate=1;vote=-EINVAL;
    soc=100;done=true;
    assert(!batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_STATUS,&v));
    assert(v.intval==POWER_SUPPLY_STATUS_FULL);cases++;
    soc=-EIO;v.intval=-777;
    assert(batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_STATUS,&v)==-EIO&&v.intval==-777);cases++;
    soc=101;
    assert(batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_CAPACITY,&v)==-ERANGE&&v.intval==-777);cases++;
    fg_error=-EIO;
    assert(batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_TEMP,&v)==-EIO&&v.intval==-777);cases++;
    assert(batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_VOLTAGE_MAX,&v)==-ENODEV);cases++;
    assert(batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT_MAX,&v)==-ENODEV);cases++;
    assert(batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_TIME_TO_FULL_NOW,&v)==-ENODATA);cases++;
    fg_ready=0;
    assert(batt_psy_get_prop(&battery,POWER_SUPPLY_PROP_CAPACITY,&v)==-ENODATA);cases++;
    printf("PASS: %d battery provider/vote/status/error cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
    c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=undefined',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

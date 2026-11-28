#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise OS4 weak termination, selected-pack parsing and vote retry."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1] / "drivers/power/supply/mca"
source = (root / "mca_strategy/strategy_charger/mca_buckchg_jeita.c").read_text()
protocol = (root / "include/mca/protocol/protocol_class.h").read_text()


def body(text, start):
    i = text.index(start)
    return text[i:text.index("\n}", i) + 2] + "\n"


pre = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <errno.h>
#include <string.h>
typedef uint32_t u32;
#define IS_ENABLED(x) 1
#define READ_ONCE(x) (x)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define mca_log_err(...) ((void)0)
#define min(a,b) ((a)<(b)?(a):(b))
static int test_vbat,voltage_error;
static int strategy_class_fg_ops_get_voltage(int *v) {*v=test_vbat;return voltage_error;}
struct voltage {int voltage,max_current;};
struct mca_buckchg_jeita_data {int iterm,vterm,max_current; struct {int size; struct voltage *volt_data;} volt_para;};
struct mca_buckchg_jeita_para {struct mca_buckchg_jeita_data *jeita_data,*jeita_ffc_data; int size,fcc_size;};
struct voter {int rc,last,count;};
struct mca_buckchg_jeita_dev {struct mca_buckchg_jeita_para jeita_para;
    int weak_delta_mv,weak_iterm_ma; bool usb_online,weak_vote_retry,support_base_flip,base_flip_same;
    unsigned weak_adapter; struct voter *vterm_voter,*iterm_voter; };
struct device_node {int present,enable_rc,count,array_rc; u32 enabled,cfg[2];};
static int of_find_property(struct device_node *n,const char *s,void *unused) {return n->present;}
static int of_property_read_u32(struct device_node *n,const char *s,u32 *out) { *out=n->enabled;return n->enable_rc;}
static int of_property_count_u32_elems(struct device_node *n,const char *s) {return n->count;}
static int of_property_read_u32_array(struct device_node *n,const char *s,u32 *v,int count) {
    assert(count==2);memcpy(v,n->cfg,8);return n->array_rc;
}
static unsigned wire_type;static int wire_error,reads;
static int protocol_class_get_adapter_type(unsigned protocol,unsigned *out) {
    assert(protocol==5);reads++;*out=wire_type;return wire_error;
}
static int mca_vote(struct voter *v,const char *name,bool enable,int val) {
    assert(enable && !strcmp(name,"jeita"));v->count++;if (!v->rc) v->last=val;return v->rc;
}
"""
check = r"""
int main(void) {
    struct voltage steps[]={{4000,1000},{4300,900}};
    struct mca_buckchg_jeita_data normal={.iterm=300,.vterm=4500,.volt_para={2,steps}}, ffc={.iterm=400,.vterm=4510};
    struct voter fv={},term={};
    struct mca_buckchg_jeita_dev d={.jeita_para={&normal,&ffc,1,1},.vterm_voter=&fv,.iterm_voter=&term};
    struct device_node node={.present=1,.enabled=1,.count=2,.cfg={10,200}};
    assert(!mca_jeita_above_lower_step(&normal,-1,4500));
    assert(mca_jeita_above_lower_step(&normal,0,3900));
    assert(!mca_jeita_above_lower_step(&normal,1,4000));
    assert(mca_jeita_above_lower_step(&normal,1,4001));
    assert(!mca_jeita_above_lower_step(&normal,2,4500));
    int index=99;
    normal.max_current=1200;test_vbat=4100;
    assert(mca_buckchg_jeita_get_curr(&normal,&index)==900 && index==1);
    test_vbat=4500;
    assert(mca_buckchg_jeita_get_curr(&normal,&index)==900 && index==-1);
    index=1;voltage_error=-EIO;
    assert(mca_buckchg_jeita_get_curr(&normal,&index)==1200 && index==-1);
    node.count=1;assert(mca_jeita_parse_weak(&node,&d)==-EINVAL && !d.weak_iterm_ma);
    node.count=2;node.cfg[1]=0;assert(mca_jeita_parse_weak(&node,&d)==-EINVAL);
    node.cfg[1]=200;node.cfg[0]=UINT_MAX;assert(mca_jeita_parse_weak(&node,&d)==-EINVAL);
    node.cfg[0]=10;ffc.vterm=10;assert(mca_jeita_parse_weak(&node,&d)==-EINVAL);ffc.vterm=4510;
    node.array_rc=-EIO;assert(mca_jeita_parse_weak(&node,&d)==-EIO);node.array_rc=0;
    node.present=0;assert(!mca_jeita_parse_weak(&node,&d) && !d.weak_iterm_ma);node.present=1;
    node.enabled=0;assert(!mca_jeita_parse_weak(&node,&d) && !d.weak_iterm_ma);node.enabled=1;
    assert(!mca_jeita_parse_weak(&node,&d) && d.weak_iterm_ma==200 && d.weak_delta_mv==10);
    assert(XM_CHARGER_TYPE_FLOAT==4 && XM_CHARGER_TYPE_HVDCP2==5);
    int v=4500,t=300;
    assert(!mca_jeita_weak_limits(&d,&v,&t) && v==4500 && t==300 && !reads);
    d.usb_online=true;
    for (unsigned a=0; a<=XM_CHARGER_TYPE_PD; a++) {
        wire_type=a;v=4500;t=300;
        assert(mca_jeita_weak_limits(&d,&v,&t)==a);
        bool weak=a>=1 && a<=4;
        assert(v==(weak?4490:4500) && t==(weak?200:300));
    }
    wire_type=XM_CHARGER_TYPE_DCP;v=4500;t=200;mca_jeita_weak_limits(&d,&v,&t);assert(v==4500 && t==200);
    t=120;mca_jeita_weak_limits(&d,&v,&t);assert(v==4500 && t==120);
    wire_error=-EIO;t=300;assert(mca_jeita_weak_limits(&d,&v,&t)==UINT_MAX && v==4490 && t==200);
    term.rc=-EIO;mca_jeita_vote_termination(&d,UINT_MAX,v,t);
    assert(d.weak_vote_retry && d.weak_adapter==0 && fv.last==4490 && term.count==1);
    term.rc=0;fv.rc=-EIO;mca_jeita_vote_termination(&d,UINT_MAX,v,t);assert(d.weak_vote_retry && term.last==200);
    fv.rc=0;mca_jeita_vote_termination(&d,UINT_MAX,v,t);assert(!d.weak_vote_retry && d.weak_adapter==UINT_MAX);
    d.usb_online=false;v=4500;t=300;assert(!mca_jeita_weak_limits(&d,&v,&t));
    mca_jeita_vote_termination(&d,0,v,t);assert(fv.last==4500 && term.last==300 && d.weak_adapter==0);
}
"""
decls = ("static int mca_buckchg_jeita_get_curr(", "static bool mca_jeita_above_lower_step(", "static unsigned int mca_jeita_weak_limits(",
         "static void mca_jeita_vote_termination(", "static bool mca_jeita_delta_valid(",
         "static int mca_jeita_parse_weak(")
program = (body(protocol, "enum adapter_protocol_type {").rstrip() + ";\n"
           + body(protocol, "enum xm_charger_type {").rstrip() + ";\n" + pre
           + "".join(body(source, decl) for decl in decls) + check)
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder)
    (path / "test.c").write_text(program)
    subprocess.run([os.environ.get("CC", "cc"), "-g", "-O1", "-fsanitize=address,undefined",
                    path / "test.c", "-o", path / "test"], check=True)
    subprocess.run([path / "test"], check=True)
print("PASS selected-pack weak termination, BC1.2 types, voltage-band boundaries, protocol errors and vote retries")

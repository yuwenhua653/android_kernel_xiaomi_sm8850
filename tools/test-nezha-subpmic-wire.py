#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the Nezha property and event implementation with a mock DSP and ordered queue."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
src = (root / "drivers/power/supply/mca/mca_qcom_subpmic_proxy/mca_nezha_subpmic.c").read_text()
props = src[src.index("enum nezha_subpmic_property"):src.index("static struct platform_class_buckchg_ops")]
events = src[src.index("enum nezha_notice"):src.index("static struct mca_adsp_glink_ops")]
pre = r"""
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef int atomic_t;
struct device {};
struct workqueue_struct {};
struct mutex {};
struct delayed_work {};
struct power_supply {};
struct work_struct { void (*run)(struct work_struct *); };
#define atomic_read(p) (*(p))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define guard(lock) (void)
#define BIT(i) (1U << (i))
#define MCA_BATT_CHGR_STATUS_TERMINATION 5
#define container_of(p, type, field) ((type *)((char *)(p)-offsetof(type,field)))
#define GFP_KERNEL 0
#define kfree free
#define kmalloc(n, flags) malloc(n)
#define dev_err_ratelimited(...) ((void)0)
#define INIT_WORK(w, fn) ((w)->run=(fn))
#define fallthrough __attribute__((fallthrough))
static int property, length, bits, result, writes, reads;
static int mca_adsp_glink_read_prop(int p, void *v, size_t n) {
    reads++; property=p; length=n; if (!result) memcpy(v,&bits,n); return result;
}
static int mca_adsp_glink_write_prop(int p, void *v, size_t n) {
    writes++; property=p; length=n; bits=0; memcpy(&bits,v,n); return result;
}
"""
mock = r"""
enum { MCA_EVENT_TYPE_CHARGE_TYPE, MCA_EVENT_TYPE_HW_INFO, MCA_EVENT_TYPE_TYPEC_PORT_STATUS,
       MCA_EVENT_CHARGE_CAP_CHANGE, MCA_EVENT_LPD_STATUS_CHANGE, MCA_EVENT_PLATE_SHOCK,
       MCA_EVENT_CC_SHORT_VBUS, MCA_EVENT_PPS_PTF, MCA_EVENT_SINK_PWR_SUSPEND_CHANGE,
       MCA_EVENT_CP_REVERT_CHANGE, STRATEGY_FUNC_TYPE_QUICK_CHARGE, STRATEGY_FUNC_TYPE_BUCK_CHARGE };
static int refreshed, count, nr;
static struct {int type, id, val;} recorded[32];
static struct work_struct *pending[32];
static void nezha_glink_state(void *p){(void)p; refreshed++;}
static void queue_work(void *q, struct work_struct *w){(void)q; assert(nr<32);pending[nr++]=w;}
static void drain(void){for(int i=0;i<nr;i++)pending[i]->run(pending[i]);nr=0;}
static u32 get_unaligned_le32(const void *p){const u8 *b=p;return b[0]|b[1]<<8|b[2]<<16|(u32)b[3]<<24;}
static void record(int t,int id,int v){recorded[count++]=(typeof(recorded[0])){t,id,v};}
static void mca_event_block_notify(int t,int e,void *v) {
    record(t,e,!v?0:e==MCA_EVENT_SINK_PWR_SUSPEND_CHANGE?*(bool*)v:*(int*)v);
}
static int mca_strategy_func_process(int t,int id,int v){record(t,id,v);return 0;}
"""
# Independent wire values and widths from OS4.0.7.0.XPACNXM.
expect_read = {
    "get_ovp_vth": 8, "get_wls_curr": 0x1007, "get_sys_volt": 0x200c,
    "get_otg_boost_enable_status": 0x200d, "get_otg_gate_enable_status": 0x200e,
    "get_usb_aicl_cont_thd": 0x2017, "get_lpd_sbu1": 0x201f, "get_lpd_sbu2": 0x2020,
    "get_lpd_cc1": 0x2021, "get_lpd_cc2": 0x2022, "get_lpd_dp": 0x2023,
    "get_lpd_dm": 0x2024, "get_lpd_control": 0x2025, "get_lpd_uart_control": 0x2026,
    "get_pack_vbat": 0x2027, "get_pack_ibat": 0x2028, "get_pack_tbat": 0x202b,
    "get_lpd_enable": 0x20009, "get_lpd_status": 0x2000a,
}
expect_write = {
    "set_too_hot_limit": 7, "set_ovp_vth": 8, "set_wls_input_curr_lmt": 0x1003,
    "set_buck_fsw": 0x2004, "set_prechg_curr": 0x200a, "set_prechg_volt": 0x200b,
    "set_boost_enable": 0x200f, "set_boost_voltage": 0x2012, "set_usb_aicl_cont_thd": 0x2017,
    "set_opt_fws": 0x2019, "set_qc3_volt": 0x201b, "set_lpd_sbu1": 0x201f,
    "set_lpd_control": 0x2025, "set_lpd_uart_control": 0x2026, "set_audio_status": 0x2102c,
}
expect_bool = {"set_wls_hiz": 0x1004, "set_wls_vdd_flag": 0x100c,
               "set_aicl_enable": 0x2014, "set_rerun_aicl": 0x2015,
               "set_restart_aicl": 0x2016, "usb_adapter_allow_override": 0x201a,
               "set_screen_status": 0x202d}
test = "int main(void){ struct nezha_subpmic sc={0}; int v=0; bool b=false;\n"
for name, prop in expect_read.items():
    test += f"bits=-123;result=0;assert(!nezha_{name}(&sc,&v)&&v==-123&&property=={prop}&&length==4);"
    test += f"result=-ENOTCONN;v=42;assert(nezha_{name}(&sc,&v)==-ENOTCONN&&v==42);\n"
for name, prop in expect_write.items():
    test += f"result=0;assert(!nezha_{name}(&sc,27)&&property=={prop}&&bits==27&&length==4);"
    test += f"assert(nezha_{name}(&sc,-1)==-EINVAL);result=-EIO;assert(nezha_{name}(&sc,3)==-EIO);\n"
for name, prop in expect_bool.items():
    test += f"result=0;assert(!nezha_{name}(&sc,true)&&property=={prop}&&bits==1&&length==1);\n"
test += r"""
 result=0;bits=1;assert(!nezha_get_usb_input_swap(&sc,&b)&&b&&length==1&&property==0x10005);
 bits=2;b=false;assert(nezha_get_wls_input_swap(&sc,&b)==-EPROTO&&!b&&property==0x10006);
 bits=5;assert(!nezha_is_charge_done(&sc,&b)&&b&&length==4&&property==0x2001);
 bits=2;assert(!nezha_get_usbin_collapse_rt_sts(&sc,&v)&&v==1&&property==0x2000e);
 result=-EIO;assert(nezha_set_eu_model(&sc,true)==-EIO&&!sc.eu_model&&!sc.eu_requested);
 result=0;assert(!nezha_set_eu_model(&sc,true)&&sc.eu_model&&sc.eu_requested&&property==0x2029&&length==1);
 u8 one[]={1,0,0,0}, zero[]={0,0,0,0}, packed[]={0x34,0x12,0x12,0};
 nezha_glink_notify(0,one,4,&sc);assert(refreshed==1);
 nezha_glink_notify(4,one,4,&sc);nezha_glink_notify(6,one,4,&sc);nezha_glink_notify(6,zero,4,&sc);
 nezha_glink_notify(7,one,4,&sc);nezha_glink_notify(8,one,1,&sc);nezha_glink_notify(9,packed,4,&sc);
 nezha_glink_notify(2,NULL,0,&sc);nezha_glink_notify(5,NULL,0,&sc);
 nezha_glink_notify(4,one,3,&sc);nezha_glink_notify(11,one,4,&sc);nezha_glink_notify(12,one,4,&sc);
 memset(one,0,sizeof(one));assert(!count&&nr==8);drain();assert(count==9);
 assert(recorded[0].id==MCA_EVENT_LPD_STATUS_CHANGE&&recorded[0].val==1);
 assert(recorded[1].id==MCA_EVENT_CC_SHORT_VBUS&&recorded[1].val==1&&recorded[2].val==0);
 assert(recorded[3].id==MCA_EVENT_PPS_PTF&&recorded[3].type==STRATEGY_FUNC_TYPE_QUICK_CHARGE);
 assert(recorded[4].type==STRATEGY_FUNC_TYPE_BUCK_CHARGE&&recorded[5].type==MCA_EVENT_TYPE_CHARGE_TYPE);
 assert(recorded[5].id==MCA_EVENT_SINK_PWR_SUSPEND_CHANGE&&recorded[5].val==1);
 assert(recorded[6].id==MCA_EVENT_CP_REVERT_CHANGE&&recorded[6].val==0x121234);
 assert(recorded[7].id==MCA_EVENT_CHARGE_CAP_CHANGE&&recorded[8].id==MCA_EVENT_PLATE_SHOCK);
 sc.eu_model=false;nezha_glink_notify(8,one,1,&sc);assert(!nr);
 nezha_glink_notify(6,zero,4,&sc);sc.link_epoch++;drain();assert(count==9);
 nezha_glink_notify(4,zero,4,&sc);sc.stopping=true;drain();assert(count==9);
 puts("PASS Nezha wire properties, error propagation, ordered notices, regional gate and stale epochs");
}
"""
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / "test.c").write_text(pre + props + mock + events + test)
    subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-fsanitize=address,undefined",
                    str(path / "test.c"), "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)

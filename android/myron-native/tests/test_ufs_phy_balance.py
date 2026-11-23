#!/usr/bin/env python3
"""Run production UFS clock/PHY functions with mocked hardware under UBSan.

No device or kernel build is required. Pass --ufs-source to test an older
ufs-qcom.c against the current PHY core, e.g. the uncorrected r3 source.
The PHY core's actual power_count/PM/regulator code is included, not modeled.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]

def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define ENOTSUPP 524
#define UFS_QCOM_BER_MODE_MAX 2
#define MODE_MIN 0
#define PRE_CHANGE 0
#define POST_CHANGE 1
#define ufs_notify_change_status notify_status
#define dev_err(...) ((void)0)
#define dev_name(x) "test"
#define trace_ufs_qcom_setup_clocks(...) ((void)0)
#define ufs_qcom_log_str(...) ((void)0)
typedef uint32_t u32;
enum notify_status { NOTIFY_PRE = PRE_CHANGE, NOTIFY_POST = POST_CHANGE };
struct phy;
struct ops { int (*power_on)(struct phy *); int (*power_off)(struct phy *); };
struct phy { int mutex, power_count, dev; int *pwr; struct ops *ops; };
struct clk_info { bool enabled; int *clk; };
struct qos { int workq; };
struct ufs_hba { void *variant; int link, pwr_info; void *dev; };
struct ufs_qcom_host {
    struct phy *generic_phy;
    int phy_mutex;
    bool is_phy_pwr_on;
    struct clk_info *ref_clki, *core_unipro_clki;
    int therm_mitigation, fwork, boost_monitor_timer, clks_on;
    bool cpufreq_dis, dbg_en;
    struct qos *ufs_qos;
};
static int pm_refs, rail_refs, hw_on, off_calls, on_calls;
static int on_error, off_error, lane_error, pm_error, rail_error;
static int idle_start, idle_time[UFS_QCOM_BER_MODE_MAX];
static struct {int mem_bw, cfg_bw;} ufs_qcom_bw_table[1][1][1];
static void mutex_lock(int *m) { assert(!*m); *m = 1; }
static void mutex_unlock(int *m) { assert(*m); *m = 0; }
static int regulator_enable(int *p) { if (rail_error) return rail_error; ++rail_refs; return 0; }
static void regulator_disable(int *p) { --rail_refs; }
static int phy_pm_runtime_get_sync(struct phy *p) { if (pm_error) return pm_error; ++pm_refs; return 0; }
static void phy_pm_runtime_put_sync(struct phy *p) { --pm_refs; }
static void phy_pm_runtime_put(struct phy *p) { --pm_refs; }
static int hw_power_on(struct phy *p) { ++on_calls; if (on_error) return on_error; hw_on=1; return 0; }
static int hw_power_off(struct phy *p) { ++off_calls; if (off_error) return off_error; hw_on=0; return 0; }
static struct ufs_qcom_host *ufshcd_get_variant(struct ufs_hba *h) { return h->variant; }
static bool ufs_qcom_is_link_active(struct ufs_hba *h) { return h->link == 0; }
static bool ufs_qcom_is_link_hibern8(struct ufs_hba *h) { return h->link == 1; }
static bool ufs_qcom_is_link_off(struct ufs_hba *h) { return h->link == 2; }
static int ufs_qcom_enable_lane_clks(struct ufs_qcom_host *h) { return lane_error; }
static void ufs_qcom_disable_lane_clks(struct ufs_qcom_host *h) {}
static void ufs_qcom_phy_set_src_clk_h8_exit(struct phy *p) {}
static void ufs_qcom_phy_set_src_clk_h8_enter(struct phy *p) {}
static int clk_prepare_enable(int *c) { return 0; }
static void clk_disable_unprepare(int *c) {}
static void ufs_qcom_wait_for_cq_hp_update(struct ufs_hba *h) {}
static void ufs_qcom_dev_ref_clk_ctrl(struct ufs_qcom_host *h, bool on) {}
static void ufs_qcom_icc_update_bw(struct ufs_qcom_host *h) {}
static void ufs_qcom_icc_set_bw(struct ufs_qcom_host *h, int a, int b) {}
static int ufs_qcom_unvote_qos_all(struct ufs_hba *h) { return 0; }
static void cancel_dwork_unvote_cpufreq(struct ufs_hba *h) {}
static int ktime_get(void) { return 0; }
static int ktime_sub(int a, int b) { return a-b; }
static int ktime_to_ms(int t) { return t; }
static bool ufshcd_is_hs_mode(int *p) { return true; }
static int atomic_read(int *v) { return *v; }
static void atomic_set(int *v, int n) { *v=n; }
static int msecs_to_jiffies(int t) { return t; }
static void queue_delayed_work(int w, int *f, int delay) {}
'''
SUFFIX = r'''
static struct ops ops = {hw_power_on, hw_power_off};
static struct phy p;
static struct ufs_qcom_host host;
static struct ufs_hba hba;
static struct clk_info ref, core;
static int rail;
static void reset(int link, bool powered) {
    memset(&p,0,sizeof(p)); memset(&host,0,sizeof(host));
    memset(&hba,0,sizeof(hba)); memset(&ref,0,sizeof(ref)); memset(&core,0,sizeof(core));
    pm_refs=rail_refs=hw_on=on_calls=off_calls=0;
    on_error=off_error=lane_error=pm_error=rail_error=0;
    p.ops=&ops; p.pwr=&rail;
    host.generic_phy=&p;host.ref_clki=&ref;host.core_unipro_clki=&core;
    hba.variant=&host;hba.link=link;
    if (powered) { assert(ufs_qcom_phy_power_on(&hba)==0);ref.enabled=core.enabled=true; }
}
static void check(int powered) {
    assert(p.power_count==powered);assert(pm_refs==powered);assert(rail_refs==powered);
    assert(hw_on==powered);assert(host.is_phy_pwr_on==(bool)powered);
    assert(!p.mutex && !host.phy_mutex);
}
int main(void) {
    unsigned cycles=0;
    /* Clocks may be gated while the link is active: do not power down PHY. */
    reset(0,true);
    for (int i=0;i<512;i++) {
        assert(ufs_qcom_setup_clocks(&hba,false,PRE_CHANGE)==0);check(1);
        assert(ufs_qcom_setup_clocks(&hba,false,POST_CHANGE)==0);check(1);
        assert(ufs_qcom_setup_clocks(&hba,true,PRE_CHANGE)==0);check(1);
        assert(ufs_qcom_setup_clocks(&hba,true,POST_CHANGE)==0);check(1);++cycles;
    }
    assert(off_calls==0 && on_calls==1);
    /* Inactive links must balance exactly one on/off pair per cycle. */
    for (int link=1;link<=2;link++) {
        reset(link,true);
        for (int i=0;i<512;i++) {
            assert(ufs_qcom_setup_clocks(&hba,false,PRE_CHANGE)==0);check(0);
            assert(ufs_qcom_setup_clocks(&hba,false,PRE_CHANGE)==0);check(0);
            assert(ufs_qcom_setup_clocks(&hba,false,POST_CHANGE)==0);check(0);
            assert(ufs_qcom_setup_clocks(&hba,true,PRE_CHANGE)==0);check(0);
            assert(ufs_qcom_setup_clocks(&hba,true,POST_CHANGE)==0);check(1);
            assert(ufs_qcom_setup_clocks(&hba,true,POST_CHANGE)==0);check(1);++cycles;
        }
        assert(off_calls==512 && on_calls==513);
        off_error=-EIO;
        assert(ufs_qcom_setup_clocks(&hba,false,PRE_CHANGE)==-EIO);check(1);
        off_error=0;assert(ufs_qcom_setup_clocks(&hba,false,PRE_CHANGE)==0);check(0);
        for (int fail=0;fail<3;fail++) {
            on_error=fail==0?-EIO:0;pm_error=fail==1?-EIO:0;rail_error=fail==2?-EIO:0;
            assert(ufs_qcom_setup_clocks(&hba,true,POST_CHANGE)==-EIO);check(0);
        }
        on_error=pm_error=rail_error=0;
        assert(ufs_qcom_setup_clocks(&hba,true,POST_CHANGE)==0);check(1);
    }
    reset(1,false);lane_error=-EIO;
    assert(ufs_qcom_setup_clocks(&hba,true,PRE_CHANGE)==-EIO);check(0);
    hba.variant=NULL;
    assert(ufs_qcom_setup_clocks(&hba,false,PRE_CHANGE)==0);
    assert(ufs_qcom_setup_clocks(&hba,true,POST_CHANGE)==0);
    printf("PASS: %u power cycles; active-link retention, inactive-link balance, repeated requests, hardware/PM/regulator failures and pre-init calls\n",cycles);
    return 0;
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ufs-source',type=Path,default=ROOT/'drivers/ufs/host/ufs-qcom.c')
    ap.add_argument('--cc',default='cc')
    args=ap.parse_args()
    ufs=args.ufs_source.read_text();phy=(ROOT/'drivers/phy/phy-core.c').read_text()
    funcs=[function(phy,'int phy_power_on('),function(phy,'int phy_power_off(')]
    funcs += [function(ufs,'static int '+name+'(') for name in ['ufs_qcom_phy_power_on','ufs_qcom_phy_power_off','ufs_qcom_setup_clocks']]
    with tempfile.TemporaryDirectory(prefix='myron-ufs-') as tmp:
        c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(PREFIX+'\n'.join(funcs)+SUFFIX)
        subprocess.run([args.cc,'-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=undefined','-fno-sanitize-recover=all',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)

if __name__=='__main__':main()

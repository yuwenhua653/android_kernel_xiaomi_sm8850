#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Host regression of the actual Nezha haptic DT parsing and F0 fallback."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'drivers/input/misc/qcom-hv-haptics.c').read_text()
a=s.index('static void haptics_nezha_calibration_fallback');b=s.index('\nstatic int haptics_get_closeloop_lra_period',a);fallback=s[a:b]
a=s.index('\t/* Preserve generic behavior unless the Nezha profile is selected. */');b=s.index('\tconfig->fifo_empty_thresh',a);parse=s[a:b]
pre=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
#define USEC_PER_SEC 1000000
#define MAX_VMAX_MV 11000
static int nezha=1;
#define IS_ENABLED(x) (nezha)
struct haptics_hw_config {
 u32 vmax_mv, custom_vmax_mv, f0_vmax_mv, f0_min_hz, f0_max_hz, f0_default_hz, f0_cal_count;
 u32 cl_t_lra_us, rc_clk_cal_count;
};
static const char *names[]={"qcom,custom_vmax_mv","qcom,f0-vmax-mv","qcom,lra-f0-min","qcom,lra-f0-max","qcom,lra-f0-default","qcom,lra-f0-cal-count"};
static u32 values[6];static unsigned int present;
static int of_property_read_u32(void *node,const char *name,u32 *value) {
 for(int i=0;i<6;i++) if(!strcmp(name,names[i]) && (present&(1<<i))){*value=values[i];return 0;}
 return -EINVAL;
}
static void *of_find_property(void *node,const char *name,void *len) {
 u32 v;return of_property_read_u32(node,name,&v)?NULL:(void *)1;
}
'''
test=r'''
static void stock(void) {
 u32 v[]={8500,2100,160,180,170,570};memcpy(values,v,sizeof(v));present=63;
}
int main(void) {
 struct haptics_hw_config c={.vmax_mv=2000};
 stock();assert(parse(&c)==0 && c.custom_vmax_mv==8500 && c.f0_vmax_mv==2100);
 c.cl_t_lra_us=5000;c.rc_clk_cal_count=1;haptics_nezha_calibration_fallback(&c);
 assert(c.cl_t_lra_us==1000000/170 && c.rc_clk_cal_count==570);
 c.cl_t_lra_us=6000;c.rc_clk_cal_count=123;haptics_nezha_calibration_fallback(&c);
 assert(c.cl_t_lra_us==6000 && c.rc_clk_cal_count==123);
 c.cl_t_lra_us=0;haptics_nezha_calibration_fallback(&c);assert(!c.cl_t_lra_us);
 stock();values[0]=11000;assert(parse(&c)==-EINVAL);
 stock();values[1]=0;assert(parse(&c)==-EINVAL);
 stock();values[4]=0;assert(parse(&c)==-EINVAL);
 stock();values[4]=190;assert(parse(&c)==-EINVAL);
 stock();values[5]=1024;assert(parse(&c)==-EINVAL);
 stock();present&=~(1<<2);assert(parse(&c)==-EINVAL);
 stock();nezha=0;assert(parse(&c)==0 && c.custom_vmax_mv==2000 && c.f0_vmax_mv==2000);
 puts("PASS: stock 8500/2100mV, F0 fallback/in-range/zero, malformed DT bounds and non-Nezha defaults");
}
'''
code=pre+fallback+'\nstatic int parse(struct haptics_hw_config *config) {\nvoid *node=NULL; int rc=0;\n'+parse+'\nfree_pbs: return rc;\n}\n'+test
with tempfile.TemporaryDirectory(prefix='nezha-haptics-') as t:
 c=Path(t)/'test.c';exe=Path(t)/'test';c.write_text(code)
 subprocess.run([os.environ.get('CC','cc'),'-std=c11','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)

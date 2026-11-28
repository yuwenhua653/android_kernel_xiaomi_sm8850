#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual thermal parsers with explicit format and exact DT values.
Host OF stubs and ASan/UBSan; not a driver probe or hardware test.
Usage: python3 tools/test-nezha-thermal-format.py PATH_TO_DT/qcom/nezha-charger-common.dtsi
"""
from pathlib import Path
import os,re,subprocess,sys,tempfile
root=Path(__file__).resolve().parents[1]
mca=root/'drivers/power/supply/mca/mca_strategy/strategy_charger'
h=(mca/'inc/mca_charger_thermal.h').read_text();h=h[h.index('#define MAX_THERMAL_LEVEL'):h.index('struct mca_thermal_ctrl_info')]
s=(mca/'mca_charger_thermal.c').read_text();s=s[s.index('static int mca_wireless_charger_thermal_parse_data('):s.index('static int mca_charger_thermal_parse_dt(')]
path=Path(sys.argv[1]) if len(sys.argv)>1 else root.parent/'sm8850-devicetrees/qcom/nezha-charger-common.dtsi'
dts=re.sub(r'/\*.*?\*/','',path.read_text(),flags=re.S)
def prop(name):
 b=re.search(r'\b'+name+r'\s*=\s*(.*?);',dts,re.S)[1]
 return [int(v,0) for v in re.findall(r'0x[0-9a-fA-F]+|\b\d+\b',b)]
wired=prop('wired_thermal');wireless=prop('wireless_thermal')
assert len(wired)==150 and len(wireless)==165
assert 'xiaomi,wireless-thermal-columns = <11>;' in dts
pre=r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define mca_log_err(...) ((void)0)
#define mca_log_debug(...) ((void)0)
struct device_node {const int *vals;int len;bool format_present;u32 cols;int format_count,format_error,read_error;};
static void *of_find_property(struct device_node*n,const char*p,void*len){return n&&n->format_present?n:NULL;}
static int of_property_count_u32_elems(struct device_node*n,const char*p){return !strcmp(p,"xiaomi,wireless-thermal-columns") ? n->format_count : n->len;}
static int of_property_read_u32(struct device_node*n,const char*p,u32*out){if(n->format_error)return n->format_error;*out=n->cols;return 0;}
static int mca_parse_dts_u32_count(struct device_node*n,const char*p,u32 rows,u32 cols){return !n||n->len<=0||n->len%cols||n->len>rows*cols?-EINVAL:n->len;}
static int mca_parse_dts_u32_array(struct device_node*n,const char*p,int*out,int len){if(n->read_error)return n->read_error;assert(len==n->len);memcpy(out,n->vals,len*sizeof(int));return 0;}
'''
arrays='static const int wired[]={'+','.join(map(str,wired))+'};\nstatic const int wireless[]={'+','.join(map(str,wireless))+'};\n'
test=r'''
int main(void){
 struct mca_wireless_thermal_data data[MAX_THERMAL_LEVEL],saved[MAX_THERMAL_LEVEL];
 struct mca_thermal_data wd[MAX_THERMAL_LEVEL];int level;
 struct device_node n={.vals=wired,.len=150};
 assert(!mca_charger_thermal_parse_data("wired_thermal",&n,wd,&level)&&level==15);
 assert(wd[0].buck_5v_in==1900&&wd[14].div4_mullti_curr==500);
 n=(struct device_node){.vals=wireless,.len=165,.format_present=true,.cols=11,.format_count=1};
 assert(!mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)&&level==15);
 assert(data[0].wireless_xiaomi_car==4400&&data[14].wireless_xiaomi_car==400);
 /* Ambiguous 110 cells MUST keep the declared/default row stride. */
 int ambiguous[110];for(int i=0;i<110;i++)ambiguous[i]=100+i;
 n=(struct device_node){.vals=ambiguous,.len=110};
 assert(!mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)&&level==11);
 assert(data[1].wireless_bpp_in==110&&data[10].wireless_authen_magnet_30w==209&&data[0].wireless_xiaomi_car==0);
 n.format_present=true;n.cols=11;n.format_count=1;
 assert(!mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)&&level==10);
 assert(data[1].wireless_bpp_in==111&&data[0].wireless_xiaomi_car==110);
 n.cols=10;assert(!mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)&&level==11);
 /* Reject malformed formats; never silently fall back to another layout. */
 memset(data,0x55,sizeof(data));memcpy(saved,data,sizeof(data));level=77;
 for(int col=0;col<=12;col++){if(col==10||col==11)continue;n.cols=col;assert(mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)==-EINVAL);}
 n.cols=11;n.format_count=2;assert(mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)==-EINVAL);
 n.format_count=1;n.format_error=-EIO;assert(mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)==-EINVAL);n.format_error=0;
 n.cols=10;n.read_error=-EIO;assert(mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)==-EIO);n.read_error=0;
 ambiguous[0]=-1;assert(mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)==-EINVAL);ambiguous[0]=100;
 for(int len=0;len<220;len++){if(len==110)continue;n.len=len;if(len<=0||len%10||len>MAX_THERMAL_LEVEL*10)assert(mca_wireless_charger_thermal_parse_data("wireless_thermal",&n,data,&level)==-EINVAL);}
 assert(!memcmp(saved,data,sizeof(data))&&level==77);
 assert(mca_wireless_charger_thermal_parse_data("wireless_thermal",NULL,data,&level)==-EINVAL);
 int flip[16],saved_flip[16],vals[17];for(int i=0;i<17;i++)vals[i]=1000-i;
 n=(struct device_node){.vals=vals,.len=16};
 assert(!mca_charger_thermal_flip_parse_data("wired_flip_thermal",&n,flip,&level)&&level==15&&flip[15]==985);
 memcpy(saved_flip,flip,sizeof(flip));level=99;
 for(int len=-1;len<=17;len++){if(len>0&&len<=16)continue;n.len=len;assert(mca_charger_thermal_flip_parse_data("wired_flip_thermal",&n,flip,&level)==-EINVAL);}
 n.len=16;n.read_error=-EIO;assert(mca_charger_thermal_flip_parse_data("wired_flip_thermal",&n,flip,&level)==-EIO);n.read_error=0;
 vals[8]=-1;assert(mca_charger_thermal_flip_parse_data("wired_flip_thermal",&n,flip,&level)==-EINVAL);
 assert(!memcmp(saved_flip,flip,sizeof(flip))&&level==99);vals[8]=992;n.len=1;
 assert(!mca_charger_thermal_flip_parse_data("wired_flip_thermal",&n,flip,&level)&&level==0);
 puts("PASS: DT tables, explicit/default 10/11 columns, ambiguous 110-cell regression, malformed formats, read failures, flip table bounds and unchanged error outputs");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(pre+h+s+arrays+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

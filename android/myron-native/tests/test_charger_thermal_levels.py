#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise production MCA sysfs/cooling level boundaries and resulting votes."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
def function(text, name):
    match = re.search(r'static\s+(?:void|int|ssize_t)\s+' + name +
                      r'\s*\([^;{}]*\)\s*\{', text)
    if not match:
        raise ValueError('Missing function: ' + name)
    start = match.end() - 1
    depth, end = 1, start + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root', type=Path, required=True)
p.add_argument('--source', type=Path)
p.add_argument('--group', choices=['all', 'sysfs', 'cooling', 'consumer'], default='all')
a = p.parse_args()
base = a.kernel_root / 'drivers/power/supply/mca/mca_strategy/strategy_charger'
s = (a.source or base / 'mca_charger_thermal.c').read_text()
header = (base / 'inc/mca_charger_thermal.h').read_text()
names = ['mca_wireless_charger_thermal_handle_limit',
         'mca_charger_thermal_flip_handle_limit',
         'mca_wireless_charger_thermal_flip_handle_limit',
         'mca_charger_thermal_handle_limit',
         'mca_charger_thermal_get_max_level',
         'mca_charger_thermal_get_cur_level',
         'mca_charger_thermal_set_cur_level',
         'mca_charger_thermal_sysfs_store']
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#define min(a,b) ((a)<(b)?(a):(b))
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define STRATEGY_FUNC_TYPE_QUICK_WIRELESS 1
#define STRATEGY_FUNC_TYPE_BASIC_WIRELESS 2
#define MCA_EVENT_WIRELESS_THERMAL_PHONE_FLAG 3
#define XM_CHARGER_TYPE_HVDCP3_B 10
#define XM_CHARGER_TYPE_HVDCP3P5 11
#define XM_CHARGER_TYPE_PPS 12
#define XM_CHARGER_TYPE_PD_VERIFY 13
#define MCA_CHARGER_THERMAL_SYSFS_ATTRS_SIZE 8
#define FG_IC_MASTER 0
typedef uint64_t u64;
struct timespec64 { long long tv_sec; };
struct delayed_work { int unused; };
struct device { void *data; };
struct thermal_cooling_device { void *devdata; };
struct device_attribute { struct { const char *name; } attr; };
struct mca_sysfs_attr_info { int sysfs_attr_name; };
struct mca_votable { int value; bool enabled; };
static struct mca_sysfs_attr_info attribute;
static struct mca_sysfs_attr_info mca_charger_thermal_sysfs_field_tbl[8];
static int votes,events;
static void *dev_get_drvdata(struct device *d) { return d->data; }
static void ktime_get_boottime_ts64(struct timespec64 *ts) { ts->tv_sec=100; }
static int mca_qcom_smem_is_zero_speed(void) { return 0; }
static int mca_strategy_func_process(int s,int e,int v) { events++;return 0; }
static int mca_vote(struct mca_votable *v,const char *name,bool en,int val) {
 assert(v); v->value=val;v->enabled=en;votes++;return 0;
}
static void mca_rerun_election(struct mca_votable *v) { assert(v); }
static struct mca_sysfs_attr_info *mca_sysfs_lookup_attr(const char *n,void *t,int size) { return &attribute; }
static void platform_fg_ops_get_batt_cell_info(int ic,const char **name) { *name="test"; }
/* Model Linux decimal kstrtoint: bounded conversion, at most one trailing LF. */
static int kstrtoint(const char *s,unsigned base,int *v) {
 char *end;long n;
 if(!*s || *s==' ' || *s=='\t' || *s=='\n') return -EINVAL;
 errno=0;n=strtol(s,&end,base);
 if(errno==ERANGE || n>INT_MAX || n<INT_MIN) return -ERANGE;
 if(end==s) return -EINVAL;
 if(*end=='\n')end++;
 if(*end) return -EINVAL;
 *v=n;return 0;
}
''' + header + r'''
static struct mca_thermal_info info;
static struct mca_thermal_info *g_wlscharger_thermal_info=&info;
static void mca_charger_thermal_update_chg_curr(struct mca_thermal_info *p) { }
''' + '\n'.join(function(s, n) for n in names) + r'''
static struct mca_votable wired[THERMAL_MODE_MAX],wireless[THERMAL_MODE_WIRELESS_MAX],flip;
static struct device dev={&info};
static struct device_attribute attr={{"test"}};
static struct thermal_cooling_device cdev={&info};
static int cases;
static void reset(int max) {
 memset(&info,0,sizeof(info));memset(wired,0,sizeof(wired));memset(wireless,0,sizeof(wireless));
 info.dev=&dev;info.batt_cell_name="test";info.online=info.wls_online=1;
 info.wired_ctrl_info.voter_ok=info.wireless_ctrl_info.voter_ok=1;
 info.wired_ctrl_info.max_level=info.wireless_ctrl_info.max_level=max;
 info.flip_voter=info.wls_flip_voter=&flip;
 for(int i=0;i<THERMAL_MODE_MAX;i++)info.wired_voter[i]=&wired[i];
 for(int i=0;i<THERMAL_MODE_WIRELESS_MAX;i++)info.wireless_voter[i]=&wireless[i];
 for(int i=0;i<MAX_THERMAL_LEVEL;i++) {
  int *w=(int *)&info.wired_thermal_data[i],*q=(int *)&info.wireless_thermal_data[i];
  for(int j=0;j<THERMAL_MODE_MAX;j++)w[j]=4000-i*100-j;
  for(int j=0;j<THERMAL_MODE_WIRELESS_MAX;j++)q[j]=3000-i*100-j;
  info.wired_flip_thermal_data[i]=2000-i*100;
  info.wireless_flip_thermal_data[i]=1000-i*50;
 }
 votes=events=0;
}
static void test_sysfs(void) {
 const int attrs[]={MCA_THERMAL_WIRED_CTRL_LIMIT,MCA_THERMAL_WIRELESS_CTRL_LIMIT,MCA_THERMAL_WIRELESS_QUICK_CHG_CTRL_LIMIT};
 const char *bad[]={"-1","-2147483648","2147483647","2147483648","4294967296","1garbage","","1\n2"};
 for(int max=0;max<=MAX_THERMAL_LEVEL;max++)for(unsigned a=0;a<3;a++) {
  reset(max);attribute.sysfs_attr_name=attrs[a];
  int *level=a==0?&info.wired_ctrl_info.limit_level:a==1?&info.wireless_ctrl_info.limit_level:&info.wireless_ctrl_info.quickchg_limit_level;
  info.smartchg_data.wls_super_sts=(a==2);
  *level=max;struct mca_thermal_info before=info;
  for(unsigned j=0;j<sizeof(bad)/sizeof(bad[0]);j++) {
   assert(mca_charger_thermal_sysfs_store(&dev,&attr,bad[j],strlen(bad[j]))<0);
   assert(!memcmp(&before,&info,sizeof(info)) && votes==0 && events==0);cases++;
  }
  char buf[32];snprintf(buf,sizeof(buf),"%d\n",max+1);
  assert(mca_charger_thermal_sysfs_store(&dev,&attr,buf,strlen(buf))==-EINVAL);
  assert(*level==max && votes==0 && events==0);cases++;
  for(int v=0;v<=max;v++) {
   snprintf(buf,sizeof(buf),"%d\n",v);size_t len=strlen(buf);
   assert(mca_charger_thermal_sysfs_store(&dev,&attr,buf,len)==(ssize_t)len);
   assert(*level==v);
   if(v)assert((a==0?wired[0].value:wireless[0].value)==(a==0?4000:3000)-(v-1)*100);
   cases++;
  }
 }
}
static void test_cooling(void) {
 for(int max=0;max<=MAX_THERMAL_LEVEL;max++)for(int mode=0;mode<2;mode++) {
  reset(max);info.support_base_flip=mode;unsigned long limit,cur;
  assert(mca_charger_thermal_get_max_level(&cdev,&limit)==0);
  assert(limit==(unsigned long)(mode && max==16?15:max));cases++;
  for(unsigned long v=0;v<=limit;v++) {
   assert(mca_charger_thermal_set_cur_level(&cdev,v)==0);
   assert(mca_charger_thermal_get_cur_level(&cdev,&cur)==0 && cur==v);
   cases++;
  }
  const unsigned long bad[]={limit+1,ULONG_MAX,(unsigned long)INT_MAX+1};
  for(unsigned i=0;i<3;i++) {
   votes=0;int old=info.wired_ctrl_info.limit_level;
   assert(mca_charger_thermal_set_cur_level(&cdev,bad[i])==-EINVAL);
   assert(info.wired_ctrl_info.limit_level==old && votes==0);cases++;
  }
 }
}
static void test_consumer_bounds(void) {
 const int bad[]={-1,INT_MIN,17,INT_MAX};
 for(unsigned b=0;b<4;b++)for(int quick=0;quick<2;quick++) {
  reset(16);info.smartchg_data.wls_super_sts=quick;
  if(quick) info.wireless_ctrl_info.quickchg_limit_level=bad[b];
  else info.wireless_ctrl_info.limit_level=bad[b];
  mca_wireless_charger_thermal_handle_limit(&info.wireless_ctrl_info,info.wireless_thermal_data,info.wireless_voter);
  assert(!votes && !events);cases++;
  info.wired_ctrl_info.limit_level=bad[b];
  mca_charger_thermal_handle_limit(&info.wired_ctrl_info,info.wired_thermal_data,info.wired_voter);
  assert(!votes);cases++;
  info.wireless_ctrl_info.limit_level=bad[b];
  mca_charger_thermal_flip_handle_limit(&info.wired_ctrl_info,info.wired_flip_thermal_data,&flip);
  mca_wireless_charger_thermal_flip_handle_limit(&info.wireless_ctrl_info,info.wireless_flip_thermal_data,&flip);
  assert(!votes);cases++;
 }
 reset(16);info.wired_ctrl_info.limit_level=info.wireless_ctrl_info.limit_level=16;
 mca_charger_thermal_flip_handle_limit(&info.wired_ctrl_info,info.wired_flip_thermal_data,&flip);
 mca_wireless_charger_thermal_flip_handle_limit(&info.wireless_ctrl_info,info.wireless_flip_thermal_data,&flip);
 assert(!votes);cases++;
 /* Valid table limits continue to take the lower configured current. */
 reset(16);info.wireless_ctrl_info.limit_level=16;info.wireless_ctrl_info.chg_curr=700;
 mca_wireless_charger_thermal_handle_limit(&info.wireless_ctrl_info,info.wireless_thermal_data,info.wireless_voter);
 for(int i=0;i<THERMAL_MODE_WIRELESS_MAX;i++)assert(wireless[i].enabled && wireless[i].value==700);
 cases++;
}
int main(int argc, char **argv) {
 assert(argc==2);
 if(!strcmp(argv[1],"all") || !strcmp(argv[1],"sysfs")) test_sysfs();
 if(!strcmp(argv[1],"all") || !strcmp(argv[1],"cooling")) test_cooling();
 if(!strcmp(argv[1],"all") || !strcmp(argv[1],"consumer")) test_consumer_bounds();
 printf("PASS: %d MCA thermal range/rejected-write/cooling/table-vote cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'test.c'
    exe = Path(tmp) / 'test'
    c.write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-Wno-unused-function',
                    '-Wno-sign-compare', '-fsanitize=undefined',
                    '-fno-sanitize-recover=undefined', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe), a.group], check=True)

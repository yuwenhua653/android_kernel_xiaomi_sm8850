#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Production parser: actual Myron DT tables, allocation/read failures, ownership."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root',required=True,type=Path)
p.add_argument('--source',type=Path)
a=p.parse_args()
base=a.kernel_root/'drivers/power/supply/mca/mca_strategy/strategy_wireless'
s=(a.source or base/'mca_quick_wireless.c').read_text()
h=(base/'inc/mca_quick_wireless.h').read_text()
fixture=json.loads((Path(__file__).parent/'fixtures/myron-wireless-tables.json').read_text())
code=r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define GFP_KERNEL 0
#define FG_IC_MASTER 0
#define FG_IC_SLAVE 1
#define mca_log_debug(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
'''
for n in ['mca_wireless_quick_charge_temp_para_ele','mca_wireless_quick_charge_volt_para_ele','mca_wireless_quick_charge_battery_type']:
    code+=re.search(r'enum '+n+r'\s*\{.*?\};',h,re.S)[0]+'\n'
for n in ['mca_wireless_quick_charge_volt_para','mca_wireless_quick_charge_volt_para_info','mca_wireless_quick_charge_temp_para','mca_wireless_quick_charge_temp_para_info','mca_wireless_quick_charge_batt_para_info']:
    code+=re.search(r'struct '+n+r'\s*\{.*?\};',h,re.S)[0]+'\n'
for n in ['TEMP_PARA_MAX_GROUP','VOLT_PARA_MAX_GROUP']:
    code+=re.search(r'^#define '+n+r' .*$',h,re.M)[0]+'\n'
for n in ['BATT_PARA_CC_NAME_LEN','BATT_PARA_CC_TEMP_23','BATT_PARA_CC_TEMP_30','BATT_PARA_CC_TEMP_40']:
    code+=re.search(r'^#define '+n+r' .*$',s,re.M)[0]+'\n'
code+=r'''
struct prop { const char *name; int count; const char **strings; int *ints; };
struct device_node { struct prop *props; int count; };
struct mca_wireless_quick_charge_info {
 struct mca_wireless_quick_charge_batt_para_info batt_para[2],base_flip_para[2];
 int support_base_flip,batt_para_cc_thr[2];
};
static int alloc_calls,read_calls,fail_alloc,fail_read,live,cases;
static void *allocations[256];
static void *kcalloc(size_t n,size_t z,int flag) {
 (void)flag;alloc_calls++;if(alloc_calls==fail_alloc)return NULL;
 void *p=calloc(n,z);assert(p);int i;for(i=0;i<256 && allocations[i];i++);assert(i<256);
 allocations[i]=p;live++;return p;
}
static void kfree(void *p) {
 if(!p)return;int i;for(i=0;i<256 && allocations[i]!=p;i++);assert(i<256);
 allocations[i]=NULL;live--;free(p);
}
static struct prop *lookup(struct device_node *n,const char *name) {
 for(int i=0;i<n->count;i++)if(!strcmp(n->props[i].name,name))return &n->props[i];return NULL;
}
static int mca_parse_dts_count_strings(struct device_node *n,const char *name,int rows,int cols) {
 struct prop *p=lookup(n,name);
 if(!p || !p->strings || p->count<=0 || p->count%cols || p->count>rows*cols)return -EINVAL;
 return p->count;
}
static int mca_parse_dts_string_index(struct device_node *n,const char *name,int i,const char **v) {
 struct prop *p=lookup(n,name);read_calls++;if(read_calls==fail_read)return -EIO;
 if(!p || !p->strings || i<0 || i>=p->count)return -EINVAL;*v=p->strings[i];return 0;
}
static int of_property_count_u32_elems(struct device_node *n,const char *name) {
 struct prop *p=lookup(n,name);return p && p->ints?p->count:-EINVAL;
}
static int mca_parse_dts_u32_array(struct device_node *n,const char *name,int *v,int len) {
 struct prop *p=lookup(n,name);read_calls++;if(read_calls==fail_read)return -EIO;
 if(!p || !p->ints || p->count<len)return -EINVAL;assert(v);memcpy(v,p->ints,len*sizeof(*v));return 0;
}
static int kstrtoint(const char *s,int base,int *v) {
 char *end;errno=0;long l=strtol(s,&end,base);if(!*s || *end)return -EINVAL;
 if(errno || l<INT_MIN || l>INT_MAX)return -ERANGE;*v=l;return 0;
}
static struct device_node *of_find_node_by_name(struct device_node *n,const char *name) {
 (void)n;(void)name;return NULL;
}
static void of_node_put(struct device_node *n) { assert(!n); }
'''
for j,(node,props) in enumerate(fixture['nodes'].items()):
    entries=[]
    for i,(name,values) in enumerate(props.items()):
        kind='strings' if values and isinstance(values[0],str) else 'ints'
        typ='const char *' if kind=='strings' else 'int '
        code+=f'static {typ}p{j}_{i}[]={{'+','.join(json.dumps(v) for v in values)+'};\n'
        entries.append('{'+json.dumps(name)+f',{len(values)},'+(f'p{j}_{i},NULL' if kind=='strings' else f'NULL,p{j}_{i}')+'}')
    code+=f'static struct prop props{j}[]={{'+','.join(entries)+'};\n'
    code+=f'static struct device_node node{j}={{props{j},sizeof(props{j})/sizeof(props{j}[0])}};\n'
for n in ['mca_wireless_quick_charge_parse_stage_para','mca_wireless_quick_charge_parse_volt_para','mca_wireless_quick_charge_free_temp_para','mca_wireless_quick_charge_parse_temp_para']:
    code+=function(s,n)+'\n'
code+=r'''
static void reset(void) { alloc_calls=read_calls=fail_alloc=fail_read=0; }
static void check_table(struct device_node *n,const char *name) {
 struct mca_wireless_quick_charge_info info={0};reset();
 assert(!mca_wireless_quick_charge_parse_temp_para(n,0,name,&info,0));
 assert(info.batt_para[0].temp_para_size==7 && live>0);
 int na=alloc_calls,nr=read_calls;
 struct mca_wireless_quick_charge_batt_para_info original=info.batt_para[0];int initial_live=live;
 /* Every failure must leave an already published table and its data intact. */
 for(int i=1;i<=na;i++){
  reset();fail_alloc=i;
  assert(mca_wireless_quick_charge_parse_temp_para(n,0,name,&info,0)==-ENOMEM);
  assert(info.batt_para[0].temp_info==original.temp_info && live==initial_live);cases++;
 }
 for(int i=1;i<=nr;i++){
  reset();fail_read=i;
  assert(mca_wireless_quick_charge_parse_temp_para(n,0,name,&info,0)==-EIO);
  assert(info.batt_para[0].temp_info==original.temp_info && live==initial_live);cases++;
 }
 reset();struct prop *p=lookup(n,name);const char *saved=p->strings[4];p->strings[4]="garbage";
 assert(mca_wireless_quick_charge_parse_temp_para(n,0,name,&info,0)<0);
 assert(live==initial_live && info.batt_para[0].temp_info==original.temp_info);p->strings[4]=saved;cases++;
 /* An old nine-column table is not silently reinterpreted as eleven columns. */
 int count=p->count;p->count=63;
 assert(mca_wireless_quick_charge_parse_temp_para(n,0,name,&info,0)==-EINVAL && live==initial_live);
 p->count=count;cases++;
 for(int role=-1;role<=2;role+=3){
  assert(mca_wireless_quick_charge_parse_temp_para(n,role,name,&info,0)==-EINVAL);cases++;
 }
 for(int mode=-1;mode<=3;mode+=4){
  assert(mca_wireless_quick_charge_parse_temp_para(n,0,name,&info,mode)==-EINVAL);cases++;
 }
 mca_wireless_quick_charge_free_temp_para(&info.batt_para[0]);assert(!live);cases++;
}
int main(void) {
 check_table(&node0,"wls_batt_para_atl");check_table(&node0,"wls_batt_para_cos");
 check_table(&node1,"wls_batt_para_atl");
 /* Stage tables are optional only when explicitly named "null". */
 struct mca_wireless_quick_charge_volt_para_info v={0};reset();
 assert(!mca_wireless_quick_charge_parse_stage_para(&node0,"null",&v));cases++;
 assert(mca_wireless_quick_charge_parse_stage_para(&node0,"missing",&v)==-EINVAL);cases++;
 assert(!mca_wireless_quick_charge_parse_volt_para(&node0,"ffc_para_atl_18_23",&v));
 struct prop *p=lookup(&node0,"ffc_stage_atl_18_23");int count=p->count;
 p->count=count-1;assert(mca_wireless_quick_charge_parse_stage_para(&node0,p->name,&v)==-EINVAL);cases++;
 p->count=count+1;assert(mca_wireless_quick_charge_parse_stage_para(&node0,p->name,&v)==-EINVAL);cases++;
 p->count=count;reset();fail_alloc=1;
 assert(mca_wireless_quick_charge_parse_stage_para(&node0,p->name,&v)==-ENOMEM && !v.stage_para);cases++;
 reset();fail_read=1;
 assert(mca_wireless_quick_charge_parse_stage_para(&node0,p->name,&v)==-EIO && !v.stage_para);cases++;
 kfree(v.volt_para);assert(!live);
 printf("PASS: %d wireless table parsing/ownership cases with three committed Myron profiles\n",cases);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src,exe=Path(tmp)/'test.c',Path(tmp)/'test'
    src.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=undefined',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

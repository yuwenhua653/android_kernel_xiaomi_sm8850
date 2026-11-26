#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test actual JEITA parser under ASan/UBSan; optional official charger DTS.
Device-managed allocations are modelled and explicitly freed on probe failure.
This does not test temperature sensors, voters, or charging on hardware.
"""
from pathlib import Path
import json, os, re, subprocess, sys, tempfile
root = Path(__file__).resolve().parents[1]
s = (root/'drivers/power/supply/mca/mca_strategy/strategy_charger/mca_buckchg_jeita.c').read_text()
body = s[s.index('static bool mca_jeita_table_valid'):s.index('static int mca_buckchg_jeita_parse_dt')]
h = (root/'drivers/power/supply/mca/mca_strategy/strategy_charger/inc/mca_buckchg_jeita.h').read_text()
h = h[h.index('#define JEITA_VOLT_DATA_MAX_GROUP'):h.index('struct mca_buckchg_jeita_proc_data')]
pre = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#define GFP_KERNEL 0
#define mca_log_err(...) do {} while (0)
#define mca_log_info(...) do {} while (0)
#define mca_log_debug(...) do {} while (0)
struct device { int unused; };
struct prop { const char *name; int count; const char *values[128]; };
struct device_node { struct prop p[32]; int count; };
static int allocation, fail_alloc, read_count, fail_read, nalloc;
static void *allocated[128];
static void *devm_kcalloc(struct device *dev, size_t n, size_t z, int flags) {
 if (++allocation == fail_alloc) return NULL;
 void *p = calloc(n,z); assert(p); assert(nalloc<128); allocated[nalloc++]=p; return p;
}
static void release(void) { while(nalloc) free(allocated[--nalloc]); allocation=read_count=0; }
static struct prop *of_find_property(struct device_node *node,const char *name,void *len) {
 for (int i=0;i<node->count;i++) if (!strcmp(node->p[i].name,name)) return &node->p[i];
 return NULL;
}
static int mca_parse_dts_count_strings(struct device_node *node,const char *name,int rows,int cols) {
 struct prop *p=of_find_property(node,name,NULL); return p?p->count:-EINVAL;
}
static int mca_parse_dts_string_index(struct device_node *node,const char *name,int i,const char **v) {
 struct prop *p=of_find_property(node,name,NULL);
 if (++read_count==fail_read || !p || i<0 || i>=p->count) return -EINVAL;
 *v=p->values[i];return 0;
}
static int kstrtoint(const char *s,unsigned base,int *v) {
 char *end;errno=0;long n=strtol(s,&end,base);
 if(errno||n<INT_MIN||n>INT_MAX||end==s||*end) return -EINVAL;
 *v=n;return 0;
}
'''
fixtures = [dict(jeita_para=['-65535','18','0','2','0','4500','66','null','18','65535','1','0','2000','4500','328','volt'],volt=['4000','2000','4500','1000'],jeita_para_ffc=['18','65535','0','1','2000','4540','722','null'])]
if len(sys.argv)>1:
    text=Path(sys.argv[1]).read_text()
    for block in re.findall(r'&mca_buckchg_jeita(?:_\w+)?\s*\{(.*?)\};',text,re.S):
        props={}
        for name,val in re.findall(r'(\w+)\s*=\s*((?:"[^"]*"[\s,]*)+);',block):
            props[name]=re.findall(r'"([^"]*)"',val)
        if 'jeita_para' in props:
            names={'jeita_para','jeita_para_ffc'}
            for key in tuple(names): names.update(props.get(key,[])[7::8])
            fixtures.append({k:v for k,v in props.items() if k in names})
    assert len(fixtures)>1, 'no JEITA tables in source'
arrays=[]
for i, props in enumerate(fixtures):
    entries=[]
    for name,values in props.items():
        assert len(values)<=128
        entries.append('{'+json.dumps(name)+','+str(len(values))+',{'+','.join(map(json.dumps,values))+'}}')
    arrays.append('static struct device_node node'+str(i)+'={.count='+str(len(entries))+',.p={'+','.join(entries)+'}};')
tests=r'''
static void test(struct device_node *node) {
 struct device dev={0};struct mca_buckchg_jeita_para result={0};
 assert(!mca_buckchg_jeita_parse_para(&dev,node,"jeita_para",&result));
 assert(result.size>0);int allocations=allocation,reads=read_count;release();
 for(int i=1;i<=allocations;i++) {
  fail_alloc=i;memset(&result,0,sizeof(result));
  assert(mca_buckchg_jeita_parse_para(&dev,node,"jeita_para",&result)<0);release();
 }
 fail_alloc=0;
 for(int i=1;i<=reads;i++) {
  fail_read=i;memset(&result,0,sizeof(result));
  assert(mca_buckchg_jeita_parse_para(&dev,node,"jeita_para",&result)<0);release();
 }
 fail_read=0;
 for(int i=0;i<node->count;i++) {
  struct prop *p=&node->p[i];int count=p->count;
  for(int bad=0;bad<3;bad++) {
   p->count=bad==0?0:bad==1?count-1:1000;
   memset(&result,0,sizeof(result));
   assert(mca_buckchg_jeita_parse_para(&dev,node,"jeita_para",&result)<0);release();
  }
  p->count=count;
  for(int j=0;j<count;j++) {
   const char *saved=p->values[j];p->values[j]="invalid";
   memset(&result,0,sizeof(result));
   assert(mca_buckchg_jeita_parse_para(&dev,node,"jeita_para",&result)<0);release();
   p->values[j]=saved;
  }
 }
 printf("PASS: JEITA table, %d allocation failures, %d read failures and malformed fields\n",allocations,reads);
}
static void ranges(void) {
 struct mca_buckchg_jeita_data t[2]={{.temp_low=-10,.temp_high=20,.vterm=4500},{.temp_low=20,.temp_high=60,.vterm=4500}};
 assert(mca_jeita_table_valid(t,2));t[1].temp_low=19;assert(!mca_jeita_table_valid(t,2));
 t[1].temp_low=21;assert(!mca_jeita_table_valid(t,2));t[1].temp_low=20;
 t[0].max_current=-1;assert(!mca_jeita_table_valid(t,2));t[0].max_current=0;
 t[0].vterm=0;assert(!mca_jeita_table_valid(t,2));assert(!mca_jeita_table_valid(t,0));
 struct device dev={0};struct mca_buckchg_jeita_para result={0};
 struct device_node n=node0;n.count--; /* Optional FFC genuinely absent. */
 assert(!mca_buckchg_jeita_parse_para(&dev,&n,"jeita_para",&result));release();
}
'''
source=pre+h+body+'\n'.join(arrays)+tests+'\nint main(void){ranges();'+''.join('test(&node'+str(i)+');' for i in range(len(fixtures)))+'assert(!nalloc);return 0;}\n'
with tempfile.TemporaryDirectory() as tmp:
    c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(source)
    subprocess.run([os.getenv('CC','clang-19'),'-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(c),'-o',str(exe)],check=True)
    env=dict(os.environ);env.setdefault('ASAN_OPTIONS','detect_leaks=0')
    subprocess.run([str(exe)],check=True,env=env)

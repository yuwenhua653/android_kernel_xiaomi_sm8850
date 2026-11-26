#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the real SC96281 FOD parser/selector against a stock Nezha DTBO.
Usage: test-sc96281-fod.py STOCK_DTBO DEVICETREES_SOURCE
No hardware access or fabricated calibration bytes.
"""
import argparse,json,os,runpy,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('dtbo',type=Path);p.add_argument('devicetrees',type=Path);a=p.parse_args()
h=runpy.run_path(str(a.devicetrees/'tools/prepare-nezha-display.py'));nodes=h['read_nodes'](a.dtbo.read_bytes())
props=next(v for v in nodes.values() if v.get('compatible')==b'mca_sc96281_fod_data\0')
root=Path(__file__).resolve().parents[1]/'drivers/power/supply/mca/mca_hardware_ic/wireless_ic/sc96281'
s=(root/'sc96281_core.c').read_text();start=s.index('static u8 sc96281_fod_case');end=s.index('static int sc96281_set_debug_fod_params',start);functions=s[start:end]
header=(root/'inc/sc96281_reg.h').read_text();start=header.index('typedef struct fod_type_t');end=header.index('typedef struct fw_params_t',start);types=header[start:end]
pre=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
typedef uint8_t u8;typedef uint32_t u32;
#define DEFAULT_FOD_PARAM_LEN 16
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define READ_ONCE(x) (x)
#define SC96281_MCA_FORWARD_2_1 2
static int nezha=1;
#define IS_ENABLED(x) (nezha)
struct device_node {int unused;};
struct property {const char *name;const unsigned char *data;size_t size;};
'''
entries=[]
for name,value in props.items():
 if name=='phandle':continue
 entries.append('{'+json.dumps(name)+', (const unsigned char[]){'+','.join(str(x) for x in value)+'}, '+str(len(value))+'}')
pre+='static struct property props[]={'+',\n'.join(entries)+'};\n'
stubs=r'''
static const char *bad_prop;static int fail_read;
static struct property *lookup(const char *name) {
 if(bad_prop && !strcmp(name,bad_prop))return NULL;
 for(unsigned i=0;i<ARRAY_SIZE(props);i++)if(!strcmp(props[i].name,name))return &props[i];return NULL;
}
static int of_property_count_strings(void *node,const char *name) {
 struct property *p=lookup(name);if(!p)return -EINVAL;
 int n=0;for(size_t i=0;i<p->size;i++)n+=!p->data[i];return n;
}
static int of_property_read_string_index(void *node,const char *name,int index,const char **s) {
 struct property *p=lookup(name);if(!p)return -EINVAL;
 for(size_t i=0;i<p->size;i+=strlen((const char *)p->data+i)+1)if(!index--){*s=(const char *)p->data+i;return 0;}return -EINVAL;
}
static int of_property_count_u8_elems(void *node,const char *name){struct property *p=lookup(name);return p?p->size:-EINVAL;}
static int of_property_read_u8_array(void *node,const char *name,void *dest,size_t n) {
 struct property *p=lookup(name);if(fail_read || !p || p->size!=n)return -EIO;memcpy(dest,p->data,n);return 0;
}
static int kstrtou32(const char *s,int base,u32 *v) {
 char *e;errno=0;unsigned long long n=strtoull(s,&e,base);
 if(errno || !*s || *e || *s=='-' || n>UINT32_MAX)return -EINVAL;*v=n;return 0;
}
static int kstrtou8(const char *s,int base,u8 *v){u32 n;if(kstrtou32(s,base,&n)||n>255)return -EINVAL;*v=n;return 0;}
struct sc96281 {int fod_lock;struct {u8 uuid[4];}proc_data;fod_params_t fod_params[35],fod_params_2_1[35],fod_params_default;int fod_params_size,fod_params_2_1_size;u8 fod_case;};
static void mutex_lock(int *m){assert(!*m);*m=1;}
static void mutex_unlock(int *m){assert(*m);*m=0;}
static int mode=2,mode_ret,write_ret;static fod_params_t written;
static int strategy_class_wireless_ops_get_adapter_charger_mode(int *out){*out=mode;return mode_ret;}
static int sc96281_set_fod(struct sc96281 *chip,fod_params_t *row){assert(chip->fod_lock);written=*row;return write_ret;}
static void uuid(struct sc96281 *c,u32 n){for(int i=0;i<4;i++)c->proc_data.uuid[i]=n>>(24-8*i);}
'''
test=r'''
int main(void) {
 struct sc96281 c={0};struct device_node node;int ret;
 c.fod_params_size=sc96281_myron_parse_table(&node,"fod_params",c.fod_params,35);assert(c.fod_params_size==32);
 c.fod_params_2_1_size=sc96281_myron_parse_table(&node,"fod_params_2_1",c.fod_params_2_1,35);assert(c.fod_params_2_1_size==2);
 assert(sc96281_myron_parse_table(&node,"fod_params_default",&c.fod_params_default,1)==1);
 assert(sc96281_fod_case(1,1)==0 && sc96281_fod_case(1,0)==1 && sc96281_fod_case(0,1)==2 && sc96281_fod_case(0,0)==2);
 for(int pass=0;pass<2;pass++) {
  mode=pass?2:0;fod_params_t *rows=pass?c.fod_params_2_1:c.fod_params;int count=pass?2:32;
  for(int i=0;i<count;i++)for(int category=0;category<3;category++) {
   c.fod_case=category;uuid(&c,rows[i].uuid);assert(sc96281_set_fod_params(0,&c)==0);
   const void *wanted=category==0?rows[i].params:category==1?rows[i].params_mag:rows[i].params_mag_thick;
   assert(!memcmp(written.params,wanted,sizeof(written.params)));
  }
 }
 uuid(&c,0xfedcba98);c.fod_case=0;assert(!sc96281_set_fod_params(0,&c));assert(!memcmp(written.params,c.fod_params_default.params,sizeof(written.params)));
 c.fod_case=3;assert(sc96281_set_fod_params(0,&c)==-EINVAL);c.fod_case=0;
 uuid(&c,c.fod_params_2_1[1].uuid);mode_ret=-EIO;assert(sc96281_set_fod_params(0,&c)==-EIO);mode_ret=0;
 write_ret=-EREMOTEIO;assert(sc96281_set_fod_params(0,&c)==-EREMOTEIO);write_ret=0;
 assert(sc96281_myron_parse_table(&node,"fod_params",c.fod_params,31)==-EINVAL);
 bad_prop="fod_params";assert(sc96281_myron_parse_table(&node,"fod_params",c.fod_params,35)==-EINVAL);bad_prop=NULL;
 fail_read=1;assert(sc96281_myron_parse_table(&node,"fod_params",c.fod_params,35)==-EIO);fail_read=0;
 nezha=0;assert(sc96281_myron_parse_table(&node,"fod_params",c.fod_params,35)==-EINVAL);assert(sc96281_fod_case(0,1)==1);
 puts("PASS: stock 32+2 FOD rows x 3 cases, default UUID, Hall mapping, bounds and provider/I2C error propagation; Myron rejects unequal cases");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp);(path/'test.c').write_text(pre+types+stubs+(root/'inc/sc96281_myron_dt.h').read_text()+functions+test)
 subprocess.run([os.environ.get('HOSTCC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(path/'test.c'),'-o',str(path/'test')],check=True)
 subprocess.run([str(path/'test')],check=True)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual QC registry with callback-blocked replacement and teardown."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root',required=True,type=Path)
p.add_argument('--source',type=Path)
a=p.parse_args()
b=a.kernel_root/'drivers/power/supply/mca'
s=(a.source or b/'mca_protocol/protocol_qc/mca_protocol_qc_class.c').read_text()
h=(b/'include/mca/protocol/protocol_qc_class.h').read_text()
s=re.sub(r'^#include .*\n','',s,flags=re.M)
s=s[:s.index('struct adapter_protocol_class_ops g_protocol_qc_ops')]
code=Path(__file__).with_name('mca_lifetime_host.h').read_text()+'\n#define TYPEC_PORT_MAX 2\n'
code+=re.search(r'struct protocol_class_qc_ops \{.*?\};',h,re.S)[0]+'\n'+s
code+=r'''
static atomic_int entered,release_cb,done;
static int token_a,token_b;
static int callback(void *data,int value) {
 assert(data==&token_a || data==&token_b);
 if(data==&token_a) { atomic_store(&entered,1);while(!atomic_load(&release_cb))usleep(100); }
 return value+1;
}
static int get_callback(int *value,void *data) { *value=17;return callback(data,10); }
static struct protocol_class_qc_ops ops={get_callback,callback,callback,get_callback};
static void *reader(void *p) {assert(protocol_class_qc_set_volt(0,7)==8);return NULL;}
static void *remover(void *p) {assert(!protocol_class_qc_unregister_ops(0,&ops,&token_a));atomic_store(&done,1);return NULL;}
static void *replacer(void *p) {assert(!protocol_class_qc_register_ops(0,&ops,&token_b));atomic_store(&done,1);return NULL;}
int main(void) {
 pthread_t rd,wr;int cases=0,v;
 assert(protocol_class_qc_register_ops(2,&ops,&token_a)==-EINVAL);
 assert(protocol_class_qc_get_qc_type(0,NULL)==-EINVAL);
 assert(protocol_class_qc_set_volt(0,1)==-ENODEV);cases+=3;
 for(int replace=0;replace<2;replace++)for(int i=0;i<64;i++) {
  atomic_store(&entered,0);atomic_store(&release_cb,0);atomic_store(&done,0);
  assert(!protocol_class_qc_register_ops(0,&ops,&token_a));
  assert(protocol_class_qc_unregister_ops(0,&ops,&token_b)==-ENOENT);
  assert(!pthread_create(&rd,NULL,reader,NULL));while(!atomic_load(&entered))usleep(100);
  assert(!pthread_create(&wr,NULL,replace?replacer:remover,NULL));
  /* Wait for publication/removal, then check the blocked old callback. */
  while(rcu_access_pointer(g_protocol_qc_data[0]) && rcu_access_pointer(g_protocol_qc_data[0])->data==&token_a)usleep(100);
  assert(!atomic_load(&done));
  atomic_store(&release_cb,1);pthread_join(rd,NULL);pthread_join(wr,NULL);
  if(replace) {
   assert(protocol_class_qc_get_qc_type(0,&v)==11 && v==17);
   assert(protocol_class_qc3_check_class_type(0,&v)==11);
   assert(protocol_class_qc_set_volt_cmd(0,8)==9);
   assert(!protocol_class_qc_unregister_ops(0,&ops,&token_b));
  }
  assert(protocol_class_qc_set_volt(0,1)==-ENODEV);cases++;
 }
 printf("PASS: %d QC registry/lifetime cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
 c,e=Path(d)/'test.c',Path(d)/'test';c.write_text(code)
 subprocess.run(['cc','-std=gnu11','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function',
 '-fsanitize=undefined','-fno-sanitize-recover=undefined',str(c),'-o',str(e)],check=True)
 subprocess.run([str(e)],check=True,timeout=30)

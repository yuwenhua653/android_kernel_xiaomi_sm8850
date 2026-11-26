#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise production sub-PMIC retry generations and probe/remove ownership."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_irq import function
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernel-root',required=True,type=Path)
p.add_argument('--source',type=Path)
a=p.parse_args()
s=(a.source or a.kernel_root/'drivers/power/supply/mca/mca_qcom_subpmic_proxy/mca_qcom_subpmic_proxy.c').read_text()
code=Path(__file__).with_name('mca_lifetime_host.h').read_text()
code+=r'''
#define MCA_EVENT_CHARGE_STATUS 1
#define SUBPMIC_RAW_CODE_GLINK_UP 0x2f
#define SUBPMIC_SYNC_RETRIES 60
#define system_wq NULL
#define msecs_to_jiffies(n) (n)
struct work_struct {int pending;};
struct delayed_work {struct work_struct work;int delay;};
#define to_delayed_work(p) container_of(p,struct delayed_work,work)
#define INIT_WORK(w,f) ((w)->pending=0)
#define INIT_DELAYED_WORK(w,f) ((w)->work.pending=0)
struct device {void *of_node;};
struct platform_device {struct device dev;void *data;};
struct notifier_block {int notifier_call,priority;};
struct qcom_subpmic {
 struct device *dev;struct delayed_work sync_cfg_work,update_usb_type_work;struct work_struct notify_change_work;
 spinlock_t sync_lock,notify_lock;unsigned int sync_retries,sync_generation;bool stopping;
 struct notifier_block ship_mode_nb,shutdown_nb;struct list_head notify_list;
 bool support_cid;int otg_cfg,cid_gpio_int;u8 eu_model;
};
struct qcom_subpmic_notify_entry {struct list_head node;int type,val;};
static int g_qcom_pmic_bc12_ops,g_adsp_qc_ops,g_qcom_buckchg_ops,g_qcom_subpmic_glink_cb;
static int qcom_subpmic_ship_mode=1,qcom_subpmic_shutdown_cb=2;
static int have_hwid=1,stage,fail_stage,owned[8],property_fail,property_calls,requeues,mutate_generation;
static void *allocation;
static struct qcom_subpmic *active;
static int acquire(int id) {stage++;if(stage==fail_stage)return -EIO;assert(!owned[id]);owned[id]=1;return 0;}
static void drop(int id) {assert(owned[id]);owned[id]=0;}
static void *devm_kzalloc(struct device *d,size_t n,int flags){return allocation=calloc(1,n);}
static bool mca_get_hwid_info(void){return have_hwid;}
static void qcom_subpmic_parse_dt(struct qcom_subpmic *s,void *n){}
static int register_reboot_notifier(struct notifier_block *n){return acquire(n->notifier_call);}
static int unregister_reboot_notifier(struct notifier_block *n){drop(n->notifier_call);return 0;}
static int device_init_wakeup(struct device *d,bool en){if(en)return acquire(3);drop(3);return 0;}
static void platform_set_drvdata(struct platform_device *p,void *d){p->data=d;}
static void *platform_get_drvdata(struct platform_device *p){return p->data;}
static int platform_bc12_class_ops_register(int role,int *ops,void *d){return acquire(4);}
static int platform_bc12_class_ops_unregister(int role,int *ops,void *d){drop(4);return 0;}
static int protocol_class_qc_register_ops(int role,int *ops,void *d){return acquire(5);}
static int protocol_class_qc_unregister_ops(int role,int *ops,void *d){drop(5);return 0;}
static int platform_class_buckchg_ops_register_v2(int role,void *d,int *ops,size_t len){return acquire(6);}
static int platform_class_buckchg_ops_unregister(int role,void *d,int *ops){drop(6);return 0;}
static int mca_adsp_glink_resister_ops(int *ops,void *d){return acquire(7);}
static void mca_adsp_glink_unregister_ops(int *ops,void *d){drop(7);}
static bool queue_delayed_work(void *q,struct delayed_work *w,int delay){requeues++;if(w->work.pending)return false;w->work.pending=1;w->delay=delay;return true;}
static bool mod_delayed_work(void *q,struct delayed_work *w,int delay){requeues++;w->work.pending=1;w->delay=delay;return true;}
static void cancel_delayed_work_sync(struct delayed_work *w){w->work.pending=0;}
static void cancel_work_sync(struct work_struct *w){w->pending=0;}
static void mca_event_block_notify(int type,int event,void *d){}
static int platform_class_cp_get_present(int role,bool *v){*v=true;return property_fail==1?-EIO:0;}
static int mca_adsp_glink_write_prop(int prop,void *v,size_t len){
 property_calls++;if(mutate_generation){active->sync_generation++;active->sync_retries=0;mutate_generation=0;}
 return property_fail==property_calls+1?-EIO:0;
}
'''
code+=re.search(r'enum mca_subpmic_prop \{.*?\};',s,re.S)[0]+'\n'
for n in ['qcom_subpmic_sync_cfg_work','qcom_subpmic_sync_cb','qcom_subpmic_probe','qcom_subpmic_remove']:
 code+=function(s,n)+'\n'
code+=r'''
static void run(struct qcom_subpmic *s){s->sync_cfg_work.work.pending=0;property_calls=0;qcom_subpmic_sync_cfg_work(&s->sync_cfg_work.work);}
int main(void) {
 struct platform_device p={0};int cases=0;
 for(int f=1;f<=7;f++) {
  stage=0;fail_stage=f;assert(qcom_subpmic_probe(&p)==-EIO);
  for(int i=1;i<=7;i++)assert(!owned[i]);free(allocation);cases++;
 }
 have_hwid=0;stage=0;assert(qcom_subpmic_probe(&p)==-EPROBE_DEFER && !stage);free(allocation);have_hwid=1;cases++;
 fail_stage=0;stage=0;assert(!qcom_subpmic_probe(&p));struct qcom_subpmic *s=p.data;active=s;
 for(int f=1;f<=5;f++)for(int cycle=0;cycle<3;cycle++) {
  s->support_cid=true;property_fail=f;qcom_subpmic_sync_cb(s);assert(s->sync_retries==0 && !s->sync_cfg_work.delay);
  for(int r=0;r<60;r++){run(s);assert(s->sync_retries==(unsigned)r+1 && s->sync_cfg_work.work.pending);}
  run(s);assert(s->sync_retries==60 && !s->sync_cfg_work.work.pending);
  for(int r=0;r<10;r++)run(s);assert(s->sync_retries==60 && !s->sync_cfg_work.work.pending);
  qcom_subpmic_sync_cb(s);assert(!s->sync_retries);property_fail=0;run(s);assert(!s->sync_retries && !s->sync_cfg_work.work.pending);cases++;
 }
 property_fail=2;mutate_generation=1;s->sync_retries=59;run(s);
 assert(!s->sync_retries && !s->sync_cfg_work.work.pending);cases++;
 for(int cid=0;cid<2;cid++){s->support_cid=cid;property_fail=0;s->sync_retries=20;run(s);assert(!s->sync_retries && property_calls==(cid?4:2));cases++;}
 struct qcom_subpmic_notify_entry *entry=calloc(1,sizeof(*entry));list_add_rcu(&entry->node,&s->notify_list);
 qcom_subpmic_remove(&p);for(int i=1;i<=7;i++)assert(!owned[i]);
 assert(s->stopping && !s->sync_cfg_work.work.pending && !s->update_usb_type_work.work.pending && s->notify_list.next==&s->notify_list);
 requeues=0;qcom_subpmic_sync_cb(s);run(s);assert(!requeues);free(s);cases++;
 printf("PASS: %d sub-PMIC recovery/unwind cases (60 retries per failure cycle)\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
 c,e=Path(d)/'test.c',Path(d)/'test';c.write_text(code)
 subprocess.run(['cc','-std=gnu11','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function',
 '-Wno-misleading-indentation','-fsanitize=undefined','-fno-sanitize-recover=undefined',str(c),'-o',str(e)],check=True)
 subprocess.run([str(e)],check=True,timeout=30)

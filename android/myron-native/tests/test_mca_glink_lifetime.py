#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run complete MCA GLINK production functions with threaded host transport mocks."""
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
s=(a.source or b/'mca_common/mca_adsp_glink.c').read_text()
s=re.sub(r'^#include .*\n','',s,flags=re.M)
s=s[:s.index('static const struct of_device_id')].replace('struct mutex', 'pthread_mutex_t')
h=(b/'include/mca/common/mca_adsp_glink.h').read_text()
code=Path(__file__).with_name('mca_lifetime_host.h').read_text()
code+=r'''
struct completion {pthread_mutex_t lock;pthread_cond_t cond;bool done;};
static void init_completion(struct completion *c){mutex_init(&c->lock);pthread_cond_init(&c->cond,NULL);c->done=false;}
static void reinit_completion(struct completion *c){mutex_lock(&c->lock);c->done=false;mutex_unlock(&c->lock);}
static void complete(struct completion *c){mutex_lock(&c->lock);c->done=true;pthread_cond_broadcast(&c->cond);mutex_unlock(&c->lock);}
static unsigned long wait_for_completion_timeout(struct completion *c,int ms) {
 struct timespec t;clock_gettime(CLOCK_REALTIME,&t);t.tv_sec+=2;
 mutex_lock(&c->lock);int ret=0;while(!c->done && !ret)ret=pthread_cond_timedwait(&c->cond,&c->lock,&t);
 bool done=c->done;mutex_unlock(&c->lock);return done;
}
#define msecs_to_jiffies(v) (v)
struct work_struct { void (*fn)(struct work_struct *); atomic_bool pending; };
#define INIT_WORK(w,f) do {(w)->fn=(f);atomic_store(&(w)->pending,false);} while(0)
#define system_wq NULL
static bool queue_work(void *q,struct work_struct *w) {return !atomic_exchange(&w->pending,true);}
static void cancel_work_sync(struct work_struct *w){atomic_store(&w->pending,false);}
static void run_work(struct work_struct *w){if(atomic_exchange(&w->pending,false))w->fn(w);}
struct device {int unused;};
struct platform_device {struct device dev;void *data;};
static void *allocation;
static void *devm_kzalloc(struct device *d,size_t n,int flags){return allocation=calloc(1,n);}
static void platform_set_drvdata(struct platform_device *p,void *d){p->data=d;}
static void *platform_get_drvdata(struct platform_device *p){return p->data;}
enum pmic_glink_state {PMIC_GLINK_STATE_DOWN,PMIC_GLINK_STATE_UP};
struct pmic_glink_hdr {u32 owner,type,opcode;};
struct pmic_glink_client_data {const char *name;u32 id;void *priv;
 int (*msg_cb)(void *,void *,size_t);void (*state_cb)(void *,enum pmic_glink_state);};
struct pmic_glink_client {struct pmic_glink_client_data data;bool alive;};
static struct pmic_glink_client transport;
static atomic_int in_write;
static int register_error,unregisters,reply_kind;
static struct pmic_glink_client *pmic_glink_register_client(struct device *d,struct pmic_glink_client_data *c) {
 if(register_error)return ERR_PTR(register_error);
 transport=(struct pmic_glink_client){.data=*c,.alive=true};return &transport;
}
static int pmic_glink_unregister_client_sync(struct pmic_glink_client *c) {
 assert(c->alive && !atomic_load(&in_write));c->alive=false;unregisters++;return 0;
}
static int pmic_glink_write(struct pmic_glink_client *,void *,size_t);
'''
code+=re.search(r'struct mca_adsp_glink_ops \{.*?\};',h,re.S)[0]+'\n'+s
code+=r'''
static int pmic_glink_write(struct pmic_glink_client *c,void *data,size_t len) {
 assert(c->alive && len==sizeof(struct mca_adsp_glink_req_msg));
 struct mca_adsp_glink_req_msg *req=data;
 struct mca_adsp_glink_resp_msg resp={.hdr=req->hdr,.property_id=req->property_id,.seq=req->seq};
 atomic_store(&in_write,1);
 if(reply_kind==1) {atomic_store(&in_write,0);return 0;}
 resp.data[0]=42;
 if(reply_kind==2)resp.retcode=1;
 /* Wrong owner/opcode/sequence/property must not complete the request. */
 for(int i=0;i<4;i++) {
  struct mca_adsp_glink_resp_msg bad=resp;
  if(i==0)bad.hdr.owner++;if(i==1)bad.hdr.opcode++;if(i==2)bad.seq++;if(i==3)bad.property_id++;
  c->data.msg_cb(c->data.priv,&bad,sizeof(bad));
  assert(((struct mca_adsp_glink_dev *)c->data.priv)->pending);
 }
 c->data.msg_cb(c->data.priv,&resp,sizeof(resp));
 atomic_store(&in_write,0);return 0;
}
static int ups,downs,notifications;
static atomic_int notify_enter,notify_release,ops_removed;
static bool block_notify;
static void up(void *p){ups++;}
static void down(void *p){downs++;}
static void notification(u32 prop,void *data,u32 len,void *p){
 assert(len==256);notifications++;
 if(block_notify){atomic_store(&notify_enter,1);while(!atomic_load(&notify_release))usleep(100);}
}
static struct mca_adsp_glink_ops ops={down,up,notification};
static int token;
static void *api_reader(void *p) {int value=777;int ret=mca_adsp_glink_read_prop(7,&value,sizeof(value));assert(ret==-ENODEV && value==777);return NULL;}
static void *notify_reader(void *p) {
 struct mca_adsp_glink_notify_msg msg={.hdr={.owner=MCA_ADSP_GLINK_OWNER,.type=MCA_ADSP_GLINK_MSG_NOTIFY}};
 mca_adsp_glink_callback(p,&msg,sizeof(msg));return NULL;
}
static void *ops_remover(void *p){mca_adsp_glink_unregister_ops(&ops,&token);atomic_store(&ops_removed,1);return NULL;}
int main(void) {
 struct platform_device p={0};int value=7,cases=0;
 assert(mca_adsp_glink_read_prop(1,&value,sizeof(value))==-ENODEV);
 assert(mca_adsp_glink_read_prop(1,NULL,4)==-EINVAL);cases+=2;
 register_error=-EPROBE_DEFER;assert(mca_adsp_glink_probe(&p)==-EPROBE_DEFER);free(allocation);register_error=0;cases++;
 for(int cycle=0;cycle<64;cycle++) {
  assert(!mca_adsp_glink_resister_ops(&ops,&token));
  ups=0;assert(!mca_adsp_glink_probe(&p));struct mca_adsp_glink_dev *m=p.data;
  run_work(&m->sync_work);assert(ups==1);
  mca_adsp_glink_unregister_ops(&ops,&token);
  reply_kind=0;value=0;assert(!mca_adsp_glink_read_prop(7,&value,sizeof(value)) && value==42);
  assert(!mca_adsp_glink_write_prop(7,&value,sizeof(value)));
  assert(!mca_adsp_glink_qbg_read_prop(7,&value,sizeof(value)));
  assert(!mca_adsp_glink_qbg_write_prop(7,&value,sizeof(value)));
  reply_kind=2;value=777;assert(mca_adsp_glink_read_prop(7,&value,sizeof(value))==-EREMOTEIO && value==777);
  assert(!mca_adsp_glink_resister_ops(&ops,&token));
  assert(mca_adsp_glink_resister_ops(&ops,&token)==-EEXIST);
  assert(!mca_adsp_glink_qbg_resister_ops(&ops,&token));
  ups=downs=notifications=0;
  mca_adsp_glink_state_cb(m,PMIC_GLINK_STATE_UP);
  mca_adsp_glink_state_cb(m,PMIC_GLINK_STATE_DOWN);
  run_work(&m->sync_work);assert(!ups && downs==2);
  assert(mca_adsp_glink_read_prop(7,&value,sizeof(value))==-ENOTCONN);
  mca_adsp_glink_state_cb(m,PMIC_GLINK_STATE_UP);run_work(&m->sync_work);assert(ups==2);
  pthread_t rd,rm;block_notify=true;atomic_store(&notify_enter,0);atomic_store(&notify_release,0);atomic_store(&ops_removed,0);
  pthread_create(&rd,NULL,notify_reader,m);while(!atomic_load(&notify_enter))usleep(100);
  pthread_create(&rm,NULL,ops_remover,NULL);
  while(__atomic_load_n(&g_mca_adsp_glink_ops_head.next,__ATOMIC_ACQUIRE)!=&g_mca_adsp_glink_ops_head)usleep(100);
  assert(!atomic_load(&ops_removed));atomic_store(&notify_release,1);
  pthread_join(rd,NULL);pthread_join(rm,NULL);block_notify=false;
  notify_reader(m);assert(notifications==1);
  mca_adsp_glink_qbg_unregister_ops(&ops,&token);
  /* A blocked request is aborted before remove drains API users and transport. */
  reply_kind=1;pthread_create(&rd,NULL,api_reader,NULL);
  for(;;){unsigned long f;spin_lock_irqsave(&m->pending_lock,f);bool pending=m->pending;spin_unlock_irqrestore(&m->pending_lock,f);if(pending)break;usleep(100);}
  mca_adsp_glink_remove(&p);pthread_join(rd,NULL);
  assert(!transport.alive && !rcu_access_pointer(g_mca_adsp_glink) && !atomic_load(&m->sync_work.pending));
  assert(mca_adsp_glink_write_prop(7,&value,sizeof(value))==-ENODEV);
  free(m);cases++;
 }
 assert(unregisters==64);
 printf("PASS: %d GLINK request/registry/rebind lifecycle cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
 c,e=Path(d)/'test.c',Path(d)/'test';c.write_text(code)
 subprocess.run(['cc','-std=gnu11','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function',
 '-Wno-sign-compare','-Wno-misleading-indentation','-fsanitize=undefined','-fno-sanitize-recover=undefined',str(c),'-o',str(e)],check=True)
 subprocess.run([str(e)],check=True,timeout=30)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the Nezha GLINK wire dispatcher, pending replies and link transitions."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "drivers/power/supply/mca/mca_common/mca_adsp_glink.c").read_text()
pre = r"""
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uint8_t u8;
typedef int spinlock_t;
enum pmic_glink_state {PMIC_GLINK_STATE_DOWN, PMIC_GLINK_STATE_UP};
struct pmic_glink_hdr {u32 owner, type, opcode;};
struct work_struct {int queued;}; struct completion {int done;};
struct mutex {int busy;};
struct list_head {void *entry;};
struct mca_adsp_glink_ops {void (*notification)(u32,void*,u32,void*);void (*glink_state_up)(void*);void (*glink_state_down)(void*);};
#define __packed __attribute__((packed))
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,x) ((v)=(x))
#define IS_ENABLED(x) 1
#define list_for_each_entry_rcu(v,h,field,cond) for((v)=(h)->entry;(v);(v)=NULL)
#define spin_lock_irqsave(s,f) do{assert(!*(s));*(s)=1;(f)=0;}while(0)
#define spin_unlock_irqrestore(s,f) do{assert(*(s));*(s)=0;}while(0)
#define srcu_read_lock(p) 0
#define srcu_read_unlock(p,i) ((void)(i))
#define mca_log_info(...) ((void)0)
#define complete(p) ((p)->done++)
#define reinit_completion(p) ((p)->done=0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define queue_work(q,w) ((w)->queued=1)
static struct mutex *take_mutex(struct mutex *m){assert(!m->busy);m->busy=1;return m;}
static void release_mutex(struct mutex **m){assert((*m)->busy);(*m)->busy=0;}
#define guard(m) __attribute__((cleanup(release_mutex))) struct mutex *held=take_mutex
static struct list_head g_mca_adsp_glink_ops_head,g_mca_adsp_glink_qbg_ops_head;
"""
definitions = source[source.index("#define MCA_ADSP_GLINK_OWNER"):source.index("/* Serialize transactions")]
begin = source[source.index("static int mca_adsp_glink_begin_request"):source.index("int mca_adsp_glink_write_prop")]
dispatch = source[source.index("static int\nmca_adsp_glink_handle_notification"):source.index("static int mca_adsp_glink_probe")]
main = r"""
static int events,up,down;
static void note(u32 id,void *data,u32 len,void *priv){assert(id==4&&len==256);events++;}
static void connected(void *priv){up++;}static void lost(void *priv){down++;}
int main(void) {
 struct mca_adsp_glink_dev m={0};
 struct mca_adsp_glink_ops ops={note,connected,lost};
 struct mca_adsp_ops_node listener={.ops=&ops};g_mca_adsp_glink_ops_head.entry=&listener;
 struct mca_adsp_glink_req_msg q={.hdr={0x800a,1,1},.property_id=7,.seq=99};
 struct mca_adsp_glink_resp_msg r={.hdr={0x800a,1,1},.property_id=7,.seq=99,.data={42}};
 struct mca_adsp_glink_notify_msg n={.hdr={0x800a,2,0},.property_id=4};
 assert(mca_adsp_glink_begin_request(&m,&q)==-ENOTCONN);
 mca_adsp_glink_state_cb(&m,PMIC_GLINK_STATE_UP);
 mca_adsp_glink_callback(&m,&n,sizeof(n));assert(!events);
 m.published=true;mca_adsp_glink_sync_work(&m.sync_work);assert(up==1);
 assert(!mca_adsp_glink_begin_request(&m,&q));
 for(int i=0;i<5;i++){
   struct mca_adsp_glink_resp_msg bad=r;
   if(i==0)bad.hdr.owner=0x8009;if(i==1)bad.hdr.opcode=2;if(i==2)bad.seq--;
   if(i==3)bad.property_id++;mca_adsp_glink_callback(&m,&bad,sizeof(bad)-(i==4));
   assert(m.pending&&!m.ack.done);
 }
 mca_adsp_glink_callback(&m,&r,sizeof(r));assert(!m.pending&&m.ack.done==1&&m.read_buf[0]==42&&!m.retcode);
 mca_adsp_glink_callback(&m,&r,sizeof(r));assert(m.ack.done==1);
 mca_adsp_glink_end_request(&m);q.seq++;r.seq++;r.retcode=17;
 assert(!mca_adsp_glink_begin_request(&m,&q));mca_adsp_glink_callback(&m,&r,sizeof(r));
 assert(m.retcode==-EREMOTEIO&&!m.read_buf[0]&&m.remote_retcode==17);
 assert(!mca_adsp_glink_begin_request(&m,&q));mca_adsp_glink_state_cb(&m,PMIC_GLINK_STATE_DOWN);
 assert(down==1&&!m.pending&&m.ack.done==1&&m.retcode==-ENOTCONN);
 mca_adsp_glink_sync_work(&m.sync_work);mca_adsp_glink_callback(&m,&n,sizeof(n));assert(!events&&up==1);
 mca_adsp_glink_state_cb(&m,PMIC_GLINK_STATE_UP);mca_adsp_glink_sync_work(&m.sync_work);assert(up==2);
 n.hdr.owner=0x8009;mca_adsp_glink_callback(&m,&n,sizeof(n));assert(!events);
 n.hdr.owner=0x800a;mca_adsp_glink_callback(&m,&n,sizeof(n)-1);assert(!events);
 mca_adsp_glink_callback(&m,&n,sizeof(n));assert(events==1);
 puts("PASS GLINK request matching, remote failure, interrupted request, stale UP and closed-link/foreign notifications");
}
"""
with tempfile.TemporaryDirectory() as directory:
    src = Path(directory) / "glink.c"
    exe = src.with_suffix("")
    src.write_text(pre + definitions + begin + dispatch + main)
    subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-fsanitize=address,undefined",
                    str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Production lock-entry functions exercised with pthreads, not kernel workqueues."""
from pathlib import Path
import os,runpy,subprocess,tempfile,re
c=runpy.run_path(str(Path(__file__).with_name('test-mca-wired-controls.py')))
fn=c['fn'];header=c['header'];pre=c['pre']
events=fn('mca_quick_charge_protection_event')+fn('mca_quick_charge_process_event')
pre+='enum {'+','.join(sorted(set(re.findall(r'\bMCA_EVENT_\w+',events))))+'};\n'
stubs=r'''
#define container_of(ptr,type,member) ((type*)((char*)(ptr)-offsetof(type,member)))
#define system_wq NULL
static int entered,maximum,stops,locked_events,vote_errno;
static struct mca_quick_charge_info *owner;
static int mca_quick_charge_chg_disable_voter_cb(struct mca_votable*,void*,int,const char*);
static int mca_quick_charge_chg_en_voter_cb(struct mca_votable*,void*,int,const char*);
static int mod_delayed_work(void*q,struct delayed_work*w,int delay){(void)q;(void)delay;WRITE_ONCE(w->pending,true);return 1;}
static void critical(void){int n=__atomic_add_fetch(&entered,1,__ATOMIC_SEQ_CST);if(n>maximum)maximum=n;assert(n==1);usleep(1000);assert(__atomic_sub_fetch(&entered,1,__ATOMIC_SEQ_CST)==0);}
static int mca_quick_charge_force_stop_charging(struct mca_quick_charge_info*i){(void)i;critical();stops++;return 0;}
static int mca_vote(struct mca_votable*v,const char*client,bool en,int val){(void)client;if(vote_errno)return vote_errno;return v==owner->chg_disable_voter?mca_quick_charge_chg_disable_voter_cb(v,owner,en?val:0,client):mca_quick_charge_chg_en_voter_cb(v,owner,en?val:1,client);}
static int mca_quick_charge_process_event_locked(int event,int value,void*data){struct mca_quick_charge_info*i=data;(void)value;critical();locked_events++;if(event==MCA_EVENT_USB_DISCONNECT)i->online=0;return 0;}
static void mca_quick_charge_monitor_work_locked(struct work_struct*w){(void)w;critical();}
static void mca_quick_charge_vfc_work_locked(struct work_struct*w){(void)w;critical();}
static void mca_quick_charge_pps_ptf_work_locked(struct work_struct*w){(void)w;critical();}
static int mca_quick_charge_get_status_locked(int status,void*value,void*data){(void)status;(void)data;critical();*(int*)value=1;return 0;}
'''
body=''.join(fn(n) for n in ['mca_quick_charge_request_stop','mca_quick_charge_chg_disable_voter_cb','mca_quick_charge_chg_en_voter_cb'])+events
body+=''.join(fn(n) for n in ['mca_quick_charge_monitor_work','mca_quick_charge_vfc_work','mca_quick_charge_pps_ptf_work','mca_quick_charge_get_status'])
test=r'''
static void*workers(void*arg){long n=(long)arg;for(int j=0;j<25;j++){if(n==0)mca_quick_charge_monitor_work(&owner->monitor_work.work);else if(n==1)mca_quick_charge_vfc_work(&owner->vfc_work.work);else if(n==2)mca_quick_charge_pps_ptf_work(&owner->pps_ptf_work.work);else assert(!mca_quick_charge_process_event(-123,0,owner));}return NULL;}
static void*disconnect(void*arg){(void)arg;assert(!mca_quick_charge_process_event(MCA_EVENT_USB_DISCONNECT,0,owner));return NULL;}
int main(void){struct mca_quick_charge_info i={0};struct mca_votable v[2];pthread_t th[4];int value=0;owner=&i;i.ready=i.online=i.sysfs_data.chg_enable=true;i.chg_disable_voter=&v[0];i.chg_en_voter=&v[1];assert(!pthread_mutex_init(&i.data_lock.raw,NULL));
 /* A voter callback invoked under the hardware lock must return instead of deadlocking. */
 mutex_lock(&i.data_lock);assert(mca_quick_charge_process_event(MCA_EVENT_SINK_PWR_SUSPEND_CHANGE,1,&i)==-EAGAIN);assert(i.force_stop&&i.monitor_work.pending&&!stops);assert(mca_quick_charge_get_status(0,&value,&i)==-EAGAIN);mutex_unlock(&i.data_lock);
 assert(!mca_quick_charge_process_event(MCA_EVENT_SINK_PWR_SUSPEND_CHANGE,1,&i)&&stops==1);
 /* -ENOENT from an actual handled protection event must not disappear. */
 vote_errno=-ENOENT;assert(mca_quick_charge_process_event(MCA_EVENT_VBAT_OVP_CHANGE,1,&i)==-ENOENT&&!locked_events);vote_errno=0;
 for(long n=0;n<4;n++)assert(!pthread_create(&th[n],NULL,workers,(void*)n));for(int n=0;n<4;n++)assert(!pthread_join(th[n],NULL));assert(maximum==1&&locked_events==25);
 mutex_lock(&i.data_lock);assert(!pthread_create(&th[0],NULL,disconnect,NULL));for(int n=0;n<10000&&!READ_ONCE(i.abort_requested);n++)usleep(10);assert(READ_ONCE(i.abort_requested)&&i.online);mutex_unlock(&i.data_lock);assert(!pthread_join(th[0],NULL));assert(!i.online);
 i.stopping=true;int old=locked_events;assert(mca_quick_charge_process_event(-123,0,&i)==-ENODEV);mca_quick_charge_monitor_work(&i.monitor_work.work);mca_quick_charge_vfc_work(&i.vfc_work.work);assert(locked_events==old);assert(!pthread_mutex_destroy(&i.data_lock.raw));
 puts("PASS: actual event/worker/status entry locks, voter trylock/deferred retry, handled errno, disconnect abort before lock, 100 concurrent entries and stopping gate (pthread model)");}
'''
with tempfile.TemporaryDirectory(prefix='mca-wired-concurrency-') as d:
 p=Path(d);(p/'test.c').write_text(pre+header+stubs+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-pthread','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

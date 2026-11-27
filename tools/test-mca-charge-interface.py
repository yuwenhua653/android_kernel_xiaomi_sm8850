#!/usr/bin/env python3
"""Run actual MCA charge-interface dispatch/registration under host sanitizers.
SRCU is modelled by a pthread rwlock; this is not an in-kernel SRCU test.
"""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
p=root/'drivers/power/supply/mca'
s=(p/'mca_common/mca_charge_interface.c').read_text()
header=(p/'include/mca/common/mca_charge_interface.h').read_text().replace('#include <linux/types.h>','')
header+=(p/'include/mca/common/mca_event.h').read_text().replace('#include <linux/notifier.h>','struct notifier_block;')
battery=(p/'mca_business/business_battery/mca_business_battery.c').read_text()
battery=battery[battery.index('static int business_battery_event_process('):]
battery=battery[:battery.index('\n}\n')+3]
body=s[s.index('#define MCA_CHARGE_IF_MAX_RW_BUFF'):s.index('static struct mca_sysfs_attr_info')]
# Keep dispatch code, excluding the sysfs table macros immediately before table.
body=body[:body.index('static ssize_t mca_charge_if_sysfs_show')] if 'static ssize_t mca_charge_if_sysfs_show' in body else body
idx=body.find('#define MCA_CHARGE_IF_SYSFS');body=body[:idx] if idx>=0 else body
body=body.replace('#ifdef CONFIG_SYSFS','')
reg=s[s.index('int mca_charge_if_ops_register('):s.index('static int mca_charge_if_probe')]
reg=reg.replace('EXPORT_SYMBOL(mca_charge_if_ops_register);','').replace('EXPORT_SYMBOL(mca_charge_if_ops_unregister);','')
preamble=r'''
#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <assert.h>
#include <sched.h>
#define __rcu
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define DEFINE_MUTEX(x) pthread_mutex_t x=PTHREAD_MUTEX_INITIALIZER
#define DEFINE_STATIC_SRCU(x) static pthread_rwlock_t x=PTHREAD_RWLOCK_INITIALIZER
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define srcu_dereference(x,s) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define rcu_access_pointer(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define rcu_assign_pointer(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define RCU_INIT_POINTER(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
static int srcu_read_lock(pthread_rwlock_t *x){pthread_rwlock_rdlock(x);return 0;}
static void srcu_read_unlock(pthread_rwlock_t *x,int ignored){pthread_rwlock_unlock(x);}
static void synchronize_srcu(pthread_rwlock_t *x){pthread_rwlock_wrlock(x);pthread_rwlock_unlock(x);}
#define mca_log_err(...) do {} while(0)
#define mca_log_info(...) do {} while(0)
#define IS_ENABLED(x) (x)
#define scnprintf snprintf
static int kstrtouint(const char *s,unsigned base,unsigned *v) {
 char *end;errno=0;unsigned long n=strtoul(s,&end,base);
 if(errno||n>UINT_MAX||end==s||(*end && strcmp(end,"\n"))||*s=='-')return -EINVAL;
 *v=n;return 0;
}
static unsigned event_count,event_code;

'''
route=r'''
struct notifier_block { int unused; };
struct power_supply { int unused; };
struct battery_psy_info { struct power_supply *batt_psy; int fake_power; };
struct business_battery {struct notifier_block batt_info_nb;struct battery_psy_info *batt_psy_info;};
#define container_of(ptr,type,member) ((type*)((char*)(ptr)-offsetof(type,member)))
static int battery_updates;
static void power_supply_changed(struct power_supply *p){assert(p);battery_updates++;}
static struct power_supply supply;
static struct battery_psy_info psy_info={.batt_psy=&supply};
static struct business_battery consumer={.batt_psy_info=&psy_info};
'''
notify=r'''
void mca_event_block_notify(unsigned int type,unsigned long code,void *data){
 assert(type==MCA_EVENT_TYPE_BATTERY_INFO);event_count++;event_code=code;
 if(CONFIG_TARGET_PRODUCT_NEZHA)business_battery_event_process(&consumer.batt_info_nb,code,data);
}
'''
tests=r'''
static int answer, calls;
static atomic_int entered,leave,unregistered;
static int set_suspend(const char *u,char *v,void *d){calls++;return answer;}
static int get_suspend(char *v,void *d){strcpy(v,d);return answer;}
static int blocking(const char *u,char *v,void *d){atomic_store(&entered,1);while(!atomic_load(&leave))sched_yield();return 0;}
static void *reader(void *p){assert(!mca_charge_if_op_set("test",0,0,"1"));return NULL;}
static void *remove_provider(void *p){assert(!mca_charge_if_ops_unregister(p));atomic_store(&unregistered,1);return NULL;}
int main(void){
 struct mca_charge_if_ops a={.type_name="buck",.set_input_suspend=set_suspend,.get_input_suspend=get_suspend,.data="1"};
 struct mca_charge_if_ops duplicate={.type_name="buck"},all={.type_name="all"};
 char buf[256];bool suspended;
 assert(mca_charge_if_ops_register(NULL)==-EINVAL);
 assert(mca_charge_if_ops_register(&all)==-EINVAL);
 assert(mca_charge_if_op_set("test",0,1,"1")==-ENODEV);
 assert(mca_charge_if_common_sysfs_set("test",MCA_CHARGE_IF_CHG_TYPE_ALL,0,"1")==-EOPNOTSUPP);
 assert(mca_charge_suspend_state_show(&suspended)==-ENODEV);
 assert(!mca_charge_if_ops_register(&a));
 assert(mca_charge_if_ops_register(&duplicate)==-EBUSY);
 assert(mca_charge_if_ops_unregister(&duplicate)==-ENOENT);
 assert(mca_charge_if_op_set("test",0,1,"1")==-EOPNOTSUPP);
 assert(mca_charge_if_op_set("test",0,1,"junk")==-EINVAL);
 assert(mca_charge_ship_mode_show(&suspended)==-EOPNOTSUPP);
 assert(!mca_charge_if_common_sysfs_set("test",MCA_CHARGE_IF_CHG_TYPE_ALL,0,"1"));
 assert(calls==1 && event_count==1);
 assert(event_code==(CONFIG_TARGET_PRODUCT_NEZHA?MCA_EVENT_BATTERY_STS_CHANGE:0x10));
 assert(battery_updates==!!CONFIG_TARGET_PRODUCT_NEZHA);
 if(CONFIG_TARGET_PRODUCT_NEZHA){
  business_battery_event_process(&consumer.batt_info_nb,MCA_EVENT_BATTERY_HEALTH_CHANGE,NULL);
  assert(battery_updates==1);
 }
 assert(!mca_charge_suspend_state_show(&suspended) && suspended);
 a.data="0";assert(!mca_charge_suspend_state_show(&suspended) && !suspended);
 a.data="x";assert(mca_charge_suspend_state_show(&suspended)==-EINVAL);
 answer=-EIO;
 assert(mca_charge_if_common_sysfs_set("test",MCA_CHARGE_IF_CHG_TYPE_ALL,0,"1")==-EIO);
 assert(event_count==1 && battery_updates==!!CONFIG_TARGET_PRODUCT_NEZHA);
 assert(mca_charge_if_op_get(0,0,buf)==-EIO);
 assert(mca_charge_suspend_state_show(&suspended)==-EIO);
 answer=0;a.set_input_suspend=blocking;
 pthread_t r,u;assert(!pthread_create(&r,0,reader,0));
 while(!atomic_load(&entered))sched_yield();
 assert(!pthread_create(&u,0,remove_provider,&a));
 for(int i=0;i<10000;i++)sched_yield();
 assert(!atomic_load(&unregistered));atomic_store(&leave,1);
 pthread_join(r,0);pthread_join(u,0);assert(atomic_load(&unregistered));
 assert(mca_charge_if_op_set("test",0,0,"1")==-ENODEV);
 assert(mca_charge_if_ops_unregister(&a)==-ENOENT);
 puts("PASS: actual dispatch, missing callbacks, failure propagation, OSS battery consumer routing, legacy event and unregister wait (SRCU host model)");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-charge-test-') as d:
 t=Path(d);(t/'test.c').write_text(preamble+header+route+battery+notify+body+reg+tests)
 for nezha in (0,1):
  subprocess.run([os.getenv('CC','cc'),'-g','-fsanitize=address,undefined','-pthread',f'-DCONFIG_TARGET_PRODUCT_NEZHA={nezha}',str(t/'test.c'),'-o',str(t/'test')],check=True)
  subprocess.run([str(t/'test')],env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),check=True)

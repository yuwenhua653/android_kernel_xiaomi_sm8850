#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise provider withdrawal, receiver telemetry and voltage admission with modeled I/O."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1] / "drivers/power/supply/mca"
strategy = (root / "mca_strategy/strategy_wireless/mca_basic_wireless.c").read_text()
cp = (root / "mca_platform/mca_platform_cp_class.c").read_text()
cls = (root / "mca_platform/mca_platform_wireless_class.c").read_text()
chip = (root / "mca_hardware_ic/wireless_ic/sc96281/sc96281_core.c").read_text()


def function(src, name):
    match = re.search(r"^(?:static )?int\s+" + name + r"\([^;]*?\)\s*\{", src, re.M)
    assert match, name
    return src[match.start():src.index("\n}", match.end()) + 2] + "\n"


for fun in re.findall(r"^int\s+(platform_class_wireless_\w+)\(", cls, re.M):
    body = function(cls, fun)
    if "platform_wireless_class_get_ic_ops(" in body:
        assert body.index("guard(srcu)") < body.index("platform_wireless_class_get_ic_ops("), fun

lookups = [m.start() for m in re.finditer(r"platform_cp_class_get_ic_ops\(role\)", cp)]
assert len(lookups) == 54
for i in lookups:
    assert "guard(srcu)(&cp_provider_srcu);" in cp[cp.rfind("\n{", 0, i):i]
pre = r"""
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
#include <errno.h>
#include <unistd.h>
typedef uint16_t u16;
typedef uint32_t u32;
#define __rcu
#define WIRELESS_ROLE_MAX 2
#define GFP_KERNEL 0
#define DEFINE_MUTEX(x) pthread_mutex_t x=PTHREAD_MUTEX_INITIALIZER
#define DEFINE_STATIC_SRCU(x) static pthread_rwlock_t x=PTHREAD_RWLOCK_INITIALIZER
#define guard(name) __attribute__((cleanup(release_##name))) __auto_type guard_##name=take_##name
static pthread_mutex_t *take_mutex(pthread_mutex_t *m){assert(!pthread_mutex_lock(m));return m;}
static void release_mutex(pthread_mutex_t **m){assert(!pthread_mutex_unlock(*m));}
static pthread_rwlock_t *take_srcu(pthread_rwlock_t *s){assert(!pthread_rwlock_rdlock(s));return s;}
static void release_srcu(pthread_rwlock_t **s){assert(!pthread_rwlock_unlock(*s));}
#define mutex_lock(p) ((void)pthread_mutex_lock(p))
#define mutex_unlock(p) ((void)pthread_mutex_unlock(p))
#define srcu_dereference(p,l) __atomic_load_n(&(p),__ATOMIC_ACQUIRE)
#define rcu_access_pointer(p) srcu_dereference(p,0)
#define rcu_dereference_protected(p,l) srcu_dereference(p,0)
#define rcu_assign_pointer(p,v) __atomic_store_n(&(p),v,__ATOMIC_RELEASE)
#define RCU_INIT_POINTER(p,v) rcu_assign_pointer(p,v)
static void synchronize_srcu(pthread_rwlock_t *s){pthread_rwlock_wrlock(s);pthread_rwlock_unlock(s);}
#define kmalloc(n,flags) malloc(n)
#define kfree free
#define EXPORT_SYMBOL(x)
#define platform_wireless_ops_invalid(p,field) (!(p)||!(p)->ops||!(p)->ops->field)
struct platform_class_wireless_ops {int (*wls_get_vout)(int *,void *);};
#define CP_ROLE_MAX 3
#define platform_cp_ops_invalid(p,field) (!(p)||!(p)->ops||!(p)->ops->field)
struct platform_class_cp_ops {int (*cp_get_mode)(int *,void *); int (*cp_get_battery_vout)(void *);};
"""
registry = cls[cls.index("struct platform_wireless_class_ops_data {"):cls.index("struct platform_wireless_dev {")]
registry += cls[cls.index("static inline struct platform_wireless_class_ops_data *"):
                cls.index("int platform_class_wireless_enable_reverse_chg")]
registry += function(cls, "platform_class_wireless_get_vout")
registry += cp[cp.index("struct platform_cp_class_ops_data {"):cp.index("struct platform_cp_dev {")]
registry += cp[cp.index("static DEFINE_MUTEX(cp_provider_lock)"):cp.index("#define platform_cp_ext_ops_invalid")]
registry += function(cp, "platform_class_cp_get_mode")
mock = r"""
static pthread_barrier_t entered, leave;
static atomic_int withdrawn;
static int owner;
static int held_read(int *out,void *p) {
    assert(p==&owner);pthread_barrier_wait(&entered);pthread_barrier_wait(&leave);*out=7;return 0;
}
static struct platform_class_wireless_ops ops={held_read};
static void *reader(void *arg){int v;assert(!platform_class_wireless_get_vout(0,&v)&&v==7);return NULL;}
static void *remove_it(void *arg){assert(!platform_class_wireless_unregister_ops(0,&owner,&ops));atomic_store(&withdrawn,1);return NULL;}
static struct platform_class_cp_ops cp_ops={held_read};
static void *cp_reader(void *arg){int v;assert(!platform_class_cp_get_mode(0,&v)&&v==7);return NULL;}
static void *cp_remove(void *arg){assert(!platform_class_cp_unregister_ops(0,&cp_ops,&owner));atomic_store(&withdrawn,1);return NULL;}
#define READ_ONCE(x) (x)
#define ABS abs
#define ABS_CEP_VALUE 4
#define VOUT_SET_MIN_MV 4000
#define VOUT_SET_DEFAULT_MV 6000
#define VOUT_SET_MAX_MV 19500
#define WORK_MODE_RX 2
#define WORK_MODE_TX 4
#define WORK_MODE_SLEEP 512
#define msleep(x) ((void)0)
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define clamp(x,lo,hi) ((x)<(lo)?(lo):(x)>(hi)?(hi):(x))
enum power_supply_property {POWER_SUPPLY_PROP_PRESENT,POWER_SUPPLY_PROP_ONLINE,POWER_SUPPLY_PROP_VOLTAGE_NOW,POWER_SUPPLY_PROP_CURRENT_NOW};
union power_supply_propval {int intval;};
struct sc96281 {bool ready,tx_requested,fod_valid,fod_fault;int workqueue,pg_detect_work;int enable_gpio,power_good_gpio;pthread_mutex_t fod_lock,data_transfer_lock;
    struct {bool power_good_flag,parallel_charge;int vout_setted,adapter_type; uint8_t uuid[4];}proc_data;};
struct power_supply {struct sc96281 *chip;};
#define power_supply_get_drvdata(p) ((p)->chip)
static int pg=1,sleep_pin=0,adc_error,mode_error,hw_mode=WORK_MODE_RX,voltage=5100,current=342,cep_error,cep,writes;
static int gpio_get_value_cansleep(int pin){return pin?pg:sleep_pin;}
#define read_cust(c,f,o) (mode_error?mode_error:(*(o)=hw_mode,0))
static int sc96281_rx_get_vout(struct sc96281 *c,u16 *v){if(!adc_error)*v=voltage;return adc_error;}
static int sc96281_rx_get_iout(struct sc96281 *c,u16 *v){if(!adc_error)*v=current;return adc_error;}
static int sc96281_rx_get_ce_value(struct sc96281 *c,int8_t *out){*out=cep;return cep_error;}
static int sc96281_rx_set_Vout(struct sc96281 *c,u16 v){writes++;return adc_error;}
"""
auth = r"""
typedef uint8_t u8;
typedef uint32_t u32;
#define AUTH_STATUS_UUID_OK 4
struct mca_votable {bool on;int limit;int error;};
struct strategy_wireless_dev {
    bool ready,stopping;
    struct {u32 uuid_value;int auth_data;} proc_data;
    struct mca_votable *charge_limit_voter,*sw_thermal_ichg_voter;
};
static int mca_vote(struct mca_votable *v,const char *client,bool on,int ma){
    assert(!strcmp(client,"wireless_thermal_xiaomi_car"));v->on=on;v->limit=ma;return v->error;
}
#define PROJECT_FLAG_UUID 8
#define PROJECT_FLAG_ADAPTER_TYPE 4
#define ADAPTER_NONE 0
#define ADAPTER_AUTH_FAILED 99
#define dev_err_ratelimited(...) ((void)0)
static int flags_reg,adapter_reg,uuid_reg,bad_reg,retired,rx_events;
enum {REG_flags=1,REG_adapter,REG_uuid};
#define read_cust(c,field,out) read_mock(#field,out,sizeof(*(out)))
static int read_mock(const char *name,void *out,size_t n){
    int id = strstr(name,"fun_flag")?REG_flags:strstr(name,"adapter_type")?REG_adapter:REG_uuid;
    int value = id==REG_flags?flags_reg:id==REG_adapter?adapter_reg:uuid_reg;
    if(id==bad_reg)return -EIO;
    memcpy(out,&value,n);return 0;
}
static void put_unaligned_be32(u32 v,u8 *out){out[0]=v>>24;out[1]=v>>16;out[2]=v>>8;out[3]=v;}
static int sc96281_drive_rx(struct sc96281 *c,bool on){assert(!on);retired++;return 0;}
#define mod_delayed_work(q,w,t) ((void)(rx_events++))
"""
test = r"""
int main(void){
 pthread_barrier_init(&entered,NULL,2);pthread_barrier_init(&leave,NULL,2);
 assert(!platform_class_wireless_register_ops(0,&owner,&ops));
 assert(platform_class_wireless_register_ops(0,&owner,&ops)==-EBUSY);
 int other,v;assert(platform_class_wireless_unregister_ops(0,&other,&ops)==-ENOENT);
 pthread_t read_thread,del_thread;pthread_create(&read_thread,NULL,reader,NULL);pthread_barrier_wait(&entered);
 pthread_create(&del_thread,NULL,remove_it,NULL);
 while(rcu_access_pointer(platform_wireless_data[0])) sched_yield();
 assert(platform_class_wireless_get_vout(0,&v)==-EOPNOTSUPP&&!atomic_load(&withdrawn));
 pthread_barrier_wait(&leave);pthread_join(read_thread,NULL);pthread_join(del_thread,NULL);assert(withdrawn);
 assert(!platform_class_wireless_register_ops(0,&other,&ops));assert(!platform_class_wireless_unregister_ops(0,&other,&ops));
 assert(platform_class_cp_register_ops_v2(0,&cp_ops,&owner,1)==-EINVAL);
 assert(!platform_class_cp_register_ops(0,&cp_ops,&owner));
 assert(platform_class_cp_register_ops(0,&cp_ops,&other)==-EBUSY);
 assert(platform_class_cp_unregister_ops(0,&cp_ops,&other)==-ENOENT);
 atomic_store(&withdrawn,0);pthread_create(&read_thread,NULL,cp_reader,NULL);pthread_barrier_wait(&entered);
 pthread_create(&del_thread,NULL,cp_remove,NULL);while(rcu_access_pointer(g_platform_cp_data[0]))sched_yield();
 assert(platform_class_cp_get_mode(0,&v)<0&&!atomic_load(&withdrawn));pthread_barrier_wait(&leave);
 pthread_join(read_thread,NULL);pthread_join(del_thread,NULL);assert(withdrawn);
 assert(!platform_class_cp_register_ops(0,&cp_ops,&other));assert(!platform_class_cp_unregister_ops(0,&cp_ops,&other));
 struct sc96281 c={.ready=true,.fod_valid=true,.power_good_gpio=1,.proc_data={true,true,5000},
                    .fod_lock=PTHREAD_MUTEX_INITIALIZER,.data_transfer_lock=PTHREAD_MUTEX_INITIALIZER};
 struct power_supply supply={&c};union power_supply_propval val={0};
 assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_PRESENT,&val)&&val.intval==1);
 assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_ONLINE,&val)&&val.intval==1);
 assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_VOLTAGE_NOW,&val)&&val.intval==5100000);
 assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_CURRENT_NOW,&val)&&val.intval==342000);
 val.intval=-77;adc_error=-EIO;assert(sc96281_supply_get(&supply,POWER_SUPPLY_PROP_ONLINE,&val)==-EIO&&val.intval==-77);
 adc_error=0;mode_error=-EREMOTEIO;assert(sc96281_supply_get(&supply,POWER_SUPPLY_PROP_ONLINE,&val)==-EREMOTEIO);
 mode_error=0;hw_mode=WORK_MODE_RX|WORK_MODE_SLEEP;assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_ONLINE,&val)&&val.intval==0);
 hw_mode=WORK_MODE_RX;c.tx_requested=true;assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_PRESENT,&val)&&!val.intval);
 c.tx_requested=false;voltage=0;assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_ONLINE,&val)&&!val.intval);
 c.fod_valid=false;assert(sc96281_set_vout(9000,&c)==-EAGAIN&&!writes);
 assert(sc96281_supply_get(&supply,POWER_SUPPLY_PROP_CURRENT_NOW,&val)==-ENODATA);
 c.fod_valid=true;cep_error=-EIO;assert(sc96281_set_vout(9000,&c)==-EIO&&!writes);
 cep_error=0;cep=6;assert(sc96281_set_vout(9000,&c)==-EAGAIN&&!writes);
 cep=0;assert(!sc96281_set_vout(9000,&c)&&writes==1&&c.proc_data.vout_setted==9000);
 pg=0;assert(!sc96281_supply_get(&supply,POWER_SUPPLY_PROP_ONLINE,&val)&&!val.intval);
 flags_reg=0;c.fod_valid=true;v=-1;assert(!sc96281_get_auth_value(&v,&c)&&!v&&c.fod_valid);
 flags_reg=12;adapter_reg=20;uuid_reg=0x10203040;
 for(bad_reg=1;bad_reg<=3;bad_reg++){
     c.fod_fault=false;c.fod_valid=true;v=-1;
     assert(sc96281_get_auth_value(&v,&c)==-EIO&&v==-1&&c.fod_fault&&!c.fod_valid);
     assert(!c.proc_data.uuid[0]&&!c.proc_data.adapter_type);
 }
 assert(retired==3&&rx_events==3);bad_reg=0;c.fod_fault=false;c.fod_valid=true;
 assert(!sc96281_get_auth_value(&v,&c)&&v==12&&!c.fod_valid&&c.proc_data.adapter_type==20);
 assert(!memcmp(c.proc_data.uuid,(u8[]){0x10,0x20,0x30,0x40},4));
 struct mca_votable main_limit={0},sw_limit={0};
 struct strategy_wireless_dev policy={.ready=true,.charge_limit_voter=&main_limit,.sw_thermal_ichg_voter=&sw_limit};
 for(int n=0;n<3;n++){
    policy.proc_data.uuid_value=(u32[]){0x01070e01,0x0e0e0205,0x11223344}[n];policy.proc_data.auth_data=4;
    assert(!strategy_wireless_set_auth_car(NULL,&policy,440,"thermal"));assert(main_limit.on==(n<2)&&sw_limit.on==(n<2));
 }
 policy.proc_data.uuid_value=0x01070e01;policy.proc_data.auth_data=0;
 assert(!strategy_wireless_set_auth_car(NULL,&policy,440,"thermal")&&!main_limit.on&&!sw_limit.on);
 policy.proc_data.auth_data=4;main_limit.error=-EIO;sw_limit.error=-EBUSY;
 assert(strategy_wireless_set_auth_car(NULL,&policy,330,"thermal")==-EIO&&sw_limit.limit==330);
 main_limit.error=0;assert(strategy_wireless_set_auth_car(NULL,&policy,0,NULL)==-EBUSY&&!main_limit.on&&!sw_limit.on);
 puts("PASS synchronized wireless/CP provider withdrawal and rebind, transactional authentication, FOD/CEP voltage gating and receiver telemetry");
}
"""
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    auth_functions = chip[chip.index("static void sc96281_fod_failure_locked"):
                          chip.index("static int sc96281_apply_fod_locked", chip.index("static void sc96281_fod_failure_locked"))]
    (p / "test.c").write_text(pre + registry + mock + function(chip, "sc96281_supply_get") +
                             function(chip, "sc96281_set_vout") + "\n#undef read_cust\n" +
                             auth + auth_functions + function(strategy, "strategy_wireless_set_auth_car") + test)
    subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-pthread", "-fsanitize=address,undefined",
                    str(p / "test.c"), "-o", str(p / "test")], check=True)
    subprocess.run([str(p / "test")], check=True)

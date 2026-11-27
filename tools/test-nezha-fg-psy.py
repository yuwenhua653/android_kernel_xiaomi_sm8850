#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual FG registry/bridge C, host sanitizers and modeled SRCU/devres only."""
import ast, os, re, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
base=root/'drivers/power/supply/mca'
s=(base/'mca_strategy/strategy_fg/mca_strategy_fg_class.c').read_text()
s=s[s.index('struct mca_fg_entry {'):s.index('static int __init')]
h=(base/'include/mca/strategy/strategy_fg_class.h').read_text().replace('#include <linux/types.h>','')
b=(base/'mca_strategy/strategy_fg/mca_nezha_fg_psy.c').read_text()
b=b[b.index('struct nezha_fg_psy {'):b.index('static const struct of_device_id')]
# Reuse the documented pthread SRCU model, without executing its test.
tree=ast.parse((root/'tools/test-mca-strategy-lifetime.py').read_text())
pre=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='pre' for t in n.targets))
props=sorted(set(re.findall(r'POWER_SUPPLY_PROP_\w+',b)))
pre+='\n#include <limits.h>\n#include <string.h>\nenum power_supply_property {'+','.join(props)+',PROP_COUNT};\n'
pre+=r'''
#define POWER_SUPPLY_STATUS_FULL 4
#define EPROBE_DEFER 517
#define ERR_PTR(x) ((void *)(long)(x))
#define PTR_ERR(x) ((long)(x))
#define IS_ERR(x) ((unsigned long)(x) >= (unsigned long)-4095)
union power_supply_propval {int intval;};
struct power_supply {int unused;};
static struct power_supply psy;
static int values[PROP_COUNT], errors[PROP_COUNT];
static int power_supply_get_property(struct power_supply *p,enum power_supply_property prop,union power_supply_propval *v){assert(p==&psy);if(errors[prop])return errors[prop];v->intval=values[prop];return 0;}
struct device {int unused;};struct platform_device {struct device dev;};
static int supplier_error,action_error,refs,nactions;
static void *allocation;
static struct {void (*fn)(void*);void *data;} actions[4];
static void release_mem(void *p){assert(!refs);kfree(p);allocation=NULL;}
static void release_psy(void *p){assert(!rcu_access_pointer(fg_entry));assert(refs==1);refs--;}
static void add_action(void (*fn)(void*),void *data){actions[nactions].fn=fn;actions[nactions++].data=data;}
static void *devm_kzalloc(struct device*d,size_t n,int f){allocation=kzalloc(n,f);if(allocation)add_action(release_mem,allocation);return allocation;}
static struct power_supply *devm_power_supply_get_by_phandle(struct device*d,const char *name){assert(!strcmp(name,"power-supplies"));if(supplier_error==1)return NULL;if(supplier_error)return ERR_PTR(supplier_error);refs++;add_action(release_psy,&psy);return &psy;}
static int dev_err_probe(struct device*d,int ret,const char *fmt,...){return ret;}
static int devm_add_action_or_reset(struct device*d,void(*fn)(void*),void*p){if(action_error){fn(p);return action_error;}add_action(fn,p);return 0;}
static void cleanup(void){while(nactions){--nactions;actions[nactions].fn(actions[nactions].data);}assert(!refs);}
'''
# release_psy references registry; place stubs after registry definitions.
split=pre.index('struct device {')
pre,stubs=pre[:split],pre[split:]
test=r'''
static int a=3,bdata=4;
static atomic_int entered,leave,removed;
static int block(void *p,int*out){atomic_store(&entered,1);while(!atomic_load(&leave))sched_yield();*out=*(int*)p;return 0;}
static void *reader(void*p){int v;assert(!strategy_class_fg_ops_get_voltage(&v)&&v==3);return NULL;}
static void *remover(void*p){assert(!strategy_class_fg_ops_unregister(&a));atomic_store(&removed,1);return NULL;}
int main(void){
 struct platform_device p={0};int v=99;bool auth=true;pthread_t rd,wr;
 struct strategy_fg_class_ops ops={.strategy_fg_get_voltage=block};
 assert(strategy_class_fg_ops_get_voltage(&v)==-ENODEV&&v==99);
 assert(!strategy_class_fg_ops_get_charging_done());
 assert(strategy_class_fg_ops_get_voltage(NULL)==-EINVAL);
 assert(strategy_class_fg_ops_get_soc_decimal(&v,NULL)==-EINVAL);
 assert(strategy_class_fg_ops_register(NULL,&ops)==-EINVAL);
 fail_alloc=1;assert(strategy_class_fg_ops_register(&a,&ops)==-ENOMEM);fail_alloc=0;
 assert(!strategy_class_fg_ops_register(&a,&ops));
 assert(strategy_class_fg_ops_register(&bdata,&ops)==-EBUSY);
 assert(strategy_class_fg_ops_unregister(&bdata)==-ENOENT);
 pthread_create(&rd,NULL,reader,NULL);while(!atomic_load(&entered))sched_yield();
 pthread_create(&wr,NULL,remover,NULL);while(rcu_access_pointer(fg_entry))sched_yield();
 assert(!atomic_load(&removed));atomic_store(&leave,1);pthread_join(rd,NULL);pthread_join(wr,NULL);
 assert(!atomic_load(&live));
 supplier_error=1;assert(nezha_fg_probe(&p)==-EPROBE_DEFER);cleanup();
 supplier_error=-ENODEV;assert(nezha_fg_probe(&p)==-ENODEV);cleanup();
 supplier_error=0;action_error=-ENOMEM;assert(nezha_fg_probe(&p)==-ENOMEM);cleanup();
 action_error=0;assert(!nezha_fg_probe(&p));assert(refs==1);
 values[POWER_SUPPLY_PROP_VOLTAGE_NOW]=4400123;
 assert(!strategy_class_fg_ops_get_voltage(&v)&&v==4400);
 values[POWER_SUPPLY_PROP_CURRENT_NOW]=2500000;
 assert(!strategy_class_fg_ops_get_current(&v)&&v==-2500000);
 values[POWER_SUPPLY_PROP_CURRENT_NOW]=-350000;
 assert(!strategy_class_fg_ops_get_current(&v)&&v==350000);
 values[POWER_SUPPLY_PROP_TEMP]=-50;assert(!strategy_class_fg_ops_get_temperature(&v)&&v==-50);
 values[POWER_SUPPLY_PROP_CAPACITY]=87;assert(strategy_class_fg_ops_get_soc()==87);
 assert(!strategy_class_fg_ops_get_rsoc(&v)&&v==87);
 values[POWER_SUPPLY_PROP_CHARGE_NOW]=1234000;assert(!strategy_class_fg_get_rm(&v)&&v==1234000);
 values[POWER_SUPPLY_PROP_STATUS]=POWER_SUPPLY_STATUS_FULL;assert(strategy_class_fg_ops_get_charging_done());
 errors[POWER_SUPPLY_PROP_STATUS]=-EIO;assert(!strategy_class_fg_ops_get_charging_done());
 errors[POWER_SUPPLY_PROP_VOLTAGE_NOW]=-EIO;v=77;assert(strategy_class_fg_ops_get_voltage(&v)==-EIO&&v==77);
 values[POWER_SUPPLY_PROP_CURRENT_NOW]=INT_MIN;assert(strategy_class_fg_ops_get_current(&v)==-ERANGE&&v==77);
 values[POWER_SUPPLY_PROP_CAPACITY]=101;assert(strategy_class_fg_ops_get_soc()==-ERANGE);
 assert(strategy_class_fg_set_fastcharge(true)==-EOPNOTSUPP);
 assert(strategy_class_fg_get_authentic(&auth)==-EOPNOTSUPP&&auth);
 assert(strategy_class_fg_ops_set_charging_done(true)==-EOPNOTSUPP);
 cleanup();assert(!atomic_load(&live));assert(strategy_class_fg_ops_get_voltage(&v)==-ENODEV);
 puts("PASS: actual FG registry/bridge units, sign, unsupported operations, failures, supplier deferral, devres order and concurrent unregister");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(pre+h+s+stubs+b+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-O1','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(c),'-o',str(exe)],check=True)
 env=dict(os.environ);env.setdefault('ASAN_OPTIONS','detect_leaks=0');subprocess.run([str(exe)],check=True,env=env,timeout=30)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test actual USB init/update/cleanup with modelled power_supply/devres APIs."""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
b=root/'drivers/power/supply/mca/mca_business/business_charger'
s=(b/'mca_charger_usb_psy.c').read_text();s=s[s.index('void business_charger_update_usb_psy'):]
h=(b/'inc/mca_charger_usb_psy.h').read_text();h=h[h.index('struct usb_psy_info {'):h.index('/* Returns ERR_PTR')]
constants=sorted(set(re.findall(r'\b(?:XM_CHARGER_TYPE_|POWER_SUPPLY_TYPE_)\w+',s)))
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
#define IS_ENABLED(x) (x)
#define ERR_PTR(e) ((void*)(intptr_t)(e))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p)||IS_ERR(p))
#define mca_log_err(...) ((void)0)
#define pr_err(...) ((void)0)
struct device {void *of_node;};
struct power_supply_desc {int type;};
struct power_supply {struct power_supply_desc *desc;int refs;};
struct power_supply_config {void *drv_data,*of_node;};
static struct power_supply_desc _usb_psy_desc,owner_desc={.type=777};
static struct power_supply owner={.desc=&owner_desc},battery,owned={.desc=&_usb_psy_desc};
static int unavailable,alloc_fail,action_fail,register_fail,registered,unregisters,changes;
static void (*action)(void *);static void *action_data,*allocation;
static void *devm_kzalloc(struct device *dev,size_t n,int f){if(alloc_fail)return NULL;assert(!allocation);return allocation=calloc(1,n);}
static struct power_supply *power_supply_get_by_name(const char *name){
 struct power_supply *p=!strcmp(name,"usb")?&owner:&battery;
 if(unavailable&&p==&owner)return NULL;p->refs++;return p;
}
static void power_supply_put(struct power_supply *p){assert(p->refs>0);p->refs--;}
static void power_supply_changed(struct power_supply *p){assert(p);changes++;}
static struct power_supply *power_supply_register(struct device *d,struct power_supply_desc *desc,struct power_supply_config *cfg){
 if(register_fail)return ERR_PTR(-EIO);assert(!registered);registered=1;return &owned;
}
static void power_supply_unregister(struct power_supply *p){assert(p==&owned&&registered);registered=0;unregisters++;}
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *data){
 if(action_fail){fn(data);return -ENOMEM;}assert(!action);action=fn;action_data=data;return 0;
}
static void devm_release_action(struct device *d,void (*fn)(void *),void *data){assert(action==fn&&action_data==data);action=NULL;fn(data);}
static void cleanup(struct device *d){if(action){void (*fn)(void*)=action;action=NULL;fn(action_data);}assert(!registered);free(allocation);allocation=NULL;assert(!owner.refs&&!battery.refs);}
'''
test=r'''
int main(void){
 struct device d={0};struct usb_psy_info *i;
 alloc_fail=1;i=business_charger_usb_psy_init(&d);assert(PTR_ERR(i)==-ENOMEM);alloc_fail=0;
 if(CONFIG_TARGET_PRODUCT_NEZHA){unavailable=1;i=business_charger_usb_psy_init(&d);assert(PTR_ERR(i)==-EPROBE_DEFER);cleanup(&d);unavailable=0;}
 else {register_fail=1;i=business_charger_usb_psy_init(&d);assert(PTR_ERR(i)==-EIO);cleanup(&d);register_fail=0;}
 action_fail=1;i=business_charger_usb_psy_init(&d);assert(PTR_ERR(i)==-ENOMEM);cleanup(&d);action_fail=0;
 i=business_charger_usb_psy_init(&d);assert(!IS_ERR(i));
 business_charger_update_usb_psy(XM_CHARGER_TYPE_PD,i);assert(changes==2);
 if(CONFIG_TARGET_PRODUCT_NEZHA){assert(i->usb_psy==&owner&&owner_desc.type==777&&!registered&&!i->usb_psy_desc);}
 else {assert(i->usb_psy==&owned&&_usb_psy_desc.type==POWER_SUPPLY_TYPE_USB_PD&&registered);}
 business_charger_usb_psy_deinit(i);business_charger_usb_psy_deinit(i);cleanup(&d);
 i=business_charger_usb_psy_init(&d);assert(!IS_ERR(i));cleanup(&d); /* later probe failure/unbind */
 if(CONFIG_TARGET_PRODUCT_NEZHA)assert(!unregisters);
 puts("PASS: USB owned/borrowed lifetime, descriptor isolation, deferral, allocation/register/action failure and repeated cleanup");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';c.write_text(pre+'\nenum {'+','.join(constants)+'};\n'+h+s+test)
 for nezha in (0,1):
  exe=Path(tmp)/str(nezha)
  subprocess.run([os.getenv('CC','cc'),'-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer','-DCONFIG_TARGET_PRODUCT_NEZHA='+str(nezha),str(c),'-o',str(exe)],check=True)
  env=dict(os.environ);env.setdefault('ASAN_OPTIONS','detect_leaks=0');subprocess.run([str(exe)],check=True,env=env)

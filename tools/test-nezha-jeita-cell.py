#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the BQ27Z561 frame reader and JEITA cell selection against a modeled gauge."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1] / "drivers/power/supply"
gauge = (root / "bq27xxx_battery.c").read_text()
jeita = (root / "mca/mca_strategy/strategy_charger/mca_buckchg_jeita.c").read_text()


def function(src, name):
    start = src.index("static int " + name + "(")
    return src[start:src.index("\n}", start) + 2] + "\n"


pre = r"""
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof(*(x)))
#define guard(mutex) (void)
#define usleep_range(a,b) ((void)0)
#define EPROBE_DEFER 517
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define FG_IC_MASTER 0
#define POWER_SUPPLY_PROP_MANUFACTURER 1
struct bq27xxx_device_info {
 int lock;
 struct {
   int (*write)(struct bq27xxx_device_info *,u8,int,bool);
   int (*read_bulk)(struct bq27xxx_device_info *,u8,u8*,int);
 } bus;
};
static int write_error,read_error,queries,refs;
static u8 wire[36];
static int write_reg(struct bq27xxx_device_info *d,u8 reg,int cmd,bool single){
 assert(reg==0x3e&&cmd==0x4b&&!single);queries++;return write_error;
}
static int read_reg(struct bq27xxx_device_info *d,u8 reg,u8 *buf,int size){
 assert(reg==0x3e&&size==36);if(read_error)return read_error;memcpy(buf,wire,36);return 0;
}
static void frame(u8 cell){
 memset(wire,0,sizeof(wire));wire[0]=0x4b;wire[2]='X';wire[3]=cell;wire[35]=8;
 u8 sum=0;for(int i=0;i<6;i++)sum+=wire[i];wire[34]=~sum;
}
static struct bq27xxx_device_info di={.bus={write_reg,read_reg}};
struct power_supply {};
struct device_node {bool has_fg;};
union power_supply_propval {const char *strval;};
static struct power_supply ps,*provider=&ps;
static bool of_property_present(struct device_node *n,const char *key){return n->has_fg;}
static struct power_supply *power_supply_get_by_phandle(struct device_node *n,const char *key){
 assert(!strcmp(key,"xiaomi,cell-supply"));if(provider && !IS_ERR(provider))refs++;return provider;
}
static void power_supply_put(struct power_supply *p){assert(p==&ps&&refs==1);refs--;}
static int platform_fg_ops_get_batt_cell_info(int role,const char **s){*s="lwn";return 0;}
"""
bridge = r"""
static int power_supply_get_property(struct power_supply *p,int prop,union power_supply_propval *v){
 assert(p==&ps&&refs==1&&prop==POWER_SUPPLY_PROP_MANUFACTURER);
 return bq27z561_cell_manufacturer(&di,&v->strval);
}
"""
main = r"""
int main(void){
 struct device_node node={true};bool second=false;const char *value="unchanged";
 frame('L');assert(!mca_jeita_second_cell(&node,&second)&&second&&!refs);
 frame('F');assert(!mca_jeita_second_cell(&node,&second)&&!second&&!refs);
 for(int i=0;i<7;i++){
   frame('L');write_error=i==0?-EIO:0;read_error=i==1?-ETIMEDOUT:0;
   if(i==2)wire[0]++;if(i==3)wire[35]=7;if(i==4)wire[35]=37;if(i==5)wire[34]++;if(i==6)frame('K');
   int expected=(int[]){-EIO,-ETIMEDOUT,-EPROTO,-EPROTO,-EPROTO,-EBADMSG,-ENODATA}[i];
   assert(bq27z561_cell_manufacturer(&di,&value)==expected&&!strcmp(value,"unchanged"));
   second=false;assert(mca_jeita_second_cell(&node,&second)==expected&&!second&&!refs);
 }
 provider=NULL;assert(mca_jeita_second_cell(&node,&second)==-EPROBE_DEFER);
 provider=(void*)(intptr_t)-EINVAL;assert(mca_jeita_second_cell(&node,&second)==-EINVAL);
 node.has_fg=false;assert(!mca_jeita_second_cell(&node,&second)&&second);
 puts("PASS BQ27Z561 chemistry query, cell selection, short/wrong/checksum replies, unavailable gauge and balanced references");
}
"""
with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / "test.c"
    exe = c.with_suffix("")
    c.write_text(pre + function(gauge, "bq27z561_cell_manufacturer") + bridge +
                 function(jeita, "mca_jeita_second_cell") + main)
    subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-fsanitize=address,undefined",
                    str(c), "-o", str(exe)], check=True)
    subprocess.run([exe], check=True)

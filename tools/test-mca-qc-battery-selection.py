#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual QC battery selector: OF ownership, mode/role and supplier errors.
Host API models only. Temperature/voltage table parsing is not exercised here.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'drivers/power/supply/mca/mca_strategy/strategy_charger/mca_strategy_quickchg.c').read_text()
a=s.index('static int mca_quick_charge_parse_batt_info(');z=s.index('\nstatic const int batt_para_cc_thr_list',a);body=s[a:z]
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define EPROBE_DEFER 517
#define BATT_PARA_MAX_GROUP 16
#define MCA_BATTERY_TYPE_SINGLE_NUM_MAX 1
#define CountryCN 0
enum {FG_IC_MASTER,FG_IC_SLAVE};
enum {MCA_QUICK_CHG_BATT_ROLE,MCA_QUICK_CHG_BATT_ID,MCA_QUICK_CHG_TEMP_PARA_NAME,MCA_QUICK_CHG_BATT_PARA_MAX};
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define mca_quick_charge_diag_context(...) ((void)0)
#define mca_quick_charge_diag_note(...) ((void)0)
#define mca_quick_charge_diag_cell(...) ((void)0)
#define mca_quick_charge_diag_table(...) ((void)0)
struct device_node {int unused;};
struct device {struct device_node *of_node;};
struct para {void *temp_info;};
struct mca_quick_charge_info {struct device *dev;int has_gbl_batt_para,batt_type;struct para batt_para[2],base_flip_para[2];};
struct mca_hwid {int country_version;};
static struct mca_hwid hwid;
static struct device_node local,global;
static int refs,missing_global,fg_error[2],fg_missing[2],count_error,read_failure,parse_error,seen_mode,parsed;
static const char *cells[]={"atl","atl"};
static const char *rows[]={"0","atl","temp","1","atl","temp"};
static const struct mca_hwid *mca_get_hwid_info(void) {return &hwid;}
static struct device_node *of_find_node_by_name(struct device_node *n,const char *name) {(void)n;(void)name;if(missing_global)return NULL;refs++;return &global;}
static void of_node_put(struct device_node *n) {if(n){assert(n==&global&&refs>0);refs--;}}
static int mca_parse_dts_count_strings(struct device_node *n,const char *name,int max,int cols) {(void)n;(void)max;(void)cols;seen_mode=!strcmp(name,"base_flip_para");assert(seen_mode||!strcmp(name,"batt_para"));return count_error?count_error:6;}
static int mca_parse_dts_string_index(struct device_node *n,const char *name,int idx,const char **out) {(void)n;(void)name;if(idx==read_failure)return -EIO;assert(idx>=0&&idx<6);*out=rows[idx];return 0;}
static int platform_fg_ops_get_batt_cell_info(int role,const char **out) {assert(role>=0&&role<2);*out=fg_missing[role]?NULL:cells[role];return fg_error[role];}
static const char *mca_quick_charge_check_model_name(const char *s) {return s;}
static int kstrtoint(const char *s,int base,int *out) {char *end;long v=strtol(s,&end,base);if(end==s||*end)return -EINVAL;*out=v;return 0;}
static int mca_quick_charge_parse_temp_para(struct device_node *n,int role,const char *name,struct mca_quick_charge_info *i,int mode) {
 (void)n;(void)name;assert(role>=0&&role<2);assert(mode==0||mode==1);if(parse_error)return parse_error;
 (mode?i->base_flip_para:i->batt_para)[role].temp_info=(void *)1;parsed++;return 0;
}
static struct device dev={.of_node=&local};
static void reset(struct mca_quick_charge_info *i) {
 assert(!refs);*i=(struct mca_quick_charge_info){.dev=&dev,.batt_type=2,.has_gbl_batt_para=1};hwid.country_version=1;
 missing_global=fg_error[0]=fg_error[1]=fg_missing[0]=fg_missing[1]=count_error=parse_error=parsed=0;read_failure=-1;rows[0]="0";rows[1]="atl";
}
'''
test=r'''
int main(void) {
 struct mca_quick_charge_info i;
 for(int mode=-1;mode<=4;mode++){reset(&i);assert(!mca_quick_charge_parse_batt_info(&i,mode));assert(seen_mode==!!mode&&parsed==2&&!refs);}
 reset(&i);missing_global=1;assert(mca_quick_charge_parse_batt_info(&i,0)==-ENOENT&&!refs);
 int errors[]={-ENODEV,-EPROBE_DEFER,-EIO,-EOPNOTSUPP};
 for(int role=0;role<2;role++)for(int e=0;e<4;e++){reset(&i);fg_error[role]=errors[e];assert(mca_quick_charge_parse_batt_info(&i,0)==(errors[e]==-ENODEV?-EPROBE_DEFER:errors[e]));assert(!refs&&!parsed);}
 for(int role=0;role<2;role++){reset(&i);fg_missing[role]=1;assert(mca_quick_charge_parse_batt_info(&i,0)==-EPROBE_DEFER&&!refs);}
 int counts[]={-EINVAL,-EIO,1,2,49,51};
 for(int n=0;n<6;n++){reset(&i);count_error=counts[n];assert(mca_quick_charge_parse_batt_info(&i,0)==(counts[n]<0?counts[n]:-EINVAL)&&!refs&&!parsed);}
 for(int n=0;n<6;n++){reset(&i);read_failure=n;assert(mca_quick_charge_parse_batt_info(&i,0)==-EIO&&!refs);}
 reset(&i);parse_error=-ENOMEM;assert(mca_quick_charge_parse_batt_info(&i,0)==-ENOMEM&&!refs);
 reset(&i);rows[0]="-1";assert(mca_quick_charge_parse_batt_info(&i,0)==-EINVAL&&!refs&&!parsed);
 reset(&i);rows[0]="2";assert(mca_quick_charge_parse_batt_info(&i,0)==-ENOENT&&!refs&&parsed==1);
 reset(&i);rows[1]="unknown";assert(mca_quick_charge_parse_batt_info(&i,0)==-ENOENT&&!refs);
 reset(&i);rows[1]="unknown";i.batt_para[0].temp_info=(void *)1;assert(mca_quick_charge_parse_batt_info(&i,1)==-ENOENT&&!refs); /* normal table cannot satisfy missing flip */
 reset(&i);i.has_gbl_batt_para=0;assert(!mca_quick_charge_parse_batt_info(&i,0)&&!refs);
 puts("PASS: actual QC battery selector, mode/role bounds, supplier errors, read failures, selected table and OF reference release");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-qc-selection-') as d:
 p=Path(d);(p/'test.c').write_text(pre+body+test)
 subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

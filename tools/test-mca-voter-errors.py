#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual MCA election/override/error paths with host API stubs.

Does not test global voter ownership, kernel mutexes, or charging hardware.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
s=(root/'drivers/power/supply/mca/mca_common/mca_voter.c').read_text()
h=(root/'drivers/power/supply/mca/include/mca/common/mca_voter.h').read_text().replace('#include <linux/types.h>','')
body=s[s.index('struct client_vote {'):s.index('struct mca_votable *mca_find_votable(')]
force=s[s.index('static int mca_force_active_get('):s.index('DEFINE_DEBUGFS_ATTRIBUTE(')]
c=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define NUM_MAX_CLIENTS 32
#define CLIENT_MAX_LEN 50
#define DEBUG_FORCE_CLIENT "DEBUG_FORCE_CLIENT"
#define EXPORT_SYMBOL(x)
#define GFP_KERNEL 0
#define mca_log_info(...) ((void)0)
#define mca_log_err(...) ((void)0)
#define mca_log_debug(...) ((void)0)
#define kstrdup(s,flags) strdup(s)
struct list_head { void *next, *prev; };
struct dentry;
struct mutex { int locked; };
static void mutex_lock(struct mutex *m) { assert(!m->locked); m->locked=1; }
static void mutex_unlock(struct mutex *m) { assert(m->locked); m->locked=0; }
static int strscpy(char *out,const char *in,size_t n) { snprintf(out,n,"%s",in); return strlen(out); }
''' +h+body+force+r'''
static int failures,calls,last_value;
static char last_client[CLIENT_MAX_LEN];
static int cb(struct mca_votable *v,void *data,int value,const char *client) {
    assert(v->vote_lock.locked && data==&calls);
    calls++; last_value=value; snprintf(last_client,sizeof(last_client),"%s",client?client:"");
    if(failures) { failures--; return -EIO; } return 0;
}
static void setup(struct mca_votable *v,int type) {
    memset(v,0,sizeof(*v)); v->name="test"; v->num_clients=NUM_MAX_CLIENTS;
    v->type=type; v->default_value=900; v->effective_result=v->effective_client_id=-EINVAL;
    v->override_result=-EINVAL; v->callback=cb; v->data=&calls;
    failures=calls=last_value=0; last_client[0]=0;
}
static void done(struct mca_votable *v) {
    assert(!v->vote_lock.locked);
    for(int i=0;i<v->num_clients;i++) free(v->client_strs[i]);
}
int main(void) {
    struct mca_votable v;
    setup(&v,MCA_VOTE_MIN); failures=1;
    assert(mca_vote(&v,"thermal",true,500)==-EIO && calls==1 && !v.voted_on);
    assert(!mca_vote(&v,"thermal",true,500) && calls==2 && v.voted_on);
    assert(!mca_vote(&v,"thermal",true,500) && calls==2);
    failures=1; assert(mca_rerun_election(&v)==-EIO && !v.voted_on);
    assert(!mca_vote(&v,"thermal",true,500) && calls==4);
    assert(!mca_vote(&v,"jeita",true,300) && last_value==300);
    assert(!mca_vote(&v,"jeita",false,0) && last_value==500);
    assert(!mca_vote(&v,"thermal",false,0) && last_value==900);
    assert(!mca_vote_override(&v,"override",true,400) && mca_get_effective_result(&v)==400);
    failures=1; assert(mca_vote_override(&v,"override",false,0)==-EIO);
    assert(mca_get_effective_result(&v)==400 && v.override_result==400);
    assert(!mca_vote_override(&v,"override",false,0) && last_value==900);
    failures=1; assert(mca_vote_override(&v,"new",true,200)==-EIO && v.override_result==-EINVAL);
    v.force_val=100; failures=1;
    assert(mca_force_active_set(&v,1)==-EIO && !v.force_active);
    assert(!mca_force_active_set(&v,1) && v.force_active && last_value==100);
    int count=calls;
    assert(!mca_vote_override(&v,"while_forced",true,350) && calls==count);
    assert(!strcmp(v.override_client,"while_forced"));
    failures=1; assert(mca_force_active_set(&v,0)==-EIO && v.force_active);
    assert(!mca_force_active_set(&v,0) && !v.force_active && last_value==350);
    assert(!strcmp(last_client,"while_forced"));
    done(&v);
    setup(&v,MCA_VOTE_MIN); v.callback=NULL;
    assert(!mca_vote_override(&v,"aggregate",true,200) && mca_get_effective_result(&v)==200);
    assert(!mca_vote_override(&v,"aggregate",false,0) && mca_get_effective_result(&v)==900);
    assert(!mca_force_active_set(&v,1)); assert(!mca_force_active_set(&v,0)); done(&v);
    setup(&v,MCA_VOTE_MIN); v.force_val=100;
    assert(!mca_force_active_set(&v,1)); assert(!mca_force_active_set(&v,0) && last_value==900);
    assert(!mca_vote_override(&v,"initial",true,100));
    assert(!mca_vote_override(&v,"initial",false,0) && last_value==900); done(&v);
    setup(&v,MCA_VOTE_MAX);
    assert(!mca_vote(&v,"a",true,100)); assert(!mca_vote(&v,"b",true,200) && last_value==200); done(&v);
    setup(&v,MCA_VOTE_OR);
    assert(!mca_vote(&v,"a",true,0)); assert(!mca_vote(&v,"b",true,1) && last_value==1); done(&v);
    setup(&v,MCA_VOTE_AND);
    assert(!mca_vote(&v,"a",true,1)); assert(!mca_vote(&v,"b",true,0) && last_value==0); done(&v);
    setup(&v,NUM_VOTABLE_TYPES);
    assert(mca_vote(&v,"bad",true,1)==-EINVAL && !v.vote_lock.locked);
    v.type=MCA_VOTE_MIN; assert(!mca_vote(&v,"bad",true,1)); done(&v);
    assert(mca_vote(NULL,"a",true,1)==-EINVAL);
    puts("PASS: actual MCA voter callback retry, override/force error state, no-callback votes and invalid-type unlock");
}
'''
with tempfile.TemporaryDirectory(prefix='mca-voter-') as d:
    p=Path(d); (p/'test.c').write_text(c)
    subprocess.run([os.getenv('CC','cc'),'-std=gnu11','-O1','-g','-Wall','-Wno-unused-function','-Werror=implicit-function-declaration','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

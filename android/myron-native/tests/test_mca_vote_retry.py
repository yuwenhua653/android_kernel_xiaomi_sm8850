#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise production MCA elections and callback retry under injected failures."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(text, name):
    m = re.search(r'^(?:static\s+)?(?:int|void|char\s*\*)\s*'+name+r'\s*\(', text, re.M)
    if not m:
        raise ValueError(name)
    i = text.index('{', m.end())
    depth, end = 1, i + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[m.start():end]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel-root', required=True, type=Path)
    ap.add_argument('--source', type=Path)
    a = ap.parse_args()
    base = a.kernel_root/'drivers/power/supply/mca'
    s = (a.source or base/'mca_common/mca_voter.c').read_text()
    h = (base/'include/mca/common/mca_voter.h').read_text()
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define NUM_MAX_CLIENTS 32
#define CLIENT_MAX_LEN 50
#define GFP_KERNEL 0
#define kstrdup(s,f) strdup(s)
#define mca_log_info(...) ((void)0)
#define mca_log_debug(...) ((void)0)
#define mca_log_err(...) ((void)0)
struct list_head { int unused; };
struct dentry;
struct mutex { int held; };
typedef uint32_t u32;
static void mutex_lock(struct mutex *m) { assert(!m->held);m->held=1; }
static void mutex_unlock(struct mutex *m) { assert(m->held);m->held=0; }
'''
    for name in ['client_vote', 'mca_votable']:
        code += re.search(r'struct '+name+r'\s*\{.*?\n\};', s, re.S)[0]+'\n'
    code += re.search(r'enum mca_votable_type\s*\{.*?\};', h, re.S)[0]+'\n'
    for name in ['mca_lock_votable','mca_unlock_votable','mca_get_client_id',
                 'mca_get_client_str','mca_vote_min','mca_vote_max','mca_vote_or',
                 'mca_vote_and','mca_get_effective_result_locked','mca_vote','mca_rerun_election']:
        code += function(s, name)+'\n'
    code += r'''
static int calls, result, cb_ret, cases;
static int cb(struct mca_votable *v,void *data,int value,const char *client) {
 assert(v->vote_lock.held);calls++;result=value;return cb_ret;
}
static void init(struct mca_votable *v,int type) {
 *v=(struct mca_votable){.name="test",.num_clients=NUM_MAX_CLIENTS,.type=type,
  .callback=cb,.effective_client_id=-EINVAL,.effective_result=-EINVAL,
  .override_result=-EINVAL,.default_value=17};calls=0;result=-123;cb_ret=0;
}
static void finish(struct mca_votable *v) {
 assert(!v->vote_lock.held);
 for(int i=0;i<v->num_clients;i++)free(v->client_strs[i]);cases++;
}
int main(void) {
 struct mca_votable v;
 for(int type=0;type<NUM_VOTABLE_TYPES;type++)for(int failed=0;failed<2;failed++) {
  init(&v,type);cb_ret=failed?-EIO:0;
  int value=type<MCA_VOTE_OR?900:1;
  assert(mca_vote(&v,"a",true,value)==cb_ret && calls==1 && result==value);
  assert(v.voted_on==!failed);cb_ret=0;
  assert(!mca_vote(&v,"a",true,value) && calls==1+failed && v.voted_on);
  assert(!mca_vote(&v,"a",true,value) && calls==1+failed);finish(&v);
 }
 /* Exhaustive two-client elections; failures never replay a stale aggregate. */
 for(int type=0;type<NUM_VOTABLE_TYPES;type++)for(int a=0;a<4;a++)
 for(int b=0;b<4;b++)for(int ea=0;ea<2;ea++)for(int eb=0;eb<2;eb++) {
  init(&v,type);int av=type<MCA_VOTE_OR?a*100:!!a,bv=type<MCA_VOTE_OR?b*100:!!b;
  cb_ret=-EIO;assert(mca_vote(&v,"a",ea,av)==-EIO);
  int expected=17;
  if(ea)expected=av;
  if(eb) {
   if(!ea)expected=bv;
   else if(type==MCA_VOTE_MIN)expected=av<bv?av:bv;
   else if(type==MCA_VOTE_MAX)expected=av>bv?av:bv;
   else if(type==MCA_VOTE_OR)expected=av||bv;
   else expected=av&&bv;
  }
  cb_ret=0;assert(!mca_vote(&v,"b",eb,bv) && calls==2 && result==expected);
  assert(!mca_vote(&v,"b",eb,bv) && calls==2);finish(&v);
 }
 init(&v,MCA_VOTE_MIN);assert(!mca_vote(&v,"a",true,900));
 cb_ret=-EIO;assert(mca_rerun_election(&v)==-EIO && !v.voted_on);
 cb_ret=0;assert(!mca_vote(&v,"a",true,900) && calls==3 && v.voted_on);finish(&v);
 init(&v,MCA_VOTE_MIN);cb_ret=1;assert(mca_vote(&v,"a",true,900)==1 && v.voted_on);
 assert(!mca_vote(&v,"a",true,900) && calls==1);finish(&v);
 for(int kind=0;kind<3;kind++) {
  init(&v,MCA_VOTE_MIN);
  if(kind==0)v.callback=NULL;if(kind==1)v.force_active=true;if(kind==2)v.override_result=500;
  assert(!mca_vote(&v,"a",true,900) && !calls && v.voted_on);finish(&v);
 }
 init(&v,NUM_VOTABLE_TYPES);assert(mca_vote(&v,"a",true,900)==-EINVAL);finish(&v);
 assert(mca_vote(NULL,"a",true,900)==-EINVAL && mca_rerun_election(NULL)==-EINVAL);cases++;
 printf("PASS: %d production MCA vote/retry cases\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
        c.write_text(code)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                        '-Wno-misleading-indentation','-fsanitize=undefined',
                        '-fno-sanitize-recover=undefined',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)

if __name__ == '__main__':
    main()

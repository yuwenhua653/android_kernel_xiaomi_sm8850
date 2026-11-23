#!/usr/bin/env python3
"""Exercise real setlocalversion with clean/dirty Git, tags and other products."""
import argparse,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--script',type=Path,default=ROOT/'scripts/setlocalversion');a=ap.parse_args();script=a.script.resolve();checks=0
 with tempfile.TemporaryDirectory(prefix='myron-release-test-') as td:
  root=Path(td);src=root/'source';out=root/'out';src.mkdir();(out/'include/config').mkdir(parents=True)
  def git(*args):return subprocess.check_output(['git','-C',str(src),*args],stderr=subprocess.DEVNULL,text=True).strip()
  git('init','-q');git('config','user.name','Local release test');git('config','user.email','release-test@example.invalid');(src/'tracked').write_text('one\n');git('add','tracked');git('commit','-qm','base');head=git('rev-parse','HEAD')[:12]
  def run(myron=True,no_local=False,local=None,auto=True):
   env=dict(os.environ);env.pop('LOCALVERSION',None);env['KERNELVERSION']='6.12.118'
   if local is not None:env['LOCALVERSION']=local
   (out/'include/config/auto.conf').write_text('CONFIG_LOCALVERSION=\n'+('CONFIG_LOCALVERSION_AUTO=y\n' if auto else '')+('CONFIG_TARGET_PRODUCT_MYRON=y\n' if myron else ''))
   cmd=['sh',str(script)]+(['--no-local'] if no_local else [])+[str(src)]
   return subprocess.check_output(cmd,cwd=out,env=env,text=True).strip()
  assert run()=='6.12.118-g'+head+'-yuzuli';checks+=1
  (src/'tracked').write_text('local edit\n');status=git('status','--porcelain');assert run()=='6.12.118-g'+head+'-yuzuli';assert git('status','--porcelain')==status;checks+=1
  assert run(myron=False)=='6.12.118-g'+head+'-dirty';checks+=1
  assert run(no_local=True)=='6.12.118-g'+head;checks+=1
  assert run(local='-test')=='6.12.118-test-g'+head+'-yuzuli';checks+=1
  assert run(myron=False,auto=False)== '6.12.118+';checks+=1
  assert run(myron=False,auto=False,local='')=='6.12.118';checks+=1
  git('add','tracked');git('commit','-qm','second');head=git('rev-parse','HEAD')[:12];assert run()=='6.12.118-g'+head+'-yuzuli';checks+=1
  git('tag','-a','v6.12.118','-m','version');assert run()=='6.12.118-yuzuli';checks+=1
  (src/'tracked').write_text('dirty tag\n');assert run()=='6.12.118-yuzuli';assert run(myron=False)=='6.12.118-dirty';checks+=2
  git('add','tracked');git('commit','-qm','after tag');head=git('rev-parse','HEAD')[:12];assert run()=='6.12.118-00001-g'+head+'-yuzuli';checks+=1
 print('PASS:',checks,'release-label cases; true Git ids, dirty worktree retained, tags, --no-local and non-Myron behavior')
if __name__=='__main__':main()

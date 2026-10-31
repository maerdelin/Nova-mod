#!/usr/bin/env python3
import subprocess, pathlib, re, time, xml.etree.ElementTree as ET, json, sys
OUT=pathlib.Path('migu/evidence/ui_automation');OUT.mkdir(parents=True,exist_ok=True)
P='com.migutv.audiomonitorx'
COMP=P+'/com.migutv.remote.MiguRemoteService'

def cmd(*args,timeout=30):
 p=subprocess.run(['adb',*args],capture_output=True,timeout=timeout)
 return (p.stdout+p.stderr).decode('utf8','replace')
def shell(*args):return cmd('shell',*args)
def capture(label):
 try:
  result=cmd('shell','uiautomator','dump','/sdcard/ui.xml',timeout=25)
  cmd('pull','/sdcard/ui.xml',str(OUT/(label+'.xml')),timeout=15)
  cmd('exec-out','screencap','-p',timeout=15)
  with (OUT/(label+'.png')).open('wb') as f:f.write(subprocess.run(['adb','exec-out','screencap','-p'],stdout=subprocess.PIPE,timeout=20).stdout)
  root=ET.parse(OUT/(label+'.xml')).getroot()
  nodes=[]
  def walk(node,ancestors):
   if node.tag!='node':
    for c in node:walk(c,ancestors)
    return
   d=node.attrib
   nodes.append({'text':d.get('text',''),'desc':d.get('content-desc',''),'rid':d.get('resource-id',''),'bounds':d.get('bounds',''),'clickable':d.get('clickable',''),'parent_bounds':[a['bounds'] for a in ancestors if a.get('clickable')=='true'][-1:]})
   for c in node:walk(c,ancestors+[d])
  walk(root,[])
  (OUT/(label+'.json')).write_text(json.dumps(nodes,ensure_ascii=False,indent=2))
  print('CAPTURE',label,'NODES',len(nodes),flush=True)
  for n in nodes:
   if n['text'] or n['desc']:print('ITEM',n['text'],n['desc'],n['bounds'],flush=True)
  return nodes
 except Exception as exc:
  print('CAPTURE_ERROR',label,repr(exc),flush=True)
  return []
def click(bounds):
 a=list(map(int,re.findall(r'\d+',bounds)))
 if len(a)!=4:return False
 x,y=(a[0]+a[2])//2,(a[1]+a[3])//2
 print('TAP',x,y,flush=True);shell('input','tap',str(x),str(y));time.sleep(1);return True
def find(nodes,words):
 for n in nodes:
  t=(n['text']+' '+n['desc']).lower()
  if any(w in t for w in words):return n
 return None
def tap(n):
 return click((n['parent_bounds'] or [n['bounds']])[0])

def state(label):
 for k,args in [('enabled','settings get secure enabled_accessibility_services'),('global','settings get secure accessibility_enabled'),('accessibility','dumpsys accessibility'),('crash','logcat -d -v threadtime')]:
  (OUT/(label+'_'+k+'.txt')).write_text(shell(*args.split()))
 print('STATE',label,(OUT/(label+'_enabled.txt')).read_text().strip(),flush=True)

print('START_TV_UI_FIRST_ENABLE',flush=True)
shell('am','start','-a','android.settings.ACCESSIBILITY_SETTINGS')
time.sleep(2)
found=False
for i in range(13):
 ns=capture('list_'+str(i))
 n=find(ns,['migu smart','migu remote','migutv'])
 if n:
  print('FOUND_MIGU',n,flush=True)
  tap(n);found=True;break
 downloaded=find(ns,['downloaded apps','installed apps','downloaded services','user services','installed services'])
 if downloaded:
  print('ENTER_SERVICE_CATEGORY',downloaded,flush=True)
  tap(downloaded);continue
 shell('input','swipe','1660','930','1660','345','460');time.sleep(1)
if not found:
 print('FAIL_MIGU_NOT_VISIBLE',flush=True);state('service_not_visible');sys.exit(35)
for i in range(5):
 ns=capture('detail_'+str(i))
 print('DETAIL_CHECK',i,flush=True)
 n=find(ns,['use service','use migu','turn on','enable','off'])
 if n:
  print('TOGGLE_CANDIDATE',n,flush=True);state('before_toggle');tap(n);break
 shell('input','keyevent','KEYCODE_DPAD_CENTER');time.sleep(1)
else:
 print('FAIL_TOGGLE_NOT_FOUND',flush=True);state('toggle_not_found');sys.exit(36)
for i in range(4):
 ns=capture('post_toggle_'+str(i))
 state('post_toggle_'+str(i))
 n=find(ns,['allow','ok','i understand','agree','confirm','turn on'])
 if n:
  print('CONFIRM_DIALOG',n,flush=True);tap(n)
 else:
  time.sleep(2)
state('final_immediate');time.sleep(12);state('final_12s')
enabled=(OUT/'final_12s_enabled.txt').read_text()
if COMP.lower() in enabled.lower():print('PASS_SERVICE_ENABLED_FIRST_BOOT',flush=True)
else:print('FAIL_FIRST_ENABLE_NOT_RETAINED',flush=True);sys.exit(37)
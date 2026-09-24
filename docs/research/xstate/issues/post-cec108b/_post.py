import json,re,subprocess,time,sys
R='basiltt/xstate-statemachine'
ALLOWED_PREFIX=('severity/','area/'); ALLOWED={'bug','enhancement','documentation','performance'}
KNOWN_AREAS={'interpreter','sync-interpreter','actors','persistence','timers','validation','perf','docs','events','plugins','receipts'}
def gh(*a,inp=None):
    r=subprocess.run(['gh',*a],capture_output=True,text=True,encoding='utf-8',input=inp)
    if r.returncode!=0: print('ERR',a[:3],r.stderr[:300]); 
    return r.stdout.strip()
def fm(path):
    t=open(path,encoding='utf-8').read()
    m=re.match(r'^---\n(.*?)\n---\n(.*)$',t,re.S)
    if not m: return {},t
    f=m.group(1); body=m.group(2)
    title=re.search(r'^title:\s*"?(.*?)"?\s*$',f,re.M).group(1)
    lm=re.search(r'^labels:\s*\[(.*?)\]',f,re.M)
    labels=[s.strip().strip('"\'') for s in lm.group(1).split(',')] if lm else []
    return {'title':title,'labels':labels},body
def clean_labels(ls):
    out=[]
    for l in ls:
        if l=='candleviewer': continue
        if l in ALLOWED or l.startswith('severity/'): out.append(l)
        elif l.startswith('area/') and l.split('/',1)[1] in KNOWN_AREAS: out.append(l)
    return sorted(set(out))
m=json.load(open('manifest.json',encoding='utf-8'))
# labels
for sev,col in [('blocker','b60205'),('high','d93f0b'),('medium','fbca04'),('low','0e8a16')]:
    gh('label','create',f'severity/{sev}','-R',R,'--color',col,'--force')
for a in KNOWN_AREAS: gh('label','create',f'area/{a}','-R',R,'--color','1d76db','--force')
mapping={}
order={'Blocker':0,'High':1,'Medium':2,'Low':3}
for it in sorted(m['new_issues'],key=lambda x:order.get(x.get('severity'),9)):
    meta,body=fm(it['file'])
    body=body.replace('CandleViewer','the adopting project')
    body=re.sub(r'\n+## Verification.*$','',body,flags=re.S)
    body+="\n\n---\nFound during round 6 of our adoption audit (#26) on main @ cec108b. Self-contained repro attached: exits 1 while the defect is present, 0 once fixed — usable directly as a regression test.\n"
    open('_body.md','w',encoding='utf-8').write(body)
    labels=clean_labels(meta['labels'])
    url=gh('issue','create','-R',R,'--title',meta['title'],'--label',','.join(labels),'--body-file','_body.md')
    num=url.rsplit('/',1)[-1]; mapping[it['r6']]=num
    print(it['r6'],'->',url,labels); time.sleep(2)
def subst(t):
    for k,v in mapping.items(): t=t.replace(f'<{k}>',f'#{v} ({k})').replace(f'&lt;{k}&gt;',f'#{v} ({k})')
    return t.replace('CandleViewer','the adopting project')
posted=[];reopened=[]
for c in m['comments']:
    t=subst(open(c['file'],encoding='utf-8').read()); open('_c.md','w',encoding='utf-8').write(t)
    n=str(c['issue']); act=c.get('action','comment')
    if 'reopen' in act:
        gh('issue','reopen',n,'-R',R,'--comment',t); reopened.append(n)
    else:
        gh('issue','comment',n,'-R',R,'--body-file','_c.md')
    posted.append(n); time.sleep(1.5)
mt=subst(open(m['meta'] if isinstance(m['meta'],str) else m['meta']['file'],encoding='utf-8').read())
open('_meta.md','w',encoding='utf-8').write(mt); gh('issue','edit','26','-R',R,'--body-file','_meta.md')
print('comments',len(posted),'reopened',reopened)
with open('../.filed-issues','a',encoding='utf-8') as f:
    f.write('\n--- 2026-09-20 post-cec108b (unreleased 0.8.1, round 6) ---\n')
    f.write('new issues filed (%d): %s\n'%(len(mapping),' '.join(f'#{v}({k})' for k,v in mapping.items())))
    f.write('comments posted: %s\nreopened: %s\nmeta #26 body replaced\n'%(' '.join('#'+p for p in posted),' '.join('#'+r for r in reopened)))
json.dump(mapping,open('_mapping.json','w'),indent=1)

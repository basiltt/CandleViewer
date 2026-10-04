import {chromium} from 'playwright-core';import {spawn} from 'child_process';
const srv=spawn('npx',['vite','preview','--port','4173'],{shell:true});await new Promise(r=>setTimeout(r,4000));
const out={};
const b=await chromium.launch({args:['--enable-gpu-rasterization','--ignore-gpu-blocklist']});
for(const [n,virt] of [[60,0],[200,0],[200,1]]){
 const p=await b.newPage({viewport:{width:1280,height:800}});
 await p.goto(`http://localhost:4173/?n=${n}&virt=${virt}`);await p.waitForSelector('.react-flow__node');
 const dur=+(process.env.DUR||15000);
 const res=await p.evaluate(async(dur)=>{const ft=[];let last=performance.now();const t0=last;let i=0;
  const el=document.querySelector('.react-flow__pane');const rect=el.getBoundingClientRect();
  const cx=rect.left+rect.width/2,cy=rect.top+rect.height/2;
  return await new Promise(res=>{const tick=(t)=>{ft.push(t-last);last=t;i++;
   const ph=(t-t0)/1000;
   // zoom via wheel + pan via synthetic wheel (ctrl=zoom)
   el.dispatchEvent(new WheelEvent('wheel',{deltaY:Math.sin(ph*2)*20,ctrlKey:true,clientX:cx,clientY:cy,bubbles:true,cancelable:true}));
   el.dispatchEvent(new WheelEvent('wheel',{deltaX:Math.cos(ph*3)*30,deltaY:0,clientX:cx,clientY:cy,bubbles:true,cancelable:true}));
   if(t-t0<dur)requestAnimationFrame(tick);else res(ft.slice(5));};requestAnimationFrame(tick);});},dur);
 res.sort((a,b)=>a-b);const pc=q=>res[Math.floor(q*(res.length-1))];
 const nodes=await p.evaluate(()=>document.querySelectorAll('.react-flow__node').length);
 out[`n${n}_virt${virt}`]={frames:res.length,p50:+pc(.5).toFixed(1),p95:+pc(.95).toFixed(1),p99:+pc(.99).toFixed(1),fpsMean:+(1000/(res.reduce((a,b)=>a+b)/res.length)).toFixed(1),domNodes:nodes};
 await p.close();}
// keyboard connect
const p=await b.newPage();await p.goto('http://localhost:4173/?n=60');await p.waitForSelector('.react-flow__node');
await p.evaluate(()=>{document.querySelectorAll('[data-port]').forEach((e,i)=>e.tabIndex=0)});
const before=await p.evaluate(()=>document.querySelectorAll('.react-flow__edge').length);
await p.focus('[data-port=out][data-node=n0]');await p.keyboard.press('Enter');
const a1=await p.textContent('#live');
await p.focus('[data-port=in][data-node=n30]');await p.keyboard.press('Enter');
const a2=await p.textContent('#live');await p.waitForTimeout(300);
const after=await p.evaluate(()=>document.querySelectorAll('.react-flow__edge').length);
out.keyboard={before,after,a1,a2};
console.log(JSON.stringify(out,null,1));await b.close();
spawn('taskkill',['/PID',String(srv.pid),'/T','/F']);process.exit(0);

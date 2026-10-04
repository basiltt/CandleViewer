import {chromium} from 'playwright-core';import {spawn} from 'child_process';
const srv=spawn('npx',['vite','preview','--port','4174'],{shell:true});await new Promise(r=>setTimeout(r,4000));
const b=await chromium.launch({args:['--enable-gpu-rasterization','--ignore-gpu-blocklist','--disable-frame-rate-limit','--disable-gpu-vsync']});
const out={};
async function run(url,sel,throttle,dur,wheelSel){
 const ctx=await b.newContext({viewport:{width:1280,height:800}});const p=await ctx.newPage();
 const c=await ctx.newCDPSession(p);await c.send('Emulation.setCPUThrottlingRate',{rate:throttle});
 await p.goto(url);await p.waitForSelector(sel,{state:'attached'});await p.waitForTimeout(1500);
 const res=await p.evaluate(async([dur,ws])=>{const ft=[];let last=performance.now();const t0=last;
  const el=document.querySelector(ws);const r=el.getBoundingClientRect();const cx=r.left+r.width/2,cy=r.top+r.height/2;
  return await new Promise(res=>{const tick=t=>{ft.push(t-last);last=t;const ph=(t-t0)/1000;
   if(window.__area){const a=window.__area;const k=1+0.3*Math.sin(ph*2);a.area.zoom(k,cx,cy);a.area.translate(80*Math.cos(ph*3),0);}
   else{el.dispatchEvent(new WheelEvent('wheel',{deltaY:Math.sin(ph*2)*20,ctrlKey:true,clientX:cx,clientY:cy,bubbles:true,cancelable:true}));
   el.dispatchEvent(new WheelEvent('wheel',{deltaX:Math.cos(ph*3)*30,deltaY:0,clientX:cx,clientY:cy,bubbles:true,cancelable:true}));}
   if(t-t0<dur)requestAnimationFrame(tick);else res(ft.slice(5));};requestAnimationFrame(tick);});},[dur,wheelSel]);
 res.sort((a,b)=>a-b);const pc=q=>res[Math.floor(q*(res.length-1))];
 await ctx.close();
 return {frames:res.length,p50:+pc(.5).toFixed(1),p95:+pc(.95).toFixed(1),p99:+pc(.99).toFixed(1),fps:+(1000/(res.reduce((a,b)=>a+b)/res.length)).toFixed(1)};}
for(const th of [1,4]){
 out[`rf200_x${th}`]=await run('http://localhost:4174/index.html?n=200','.react-flow__node',th,8000,'.react-flow__pane');
 out[`rf200virt_x${th}`]=await run('http://localhost:4174/index.html?n=200&virt=1','.react-flow__node',th,8000,'.react-flow__pane');
 out[`rete200_x${th}`]=await run('http://localhost:4174/rete.html?n=200','#root div div',th,8000,'#root');
}
console.log(JSON.stringify(out,null,1));await b.close();
spawn('taskkill',['/PID',String(srv.pid),'/T','/F']);process.exit(0);

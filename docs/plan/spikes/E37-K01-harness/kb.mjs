import {chromium} from 'playwright-core';import {spawn} from 'child_process';
const srv=spawn('npx',['vite','preview','--port','4175'],{shell:true});await new Promise(r=>setTimeout(r,4000));
const b=await chromium.launch();const p=await b.newPage({viewport:{width:1280,height:800}});
await p.goto('http://localhost:4175/index.html?n=60');await p.waitForSelector('.react-flow__node');
const out={};
out.before=await p.evaluate(()=>document.querySelectorAll('.react-flow__edge').length);
await p.evaluate(()=>{document.querySelectorAll('[data-port]').forEach(e=>e.tabIndex=-1);document.querySelector('[data-port=out][data-node=n0]').tabIndex=0});
await p.focus('[data-port=out][data-node=n0]');await p.keyboard.press('Enter');out.a1=await p.textContent('#live');
await p.focus('[data-port=in][data-node=n1]');
const seq=[];for(let i=0;i<5;i++){await p.keyboard.press('ArrowDown');seq.push(await p.evaluate(()=>document.activeElement.getAttribute('aria-label')));}
out.downSeq=seq;await p.keyboard.press('ArrowUp');out.up=await p.evaluate(()=>document.activeElement.getAttribute('aria-label'));
out.tabStops=await p.evaluate(()=>[...document.querySelectorAll('[data-port]')].filter(e=>e.tabIndex===0).length);
await p.keyboard.press('Enter');out.a2=await p.textContent('#live');await p.waitForTimeout(300);
out.after=await p.evaluate(()=>document.querySelectorAll('.react-flow__edge').length);
// cancel path
await p.focus('[data-port=out][data-node=n2]');await p.keyboard.press('Enter');await p.keyboard.press('Escape');out.cancel=await p.textContent('#live');
console.log(JSON.stringify(out,null,1));await b.close();spawn('taskkill',['/PID',String(srv.pid),'/T','/F']);process.exit(0);

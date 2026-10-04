import ELK from 'elkjs/lib/elk.bundled.js';import dagre from '@dagrejs/dagre';import {gen} from './gen.mjs';
const med=a=>a.sort((x,y)=>x-y)[a.length>>1];
for(const n of [60,200]){const g=gen(n);
 const dt=[];for(let i=0;i<7;i++){const d=new dagre.graphlib.Graph();d.setGraph({rankdir:'LR'});d.setDefaultEdgeLabel(()=>({}));
  g.nodes.forEach(x=>d.setNode(x.id,{width:200,height:70}));g.edges.forEach(e=>d.setEdge(e.source,e.target));
  const t=performance.now();dagre.layout(d);dt.push(performance.now()-t);}
 const elk=new ELK();const et=[];
 for(let i=0;i<7;i++){const t=performance.now();await elk.layout({id:'r',layoutOptions:{'elk.algorithm':'layered','elk.direction':'RIGHT'},
  children:g.nodes.map(x=>({id:x.id,width:200,height:70})),edges:g.edges.map(e=>({id:e.id,sources:[e.source],targets:[e.target]}))});et.push(performance.now()-t);}
 console.log(n,'edges',g.edges.length,'dagre ms',dt.map(x=>x.toFixed(0)).join(','),'median',med(dt).toFixed(1),'| elk ms',et.map(x=>x.toFixed(0)).join(','),'median',med(et).toFixed(1));}

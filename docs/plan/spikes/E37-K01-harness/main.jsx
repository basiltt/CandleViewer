import React,{useState,useCallback,useRef,useEffect,memo} from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow,ReactFlowProvider,applyNodeChanges,applyEdgeChanges,addEdge,useReactFlow,Handle,Position} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {gen} from './gen.js';
const q=new URLSearchParams(location.search);const N=+(q.get('n')||200);const VIRT=q.get('virt')==='1';
// Keyboard connect state lives in a module store (controlled by our code, not the library)
let pending=null;const live=()=>document.getElementById('live');
const say=t=>{live().textContent=t};
const Node=memo(({id,data})=>{
 const onKey=(port)=>(ev)=>{
  if(ev.key!=='Enter')return;
  if(port==='out'){pending=id;say('Connecting from '+data.label+'. Move to a target input and press Enter.');}
  else if(pending&&pending!==id){window.__connect({source:pending,target:id,sourceHandle:'out',targetHandle:'in'});say('Connected '+pending+' to '+id);pending=null;}
 };
 return <div role="group" aria-label={data.label} className={'rule '+data.kind} style={{width:200,height:70,border:'1px solid #888',borderRadius:6,background:'#1b2230',color:'#ddd',padding:6,font:'12px sans-serif',boxSizing:'border-box'}}>
  <button data-port="in" data-node={id} aria-label={data.label+' input'} tabIndex={-1} onKeyDown={onKey('in')} style={{position:'absolute',left:-8,top:28,width:14,height:14}}/>
  <Handle id="in" type="target" position={Position.Left} isConnectable/>
  <div>{data.label}</div>
  <button data-port="out" data-node={id} aria-label={data.label+' output'} tabIndex={-1} onKeyDown={onKey('out')} style={{position:'absolute',right:-8,top:28,width:14,height:14}}/>
  <Handle id="out" type="source" position={Position.Right} isConnectable/>
 </div>;});
const nodeTypes={rule:Node};
function App(){
 const g=useRef(gen(N));const [nodes,setNodes]=useState(g.current.nodes);const [edges,setEdges]=useState(g.current.edges);
 const rf=useReactFlow();
 window.__connect=useCallback(c=>setEdges(e=>addEdge({...c,id:'k'+Date.now()},e)),[]);
 window.__rf=rf;window.__edges=()=>edges.length;
 return <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={c=>setNodes(n=>applyNodeChanges(c,n))}
  onEdgesChange={c=>setEdges(e=>applyEdgeChanges(c,e))} onConnect={window.__connect} onlyRenderVisibleElements={VIRT}
  nodesFocusable edgesFocusable fitView minZoom={0.1}/>;}
createRoot(document.getElementById('root')).render(<><div id="live" aria-live="polite" style={{position:'absolute',zIndex:9,left:0,top:0,color:'#fff'}}/><ReactFlowProvider><App/></ReactFlowProvider></>);

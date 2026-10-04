import {NodeEditor,ClassicPreset} from 'rete';
import {AreaPlugin,AreaExtensions} from 'rete-area-plugin';
import {gen} from './gen.js';
const N=+(new URLSearchParams(location.search).get('n')||200);
const sock=new ClassicPreset.Socket('s');
(async()=>{
 const g=gen(N);const editor=new NodeEditor();const area=new AreaPlugin(document.getElementById('root'));
 editor.use(area);
 // minimal DOM renderer (no framework plugin): nodes and edges as DOM elements
 area.addPipe(c=>{
  if(c.type==='render'){const {data}=c.data;
   if(data.type==='node'){const el=c.data.element;el.innerHTML='';const d=document.createElement('div');
    d.style.cssText='width:200px;height:70px;border:1px solid #888;background:#1b2230;color:#ddd;font:12px sans-serif;padding:6px;box-sizing:border-box';
    d.textContent=data.payload.label;el.appendChild(d);}
   if(data.type==='connection'){const el=c.data.element;el.innerHTML='<svg style="overflow:visible;position:absolute;width:1px;height:1px"><path d="M0 0L60 40" stroke="#888" fill="none"/></svg>';}
  }return c;});
 const nodes={};
 for(const n of g.nodes){const node=new ClassicPreset.Node(n.data.label);node.addInput('in',new ClassicPreset.Input(sock));node.addOutput('out',new ClassicPreset.Output(sock));
  nodes[n.id]=node;await editor.addNode(node);await area.translate(node.id,n.position);}
 for(const e of g.edges){await editor.addConnection(new ClassicPreset.Connection(nodes[e.source],'out',nodes[e.target],'in'));}
 window.__area=area;window.__ready=1;
})();

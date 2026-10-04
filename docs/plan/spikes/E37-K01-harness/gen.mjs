// Deterministic IR-shaped graph: trigger -> conditions -> boolean combiners -> actions
export function gen(n){let s=7;const r=()=>(s=(s*1103515245+12345)&0x7fffffff)/0x7fffffff;
const nodes=[],edges=[];const kinds=['trigger','compare','temporal','bool','action'];
const per=Math.ceil(n/5);
for(let i=0;i<n;i++){const k=Math.min(4,Math.floor(i/per));
 nodes.push({id:'n'+i,type:'rule',position:{x:k*320,y:(i%per)*110},data:{kind:kinds[k],label:kinds[k]+' '+i}});}
let e=0;for(let i=per;i<n&&e<260;i++){const k=Math.floor(i/per);
 const srcs=[0,1].map(()=>(k-1)*per+Math.floor(r()*per));
 for(const s2 of srcs){if(e<260&&s2<n){edges.push({id:'e'+e++,source:'n'+s2,target:'n'+i,sourceHandle:'out',targetHandle:'in'});}}}
return{nodes,edges};}

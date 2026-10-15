import {useEffect,useRef} from 'react';
import cytoscape from 'cytoscape';
import type {RuntimeGraphData,RuntimeEdge} from './types';
const evidenceColorTokens:Record<string,string>={STATIC_ONLY:'--palette-98a4ad',DYNAMIC_ONLY:'--palette-b17a28',STATIC_AND_DYNAMIC:'--palette-20775e',MIXED:'--palette-7964a7',STATIC:'--palette-98a4ad'};
export const evidenceColors:Record<string,string>=Object.fromEntries(Object.entries(evidenceColorTokens).map(([kind,token])=>[kind,`var(${token})`]));
const readThemeColor = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export function RuntimeGraph({data,onEdge}:{data:RuntimeGraphData;onEdge:(e:RuntimeEdge)=>void}){
  const ref=useRef<HTMLDivElement>(null);const callback=useRef(onEdge);callback.current=onEdge;
  useEffect(()=>{
    if(!ref.current)return;
    const nodes=data.nodes.slice(0,150);const ids=new Set(nodes.map(n=>n.id));
    const edges=data.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)).slice(0,1000);
    const cy=cytoscape({container:ref.current,elements:[...nodes.map(n=>({data:{id:n.id,label:(n.name||n.id).split('.').at(-1),color:readThemeColor(evidenceColorTokens[n.evidence_type||'DYNAMIC_ONLY'])}})),...edges.map(e=>({data:{id:e.id,source:e.source,target:e.target,color:readThemeColor(evidenceColorTokens[e.evidence_type||(e.evidence_types&&e.evidence_types.length>1?'MIXED':e.evidence_types?.[0])||'DYNAMIC_ONLY'])}}))],style:[{selector:'node',style:{label:'data(label)','background-color':'data(color)',color:readThemeColor('--palette-223a31'),'font-size':11,'text-valign':'bottom','text-margin-y':7}},{selector:'edge',style:{'line-color':'data(color)','target-arrow-color':'data(color)','target-arrow-shape':'triangle','curve-style':'bezier',width:2}},{selector:'edge:selected',style:{width:5}}],layout:{name:nodes.length<15?'circle':'cose',animate:false,padding:40},wheelSensitivity:.2});
    cy.on('tap','edge',event=>{const edge=edges.find(e=>e.id===event.target.id());if(edge)callback.current(edge);});
    return()=>cy.destroy();
  },[data]);
  return <><div ref={ref} className="runtime-canvas"/><p className="muted">Showing up to 150 nodes and 1,000 edges. Click an edge for its evidence. Full data is available in the report export.</p></>;
}

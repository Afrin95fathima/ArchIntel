import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import cytoscape, { type Core } from 'cytoscape';
import { Maximize2, Layers, MousePointer2, ArrowDownRight, X } from 'lucide-react';
import { api } from './api';
import type { Domain, GraphData, GraphNode } from './types';
import { Badge, Button, ErrorBox, Loading, PageTitle } from './components';

const colorTokens = ['--palette-327863','--palette-5579ad','--palette-aa8551','--palette-8771a9','--palette-5d9194','--palette-b26d70','--palette-77834e'];
const readThemeColor = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function GraphCanvas({data,domains,onNode,onDrill,compact=false,cycleNodeIds=[]}: {data:GraphData;domains:Domain[];onNode?:(node:GraphNode)=>void;onDrill?:(node:GraphNode)=>void;compact?:boolean;cycleNodeIds?:string[]}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<Core|null>(null);
  const callbacks = useRef({onNode,onDrill});
  callbacks.current={onNode,onDrill};
  useEffect(()=>{
    if (!container.current) return;
    const colors = colorTokens.map(readThemeColor);
    const cy = cytoscape({container:container.current,
      elements:[...data.nodes.map(n=>({data:{id:n.id,label:n.name?.split('.').at(-1)||n.simple_name||n.id.split('.').at(-1),size:Math.min(78,42+(n.class_count||1)*2),color:colors[Math.max(0,domains.findIndex(d=>d.id===(n.domain_id||n.id)))%colors.length],cycle:cycleNodeIds.includes(n.id)}})),
        ...data.edges.map(e=>({data:{id:e.id,source:e.source,target:e.target,weight:e.weight||1}}))],
      style:[
        {selector:'node',style:{'background-color':'data(color)','label':'data(label)','color':readThemeColor('--palette-283c35'),'font-family':'Inter, system-ui','font-size':11,'font-weight':600,'text-valign':'bottom','text-margin-y':9,'width':'data(size)','height':'data(size)','border-width':6,'border-color':readThemeColor('--palette-fff'),'text-wrap':'wrap','text-max-width':'140px'}},
        {selector:'edge',style:{'width':1.5,'line-color':readThemeColor('--palette-bfccc6'),'target-arrow-color':readThemeColor('--palette-91a79b'),'target-arrow-shape':'triangle','curve-style':'bezier','arrow-scale':.8}},
        {selector:'node:selected',style:{'border-color':readThemeColor('--palette-b8d8c7'),'border-width':8}},
        {selector:'node[cycle = true]',style:{'border-color':'#b44747','border-width':8}},
        {selector:'edge:selected',style:{'line-color':readThemeColor('--palette-24644c'),'width':3}}
      ],
      layout:data.nodes.length<=12 ? {name:'circle',animate:false,padding:38} : {name:'cose',animate:false,randomize:false,nodeRepulsion:()=>18000,idealEdgeLength:()=>125,gravity:.3,padding:40},
      wheelSensitivity:.22,minZoom:.15,maxZoom:3
    });
    cy.on('tap','node',event=>{const node=data.nodes.find(n=>n.id===event.target.id());if(node)callbacks.current.onNode?.(node);});
    cy.on('dbltap','node',event=>{const node=data.nodes.find(n=>n.id===event.target.id());if(node)callbacks.current.onDrill?.(node);});
    instance.current=cy;
    return ()=>{cy.destroy();instance.current=null;};
  },[data,domains,cycleNodeIds]);
  return <div className={'graph-canvas-wrap '+(compact?'compact':'')}><div className="graph-canvas" ref={container}/><button className="graph-fit" onClick={()=>instance.current?.fit(undefined,40)} aria-label="Fit graph"><Maximize2 size={16}/></button>{data.nodes.length===0&&<div className="graph-empty">No nodes in this selection.</div>}</div>;
}

export function GraphExplorer({analysisId,domains}: {analysisId:string;domains:Domain[]}) {
  const [level,setLevel]=useState('domains');
  const [domain,setDomain]=useState('');
  const [packageName,setPackage]=useState('');
  const [selected,setSelected]=useState<GraphNode|null>(null);
  const graph=useQuery({queryKey:['graph',analysisId,level,domain,packageName],queryFn:()=>api<GraphData>('/analyses/'+analysisId+'/graph/'+level+'?limit=150'+(domain?'&domain_id='+encodeURIComponent(domain):'')+(packageName?'&package='+encodeURIComponent(packageName):''))});
  function changeLevel(next:string) {setLevel(next);setSelected(null);setPackage('');if(next==='domains')setDomain('');}
  function drill(node:GraphNode) { if(level==='domains'){setDomain(node.id);setLevel('packages');}else if(level==='packages'){setPackage(node.id);setLevel('classes');}setSelected(null);}
  return <><PageTitle eyebrow="ARCHITECTURE EXPLORER" title="See how everything connects." description="Start with candidate domains. Expand into packages and classes to inspect the evidence."/>
    <div className="graph-toolbar"><div className="segmented">{['domains','packages','classes'].map(l=><button key={l} onClick={()=>changeLevel(l)} className={level===l?'selected':''}>{l[0].toUpperCase()+l.slice(1)}</button>)}</div><select aria-label="Filter graph by domain" value={domain} onChange={e=>{setDomain(e.target.value);setPackage('');if(level==='domains')setLevel('packages');}}><option value="">All domains</option>{domains.map(d=><option value={d.id} key={d.id}>{d.name}</option>)}</select><span className="muted"><MousePointer2 size={14}/> Double-click to expand</span></div>
    {packageName&&<div className="breadcrumb-filter"><Layers size={15}/>{packageName}<button onClick={()=>setPackage('')}>Clear</button></div>}
    {graph.isPending?<Loading/>:graph.error?<ErrorBox error={graph.error}/>:graph.data&&<div className="graph-panel"><GraphCanvas data={graph.data} domains={domains} onNode={setSelected} onDrill={drill}/>
      {selected&&<aside className="node-inspector"><button className="icon-button close" onClick={()=>setSelected(null)} aria-label="Close node details"><X size={16}/></button><Badge tone="green">{level.slice(0,-1)}</Badge><h3>{selected.name||selected.fqn||selected.id}</h3>{selected.class_count!==undefined&&<p>{selected.class_count} classes</p>}{selected.class_type&&<p>{selected.class_type}</p>}{selected.annotations?.map(a=><small key={a}>{a}</small>)}{selected.metrics&&<dl>{Object.entries(selected.metrics).filter(([,v])=>typeof v==='number').map(([k,v])=><div key={k}><dt>{k.replaceAll('_',' ')}</dt><dd>{String(v)}</dd></div>)}</dl>}{level!=='classes'&&<Button onClick={()=>drill(selected)}>Expand {level==='domains'?'packages':'classes'}<ArrowDownRight size={16}/></Button>}</aside>}
      <div className="graph-footer"><span>{graph.data.nodes.length} / {graph.data.total_nodes} nodes · {graph.data.edges.length} visible edges</span><span>Arrow: dependent → dependency</span></div>
      {graph.data.truncated&&<div className="notice">This view is capped at 150 nodes and 2,000 edges. Select a domain or package to narrow the graph.</div>}
    </div>}
    <div className="graph-legend">{domains.map((d,i)=><span key={d.id}><i style={{background:`var(${colorTokens[i%colorTokens.length]})`}}/>{d.name}</span>)}</div>
  </>;
}

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowDownRight, Boxes, Braces, Database, Download, Layers3, Network, Package, Workflow, Printer } from 'lucide-react';
import { api } from './api';
import { Badge, ErrorBox, Loading, PageTitle, Stat } from './components';
import { GraphCanvas } from './GraphExplorer';
import type { Domain, GraphData, GraphNode, Summary } from './types';
import type { Cycle } from './types';
import './architecture.css';

type ArchitectureLayer = 'api' | 'business' | 'data' | 'support';
const layerLabels: Record<ArchitectureLayer, string> = {
  api: 'Entry points and API', business: 'Business logic', data: 'Data access and models', support: 'Supporting code',
};
const layerIcons = {api: Workflow, business: Braces, data: Database, support: Layers3};

function architectureLayer(node: GraphNode): ArchitectureLayer {
  const identity = `${node.name || node.id} ${(node.annotations || []).join(' ')}`.toLowerCase();
  if (/controller|restcontroller|requestmapping|path|endpoint|resource|listener|consumer|scheduled/.test(identity)) return 'api';
  if (/service|usecase|interactor|manager|coordinator|handler|facade|workflow/.test(identity)) return 'business';
  if (/repository|repositories|dao|entity|entities|model|models|document|record|mapper/.test(identity)) return 'data';
  return 'support';
}

function ArchitectureClassGroup({layer,nodes,complete}:{layer:ArchitectureLayer;nodes:GraphNode[];complete:boolean}) {
  const Icon=layerIcons[layer];
  return <details className="architecture-class-group">
    <summary><Icon size={15}/><span>{layerLabels[layer]}</span><strong>{nodes.length}{complete?'':' shown'}</strong></summary>
    {nodes.length?<ul>{nodes.slice(0,40).map(node=><li key={node.id} title={node.name || node.id}>{node.name || node.id}</li>)}</ul>:<p>No matching classes were identified in this group.</p>}
    {nodes.length>40&&<small>Showing 40 of {nodes.length} matching classes.</small>}
  </details>;
}

export function ArchitectureBlueprint({analysisId,applicationName,summary,domains}:{analysisId:string;applicationName:string;summary:Summary;domains:Domain[]}) {
  const [selectedId,setSelectedId]=useState('');
  const domainGraph=useQuery({queryKey:['architecture-blueprint-domains',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/domains?limit=400`)});
  const classGraph=useQuery({queryKey:['architecture-blueprint-classes',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/classes?limit=400`)});
  const packageGraph=useQuery({queryKey:['architecture-blueprint-packages',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/packages?limit=400`)});
  const [diagramLevel,setDiagramLevel]=useState<'system'|'module'|'package'>('module');
  const allDomains=useQuery({queryKey:['architecture-blueprint-all-domains',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/domains?limit=400`),enabled:diagramLevel==='system'});
  const cycles=useQuery({queryKey:['architecture-blueprint-cycles',analysisId],queryFn:()=>api<{items:Cycle[]}>('/analyses/'+analysisId+'/cycles')});

  const selected=domains.find(domain=>domain.id===selectedId);
  const classNodes=classGraph.data?.nodes||[];
  const selectedClasses=useMemo(()=>classNodes.filter(node=>node.domain_id===selectedId),[classNodes,selectedId]);
  const grouped=useMemo(()=>Object.fromEntries((['api','business','data','support'] as ArchitectureLayer[]).map(layer=>[layer,selectedClasses.filter(node=>architectureLayer(node)===layer)])) as Record<ArchitectureLayer,GraphNode[]>,[selectedClasses]);
  const names=useMemo(()=>Object.fromEntries(domains.map(domain=>[domain.id,domain.name])),[domains]);
  const edges=[...(domainGraph.data?.edges||[])].sort((a,b)=>(b.weight||0)-(a.weight||0));
  const artifact=summary.artifact?.filename||'Analyzed artifact';
  const packaging=summary.artifact?.manifest?.packaging||'Compiled artifact';
  const completeClassSample=!!classGraph.data&&!classGraph.data.truncated;
  const diagramGraph=diagramLevel==='package'?packageGraph.data:diagramLevel==='system'?allDomains.data:domainGraph.data;
  const cycleNodeIds=useMemo(()=>{
    if(!diagramGraph)return [];
    const members=new Set((cycles.data?.items||[]).flatMap(cycle=>cycle.members));
    if(diagramLevel==='package')return (diagramGraph.nodes||[]).filter(node=>(node.name||node.id)&&[...members].some(id=>id.startsWith((node.name||node.id)+'.'))).map(node=>node.id);
    return (diagramGraph.nodes||[]).filter(node=>domains.some(domain=>domain.id===node.id&&domain.classes.some(name=>members.has(name)))).map(node=>node.id);
  },[diagramGraph,cycles.data,diagramLevel,domains]);

  function downloadMermaid(){
    if(!diagramGraph)return;
    const labels=new Map(diagramGraph.nodes.map(node=>[node.id,node.name||node.id]));
    const safe=(id:string)=>'n_'+Array.from(id).map(char=>char.codePointAt(0)!.toString(16)).join('_');
    const lines=['flowchart LR',...diagramGraph.nodes.map(node=>`  ${safe(node.id)}["${(labels.get(node.id)||node.id).replace(/["\[\]{}]/g,' ')}"]${cycleNodeIds.includes(node.id)?':::cycle':''}`),...diagramGraph.edges.map(edge=>`  ${safe(edge.source)} -->|${edge.weight||1}| ${safe(edge.target)}`),'  classDef cycle fill:#fff0f0,stroke:#b44747,stroke-width:3px;'];
    const url=URL.createObjectURL(new Blob([lines.join('\n')+'\n'],{type:'text/vnd.mermaid;charset=utf-8'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`${applicationName.replace(/[^a-z0-9-_]+/gi,'-').toLowerCase()}-${diagramLevel}-architecture.mmd`;anchor.click();URL.revokeObjectURL(url);
  }

  function exportSvgElement(){
    if(!diagramGraph)return null;
    const width=1200,columns=5,height=Math.max(480,Math.ceil(diagramGraph.nodes.length/columns)*130+100);
    const points=new Map<string,{x:number;y:number}>();
    diagramGraph.nodes.forEach((node,index)=>points.set(node.id,{x:120+(index%columns)*240,y:80+Math.floor(index/columns)*130}));
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('xmlns','http://www.w3.org/2000/svg');svg.setAttribute('width',String(width));svg.setAttribute('height',String(height));svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    const style=document.createElementNS(svg.namespaceURI,'style');style.textContent='text{font:14px Inter,Arial,sans-serif;fill:#243b31}.node{fill:#eef4ec;stroke:#52846a;stroke-width:2}.cycle{fill:#fff0f0;stroke:#b44747;stroke-width:3}.edge{stroke:#82968a;stroke-width:2;fill:none;marker-end:url(#arrow)}';svg.append(style);
    const defs=document.createElementNS(svg.namespaceURI,'defs');defs.innerHTML='<marker id="arrow" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L0,8 L9,4 z" fill="#82968a"/></marker>';svg.append(defs);
    const title=document.createElementNS(svg.namespaceURI,'text');title.setAttribute('x','24');title.setAttribute('y','30');title.setAttribute('font-weight','700');title.textContent=`${applicationName} - ${diagramLevel} architecture`;svg.append(title);
    for(const edge of diagramGraph.edges){const a=points.get(edge.source),b=points.get(edge.target);if(!a||!b)continue;const line=document.createElementNS(svg.namespaceURI,'line');line.setAttribute('x1',String(a.x));line.setAttribute('y1',String(a.y));line.setAttribute('x2',String(b.x));line.setAttribute('y2',String(b.y));line.setAttribute('class','edge');svg.append(line);}
    for(const node of diagramGraph.nodes){const p=points.get(node.id)!;const group=document.createElementNS(svg.namespaceURI,'g');const shape=document.createElementNS(svg.namespaceURI,'rect');shape.setAttribute('x',String(p.x-70));shape.setAttribute('y',String(p.y-25));shape.setAttribute('width','140');shape.setAttribute('height','50');shape.setAttribute('rx','12');shape.setAttribute('class',cycleNodeIds.includes(node.id)?'cycle':'node');group.append(shape);const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',String(p.x));label.setAttribute('y',String(p.y+5));label.setAttribute('text-anchor','middle');label.textContent=(node.name||node.id).slice(0,24);group.append(label);svg.append(group);}
    return svg;
  }
  function saveBlob(blob:Blob,extension:string,type:string){const url=URL.createObjectURL(new Blob([blob],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`${applicationName.replace(/[^a-z0-9-_]+/gi,'-').toLowerCase()}-${diagramLevel}-architecture.${extension}`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function downloadSvg(){const svg=exportSvgElement();if(svg)saveBlob(new Blob([new XMLSerializer().serializeToString(svg)]),'svg','image/svg+xml;charset=utf-8');}
  function downloadPng(){const svg=exportSvgElement();if(!svg)return;const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml'}));const image=new Image();image.onload=()=>{const canvas=document.createElement('canvas');canvas.width=Number(svg.getAttribute('width'))*2;canvas.height=Math.round(Number(svg.getAttribute('height'))*2);const context=canvas.getContext('2d');if(context){context.fillStyle='#ffffff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);canvas.toBlob(blob=>{if(blob)saveBlob(blob,'png','image/png');URL.revokeObjectURL(url);});}else URL.revokeObjectURL(url);};image.onerror=()=>URL.revokeObjectURL(url);image.src=url;}

  return <>
    <PageTitle eyebrow="APPLICATION ARCHITECTURE" title="How the analyzed application is put together." description="A static blueprint of the scanned code: candidate modules, code layers, and the dependencies connecting them." action={<Badge tone="green">STATIC ANALYSIS</Badge>}/>
    <div className="architecture-caveat"><Network size={17}/><p><strong>Evidence boundary:</strong> these are code-derived candidate modules. This view does not claim they are separately deployed services or prove runtime traffic.</p></div>
    <section className="architecture-system-boundary" aria-label="Analyzed application boundary">
      <div className="architecture-system-heading"><span className="architecture-app-icon"><Package size={21}/></span><div><small>ANALYZED APPLICATION</small><h2>{applicationName}</h2><p>{artifact} Ã‚Â· {packaging.replaceAll('_',' ')}</p></div><Badge tone="neutral">{summary.scanner?.name||'Static scanner'} analysis</Badge></div>
      <div className="architecture-stats"><Stat label="Classes" value={summary.class_count.toLocaleString()} note="Application bytecode classes" icon={<Braces size={17}/>}/><Stat label="Packages" value={summary.package_count.toLocaleString()} note="Packages discovered" icon={<Layers3 size={17}/>}/><Stat label="Candidate modules" value={domains.length.toLocaleString()} note="Inferred from package and dependency structure" icon={<Boxes size={17}/>}/><Stat label="Static dependencies" value={summary.dependency_count.toLocaleString()} note="Directed class dependencies" icon={<Network size={17}/>}/><Stat label="External references" value={summary.external_dependency_count.toLocaleString()} note="References outside scanned classes" icon={<Database size={17}/>}/></div>
    </section>

    <div className="architecture-blueprint-grid">
      <section className="panel architecture-topology">
        <div className="panel-heading"><div><h2>{diagramLevel==='system'?'System relationship map':diagramLevel==='package'?'Package relationship map':'Module relationship map'}</h2><p>Bounded aggregate graph; arrows point from a dependent node to its dependency. Red outlines indicate cycle membership.</p></div><div className="architecture-export-actions"><label className="architecture-level-select">Diagram level<select aria-label="Diagram level" value={diagramLevel} onChange={event=>setDiagramLevel(event.target.value as typeof diagramLevel)}><option value="system">System</option><option value="module">Module</option><option value="package">Package</option></select></label><button className="button secondary" disabled={!diagramGraph?.nodes.length} onClick={downloadMermaid}>Mermaid</button><button className="button secondary" disabled={!diagramGraph?.nodes.length} onClick={downloadSvg}><Download size={15}/>SVG</button><button className="button secondary" disabled={!diagramGraph?.nodes.length} onClick={downloadPng}><Download size={15}/>PNG</button><button className="button secondary" disabled={!diagramGraph?.nodes.length} onClick={()=>window.print()}><Printer size={15}/>Print / PDF</button><Badge tone="green">{diagramGraph?.total_nodes||0} nodes</Badge></div></div>
        {(diagramLevel==='system'&&(allDomains.isPending||allDomains.isError))||(diagramLevel==='package'&&(packageGraph.isPending||packageGraph.isError))||(diagramLevel==='module'&&(domainGraph.isPending||domainGraph.isError))?<Loading text="Building aggregate map..."/>:diagramGraph&&<>
          <GraphCanvas data={diagramGraph} domains={domains} cycleNodeIds={cycleNodeIds} onNode={node=>setSelectedId(node.id)}/>
          <div className="architecture-map-footer"><span><i className="architecture-arrow-key"/> Dependent to dependency</span><span>{diagramGraph.total_edges} aggregate relationships; {cycleNodeIds.length} nodes participate in cycles</span><span>Select a module to inspect its contents</span></div>
        </>}
      </section>
      <aside className="panel architecture-facts">
        <p className="eyebrow">WHAT THIS SCAN CAN TELL YOU</p>
        <h2>Code structure, with its limits visible.</h2>
        <div className="architecture-fact"><strong>Candidate boundaries</strong><span>Package clusters and dependency patterns suggest where related code sits.</span></div>
        <div className="architecture-fact"><strong>Dependency direction</strong><span>Arrows show static references from caller/dependent to dependency.</span></div>
        <div className="architecture-fact"><strong>Code roles</strong><span>Class annotations and names help group entry points, business logic, and data code.</span></div>
        <div className="architecture-fact muted"><strong>Deployment and runtime</strong><span>Not established by a static scan. Use runtime evidence separately to confirm what communicates while the app runs.</span></div>
        <p className="architecture-confidence-note">Role labels use annotation and class-name patterns. Review them against the source before treating them as confirmed layers.</p>
      </aside>
    </div>

    <section className="architecture-modules-section">
      <div className="panel-heading"><div><p className="eyebrow">APPLICATION COMPONENTS</p><h2>Candidate modules and their code layers</h2><p>Select a module to inspect packages and class names found in the scan.</p></div></div>
      {classGraph.error?<ErrorBox error={classGraph.error}/>:classGraph.isPending?<Loading text="Loading analyzed classesÃ¢â‚¬Â¦"/>:<>
        {classGraph.data?.truncated&&<div className="notice">The class detail view is capped at 400 classes. Module totals remain from the full analysis; expanders show only the classes returned for this view.</div>}
        <div className="architecture-module-grid">{domains.map((domain,index)=>{
          const members=classNodes.filter(node=>node.domain_id===domain.id);
          const groups=Object.fromEntries((['api','business','data','support'] as ArchitectureLayer[]).map(layer=>[layer,members.filter(node=>architectureLayer(node)===layer)])) as Record<ArchitectureLayer,GraphNode[]>;
          return <article className={'architecture-module-card '+(selectedId===domain.id?'selected':'')} key={domain.id}>
            <button className="architecture-module-select" onClick={()=>setSelectedId(domain.id)} aria-pressed={selectedId===domain.id}>
              <span className="architecture-module-number">{String(index+1).padStart(2,'0')}</span><span><strong>{domain.name}</strong><small>{domain.class_count} classes Ã‚Â· {domain.package_count} packages Ã‚Â· {Math.round(domain.confidence*100)}% heuristic confidence</small></span><ArrowDownRight size={17}/>
            </button>
            <div className="architecture-package-list"><strong>Packages</strong><span>{domain.packages.slice(0,4).join(' Ã‚Â· ')||'No package names recorded'}{domain.packages.length>4?` Ã‚Â· +${domain.packages.length-4} more`:''}</span></div>
            <div className="architecture-layer-summary">{(['api','business','data','support'] as ArchitectureLayer[]).map(layer=>{const Icon=layerIcons[layer];return <span key={layer} title={layerLabels[layer]}><Icon size={13}/>{groups[layer].length}{classGraph.data?.truncated?' shown':''}</span>;})}</div>
          </article>;
        })}</div>
      </>}
    </section>

    {selected&&<section className="panel architecture-selected-detail" aria-live="polite">
      <div className="panel-heading"><div><p className="eyebrow">SELECTED CANDIDATE MODULE</p><h2>{selected.name}</h2><p>{selected.class_count} classes across {selected.package_count} packages Ã‚Â· {selected.confidence_note}</p></div><button className="text-link" onClick={()=>setSelectedId('')}>Clear selection</button></div>
      <div className="architecture-detail-stats"><span><strong>{selected.metrics.incoming_edges}</strong> incoming class dependencies</span><span><strong>{selected.metrics.outgoing_edges}</strong> outgoing class dependencies</span><span><strong>{selected.metrics.internal_edges}</strong> internal class dependencies</span><span><strong>{selected.database.status.replaceAll('_',' ')}</strong> data signals</span></div>
      <div className="architecture-class-groups">{(['api','business','data','support'] as ArchitectureLayer[]).map(layer=><ArchitectureClassGroup key={layer} layer={layer} nodes={grouped[layer]} complete={completeClassSample}/>)}</div>
      <div className="architecture-domain-dependencies"><h3>Connected candidate modules</h3>{edges.filter(edge=>edge.source===selected.id||edge.target===selected.id).length?<ul>{edges.filter(edge=>edge.source===selected.id||edge.target===selected.id).map(edge=><li key={edge.id}><span>{names[edge.source]||edge.source}</span><ArrowDownRight size={15}/><span>{names[edge.target]||edge.target}</span><strong>{edge.weight||1} class dependency pair{edge.weight===1?'':'s'}</strong></li>)}</ul>:<p>No cross-module dependency was found in this static scan.</p>}</div>
    </section>}
  </>;
}

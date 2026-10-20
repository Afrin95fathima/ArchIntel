import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowDownRight, Boxes, Braces, Database, Download, Layers3, Network, Package, Workflow, Printer } from 'lucide-react';
import { api } from './api';
import { Badge, ErrorBox, Loading, PageTitle, Stat } from './components';
import { GraphCanvas } from './GraphExplorer';
import type { Analysis, Assessment, Cycle, Domain, GraphData, GraphNode, Issue, Items, Summary } from './types';
import type { RuntimeSession } from './runtime/types';
import { buildDiagramNodeColors, compareDiagramNodeColors, type DiagramColorMode, type DiagramCoverage } from './architectureDiagram';
import './architecture.css';

type ArchitectureLayer = 'api' | 'business' | 'data' | 'support';
const layerLabels: Record<ArchitectureLayer, string> = {
  api: 'Entry points and API', business: 'Business logic', data: 'Data access and models', support: 'Supporting code',
};
const layerIcons = {api: Workflow, business: Braces, data: Database, support: Layers3};
type DiagramMode='dependencies'|'modernization'|'before-after';
const colorLabels:Record<DiagramColorMode,string>={debt:'Technical debt',coverage:'Runtime coverage',wave:'Modernization wave'};
const EMPTY_ISSUES:Issue[]=[];
const EMPTY_ASSESSMENTS:Assessment[]=[];
const EMPTY_CYCLES:Cycle[]=[];

function architectureLayer(node: GraphNode): ArchitectureLayer {
  const identity = `${node.name || node.id} ${(node.annotations || []).join(' ')}`.toLowerCase();
  if (/controller|restcontroller|requestmapping|path|endpoint|resource|listener|consumer|scheduled/.test(identity)) return 'api';
  if (/service|usecase|interactor|manager|coordinator|handler|facade|workflow/.test(identity)) return 'business';
  if (/repository|repositories|dao|entity|entities|model|models|document|record|mapper/.test(identity)) return 'data';
  return 'support';
}

function cycleNodes(graph:GraphData|undefined,cycles:Cycle[],level:'system'|'module'|'package'){
  if(!graph)return [];
  if(level==='package'){
    const members=cycles.flatMap(cycle=>cycle.members);
    return graph.nodes.filter(node=>members.some(name=>name===(node.name||node.id)||name.startsWith((node.name||node.id)+'.'))).map(node=>node.id);
  }
  const impacted=new Set(cycles.flatMap(cycle=>cycle.impacted_domains||[]));
  return graph.nodes.filter(node=>impacted.has(node.id)).map(node=>node.id);
}

function ArchitectureClassGroup({layer,nodes,complete}:{layer:ArchitectureLayer;nodes:GraphNode[];complete:boolean}) {
  const Icon=layerIcons[layer];
  return <details className="architecture-class-group">
    <summary><Icon size={15}/><span>{layerLabels[layer]}</span><strong>{nodes.length}{complete?'':' shown'}</strong></summary>
    {nodes.length?<ul>{nodes.slice(0,40).map(node=><li key={node.id} title={node.name || node.id}>{node.name || node.id}</li>)}</ul>:<p>No class matched this group's annotation or name pattern (see Role labels).</p>}
    {nodes.length>40&&<small>Showing 40 of {nodes.length} matching classes.</small>}
  </details>;
}

export function ArchitectureBlueprint({analysisId,applicationId,analyses,applicationName,summary,domains}:{analysisId:string;applicationId:string;analyses:Analysis[];applicationName:string;summary:Summary;domains:Domain[]}) {
  const [selectedId,setSelectedId]=useState('');
  const [diagramMode,setDiagramMode]=useState<DiagramMode>('dependencies');
  const [colorMode,setColorMode]=useState<DiagramColorMode>('debt');
  const [baselineId,setBaselineId]=useState('');
  const [runtimeSessionId,setRuntimeSessionId]=useState('');
  const [exportSide,setExportSide]=useState<'before'|'after'>('after');
  const domainGraph=useQuery({queryKey:['architecture-blueprint-domains',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/domains?limit=400`)});
  const classGraph=useQuery({queryKey:['architecture-blueprint-classes',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/classes?limit=400`)});
  const packageGraph=useQuery({queryKey:['architecture-blueprint-packages',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/packages?limit=400`)});
  const [diagramLevel,setDiagramLevel]=useState<'system'|'module'|'package'>('module');
  const allDomains=useQuery({queryKey:['architecture-blueprint-all-domains',analysisId],queryFn:()=>api<GraphData>(`/analyses/${analysisId}/graph/domains?limit=400`),enabled:diagramLevel==='system'});
  const cycles=useQuery({queryKey:['architecture-blueprint-cycles',analysisId],queryFn:()=>api<{items:Cycle[]}>('/analyses/'+analysisId+'/cycles')});
  const issues=useQuery({queryKey:['architecture-blueprint-issues',analysisId],queryFn:()=>api<Items<Issue>>(`/analyses/${analysisId}/issues?limit=500`)});
  const assessments=useQuery({queryKey:['architecture-blueprint-modernization',analysisId],queryFn:()=>api<Items<Assessment>>(`/analyses/${analysisId}/modernization`)});
  const sessions=useQuery({queryKey:['architecture-blueprint-sessions',applicationId],queryFn:()=>api<RuntimeSession[]>(`/applications/${applicationId}/runtime-sessions`),enabled:!!applicationId});
  const matchingSessions=(sessions.data||[]).filter(session=>session.analysis_id===analysisId&&session.span_count>0);
  const runtimeSession=matchingSessions.find(session=>session.id===runtimeSessionId)||matchingSessions[0];
  const runtimeCoverage=useQuery({queryKey:['architecture-blueprint-coverage',runtimeSession?.id],queryFn:()=>api<DiagramCoverage>(`/runtime-sessions/${runtimeSession!.id}/coverage`),enabled:!!runtimeSession&&colorMode==='coverage'&&diagramMode!=='before-after'});

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
  const activeGraphQuery=diagramLevel==='package'?packageGraph:diagramLevel==='system'?allDomains:domainGraph;
  const completedAnalyses=useMemo(()=>analyses.filter(row=>row.application_id===applicationId&&row.status==='COMPLETED').sort((a,b)=>a.created_at.localeCompare(b.created_at)),[analyses,applicationId]);
  const currentIndex=completedAnalyses.findIndex(row=>row.id===analysisId);
  const earlierAnalyses=completedAnalyses.filter(row=>row.id!==analysisId&&(currentIndex<0||completedAnalyses.indexOf(row)<currentIndex));
  const baseline=earlierAnalyses.find(row=>row.id===baselineId)||earlierAnalyses.at(-1);
  const baselineGraph=useQuery({queryKey:['architecture-blueprint-before',baseline?.id,diagramLevel],queryFn:()=>api<GraphData>(`/analyses/${baseline!.id}/graph/${diagramLevel==='package'?'packages':'domains'}?limit=400`),enabled:diagramMode==='before-after'&&!!baseline});
  const baselineCycles=useQuery({queryKey:['architecture-blueprint-before-cycles',baseline?.id],queryFn:()=>api<Items<Cycle>>(`/analyses/${baseline!.id}/cycles`),enabled:diagramMode==='before-after'&&!!baseline});
  const cycleNodeIds=useMemo(()=>cycleNodes(diagramGraph,cycles.data?.items||EMPTY_CYCLES,diagramLevel),[diagramGraph,cycles.data,diagramLevel]);
  const beforeCycleNodeIds=useMemo(()=>cycleNodes(baselineGraph.data,baselineCycles.data?.items||EMPTY_CYCLES,diagramLevel),[baselineGraph.data,baselineCycles.data,diagramLevel]);
  const issuesList=issues.data?.items||EMPTY_ISSUES;
  const assessmentList=assessments.data?.items||EMPTY_ASSESSMENTS;
  const colorContext=diagramMode==='modernization'?'wave':colorMode;
  const nodeColors=useMemo(()=>diagramGraph?buildDiagramNodeColors(diagramGraph,colorContext,domains,issuesList,assessmentList,runtimeCoverage.data):{},[diagramGraph,colorContext,domains,issuesList,assessmentList,runtimeCoverage.data]);
  const comparison=useMemo(()=>baselineGraph.data&&diagramGraph?compareDiagramNodeColors(baselineGraph.data,diagramGraph):null,[baselineGraph.data,diagramGraph]);
  const exportingBefore=diagramMode==='before-after'&&exportSide==='before';
  const exportGraph=exportingBefore?baselineGraph.data:diagramGraph;
  const exportNodeColors=exportingBefore&&comparison?comparison.before:diagramMode==='before-after'&&comparison?comparison.after:nodeColors;
  const exportCycleNodeIds=exportingBefore?beforeCycleNodeIds:cycleNodeIds;

  function downloadMermaid(){
    if(!exportGraph)return;
    const safe=(id:string)=>'n_'+Array.from(id).map(char=>char.codePointAt(0)!.toString(16)).join('_');
    const lines=['flowchart LR',...exportGraph.nodes.map(node=>`  ${safe(node.id)}["${(node.name||node.id).replace(/[\r\n"\[\]{}]/g,' ')}"]`),...exportGraph.edges.map(edge=>`  ${safe(edge.source)} -->|${edge.weight||1}| ${safe(edge.target)}`),...exportCycleNodeIds.map(id=>`  class ${safe(id)} cycle;`),...Object.entries(exportNodeColors).map(([id,color])=>`  class ${safe(id)} color_${color.slice(1)};`),'  classDef cycle fill:#fff0f0,stroke:#b44747,stroke-width:3px;',...Array.from(new Set(Object.values(exportNodeColors))).map(color=>`  classDef color_${color.slice(1)} fill:${color},stroke:#ffffff;`)];
    const url=URL.createObjectURL(new Blob([lines.join('\n')+'\n'],{type:'text/vnd.mermaid;charset=utf-8'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`${applicationName.replace(/[^a-z0-9-_]+/gi,'-').toLowerCase()}-${diagramLevel}-architecture.mmd`;anchor.click();URL.revokeObjectURL(url);
  }

  function exportSvgElement(){
    if(!diagramGraph)return null;
    if(!exportGraph)return null;
    const width=1200,columns=5,height=Math.max(480,Math.ceil(exportGraph.nodes.length/columns)*130+100);
    const points=new Map<string,{x:number;y:number}>();
    exportGraph.nodes.forEach((node,index)=>points.set(node.id,{x:120+(index%columns)*240,y:80+Math.floor(index/columns)*130}));
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('xmlns','http://www.w3.org/2000/svg');svg.setAttribute('width',String(width));svg.setAttribute('height',String(height));svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    const style=document.createElementNS(svg.namespaceURI,'style');style.textContent='text{font:14px Inter,Arial,sans-serif;fill:#243b31}.node{fill:#eef4ec;stroke:#52846a;stroke-width:2}.cycle{fill:#fff0f0;stroke:#b44747;stroke-width:3}.edge{stroke:#82968a;stroke-width:2;fill:none;marker-end:url(#arrow)}';svg.append(style);
    const defs=document.createElementNS(svg.namespaceURI,'defs');defs.innerHTML='<marker id="arrow" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L0,8 L9,4 z" fill="#82968a"/></marker>';svg.append(defs);
    const title=document.createElementNS(svg.namespaceURI,'text');title.setAttribute('x','24');title.setAttribute('y','30');title.setAttribute('font-weight','700');title.textContent=`${applicationName} - ${diagramLevel} ${diagramMode} architecture`;svg.append(title);
    for(const edge of exportGraph.edges){const a=points.get(edge.source),b=points.get(edge.target);if(!a||!b)continue;const line=document.createElementNS(svg.namespaceURI,'line');line.setAttribute('x1',String(a.x));line.setAttribute('y1',String(a.y));line.setAttribute('x2',String(b.x));line.setAttribute('y2',String(b.y));line.setAttribute('class','edge');svg.append(line);}
    for(const node of exportGraph.nodes){const p=points.get(node.id)!;const group=document.createElementNS(svg.namespaceURI,'g');const shape=document.createElementNS(svg.namespaceURI,'rect');shape.setAttribute('x',String(p.x-70));shape.setAttribute('y',String(p.y-25));shape.setAttribute('width','140');shape.setAttribute('height','50');shape.setAttribute('rx','12');shape.setAttribute('class',exportCycleNodeIds.includes(node.id)?'cycle':'node');if(!exportCycleNodeIds.includes(node.id)&&exportNodeColors[node.id])shape.setAttribute('style',`fill:${exportNodeColors[node.id]}`);group.append(shape);const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',String(p.x));label.setAttribute('y',String(p.y+5));label.setAttribute('text-anchor','middle');label.textContent=(node.name||node.id).slice(0,24);group.append(label);svg.append(group);}
    return svg;
  }
  function saveBlob(blob:Blob,extension:string,type:string){const url=URL.createObjectURL(new Blob([blob],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`${applicationName.replace(/[^a-z0-9-_]+/gi,'-').toLowerCase()}-${diagramLevel}-${diagramMode}${exportingBefore?'-before':''}-architecture.${extension}`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function downloadSvg(){const svg=exportSvgElement();if(svg)saveBlob(new Blob([new XMLSerializer().serializeToString(svg)]),'svg','image/svg+xml;charset=utf-8');}
  function downloadPng(){const svg=exportSvgElement();if(!svg)return;const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml'}));const image=new Image();image.onload=()=>{const sourceWidth=Number(svg.getAttribute('width')),sourceHeight=Number(svg.getAttribute('height'));const scale=Math.min(2,Math.sqrt(16_000_000/(sourceWidth*sourceHeight)));const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.floor(sourceWidth*scale));canvas.height=Math.max(1,Math.floor(sourceHeight*scale));const context=canvas.getContext('2d');if(context){context.fillStyle='#ffffff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);canvas.toBlob(blob=>{if(blob)saveBlob(blob,'png','image/png');URL.revokeObjectURL(url);});}else URL.revokeObjectURL(url);};image.onerror=()=>URL.revokeObjectURL(url);image.src=url;}

  return <>
    <PageTitle eyebrow="APPLICATION ARCHITECTURE" title="Modules, packages and dependencies." description="A static blueprint of the scanned code: candidate modules, code layers, and the dependencies connecting them." action={<Badge tone="green">STATIC ANALYSIS</Badge>}/>
    <div className="architecture-caveat"><Network size={17}/><p><strong>Evidence boundary:</strong> these are code-derived candidate modules. Modules are code-derived, not deployed services.</p></div>
    <section className="architecture-system-boundary" aria-label="Analyzed application boundary">
      <div className="architecture-system-heading"><span className="architecture-app-icon"><Package size={21}/></span><div><small>ANALYZED APPLICATION</small><h2>{applicationName}</h2><p>{artifact} · {packaging.replaceAll('_',' ')}</p></div><Badge tone="neutral">{summary.scanner?.name||'Static scanner'} analysis</Badge></div>
      <div className="architecture-stats"><Stat label="Classes" value={summary.class_count.toLocaleString()} note="Application bytecode classes" icon={<Braces size={17}/>}/><Stat label="Packages" value={summary.package_count.toLocaleString()} note="Packages discovered" icon={<Layers3 size={17}/>}/><Stat label="Candidate modules" value={domains.length.toLocaleString()} note="Inferred from package and dependency structure" icon={<Boxes size={17}/>}/><Stat label="Static dependencies" value={summary.dependency_count.toLocaleString()} note="Directed class dependencies" icon={<Network size={17}/>}/><Stat label="External references" value={summary.external_dependency_count.toLocaleString()} note="References outside scanned classes" icon={<Database size={17}/>}/></div>
    </section>

    <div className="architecture-blueprint-grid">
      <section className="panel architecture-topology">
        <div className="panel-heading"><div><h2>{diagramMode==='before-after'?'Before and after baseline':diagramMode==='modernization'?'Modernization wave map':diagramLevel==='system'?'System relationship map':diagramLevel==='package'?'Package relationship map':'Module relationship map'}</h2><p>Bounded aggregate graph; arrows point from a dependent node to its dependency. Red outlines mark cycle involvement. Node colors show the selected evidence overlay.</p></div><div className="architecture-export-actions"><label className="architecture-level-select">Diagram view<select aria-label="Diagram view" value={diagramMode} onChange={event=>setDiagramMode(event.target.value as DiagramMode)}><option value="dependencies">Dependencies</option><option value="modernization">Modernization waves</option><option value="before-after">Before / after</option></select></label><label className="architecture-level-select">Diagram level<select aria-label="Diagram level" value={diagramLevel} onChange={event=>setDiagramLevel(event.target.value as typeof diagramLevel)}><option value="system">System</option><option value="module">Module</option><option value="package">Package</option></select></label>{diagramMode==='before-after'&&<label className="architecture-level-select">Before scan<select aria-label="Before scan" value={baseline?.id||''} onChange={event=>setBaselineId(event.target.value)}>{earlierAnalyses.map(row=><option key={row.id} value={row.id}>{new Date(row.created_at).toLocaleDateString()} · {row.id.slice(0,6)}</option>)}</select></label>}{diagramMode==='dependencies'&&<label className="architecture-level-select">Color nodes by<select aria-label="Color nodes by" value={colorMode} onChange={event=>setColorMode(event.target.value as DiagramColorMode)}>{Object.entries(colorLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>}{diagramMode==='dependencies'&&colorMode==='coverage'&&matchingSessions.length>0&&<label className="architecture-level-select">Runtime session<select aria-label="Runtime session" value={runtimeSession?.id||''} onChange={event=>setRuntimeSessionId(event.target.value)}>{matchingSessions.map(session=><option key={session.id} value={session.id}>{session.name} · {session.environment}</option>)}</select></label>}{diagramMode==='before-after'&&<label className="architecture-level-select">Export side<select aria-label="Export side" value={exportSide} onChange={event=>setExportSide(event.target.value as typeof exportSide)}><option value="before">Before</option><option value="after">After</option></select></label>}<button className="button secondary" disabled={!exportGraph?.nodes.length} onClick={downloadMermaid}>Mermaid</button><button className="button secondary" disabled={!exportGraph?.nodes.length} onClick={downloadSvg}><Download size={15}/>SVG</button><button className="button secondary" disabled={!exportGraph?.nodes.length} onClick={downloadPng}><Download size={15}/>PNG</button><button className="button secondary" onClick={()=>window.print()}><Printer size={15}/>Print / PDF</button><Badge tone="green">{diagramGraph?.total_nodes||0} nodes</Badge></div></div>
        {activeGraphQuery.error?<ErrorBox error={activeGraphQuery.error}/>:activeGraphQuery.isPending?<Loading text="Building aggregate map..."/>:diagramGraph&&<>
          {diagramMode==='before-after'?<>{baselineGraph.isPending?<Loading text="Loading before scan..."/>:baselineGraph.error?<p role="alert">Unable to load the selected earlier scan.</p>:baselineGraph.data&&comparison&&baseline?<div className="architecture-before-after"><section><h3>Before · {new Date(baseline.created_at).toLocaleDateString()}</h3><GraphCanvas data={baselineGraph.data} domains={domains} cycleNodeIds={beforeCycleNodeIds} nodeColors={comparison.before}/></section><section><h3>After · current scan</h3><GraphCanvas data={diagramGraph} domains={domains} cycleNodeIds={cycleNodeIds} nodeColors={comparison.after}/></section></div>:<p>No earlier completed scan is available for this application.</p>}{comparison&&<div className="architecture-map-footer"><span>{comparison.added} added</span><span>{comparison.removed} removed</span><span>{comparison.unchanged} unchanged</span><span>Red = removed; green = added; gray = present in both. Counts compare bounded visible nodes.</span></div>}</>:<><GraphCanvas data={diagramGraph} domains={domains} cycleNodeIds={cycleNodeIds} nodeColors={nodeColors} onNode={node=>setSelectedId(node.id)}/><div className="architecture-map-footer"><span><i className="architecture-arrow-key"/> Dependent to dependency</span><span>{diagramGraph.total_edges} aggregate relationships; {cycleNodeIds.length} nodes participate in cycles</span><span>{diagramMode==='modernization'?`${assessmentList.length} candidate domains assigned to modernization waves`:colorLabels[colorContext]}</span>{diagramMode==='modernization'&&<span>Color maps to wave order; lower numbers are earlier waves.</span>}{diagramMode==='dependencies'&&colorMode==='debt'&&<span>Green: no listed debt · yellow to red: low through critical/high severity.</span>}{diagramMode==='dependencies'&&colorMode==='coverage'&&<><span>Red: &lt;40% · amber: 40–79% · green: ≥80% observed · gray: unavailable.</span><span>{runtimeSession?runtimeSession.name:'No runtime session with observations'}</span></>}{issues.error&&colorMode==='debt'&&<span role="alert">Technical-debt colors unavailable.</span>}{runtimeCoverage.error&&colorMode==='coverage'&&<span role="alert">Runtime coverage colors unavailable.</span>}{diagramMode==='modernization'&&assessments.error&&<span role="alert">Wave colors unavailable.</span>}</div></>}
        </>}
      </section>
      <aside className="panel architecture-facts">
        <p className="eyebrow">WHAT THIS SCAN CAN TELL YOU</p>
        <h2>Code structure, with its limits visible.</h2>
        <div className="architecture-fact"><strong>Candidate boundaries</strong><span>Candidate boundary = a package cluster with dense internal dependencies.</span></div>
        <div className="architecture-fact"><strong>Dependency direction</strong><span>Arrows show static references from caller/dependent to dependency.</span></div>
        <div className="architecture-fact"><strong>Code roles</strong><span>Code role = a class group inferred from annotations (@Controller, @Repository) and class names.</span></div>
        <div className="architecture-fact muted"><strong>Deployment and runtime</strong><span>Not established by a static scan. Use runtime evidence separately to confirm what communicates while the app runs.</span></div>
        <p className="architecture-confidence-note">Role label = an annotation or class-name pattern match (for example @Controller or *Repository). Review them against the source before treating them as confirmed layers.</p>
      </aside>
    </div>

    <section className="architecture-modules-section">
      <div className="panel-heading"><div><p className="eyebrow">APPLICATION COMPONENTS</p><h2>Candidate modules and their code layers</h2><p>Select a module to inspect packages and class names found in the scan.</p></div></div>
      {classGraph.error?<ErrorBox error={classGraph.error}/>:classGraph.isPending?<Loading text="Loading analyzed classes…"/>:<>
        {classGraph.data?.truncated&&<div className="notice">The class detail view is capped at 400 classes. Module totals remain from the full analysis; expanders show only the classes returned for this view.</div>}
        <div className="architecture-module-grid">{domains.map((domain,index)=>{
          const members=classNodes.filter(node=>node.domain_id===domain.id);
          const groups=Object.fromEntries((['api','business','data','support'] as ArchitectureLayer[]).map(layer=>[layer,members.filter(node=>architectureLayer(node)===layer)])) as Record<ArchitectureLayer,GraphNode[]>;
          return <article className={'architecture-module-card '+(selectedId===domain.id?'selected':'')} key={domain.id}>
            <button className="architecture-module-select" onClick={()=>setSelectedId(domain.id)} aria-pressed={selectedId===domain.id}>
              <span className="architecture-module-number">{String(index+1).padStart(2,'0')}</span><span><strong>{domain.name}</strong><small>{domain.class_count} classes · {domain.package_count} packages · {Math.round(domain.confidence*100)}% heuristic confidence</small></span><ArrowDownRight size={17}/>
            </button>
            <div className="architecture-package-list"><strong>Packages</strong><span>{domain.packages.slice(0,4).join(' · ')||'No package names recorded'}{domain.packages.length>4?` · +${domain.packages.length-4} more`:''}</span></div>
            <div className="architecture-layer-summary">{(['api','business','data','support'] as ArchitectureLayer[]).map(layer=>{const Icon=layerIcons[layer];return <span key={layer} title={layerLabels[layer]}><Icon size={13}/>{groups[layer].length}{classGraph.data?.truncated?' shown':''}</span>;})}</div>
          </article>;
        })}</div>
      </>}
    </section>

    {selected&&<section className="panel architecture-selected-detail" aria-live="polite">
      <div className="panel-heading"><div><p className="eyebrow">SELECTED CANDIDATE MODULE</p><h2>{selected.name}</h2><p>{selected.class_count} classes across {selected.package_count} packages · {selected.confidence_note}</p></div><button className="text-link" onClick={()=>setSelectedId('')}>Clear selection</button></div>
      <div className="architecture-detail-stats"><span><strong>{selected.metrics.incoming_edges}</strong> incoming class dependencies</span><span><strong>{selected.metrics.outgoing_edges}</strong> outgoing class dependencies</span><span><strong>{selected.metrics.internal_edges}</strong> internal class dependencies</span><span><strong>{selected.database.status.replaceAll('_',' ')}</strong> data signals</span></div>
      <div className="architecture-class-groups">{(['api','business','data','support'] as ArchitectureLayer[]).map(layer=><ArchitectureClassGroup key={layer} layer={layer} nodes={grouped[layer]} complete={completeClassSample}/>)}</div>
      <div className="architecture-domain-dependencies"><h3>Connected candidate modules</h3>{edges.filter(edge=>edge.source===selected.id||edge.target===selected.id).length?<ul>{edges.filter(edge=>edge.source===selected.id||edge.target===selected.id).map(edge=><li key={edge.id}><span>{names[edge.source]||edge.source}</span><ArrowDownRight size={15}/><span>{names[edge.target]||edge.target}</span><strong>{edge.weight||1} class dependency pair{edge.weight===1?'':'s'}</strong></li>)}</ul>:<p>No cross-module dependency was found in this scan.</p>}</div>
    </section>}
  </>;
}

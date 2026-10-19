import type { Assessment, Domain, GraphData, GraphNode, Issue } from './types';

export type DiagramColorMode='debt'|'coverage'|'wave';
export type DomainCoverage={id:string;observed:number;total:number;unobserved_classes:string[]};
export type DiagramCoverage={domain_observations:DomainCoverage[]};

const DEBT_COLORS={critical:'#a83232',high:'#c6534b',medium:'#d08a35',low:'#d3b24c',none:'#5c9570'};
const COVERAGE_COLORS={unknown:'#9aa69c',low:'#c6534b',partial:'#d08a35',high:'#5c9570'};
const WAVE_COLORS=['#4f8063','#5579ad','#aa8551','#8771a9','#5d9194','#b26d70','#77834e'];

function nodeDomains(node:GraphNode):string[]{return node.domain_ids?.length?node.domain_ids:[node.domain_id||node.id];}

export function buildDiagramNodeColors(data:GraphData,mode:DiagramColorMode,domains:Domain[],issues:Issue[],assessments:Assessment[],coverage?:DiagramCoverage):Record<string,string>{
  const observations=new Map((coverage?.domain_observations||[]).map(row=>[row.id,row]));
  const result:Record<string,string>={};
  for(const node of data.nodes){
    const ids=nodeDomains(node);
    if(mode==='wave'){
      const waves=assessments.filter(row=>ids.includes(row.domain_id)).map(row=>row.wave).filter(Number.isFinite);
      if(waves.length)result[node.id]=WAVE_COLORS[Math.max(0,Math.min(WAVE_COLORS.length-1,Math.min(...waves)-1))];
      continue;
    }
    if(mode==='debt'){
      const rank=(severity:string)=>({CRITICAL:4,HIGH:3,MEDIUM:2,LOW:1}[severity.toUpperCase()]||0);
      const packageNode=!!node.name?.includes('.');
      const linked=issues.filter(issue=>packageNode?
        issue.entity_id===node.name||issue.entity_id.startsWith((node.name||node.id)+'.'):
        issue.domain_ids.some(id=>ids.includes(id))||issue.entity_id===node.id);
      const highest=linked.reduce((value,issue)=>Math.max(value,rank(issue.severity)),0);
      result[node.id]=highest===4?DEBT_COLORS.critical:highest===3?DEBT_COLORS.high:highest===2?DEBT_COLORS.medium:highest===1?DEBT_COLORS.low:DEBT_COLORS.none;
      continue;
    }
    if(!coverage){result[node.id]=COVERAGE_COLORS.unknown;continue;}
    const matchingDomains=domains.filter(domain=>ids.includes(domain.id)||domain.packages.includes(node.name||node.id));
    if(node.name&&node.name.includes('.')){
      const packageName=node.name;
      const classes=matchingDomains.flatMap(domain=>domain.classes.filter(name=>name.startsWith(packageName+'.')));
      if(classes.length){
        const unobserved=new Set(matchingDomains.flatMap(domain=>observations.get(domain.id)?.unobserved_classes||[]));
        const observed=classes.filter(name=>!unobserved.has(name)).length;
        const ratio=observed/classes.length;
        result[node.id]=ratio>=.8?COVERAGE_COLORS.high:ratio>=.4?COVERAGE_COLORS.partial:COVERAGE_COLORS.low;
        continue;
      }
    }
    const available=ids.map(id=>observations.get(id)).filter((row):row is DomainCoverage=>!!row&&row.total>0);
    const total=available.reduce((sum,row)=>sum+row.total,0),observed=available.reduce((sum,row)=>sum+row.observed,0);
    result[node.id]=total?observed/total>=.8?COVERAGE_COLORS.high:observed/total>=.4?COVERAGE_COLORS.partial:COVERAGE_COLORS.low:COVERAGE_COLORS.unknown;
  }
  return result;
}

export function compareDiagramNodeColors(before:GraphData,after:GraphData):{before:Record<string,string>;after:Record<string,string>;added:number;removed:number;unchanged:number}{
  const beforeIds=new Set(before.nodes.map(node=>node.id)),afterIds=new Set(after.nodes.map(node=>node.id));
  const beforeColors=Object.fromEntries(before.nodes.map(node=>[node.id,afterIds.has(node.id)?'#84958a':'#c6534b']));
  const afterColors=Object.fromEntries(after.nodes.map(node=>[node.id,beforeIds.has(node.id)?'#84958a':'#5c9570']));
  return {before:beforeColors,after:afterColors,added:[...afterIds].filter(id=>!beforeIds.has(id)).length,
    removed:[...beforeIds].filter(id=>!afterIds.has(id)).length,unchanged:[...afterIds].filter(id=>beforeIds.has(id)).length};
}

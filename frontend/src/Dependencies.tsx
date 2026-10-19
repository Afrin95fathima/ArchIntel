import { useState } from 'react';
import { GitBranch, Activity } from 'lucide-react';
import { Metrics } from './Insights';
import { CircularDependencies } from './insight/Cycles';
import { Tabs } from './ui/Tabs';
import type { Cycle, Metric } from './types';

export function Dependencies({analysisId,metrics,initialTab='cycles'}:{analysisId:string;cycles?:Cycle[];metrics:Metric[];initialTab?:'cycles'|'metrics'}){
  const [tab,setTab]=useState<'cycles'|'metrics'>(initialTab);
  return <div className="dependencies-workspace"><Tabs label="Dependency analysis" value={tab} onChange={setTab} items={[{value:'cycles',label:'Circular dependencies',icon:<GitBranch size={16}/>},{value:'metrics',label:'Architecture metrics',icon:<Activity size={16}/>}]} />{tab==='cycles'?<CircularDependencies analysisId={analysisId}/>:<Metrics metrics={metrics}/>}</div>;
}

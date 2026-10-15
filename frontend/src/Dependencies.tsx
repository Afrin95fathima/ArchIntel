import { useState } from 'react';
import { GitBranch, Activity } from 'lucide-react';
import { Cycles, Metrics } from './Insights';
import { Tabs } from './ui/Tabs';
import type { Cycle, Metric } from './types';

export function Dependencies({cycles,metrics,initialTab='cycles'}:{cycles:Cycle[];metrics:Metric[];initialTab?:'cycles'|'metrics'}){
  const [tab,setTab]=useState<'cycles'|'metrics'>(initialTab);
  return <div className="dependencies-workspace"><Tabs label="Dependency analysis" value={tab} onChange={setTab} items={[{value:'cycles',label:'Circular dependencies',icon:<GitBranch size={16}/>},{value:'metrics',label:'Architecture metrics',icon:<Activity size={16}/>}]} />{tab==='cycles'?<Cycles cycles={cycles}/>:<Metrics metrics={metrics}/>}</div>;
}

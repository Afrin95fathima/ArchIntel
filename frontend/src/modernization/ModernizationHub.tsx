import { useState } from 'react';
import { GitBranch, Route } from 'lucide-react';
import { PlanningWorkspace } from './PlanningWorkspace';
import { Modernization } from '../Insights';
import { Tabs } from '../ui/Tabs';
import type { Application, Assessment } from '../types';

type ServiceIntent = { applicationId:string; versionId:string; assessmentId:string; decisionId:string; candidateId:string; candidateName:string; rolloutMode:string };

export function ModernizationHub({applications,assessments,confidenceByDomain,onStartService,initialTab='proposal'}:{applications:Application[];assessments:Assessment[];confidenceByDomain:Record<string,number>;onStartService:(intent:ServiceIntent)=>void;initialTab?:'proposal'|'sequence'}) {
  const [tab,setTab]=useState<'proposal'|'sequence'>(initialTab);
  return <div className="modernization-hub">
    <Tabs label="Modernization workspace" value={tab} onChange={setTab} items={[{value:'proposal',label:'Proposal workspace',icon:<Route size={16}/>},{value:'sequence',label:'Extraction sequence',icon:<GitBranch size={16}/>}]} />
    {tab==='proposal'?<PlanningWorkspace applications={applications} onStartService={onStartService}/>:assessments.length?<Modernization assessments={assessments} confidenceByDomain={confidenceByDomain}/>:<section className="empty"><h2>Complete a static analysis to see the sequence.</h2><p>Candidate ordering and readiness are generated from the selected analysis. No architecture sequence is available yet.</p></section>}
  </div>;
}

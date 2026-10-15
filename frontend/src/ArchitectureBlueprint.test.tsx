import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it,vi} from 'vitest';
import {ArchitectureBlueprint} from './ArchitectureBlueprint';

vi.mock('cytoscape',()=>({default:()=>({on:vi.fn(),destroy:vi.fn(),fit:vi.fn()})}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const domain={id:'d1',name:'Billing',confidence:.6,class_count:2,package_count:1,classes:['org.app.billing.Invoice','org.app.billing.Service'],packages:['org.app.billing'],evidence:[],confidence_note:'heuristic',metrics:{cross_domain_ratio:0,internal_cohesion:1,incoming_edges:0,outgoing_edges:0,internal_edges:1},database:{status:'UNKNOWN',repositories:[],note:'',shared_repositories:[]}};
const graph={nodes:[{id:'d1',name:'Billing',class_count:2}],edges:[],total_nodes:1,total_edges:0,truncated:false};
const summary={class_count:2,package_count:1,dependency_count:1,domain_count:1,issue_count:0,external_dependency_count:0,class_scc_count:0,package_scc_count:0,average_readiness:50,issue_counts:{},artifact:{filename:'app.jar',sha256:'x',size:1},scanner:{name:'fixture',version:'1',normalized_results:'json'},limitations:[],algorithm_version:'1'} as never;
it('switches between aggregate diagram levels and exposes safe exports',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url.includes('/cycles')?{items:[]}:graph),{status:200,headers:{'Content-Type':'application/json'}})));
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ArchitectureBlueprint analysisId='a' applicationName='Fixture' summary={summary} domains={[domain as never]}/></QueryClientProvider>);
 expect(await screen.findByRole('heading',{name:'Module relationship map'})).toBeTruthy();
 const level=screen.getByLabelText('Diagram level');fireEvent.change(level,{target:{value:'system'}});
 expect(await screen.findByRole('heading',{name:'System relationship map'})).toBeTruthy();
 fireEvent.change(level,{target:{value:'package'}});expect(await screen.findByRole('heading',{name:'Package relationship map'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'Mermaid'})).toBeTruthy();
 expect(screen.getByRole('button',{name:/Print \/ PDF/})).toBeTruthy();
});

import {cleanup,render,screen,within} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {DatabaseCallers,MappingDetails} from './RuntimeMappingTables';
import type {MappingReport} from './types';

afterEach(cleanup);
const ref=(n:number)=>({session_id:'s1',trace_id:'1'.repeat(32),span_id:n.toString(16).padStart(16,'0')});
const report:MappingReport={
  why:'This table ties runtime spans to scanned classes. 5 of 9 spans mapped to a class by name; 1 identify a controller method by route only and do not add to class coverage; 3 did not map.',
  counts:{events:9,mapped:5,route_resolved:1,unmapped:3},truncated:false,
  resolved:[
    {runtime_identifier:'org.x.OwnerController',static_class:'org.x.OwnerController',static_method:null,rule:'exact',rule_label:'Exact fully qualified class name',confidence:1,event_count:5,sample_span_ids:[ref(1),ref(2),ref(3)]},
    {runtime_identifier:'GET /owners/{id}',static_class:'org.x.OwnerController',static_method:'showOwner',rule:'route_match',rule_label:'HTTP method and route matched a controller mapping in the scan',confidence:.8,event_count:1,sample_span_ids:[ref(9)],declared_route:'/owners/{ownerId}'}],
  unmapped:[{runtime_identifier:null,event_type:'DATABASE_CALL',span_names:['SELECT owners'],instrumentation_scope:'io.opentelemetry.jdbc',scope_version:null,span_kind:'CLIENT',event_count:3,missing_attributes:['code.namespace','code.function'],
    reason_code:'NO_CODE_ATTRIBUTES',reason:'The span carries no code.namespace / code.function attributes, which this instrumentation does not set on client spans.',closest_candidate:null,similarity:null,
    still_tells_us:'A h2 SELECT on owners.',sample_span_ids:[ref(4),ref(5),ref(6)]}]};

it('shows the purpose line with counts, the rule and event count of each resolved identity, and every field of an unmapped group',()=>{
  render(<MappingDetails report={report}/>);
  expect(screen.getByText(/5 of 9 spans mapped to a class by name/)).toBeTruthy();
  const resolved=screen.getAllByRole('table')[0];
  const route=within(resolved).getByText('GET /owners/{id}').closest('tr')!;
  expect(within(route).getByText('showOwner()',{exact:false})).toBeTruthy();
  expect(within(route).getByText('route_match')).toBeTruthy();
  expect(within(route).getByText(/via route \/owners\/\{ownerId\}/)).toBeTruthy();
  const unmapped=within(screen.getAllByRole('table')[1]).getAllByRole('row')[1];
  expect(within(unmapped).getByText('NO_CODE_ATTRIBUTES')).toBeTruthy();
  expect(within(unmapped).getByText('code.namespace, code.function')).toBeTruthy();
  expect(within(unmapped).getByText(/kind CLIENT · type DATABASE_CALL · scope io.opentelemetry.jdbc/)).toBeTruthy();
  expect(within(unmapped).getByText('A h2 SELECT on owners.')).toBeTruthy();
  expect(within(unmapped).getAllByText(/^0{15}[456]$/)).toHaveLength(3);
  expect(screen.queryByText('No class attribute')).toBeNull();
});

it('says why nothing is shown for a session completed before these details existed',()=>{
  render(<MappingDetails/>);
  expect(screen.getByText(/completed before mapping details were captured/)).toBeTruthy();
});

it('shows the caller, depth, operation and tables, and a reason code instead of the word Unknown',()=>{
  render(<DatabaseCallers summary={{total:3,resolved:2,unresolved:1,by_reason:{PARENT_MISSING_FROM_SESSION:1},by_depth:{'0':1,'3':1},text:'2 of 3 database observations resolved to a caller. Unresolved: PARENT_MISSING_FROM_SESSION (1).'}} rows={[
    {caller:'org.x.OwnerRepository',caller_class:'org.x.OwnerRepository',caller_method:'findByLastName',depth:3,domain_id:null,system:'h2',resource:'owners',tables:['owners','pets'],operation:'SELECT',call_count:4,sample_span_ids:[ref(7)]},
    {caller:null,caller_class:null,caller_method:null,depth:null,reason_code:'PARENT_MISSING_FROM_SESSION',reason:'The parent span 0000000000000003 (depth 1) is not in this session and no spans were dropped, so it was never received.',domain_id:null,system:'h2',resource:'owners',tables:['owners'],operation:'DELETE',call_count:1,sample_span_ids:[ref(8)]}]}/>);
  expect(screen.getByText('2 of 3 database observations resolved to a caller. Unresolved: PARENT_MISSING_FROM_SESSION (1).')).toBeTruthy();
  const rows=screen.getAllByRole('row');
  expect(within(rows[1]).getByText('org.x.OwnerRepository.findByLastName()')).toBeTruthy();
  expect(within(rows[1]).getByText('3')).toBeTruthy();
  expect(within(rows[1]).getByText('owners, pets')).toBeTruthy();
  expect(within(rows[2]).getByText('Not resolved: PARENT_MISSING_FROM_SESSION')).toBeTruthy();
  expect(within(rows[2]).getByText(/never received/)).toBeTruthy();
  expect(screen.queryByText('Unknown')).toBeNull();
});

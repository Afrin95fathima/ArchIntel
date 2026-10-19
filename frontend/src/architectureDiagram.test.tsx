import {expect,it} from 'vitest';
import {buildDiagramNodeColors,compareDiagramNodeColors} from './architectureDiagram';
import type {Assessment,Domain,GraphData,Issue} from './types';

const graph=(nodes:GraphData['nodes']):GraphData=>({nodes,edges:[],total_nodes:nodes.length,total_edges:0,truncated:false});
const domain={id:'billing',name:'Billing',confidence:.8,class_count:2,package_count:1,classes:['app.billing.Invoice','app.billing.Service'],packages:['app.billing'],evidence:[],confidence_note:'heuristic',metrics:{cross_domain_ratio:0,internal_cohesion:1,incoming_edges:0,outgoing_edges:0,internal_edges:1},database:{status:'UNKNOWN',repositories:[],note:'',shared_repositories:[]}} as Domain;
const issue={id:'i',issue_type:'GOD_CLASS',severity:'HIGH',title:'Debt',entity_id:'app.billing.Invoice',entity_type:'CLASS',description:'',why_it_matters:'',recommendation:'',evidence:{},domain_ids:['billing']} as Issue;

it('colors graph nodes by debt severity, observed coverage, or modernization wave',()=>{
  const data=graph([{id:'billing',name:'Billing',class_count:2},{id:'app.billing',name:'app.billing',domain_ids:['billing'],class_count:2}]);
  const debt=buildDiagramNodeColors(data,'debt',[domain],[issue],[]);
  expect(debt.billing).toBe('#c6534b');
  expect(debt['app.billing']).toBe('#c6534b');
  const coverage=buildDiagramNodeColors(data,'coverage',[domain],[],[],{domain_observations:[{id:'billing',observed:1,total:2,unobserved_classes:['app.billing.Invoice']}]});
  expect(coverage.billing).toBe('#d08a35');
  expect(coverage['app.billing']).toBe('#d08a35');
  expect(buildDiagramNodeColors(data,'coverage',[domain],[],[]).billing).toBe('#9aa69c');
  const wave=buildDiagramNodeColors(data,'wave',[domain],[],[{domain_id:'billing',wave:2} as Assessment]);
  expect(wave.billing).toBe('#5579ad');
  expect(wave['app.billing']).toBe('#5579ad');
});

it('marks added and removed nodes in before and after graph views',()=>{
  const before=graph([{id:'keep'},{id:'removed'}]);
  const after=graph([{id:'keep'},{id:'added'}]);
  const diff=compareDiagramNodeColors(before,after);
  expect(diff).toEqual({before:{keep:'#84958a',removed:'#c6534b'},after:{keep:'#84958a',added:'#5c9570'},added:1,removed:1,unchanged:1});
});

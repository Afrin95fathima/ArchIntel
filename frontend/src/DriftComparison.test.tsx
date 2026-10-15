import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { DriftComparison } from './DriftComparison';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const analyses=[{id:'baseline-1',application_id:'app',status:'COMPLETED',created_at:'2026-01-01T00:00:00Z'},{id:'candidate-2',application_id:'app',status:'COMPLETED',created_at:'2026-02-01T00:00:00Z'}] as never[];
const older={algorithm_version:'0.2.0',summary:{class_count:1,package_count:1,dependency_count:1,domain_count:1,issue_count:2,average_readiness:55},classes:[{id:'a.A',domain_id:'d'}],edges:[{source:'a.A',target:'a.B',dependency_type:'METHOD_CALL'}],domains:[{id:'d'}]};
const newer={algorithm_version:'0.2.1',summary:{class_count:2,package_count:1,dependency_count:1,domain_count:1,issue_count:1,average_readiness:60},classes:[{id:'a.A',domain_id:'d'},{id:'a.B',domain_id:'d'}],edges:[{source:'a.A',target:'a.B',dependency_type:'FIELD_TYPE'}],domains:[{id:'d'}]};
it('renders read-only drift counts and version context for saved analyses',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url.includes('baseline-1')?older:newer),{status:200,headers:{'Content-Type':'application/json'}})));
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><DriftComparison analyses={analyses} applicationId="app"/></QueryClientProvider>);
 expect(await screen.findByText(/Algorithm versions/)).toBeTruthy();
 expect(screen.getAllByText('2').length).toBeGreaterThan(0);
 expect(screen.getByText(/Exact identity additions/)).toBeTruthy();
});

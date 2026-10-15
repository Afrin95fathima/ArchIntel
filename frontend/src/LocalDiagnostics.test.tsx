import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {LocalDiagnostics} from './LocalDiagnostics';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('shows local readiness separately from deferred container workflows',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({
    mode:'LOCAL_POC',core_ready:true,summary:'Local static-analysis setup is ready.',
    checks:[
      {id:'database',label:'Local database',state:'READY',required:true,detail:'Connected.'},
      {id:'static_scanner',label:'Java static-analysis tools',state:'READY',required:true,detail:'Installed.'},
      {id:'container_workflows',label:'Container build and security workflows',state:'DEFERRED',required:false,detail:'Docker is deferred.'}
    ],workflows:{static_analysis:'READY',runtime_observation:'OPTIONAL_SETUP',source_build_and_security:'DEFERRED'}
  })}));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><LocalDiagnostics/></QueryClientProvider>);
  expect(await screen.findByText('Local static-analysis setup is ready.')).toBeTruthy();
  expect(screen.getAllByText('DEFERRED')).toHaveLength(2);
  expect(screen.getByText(/Docker is not required for static analysis/)).toBeTruthy();
});

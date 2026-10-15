import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { App } from './App';

afterEach(()=>{cleanup();vi.unstubAllGlobals();localStorage.clear();});
function mount(ready=true){
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async (url:string)=>({
    ok:!url.endsWith('/ready')||ready,
    json:async()=>url.endsWith('/ready')?(ready?{status:'ready',database:'PostgreSQL'}:{detail:'Unavailable'}):[]
  })));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><App/></QueryClientProvider>);
}
it('shows the real workflow and explicitly labeled synthetic demo',async()=>{
  mount();
  expect(await screen.findByText('Services ready')).toBeTruthy();
  expect(screen.getByText('Meet Northstar Commerce.')).toBeTruthy();
  expect(screen.getByText(/synthetic Java monolith/)).toBeTruthy();
});
it('reports service unavailability',async()=>{
  mount(false);
  expect(await screen.findByText('Services unavailable')).toBeTruthy();
});
it('opens a working upload dialog with artifact and project inputs',async()=>{
  mount();
  fireEvent.click(screen.getByRole('button',{name:'Analyze application'}));
  expect(screen.getByRole('dialog',{name:'Analyze application'})).toBeTruthy();
  const upload=screen.getByLabelText('Java artifact or compiled project ZIP') as HTMLInputElement;
  expect(upload.accept).toContain('.zip');
  expect(screen.getByText(/source-only ZIPs are not supported yet/i)).toBeTruthy();
  expect((screen.getByRole('button',{name:'Start architecture analysis'}) as HTMLButtonElement).disabled).toBe(true);
});

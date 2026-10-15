import {describe,it,expect,vi,afterEach} from 'vitest';
import {render,screen,cleanup} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {RuntimeAnalysis} from './RuntimeAnalysis';
vi.mock('./RuntimeGraph',()=>({RuntimeGraph:()=>null,evidenceColors:{}}));
afterEach(()=>cleanup());
describe('Runtime setup',()=>{
  it('requires a completed static baseline before creating a session',()=>{
    render(<QueryClientProvider client={new QueryClient()}><RuntimeAnalysis applications={[]} analyses={[]}/></QueryClientProvider>);
    expect((screen.getByRole('button',{name:'Create runtime session'}) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Complete a static analysis first/)).toBeTruthy();
    expect(screen.getByText(/Unobserved does not mean unused/)).toBeTruthy();
  });
});

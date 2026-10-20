import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ChangesetCard} from './ChangesetCard';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const make=(id:string,file:string)=>({id,state:'PROPOSED',files:[file],risk:'LOW',fingerprint:'fp-'+id});
function mount(responses:Record<string,()=>Promise<unknown>|unknown>){
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
    const key=Object.keys(responses).find(k=>url.endsWith(k));
    if(!key)return{ok:true,json:async()=>({})};
    try{return{ok:true,json:async()=>await responses[key]()};}catch(e){return{ok:false,status:500,json:async()=>({detail:(e as Error).message})};}
  }));
  const props={base:'/transformation/tasks/t1',busy:false,canNote:true,act:async(fn:()=>Promise<void>)=>{await fn();},revision:()=>({expected_revision:1,note:'n'})};
  render(<><ChangesetCard changeset={make('c1','A.java')} {...props}/><ChangesetCard changeset={make('c2','B.java')} {...props}/></>);
}

it('shows each patch under its own changeset and not under the other one',async()=>{
  mount({'/changesets/c1':()=>({diff:'--- A\n+++ A'}),'/changesets/c2':()=>({diff:'--- B\n+++ B'})});
  const [firstButton]=screen.getAllByRole('button',{name:'Inspect patch'});
  fireEvent.click(firstButton);
  const preview=await screen.findByRole('region',{name:'Patch preview: A.java'});
  expect(within(preview).getByText(/\+\+\+ A/)).toBeTruthy();
  expect(screen.queryByRole('region',{name:'Patch preview: B.java'})).toBeNull();
  expect(within(screen.getByRole('article',{name:'Changeset B.java'})).queryByText(/\+\+\+/)).toBeNull();
});

it('only the clicked inspect button is in the loading state',async()=>{
  let release!:(value:unknown)=>void;
  mount({'/changesets/c1':()=>new Promise(resolve=>{release=resolve;})});
  const [first,second]=screen.getAllByRole('button',{name:'Inspect patch'}) as HTMLButtonElement[];
  fireEvent.click(first);
  await waitFor(()=>expect(first.disabled).toBe(true));
  expect(second.disabled).toBe(false);
  release({diff:'x'});
  await screen.findByRole('region',{name:'Patch preview: A.java'});
});

it('shows a failed load as text under that changeset and toggles an open preview without another request',async()=>{
  mount({'/changesets/c1':()=>{throw new Error('Patch store unavailable');},'/changesets/c2':()=>({diff:'ok'})});
  const [first,second]=screen.getAllByRole('button',{name:'Inspect patch'}) as HTMLButtonElement[];
  fireEvent.click(first);
  expect(await within(screen.getByRole('article',{name:'Changeset A.java'})).findByText(/Patch store unavailable/)).toBeTruthy();
  fireEvent.click(second);
  await screen.findByRole('region',{name:'Patch preview: B.java'});
  fireEvent.click(second);
  await waitFor(()=>expect(screen.queryByRole('region',{name:'Patch preview: B.java'})).toBeNull());
  fireEvent.click(second);
  expect(await screen.findByRole('region',{name:'Patch preview: B.java'})).toBeTruthy();
  const reads=(fetch as unknown as {mock:{calls:[string][]}}).mock.calls.filter(([url])=>url.endsWith('/changesets/c2'));
  expect(reads).toHaveLength(1);
});

import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Assistant } from './Assistant';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('separates cited facts from recommendations and submits the question',async()=>{
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({answer:'Evidence only.',facts:[{id:'summary',kind:'summary',text:'There are 40 classes.'}],recommendations:['Validate boundaries.'],sources:[{id:'summary',kind:'summary'}],mode:'LOCAL_EVIDENCE',limitations:[]})});
  vi.stubGlobal('fetch',fetch);
  render(<Assistant analysisId="run-1" domains={[]}/>);
  fireEvent.change(screen.getByLabelText('Ask an architecture question'),{target:{value:'Where should modernization begin?'}});
  fireEvent.click(screen.getByLabelText('Send question'));
  expect(await screen.findByText('There are 40 classes.')).toBeTruthy();
  expect(screen.getByText('Recommendations for investigation')).toBeTruthy();
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/analyses/run-1/assistant/query');
});

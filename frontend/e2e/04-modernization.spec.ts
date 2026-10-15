import {test,expect} from '@playwright/test';
import {signIn} from './security-helper';

test('version-bound modernization preview, evidence explanation, waves and review',async({page})=>{
  await signIn(page);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');await page.getByRole('button',{name:'Explore demo application'}).click();
  await expect(page.getByRole('heading',{name:'A clearer picture. A smarter next step.'})).toBeVisible({timeout:150000});
  await page.getByRole('button',{name:'Evidence & digital twin',exact:true}).click();
  await page.getByRole('button',{name:'Preview architecture version',exact:true}).click();
  await expect(page.getByText(/Preview: \d+ facts/)).toBeVisible();
  await page.getByRole('button',{name:'Save architecture version',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Architecture facts',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Modernization intelligence',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Turn evidence into a reviewed plan.'})).toBeVisible();
  await page.getByRole('button',{name:'Preview modernization plan',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Validated preview',exact:true})).toBeVisible();
  const saved=page.waitForResponse(r=>r.request().method()==='POST'&&/\/modernization$/.test(r.url()));
  await page.getByRole('button',{name:'Save modernization plan',exact:true}).click();
  const plan=await(await saved).json();expect(plan.document.validation.status).toBe('VALIDATED');
  await expect(page.getByRole('heading',{name:'Evidence-backed decisions',exact:true})).toBeVisible();
  await page.getByRole('button',{name:/Explain why:/}).first().click();
  await expect(page.getByRole('heading',{name:'Decision explanation',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Readiness & confidence',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Readiness and evidence confidence',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'Unavailable',exact:true}).first()).toBeVisible();
  await page.getByRole('button',{name:'Target & waves',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Target architecture and dependency waves',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:/Wave 1:/})).toBeVisible();
  await page.getByRole('button',{name:'Review',exact:true}).click();
  await page.getByLabel('Planning review note',{exact:true}).fill('Accept the proposed investigation sequence; no source execution approved.');
  await page.getByRole('button',{name:'Record planning review',exact:true}).click();
  await expect(page.getByText(/Revision 1: APPROVED_PLANNING/)).toBeVisible();
  const exportResponse=await page.request.get('/api/v1/architecture-versions/'+plan.document.version_id+'/modernization/'+plan.id+'/export');
  expect((await exportResponse.json()).fingerprint).toBe(plan.document.fingerprint);
  if(process.env.ARCHINTEL_RUN_GRAPH_TESTS==='1'){
    await page.getByRole('button',{name:'Graph',exact:true}).click();
    await expect(page.locator('.runtime-canvas canvas').first()).toBeVisible({timeout:30000});
  }
  await page.getByRole('button',{name:'Readiness & confidence',exact:true}).click();
  await page.screenshot({path:'../docs/screenshots/phase5-modernization.png',fullPage:true});
  await page.reload();await page.getByRole('button',{name:'Modernization intelligence',exact:true}).click();
  await expect(page.getByRole('combobox',{name:'Saved planning proposal',exact:true})).toHaveValue(plan.id);
  expect(errors).toEqual([]);
});

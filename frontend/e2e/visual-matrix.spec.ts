import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { signIn } from './security-helper';

test('capture redesigned screens at supported desktop widths', async ({ page }) => {
  await signIn(page);
  await page.goto('/');
  await expect(page.getByText('Services ready')).toBeVisible();
  await page.getByRole('button', { name: 'Explore demo application' }).click();
  await expect(page.getByRole('heading', { name: 'A clearer picture. A smarter next step.' })).toBeVisible({ timeout: 150000 });
  const applications=await (await page.request.get('/api/v1/applications')).json() as {id:string}[];
  const analyses=await (await page.request.get('/api/v1/analyses')).json() as {id:string;application_id:string;status:string}[];
  const app=applications[0];
  const run=analyses.find(item=>item.application_id===app.id&&item.status==='COMPLETED');
  expect(run).toBeTruthy();
  const identity=await (await page.request.get('/api/v1/security/me')).json() as {csrf_token:string};
  const headers={'X-CSRF-Token':identity.csrf_token};
  const versionResponse=await page.request.post(`/api/v1/applications/${app.id}/architecture-versions`,{headers,data:{analysis_id:run!.id,name:'UI screenshot architecture',runtime_session_ids:[]}});
  expect(versionResponse.ok()).toBeTruthy();
  const version=await versionResponse.json() as {id:string};
  const proposalResponse=await page.request.post(`/api/v1/architecture-versions/${version.id}/modernization`,{headers,data:{strategy:'MODULAR_MONOLITH',objective:'Improve modular boundaries while preserving behavior.'}});
  expect(proposalResponse.ok()).toBeTruthy();

  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(300);
    const nav = async (name: string) => page.getByRole('button', { name, exact: true }).click();
    await nav('Overview');
    await expect(page.getByRole('heading', { name: 'A clearer picture. A smarter next step.' })).toBeVisible();
    const capture = async (name: string) => {
      await page.evaluate(() => { window.scrollTo(0,0); const navigation=document.querySelector<HTMLElement>('.nav-groups'); if(navigation)navigation.scrollTop=0; });
      const directory = path.resolve('..', 'docs', 'screenshots', String(width));
      mkdirSync(directory, { recursive: true });
      await page.screenshot({ path: path.join(directory, `${name}.png`), fullPage: true });
    };
    await capture('overview');
    await nav('Architecture explorer'); await expect(page.locator('.graph-canvas')).toBeVisible(); await capture('architecture-explorer');
    await nav('Candidate domains'); await expect(page.locator('.sequence-table')).toBeVisible(); await capture('domains');
    await nav('Technical debt'); await expect(page.locator('.issue-list')).toBeVisible(); await capture('technical-debt');
    await nav('Dependencies'); await expect(page.locator('.dependencies-workspace')).toBeVisible(); await capture('dependencies-cycles');
    await page.getByRole('tab', { name: 'Architecture metrics' }).click(); await capture('dependencies-metrics');
    await nav('Modernization'); await expect(page.getByRole('tab', { name: 'Proposal workspace' })).toBeVisible(); await capture('modernization-proposal');
    await page.getByRole('tab', { name: 'Extraction sequence' }).click(); await capture('modernization-sequence');
    await nav('Architecture assistant'); await expect(page.getByLabel('Ask an architecture question')).toBeVisible(); await capture('architecture-assistant');
    await nav('Dynamic analysis'); await expect(page.getByRole('heading', { name: 'Observe architecture in motion.' })).toBeVisible(); await capture('dynamic-analysis');
    await nav('Evidence & digital twin'); await expect(page.getByRole('heading', { name: 'Trace conclusions to their evidence.' })).toBeVisible(); await capture('evidence-digital-twin');
    await nav('Reports'); await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible();
    await page.getByRole('button',{name:'Preview report'}).click(); await expect(page.getByRole('heading',{name:'Executive summary'})).toBeVisible();
    await capture('reports');
    const pdfLink=page.getByRole('link',{name:'Download PDF report'});const pdfResponse=await page.request.get(await pdfLink.getAttribute('href')||'');expect(pdfResponse.ok()).toBeTruthy();expect(pdfResponse.headers()['content-type']).toContain('application/pdf');
    const pdfText=Buffer.from(await pdfResponse.body()).toString('latin1');const pageCount=pdfText.match(/\/Type \/Pages \/Kids \[[\s\S]*?\] \/Count (\d+)/);expect(pageCount).toBeTruthy();expect(Number(pageCount?.[1])).toBeGreaterThanOrEqual(8);expect(Number(pageCount?.[1])).toBeLessThanOrEqual(14);
    await nav('Source tasks'); await expect(page.getByRole('heading', { name: 'Prepare a controlled source change.' })).toBeVisible(); await capture('source-tasks');
    await nav('Local setup'); await expect(page.locator('main')).toBeVisible(); await capture('local-setup');
    await nav('Design system'); await expect(page.getByRole('heading', { name: 'ArchIntel interface catalog' })).toBeVisible(); await capture('ui-kit');
  }
});

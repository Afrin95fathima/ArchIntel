import {expect, type Page, type Cookie} from '@playwright/test';
import {readFileSync} from 'node:fs';
import path from 'node:path';
export const owner={username:'browser-owner',password:'browser-owner-password-2026'};
let ownerCookies:Cookie[]=[];
export async function signIn(page:Page){
  const data=process.env.ARCHINTEL_BROWSER_DATA;
  if(!data)throw new Error('Run with playwright.security.config.ts for an isolated authenticated database.');
  // Reuse this test worker's session across feature pages, as a signed-in user would.
  // Repeated successful logins also consume the application's deliberate rate limit.
  if(ownerCookies.length){
    await page.context().addCookies(ownerCookies);
    const current=await page.request.get('/api/v1/security/me');
    if(current.ok()&&(await current.json()).username===owner.username)return;
    ownerCookies=[];
  }
  const state=await (await page.request.get('/api/v1/security/status')).json();
  if(state.setup_required){
    const response=await page.request.post('/api/v1/security/bootstrap',{headers:{'X-ArchIntel-Request':'1'},data:{...owner,bootstrap_key:readFileSync(path.join(data,'security-bootstrap.key'),'utf8').trim()}});
    expect(response.ok()).toBeTruthy();
  }else{
    const response=await page.request.post('/api/v1/security/login',{headers:{'X-ArchIntel-Request':'1'},data:owner});
    expect(response.ok()).toBeTruthy();
  }
  ownerCookies=await page.context().cookies();
}

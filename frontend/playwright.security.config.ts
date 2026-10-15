import {defineConfig} from '@playwright/test';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
const data=process.env.ARCHINTEL_BROWSER_DATA||path.resolve('../.data/browser-validation-'+randomUUID());
process.env.ARCHINTEL_BROWSER_DATA=data;
export default defineConfig({
  testDir:'./e2e',testMatch:['00-security.spec.ts','01-ai.spec.ts','02-runtime.spec.ts','03-evidence.spec.ts','04-modernization.spec.ts','05-transformation.spec.ts','prototype.spec.ts','visual-matrix.spec.ts'],timeout:180000,workers:1,
  use:{baseURL:'http://127.0.0.1:18001',headless:true,
    launchOptions:{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'},
    viewport:{width:1440,height:1000},screenshot:'only-on-failure'},
  webServer:{command:'..\\.runtime\\python\\tools\\python.exe ..\\scripts\\security_browser_server.py',
    url:'http://127.0.0.1:18001/api/v1/health',reuseExistingServer:false,timeout:120000,
    env:{ARCHINTEL_BROWSER_DATA:data}},
  reporter:[['list'],['html',{open:'never',outputFolder:'playwright-security-report'}]]
});

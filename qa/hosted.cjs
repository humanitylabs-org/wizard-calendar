/* Isolated registered iframe using the exact pinned shared host implementations.
 * The registry and surrounding DOM are a TEST HARNESS, not the production shell. */
const {chromium} = require('playwright');
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), crypto=require('node:crypto');
const base=process.env.CALENDAR_URL||'http://127.0.0.1:18787';
const out=process.env.QA_OUT||path.join(__dirname,'../evidence');
const revision='9a7bcc89f15cb733462d12e7c84bcade47cebc27';
const shared={'app-services.js':'529d8c05d1ef2aac3a8db5fd92a861f4ed769604c44ef325a8521b1cb8510324','appearance-host.js':'5b95250298e2604b5eb1954be2f1ef7e9364e6b6ac24e9c7f31f71a9c4645390'};
(async()=>{
 const resources={};
 for(const [name,digest] of Object.entries(shared)) {
   const r=await fetch(`https://raw.githubusercontent.com/humanitylabs-org/wizard-ux/${revision}/web/core/${name}`);
   assert.ok(r.ok); const text=await r.text(); assert.equal(crypto.createHash('sha256').update(text).digest('hex'),digest); resources[name]=text;
 }
 const browserPath=process.env.BROWSER_PATH;
 const browser=await chromium.launch(browserPath
   ? {headless:true,executablePath:browserPath}
   : {headless:true,channel:process.env.BROWSER_CHANNEL || 'chrome'});
 const checks=[], errors=[];
 try {
  const context=await browser.newContext({viewport:{width:1280,height:900}});
  const page=await context.newPage(); page.on('pageerror',e=>errors.push(String(e))); page.on('dialog',d=>d.accept());
  await page.route(base+'/__qa-host',r=>r.fulfill({contentType:'text/html',body:`<!doctype html><html data-skin="nebula" style="color-scheme:dark;--bg:#10121c;--ink:#f3efff;--violet-2:#a899ff"><head><script>window.WizCore={apps:()=>({APPS:[{id:'wizard-calendar',url:'/wizard-calendar/',kind:'app'}]})}</script><script src="/__qa-core/app-services.js"></script><script src="/__qa-core/appearance-host.js"></script></head><body><div class="device"><div class="win" style="width:1000px;height:800px;background:#10121c"><iframe style="width:100%;height:100%;border:0"></iframe></div></div><script>const f=document.querySelector('iframe');f.src='/wizard-calendar/';window.detach=WizAppServices.attach(f,{appId:'wizard-calendar',path:'/wizard-calendar/'});</script></body></html>`}));
  await page.route(base+'/__qa-core/*',r=>r.fulfill({contentType:'text/javascript',body:resources[r.request().url().split('/').pop()]}));
  await page.goto(base+'/__qa-host');
  const frame=()=>page.frames().find(f=>f.url()===base+'/wizard-calendar/');
  await page.waitForFunction(()=>document.querySelector('iframe').contentWindow.WizardApp?.hosted);
  await page.waitForFunction(()=>WizAppearance.inspect().some(s=>s.acked));
  checks.push('real pinned shared host authorizes registered same-origin Calendar frame');
  await frame().locator('[data-cals]').first().click();
  assert.equal(await page.evaluate(()=>WizAppServices.back(document.querySelector('iframe'))),'handled');
  await frame().waitForFunction(()=>document.querySelector('[data-sheet]').hidden);
  assert.equal(await page.evaluate(()=>WizAppServices.back(document.querySelector('iframe'))),'atRoot');
  checks.push('host Back closes Settings; atRoot reported without iframe navigation');
  for(const skin of ['nebula','solstice','paper','verdant','noir','rose']) {
    for(const scheme of ['light','dark']) {
      await page.evaluate(({skin,scheme})=>{const root=document.documentElement;root.dataset.skin=skin;root.style.colorScheme=scheme;root.style.setProperty('--bg',scheme==='light'?'#faf8f2':'#15121f');root.style.setProperty('--ink',scheme==='light'?'#24212b':'#f5efff');WizAppearance.sync();},{skin,scheme});
      await frame().waitForFunction(({skin,scheme})=>WizardApp.theme.get()?.skin===skin&&WizardApp.theme.get()?.colorScheme===scheme,{skin,scheme});
      assert.equal(await frame().evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgba(0, 0, 0, 0)');
    }
  }
  checks.push('six skin identifiers × light/dark applied live without reload, transparent hosted canvas');
  await page.evaluate(()=>{document.querySelector('.device').classList.add('immersive');document.querySelector('.win').classList.add('full')});
  await frame().waitForFunction(()=>WizardApp.theme.get()?.presentation==='immersive');
  checks.push('immersive presentation propagated by actual shared Appearance host');
  await frame().locator('[data-cals]').first().click();
  let unblock;
  const gate=new Promise(resolve=>unblock=resolve);
  await page.route('**/api/import',async r=>{await gate;await r.continue()});
  await frame().locator('[data-import]').setInputFiles(path.join(__dirname,'../fixtures/example.json'));
  await page.waitForFunction(()=>WizAppServices.update.busy());
  assert.ok((await page.evaluate(()=>WizAppServices.inspect())).some(s=>s.holds.includes('calendar import')));
  unblock();
  await frame().waitForFunction(()=>document.querySelector('[data-c-msg]')?.textContent.includes('Imported 2 events'));
  await page.waitForFunction(()=>!WizAppServices.update.busy());
  checks.push('real shared update hold spans asynchronous import/readback and releases after success');
  await page.unroute('**/api/import');
  await page.route('**/api/events*',r=>r.abort());
  await frame().locator('[data-sync]').click();
  await frame().waitForFunction(()=>document.querySelector('[data-status]').textContent.includes('Unable to load'));
  assert.equal((await (await context.request.get(base+'/api/export')).json()).events.length,2);
  await page.unroute('**/api/events*');
  await frame().locator('[data-sync]').click();
  await frame().waitForFunction(()=>document.querySelector('[data-status]').textContent.includes('2 visible events'));
  checks.push('failed refresh preserves snapshot, exposes retry and recovers online');
  await frame().locator('[data-close]').click();
  await page.screenshot({path:path.join(out,'calendar-hosted.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={ok:true,harness:true,productionShell:false,sharedRevision:revision,count:checks.length,checks,errors};
  fs.writeFileSync(path.join(out,'hosted.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});

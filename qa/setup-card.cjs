/* Setup-card regression: real pinned WizardApp + shared host, no production shell.
 * Light uses explicit host compatibility tokens: Wizard Nebula/Grove ship dark palettes.
 * No account data; provider is not contacted. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const base=process.env.CALENDAR_URL||'http://127.0.0.1:18787',out=process.env.QA_OUT||path.join(__dirname,'../evidence');
const rev='9a7bcc89f15cb733462d12e7c84bcade47cebc27';
const shared={'skins.js':'57cfe09a435b67fdee38a33b060ed3038ef858b1037df11cef38a96c9c58078c','app-services.js':'529d8c05d1ef2aac3a8db5fd92a861f4ed769604c44ef325a8521b1cb8510324','appearance-host.js':'5b95250298e2604b5eb1954be2f1ef7e9364e6b6ac24e9c7f31f71a9c4645390'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});const resources={};
 for(const [name,digest] of Object.entries(shared)){
  const r=await fetch(`https://raw.githubusercontent.com/humanitylabs-org/wizard-ux/${rev}/web/core/${name}`);assert.ok(r.ok);
  const text=await r.text();assert.equal(crypto.createHash('sha256').update(text).digest('hex'),digest);resources[name]=text;
 }
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'chrome'}),checks=[],errors=[];
 try{
  for(const width of [390,1280]){
   const context=await browser.newContext({viewport:{width,height:width===390?844:900},isMobile:width===390,hasTouch:width===390,deviceScaleFactor:1,timezoneId:'Pacific/Honolulu',...(width===390?{userAgent:'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36'}:{})});
   const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
   await context.request.post(base+'/api/import',{data:JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/empty.json')))});
   await page.route(base+'/__qa-setup',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html data-skin="nebula"><head><meta name="viewport" content="width=device-width,initial-scale=1"><script src="/__qa-core/skins.js"></script><script>window.WizCore={apps:()=>({APPS:[{id:"wizard-calendar",url:"/wizard-calendar/",kind:"app"}]})}</script><script src="/__qa-core/app-services.js"></script><script src="/__qa-core/appearance-host.js"></script><style>html,body{margin:0;height:100%;color-scheme:dark}.device,.win{width:100%;height:100%;background:var(--bg,#05030c)}iframe{display:block;width:100%;height:100%;border:0}</style></head><body><div class="device"><div class="win"><iframe></iframe></div></div><script>const f=document.querySelector("iframe");f.src="/wizard-calendar/";WizAppServices.attach(f,{appId:"wizard-calendar",path:"/wizard-calendar/"});</script></body></html>'}));
   await page.route(base+'/__qa-core/*',r=>r.fulfill({contentType:'text/javascript',body:resources[r.request().url().split('/').pop()]}));
   await page.goto(base+'/__qa-setup');
   await page.waitForFunction(()=>document.querySelector('iframe').contentWindow.WizardApp?.hosted);
   const frame=page.frames().find(f=>f.url()===base+'/wizard-calendar/');
   await frame.waitForSelector('[data-setup]:not([hidden])');
   assert.equal(await frame.evaluate(()=>innerWidth),width);
   const docIdentity=await frame.evaluate(()=>window.__setupIdentity=crypto.randomUUID());
   for(const skin of ['nebula','grove']) for(const scheme of ['dark','light']){
    await page.evaluate(({skin,scheme})=>{
     const root=document.documentElement;WosSkin.set(skin);
     // Explicit compatibility override, not a shipped shell light selector.
     if(scheme==='light'){
      const values={'bg':skin==='grove'?'#f2f6ef':'#f6f3fc','ink':'#211b30','ink-2':'#51465e','ink-3':'#675b75','line-2':'#b9adc9','violet-2':skin==='grove'?'#44631c':'#6942bb','sk-win':skin==='grove'?'#f2f6ef':'#f6f3fc','glass-2':'#e5dfee'};
      for(const [k,v] of Object.entries(values))root.style.setProperty('--'+k,v);
     }
     root.style.colorScheme=scheme;document.body.style.colorScheme=scheme;document.querySelector('iframe').style.colorScheme=scheme;WizAppearance.sync();
    },{skin,scheme});
    await frame.waitForFunction(({skin,scheme})=>WizardApp.theme.get()?.skin===skin&&WizardApp.theme.get()?.colorScheme===scheme,{skin,scheme});
    await page.waitForFunction(()=>WizAppearance.inspect().some(s=>s.acked));
    assert.equal(await frame.evaluate(()=>window.__setupIdentity),docIdentity);
    assert.equal(await frame.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgba(0, 0, 0, 0)');
    const link=frame.locator('[data-setup] [data-connect]');
    assert.equal(await link.getAttribute('target'),'_top');assert.equal(await link.getAttribute('href'),'/wizard-connectors/');
    const metrics=await link.evaluate(el=>{
     const s=getComputedStyle(el),rect=el.getBoundingClientRect(),c=document.createElement('canvas').getContext('2d');
     function lum(color){c.fillStyle=color;c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data].slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((v,n,i)=>v+n*[.2126,.7152,.0722][i],0)}
     const a=lum(s.color),b=lum(s.backgroundColor);return {color:s.color,background:s.backgroundColor,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),height:rect.height,left:rect.left,right:rect.right,innerWidth};
    });
    assert.ok(metrics.contrast>=4.5,JSON.stringify(metrics));assert.ok(metrics.height>=44);assert.ok(metrics.left>=0&&metrics.right<=width);
    await link.focus();assert.notEqual(await link.evaluate(el=>getComputedStyle(el).outlineStyle),'none');await link.blur();
    await page.screenshot({path:path.join(out,`cal-final-setup-${width}-${skin}-${scheme}.png`),fullPage:true});
    checks.push({width,skin,scheme,lightCompatibility:scheme==='light',...metrics});
   }
   // Nonempty actual fixture verifies browser timezone fallback; owner zone is an API fixture.
   await context.request.post(base+'/api/import',{data:JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/example.json')))});
   await frame.goto(base+'/wizard-calendar/');await frame.waitForFunction(()=>document.querySelector('[data-status]').textContent.includes('Pacific/Honolulu'));
   await page.route('**/api/events',async r=>{const res=await r.fetch();const d=await res.json();d.display_timezone='Asia/Bangkok';await r.fulfill({response:res,json:d})});
   await frame.goto(base+'/wizard-calendar/');await frame.waitForFunction(()=>document.querySelector('[data-status]').textContent.includes('Asia/Bangkok'));
   await page.unroute('**/api/events');
   await context.request.post(base+'/api/import',{data:JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/empty.json')))});
   await frame.goto(base+'/wizard-calendar/');await frame.waitForSelector('[data-setup]:not([hidden])');
   await page.route(base+'/wizard-connectors/',r=>r.fulfill({contentType:'text/html',body:'<h1>Connected accounts fallback destination (QA)</h1>'}));
   await frame.locator('[data-setup] [data-connect]').click();await page.waitForURL(base+'/wizard-connectors/');
   await context.close();
  }
  assert.deepEqual(errors,[]);assert.equal(checks.length,8);
  const result={ok:true,productionShell:false,sharedRevision:rev,setupCases:checks.length,checks,errors,timezone:'browser fallback and owner-zone API fixture exercised',navigation:'top-level fallback clicked in phone and desktop; shared WizardApp has no open-app API'};
  fs.writeFileSync(path.join(out,'setup-card.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});

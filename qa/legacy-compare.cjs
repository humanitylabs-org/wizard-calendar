/* Optional read-only live-view comparison. Set LEGACY_WEB_DIR to a private copy
 * of the serving legacy web directory. Only synthetic API data is injected. */
const {launch,url,shots,seed,base}=require('./parity_helpers.cjs');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const legacy=process.env.LEGACY_WEB_DIR;assert.ok(legacy,'LEGACY_WEB_DIR required');
 const b=await launch();const results=[];
 try{
  for(const width of [393,1280]){
   const ctx=await b.newContext({viewport:{width,height:892},timezoneId:'Asia/Bangkok',colorScheme:'dark'});
   await seed(ctx.request);const doc=await (await ctx.request.get(base+'/api/events')).json();
   const captures={};
   for(const kind of ['legacy','candidate']){
    const p=await ctx.newPage();
    if(kind==='legacy'){
     for(const name of ['index.html','app.js','app.css','wizard-appearance.js'])await p.route(name==='index.html'?url:url+name,r=>r.fulfill({path:path.join(legacy,name),contentType:name.endsWith('js')?'text/javascript':name.endsWith('css')?'text/css':'text/html'}));
     await p.route('**/api/events*',r=>r.fulfill({json:{...doc,syncedAt:new Date().toISOString(),connected:[],syncError:null,syncing:false}}));
    }
    await p.goto(url);await p.waitForSelector('.blk');captures[kind]={};
    for(const mode of ['week','day','month']){
     await p.locator(`[data-mode="${mode}"]`).click();await p.locator('[data-today-btn]').click();
     captures[kind][mode]=await p.evaluate(()=>({heading:document.querySelector('[data-month]').textContent,columns:document.querySelectorAll('.tg-cols .col').length,days:document.querySelectorAll('.grid .day').length,overflow:document.documentElement.scrollWidth>innerWidth,blocks:[...document.querySelectorAll('.blk')].map(e=>({id:e.dataset.ev,top:e.style.top,height:e.style.height,left:e.style.left,width:e.style.width})),grid:[...document.querySelectorAll('.grid .day')].map(e=>({day:e.dataset.day,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})),tabs:document.querySelector('.tabs').getBoundingClientRect().y}));
     await p.screenshot({path:path.join(shots,`cal-parity-compare-${kind}-${width}-${mode}.png`)});
    }
    await p.locator('[data-mode="day"]').click();await p.locator('[data-today-btn]').click();await p.locator('.blk').first().click();await p.waitForSelector('[data-sheet]:not([hidden])');
    captures[kind].event=await p.locator('[data-sheet]').innerText();
    for(const text of ['When','Calendar','Where','Guests','Notes','Join Meet','Open in Google Calendar','Map'])assert.ok(captures[kind].event.includes(text),kind+' missing '+text);
    await p.close();
   }
   for(const mode of ['week','day','month']){
    assert.deepEqual(captures.candidate[mode],captures.legacy[mode],`${width}/${mode} geometry/content mismatch`);
    results.push(`${width}/${mode}: exact title, columns/month cells, block positions/sizes, today/selection cell geometry, bottom tabs and no overflow match live`);
   }
   assert.equal(captures.candidate.event,captures.legacy.event,'event details changed');
   results.push(`${width}: exact event details text/actions match live`);await ctx.close();
  }
  fs.writeFileSync(path.join(shots,'legacy-compare.json'),JSON.stringify({ok:true,synthetic:true,checks:results,count:results.length},null,2));console.log(JSON.stringify({ok:true,checks:results,count:results.length},null,2));
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exit(1)});

const fs=require('fs'),path=require('path'); const {launch,url,shots,seed}=require('./qa/parity_helpers.cjs');
(async()=>{ fs.mkdirSync(shots,{recursive:true});const b=await launch();let checks=[];
 for(const width of [360,393,420,800]){const ctx=await b.newContext({viewport:{width,height:850},timezoneId:'Asia/Bangkok'}); const p=await ctx.newPage(); await ctx.addInitScript(() => localStorage.setItem('wc.mode', 'month')); /* month-view suite */
 if(process.env.QA_CSS)await p.route('**/app.css',r=>r.fulfill({contentType:'text/css',body:fs.readFileSync(process.env.QA_CSS,'utf8')}));
 await seed(ctx.request);await p.goto(url);await p.waitForSelector('.day.today.sel');
 let data=await p.evaluate(()=>{let t=document.querySelector('.day.today'),a=t.nextElementSibling,r=t.getBoundingClientRect(),ar=a.getBoundingClientRect(),nr=t.querySelector('.n').getBoundingClientRect();return {today:{x:r.x,w:r.width,h:r.height},adjacent:{x:ar.x,w:ar.width,h:ar.height},center:nr.x+nr.width/2,expectedCenter:r.x+r.width/2,border:getComputedStyle(t).borderRightWidth,widget:null,overflow:document.documentElement.scrollWidth>innerWidth}});
 if(Math.abs(data.today.w-data.adjacent.w)>.6||Math.abs(data.today.h-data.adjacent.h)>.6||Math.abs(data.center-data.expectedCenter)>.6||data.border!=='0px'||data.overflow)throw Error(JSON.stringify({width,...data}));
 await p.locator('.day.today').evaluate(e=>e.nextElementSibling.click());let selected=await p.locator('.day.sel').boundingBox();if(Math.abs(selected.width-data.today.w)>.6)throw Error('selection sizes differ');
 await p.locator('[data-month]').click();await p.locator('header [data-cals]').click();await p.goBack();if(await p.locator('[data-sheet]').isVisible()||!p.url().includes('/wizard-calendar/'))throw Error('Back left app');
 checks.push({width,...data});await p.screenshot({path:path.join(shots,`cal-parity-geometry-${width}.png`)});await ctx.close();}
 console.log(JSON.stringify({passed:true,checks},null,2));await b.close();})().catch(e=>{console.error(e);process.exit(1)});

// Disposable synthetic data only. Never run these destructive suites on an owner install.
const {chromium}=require('playwright');
const path=require('node:path');
const base=process.env.CALENDAR_URL||'http://127.0.0.1:18787';
const url=base+'/wizard-calendar/';
const shots=process.env.QA_OUT||path.join(__dirname,'../evidence');
async function launch(){return chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'chrome'});}
async function seed(request){
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const plus=n=>new Date(Date.parse(today+'T12:00:00Z')+n*864e5).toISOString().slice(0,10);
 const ev=(id,title,start,end,extra={})=>({id,title,cal:'fixture',start,end,allDay:false,location:'Synthetic room',description:'Private QA notes',attendees:2,meet:'https://meet.google.com/qa-fixture',link:'https://calendar.google.com/',...extra});
 const doc={schemaVersion:1,timezone:'Asia/Bangkok',calendars:[{id:'fixture',name:'Synthetic Work',color:'#9fe1e7'},{id:'hidden',name:'Synthetic Hidden',color:'#cca6ac'},{id:'failed',name:'Synthetic Failed',color:'#16a765'}],events:[ev('fixture:morning','Synthetic planning',today+'T09:00:00+07:00',today+'T10:30:00+07:00'),ev('fixture:overlap','Synthetic overlap',today+'T10:00:00+07:00',today+'T11:00:00+07:00'),ev('fixture:all','Synthetic all day',today,plus(2),{allDay:true}),ev('hidden:event','Hidden fixture',today+'T14:00:00+07:00',today+'T15:00:00+07:00',{cal:'hidden'})]};
 let r=await request.post(base+'/api/import',{data:doc});if(!r.ok())throw Error(await r.text());
 r=await request.post(base+'/api/calendars/visibility',{data:{id:'hidden',visible:false}});if(!r.ok())throw Error(await r.text());
}
module.exports={launch,base,url,shots,seed};

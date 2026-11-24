#!/usr/bin/env node
// One public, anonymous UI pagination click. Diagnostic only: no session
// material, request values, HTML or reconstructed DOM is logged or persisted.
// This is NOT an immutable raw receipt or an acquisition adapter.
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const URL0 = 'https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027';
const origin = new URL(URL0).origin;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const sha = s => createHash('sha256').update(s).digest('hex');
function range(s) {
  const matches = [...String(s).matchAll(/\b(\d[\d,.]*)\s*[-–]\s*(\d[\d,.]*)\s+of\s+(\d[\d,.]*)\b/gi)];
  const values = [...new Set(matches.map(m => JSON.stringify(m.slice(1).map(x=>Number(x.replace(/[,.]/g,''))))))];
  if (values.length !== 1) return null;
  const [first,last,total] = JSON.parse(values[0]);
  return first > 0 && first <= last && last <= total ? {first,last,total} : null;
}
function nextRange(a,b) {
  return !!a && !!b && a.first === 1 && a.last < a.total && b.first === a.last+1 && b.total === a.total && b.last >= b.first;
}
function officialAjax(url) {
  try {
    const u = new URL(url);
    return u.origin === origin && /^\/ords\/(?:[^/]+\/)*wwv_flow\.ajax$/i.test(u.pathname);
  } catch { return false; }
}
// Interpret only the native control's observed pagination metadata, never build
// a request from it. Mirrored controls are equivalent only within one report
// and with the identical complete action value.
function selectNextControl(controls, first) {
  const explicit = controls.filter(c => c.next);
  const candidates = explicit.filter(c => {
    if (!c.report || !c.pagination) return false;
    const m = /^pgR_min_row=(\d+)max_rows=(\d+)rows_fetched=(\d+)$/.exec(c.pagination);
    if (!m) return false;
    const [start,max,fetched] = m.slice(1).map(Number);
    return [start,max,fetched].every(Number.isSafeInteger) &&
      start === first.last+1 && max === first.last-first.first+1 &&
      fetched > 0 && fetched <= max;
  });
  if (!candidates.length) return {index:null,count:0};
  // An explicit contradictory Next control is not an ignorable alternative.
  if (candidates.length !== explicit.length) return {index:null,count:candidates.length};
  const c = candidates[0];
  if (!candidates.every(x=>x.report===c.report && x.pagination===c.pagination))
    return {index:null,count:candidates.length};
  return {index:c.index,count:candidates.length};
}
// A transient hit is not enough: require the same native target twice.
function stableTarget(a,b) {
  if(!a?.unambiguous||!b?.unambiguous||!a.hittable||!b.hittable||
     !a.target||!b.target||a.matchingNext!==b.matchingNext) return false;
  const x=a.target,y=b.target;
  return x.index===y.index&&x.report===y.report&&x.action===y.action&&
    [x.x,x.y,y.x,y.y].every(Number.isFinite)&&
    Math.abs(x.x-y.x)<=0.5&&Math.abs(x.y-y.y)<=0.5;
}
// Keyboard activation is a native browser fallback, never a synthetic DOM click.
function stableFocus(a,b) {
  if(!a?.unambiguous||!b?.unambiguous||!a.focused||!b.focused||
     !a.focusTarget||!b.focusTarget||a.matchingNext!==b.matchingNext)return false;
  const x=a.focusTarget,y=b.focusTarget;
  return x.index===y.index&&x.report===y.report&&x.action===y.action&&
    x.nativeButton===true&&y.nativeButton===true;
}
if (process.argv.includes('--self-test')) {
  assert.deepEqual(range('1 - 50 of 1,002'),{first:1,last:50,total:1002});
  assert.equal(range('1 - 50 of 1002 51 - 100 of 1002'),null);
  assert.equal(range('1 - 50 of 10'),null);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 100 of 1002')),true);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 100 of 1003')),false);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('1 - 50 of 1002')),false);
  assert.equal(officialAjax(origin+'/ords/wwv_flow.ajax?session=secret'),true);
  assert.equal(officialAjax('https://example.org/ords/wwv_flow.ajax'),false);
  const first = {first:1,last:50,total:1002};
  const next = {index:0,next:true,report:1,pagination:'pgR_min_row=51max_rows=50rows_fetched=50'};
  const mirror = {...next,index:1};
  assert.deepEqual(selectNextControl([next,mirror],first),{index:0,count:2});
  assert.deepEqual(selectNextControl([next,{...mirror,report:2}],first),{index:null,count:2});
  assert.deepEqual(selectNextControl([next,{...mirror,pagination:'pgR_min_row=51max_rows=50rows_fetched=49'}],first),{index:null,count:2});
  assert.deepEqual(selectNextControl([{...next,pagination:'pgR_min_row=101max_rows=50rows_fetched=50'},mirror],first),{index:null,count:1});
  assert.deepEqual(selectNextControl([next,{...mirror,pagination:'unrecognized'}],first),{index:null,count:1});
  assert.deepEqual(selectNextControl([next,{...mirror,report:0}],first),{index:null,count:1});
  assert.deepEqual(selectNextControl([next,{...mirror,next:false}],first),{index:0,count:1});
  assert.deepEqual(selectNextControl([{...next,report:0}],first),{index:null,count:0});
  assert.deepEqual(selectNextControl([{...next,pagination:'unrecognized'}],first),{index:null,count:0});
  assert.deepEqual(selectNextControl([{...next,next:false}],first),{index:null,count:0});
  assert.deepEqual(selectNextControl([{...next,pagination:'pgR_min_row=51max_rows=100rows_fetched=50'}],first),{index:null,count:0});
  const hit = {unambiguous:true,hittable:true,matchingNext:2,target:{index:0,report:1,action:next.pagination,x:100,y:200}};
  assert.equal(stableTarget(hit,{...hit,target:{...hit.target,x:100.25}}),true);
  assert.equal(stableTarget(hit,{...hit,hittable:false}),false);
  assert.equal(stableTarget(hit,{...hit,target:{...hit.target,index:1}}),false);
  assert.equal(stableTarget(hit,{...hit,target:{...hit.target,report:2}}),false);
  assert.equal(stableTarget(hit,{...hit,target:{...hit.target,action:'different'}}),false);
  assert.equal(stableTarget(hit,{...hit,target:{...hit.target,y:201}}),false);
  assert.equal(stableTarget(hit,{...hit,matchingNext:1}),false);
  assert.equal(stableTarget(hit,{...hit,target:{...hit.target,x:NaN}}),false);
  assert.equal(stableTarget(null,hit),false);
  const focus={unambiguous:true,focused:true,matchingNext:2,focusTarget:{index:0,report:1,action:next.pagination,nativeButton:true}};
  assert.equal(stableFocus(focus,{...focus}),true);
  assert.equal(stableFocus(focus,{...focus,focused:false}),false);
  assert.equal(stableFocus(focus,{...focus,unambiguous:false}),false);
  assert.equal(stableFocus(focus,{...focus,matchingNext:1}),false);
  for(const delta of [{index:1},{report:2},{action:'other'},{nativeButton:false}])
    assert.equal(stableFocus(focus,{...focus,focusTarget:{...focus.focusTarget,...delta}}),false);
  assert.equal(stableFocus(null,focus),false);
  console.log('PASS: public UI protocol diagnostic range, endpoint, native-control equivalence, stable hit and native focus guards');
  process.exit(0);
}
let dir, chrome, ws;
const base = {schema:'MYSMIS_UI_PROTOCOL_DISCOVERY_V1',canonicalUrl:URL0,
  runId:process.env.GITHUB_RUN_ID || 'local',parserVersion:'MYSMIS_UI_PROTOCOL_DISCOVERY_V1',
  sourceFamily:'ROMANIA_MIPE_MYSMIS',programmeFamily:'ROMANIA_MULTI_PROGRAMME',
  authorityClass:'T1_OFFICIAL_MYSMIS_REPORTING',observationState:'PROTOCOL_DISCOVERY_ONLY',
  rawPersisted:false,immutableReceipt:false,materialFactUse:false,publishAuthorized:false,
  openCallAuthorized:false,deadlineAuthorized:false,budgetAuthorized:false,eligibilityAuthorized:false,
  publicationEffect:'NONE'};
let status='NOT_STARTED';
const counters={sameOriginPosts:0,officialAjaxPosts:0,officialAjax200:0,officialAjaxFinished:0};
try {
  dir=await mkdtemp(join(tmpdir(),'mysmis-public-ui-'));
  status='PROFILE_CREATED';
  chrome=spawn(process.env.CHROME_BIN || 'google-chrome',[
    '--headless=new','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',
    '--disable-background-networking','--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0','--user-data-dir='+dir,'about:blank'
  ],{stdio:'ignore'});
  status='BROWSER_SPAWN_REQUESTED';
  let spawnError=false; chrome.on('error',()=>{spawnError=true;});
  let port;
  for(let i=0;i<40&&!port&&!spawnError;i++){
    try {port=Number((await readFile(join(dir,'DevToolsActivePort'),'utf8')).split('\n')[0]);}catch{}
    if(!port) await sleep(250);
  }
  if(!port) throw new Error('browser unavailable');
  status='DEVTOOLS_PORT_READY';
  const tabs=await (await fetch('http://127.0.0.1:'+port+'/json/list',{signal:AbortSignal.timeout(3000)})).json();
  const tab=tabs.find(t=>t.type==='page');
  if(!tab?.webSocketDebuggerUrl) throw new Error('no page');
  status='DEVTOOLS_PAGE_FOUND';
  ws=new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{
    ws.addEventListener('open',resolve,{once:true});
    ws.addEventListener('error',reject,{once:true});
    setTimeout(reject,3000).unref();
  });
  status='DEVTOOLS_CONNECTED';
  let id=0, capture=false;
  const pending=new Map(), requests=new Map(), responses=new Map(), finished=new Set();
  ws.addEventListener('message',e=>{
    try {
      const m=JSON.parse(e.data);
      if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error('CDP error')):p.resolve(m.result);}return;}
      if(!capture)return;
      const p=m.params||{};
      if(m.method==='Network.requestWillBeSent' && p.request?.method==='POST') {
        try {if(new URL(p.request.url).origin===origin)counters.sameOriginPosts++;}catch{}
        if(officialAjax(p.request.url)){requests.set(p.requestId,true);counters.officialAjaxPosts++;}
      }
      if(m.method==='Network.responseReceived' && requests.has(p.requestId) && officialAjax(p.response?.url) && p.response.status===200){responses.set(p.requestId,{mimeType:String(p.response.mimeType||'').split(';')[0]});counters.officialAjax200++;}
      if(m.method==='Network.loadingFinished' && requests.has(p.requestId)){finished.add(p.requestId);counters.officialAjaxFinished++;}
    } catch {}
  });
  function cdp(method,params={}){
    return new Promise((resolve,reject)=>{
      const k=++id; const timer=setTimeout(()=>{pending.delete(k);reject(new Error('CDP timeout'));},5000);
      pending.set(k,{resolve:v=>{clearTimeout(timer);resolve(v);},reject:e=>{clearTimeout(timer);reject(e);}});
      ws.send(JSON.stringify({id:k,method,params}));
    });
  }
  async function evaluate(expression){
    const r=await cdp('Runtime.evaluate',{expression,returnByValue:true});
    if(r.exceptionDetails)throw new Error('page evaluation failed');
    return r.result?.value;
  }
  await cdp('Page.enable');await cdp('Network.enable',{maxTotalBufferSize:4000000,maxResourceBufferSize:2000000});
  status='CDP_ENABLED';
  const navigation=await cdp('Page.navigate',{url:URL0});
  if(navigation?.errorText)throw new Error('navigation rejected');
  status='NAVIGATION_REQUESTED';
  const snapshot=()=>evaluate("({url:location.origin+location.pathname,text:[...document.querySelectorAll('.a-IRR-pagination')].map(e=>e.innerText).join(' '),ready:document.readyState==='complete'&&typeof window.apex?.jQuery==='function'&&typeof window.apex?.server?.plugin==='function'})");
  // A navigation may destroy the initial execution context between polls.
  // Retry only passive snapshots within a fixed time/attempt budget; no new
  // navigation or click and no relaxation of origin/range/readiness gates.
  let first;
  const firstPollDeadline=Date.now()+15000;
  const firstPoll={attempts:0,evaluationFailures:0,officialDocument:0,ready:0,rangePresent:0};
  for(let i=0;i<60&&Date.now()<firstPollDeadline;i++){
    firstPoll.attempts++;
    let s;
    try{s=await snapshot();}catch{firstPoll.evaluationFailures++;await sleep(250);continue;}
    if(s?.url===URL0){firstPoll.officialDocument++;if(s.ready)firstPoll.ready++;if(range(s.text))firstPoll.rangePresent++;}
    if(s?.url===URL0&&s.ready&&range(s.text)){first=range(s.text);break;}
    await sleep(250);
  }
  console.log(JSON.stringify({...base,status:'UI_FIRST_PAGE_READINESS_ONLY',fetchedAt:new Date().toISOString(),firstPoll,paginationProtocolConfirmed:false}));
  if(!first||first.first!==1||first.last>=first.total)throw new Error('first page range missing');
  status='FIRST_PAGE_CONFIRMED';
  // Do not click a generic enabled button. Require an explicit accessible
  // next label, then verify the hit target after scrolling into view.
  // Report only bounded structural counts, never attributes, labels or session data.
  // Resolve the accessible label from standard DOM mechanisms, including nested
  // SVG titles and aria-labelledby. A data-pagination attribute alone is not proof.
  const inspectTarget = (scroll, focus=false) => evaluate(`(()=>{if(location.origin+location.pathname!==${JSON.stringify(URL0)})return null;
    const current=(${range.toString()})([...document.querySelectorAll('.a-IRR-pagination')].map(e=>e.innerText).join(' '));
    if(!current||JSON.stringify(current)!==${JSON.stringify(JSON.stringify(first))})return null;
    const a=[...document.querySelectorAll('.a-IRR-button--pagination:not([disabled]):not([aria-disabled=true])')].filter(e=>e.getClientRects().length>0);
    const label=e=>[e.getAttribute('aria-label'),e.getAttribute('title'),e.innerText,
      ...[...(e.getAttribute('aria-labelledby')||'').split(/\\s+/)].filter(Boolean).map(id=>document.getElementById(id)?.textContent),
      ...[...e.querySelectorAll('[title], [aria-label], svg title')].map(x=>[x.getAttribute('title'),x.getAttribute('aria-label'),x.textContent].join(' '))].filter(Boolean).join(' ');
    const next=a.filter(e=>/\\bnext\\b|următoar/i.test(label(e)));
    const reports=[...document.querySelectorAll('.a-IRR')];
    const descriptors=a.map((e,index)=>({index,next:next.includes(e),
      report:reports.indexOf(e.closest('.a-IRR'))+1,pagination:e.getAttribute('data-pagination')}));
    const selection=(${selectNextControl.toString()})(descriptors,${JSON.stringify(first)});
    const result={enabled:a.length,explicitNext:next.length,hasPaginationData:a.filter(e=>e.hasAttribute('data-pagination')).length,
      rowSelects:[...document.querySelectorAll('select')].filter(e=>e.getClientRects().length>0&&/rows|rânduri/i.test([e.getAttribute('aria-label'),e.getAttribute('title'),...[...e.labels||[]].map(l=>l.textContent)].join(' '))).length,
      matchingNext:selection.count,unambiguous:selection.index!==null,hittable:false,target:null,focused:false,focusTarget:null};
    if(selection.index===null)return result;
    if(${scroll})a[selection.index].scrollIntoView({block:'center',inline:'center',behavior:'instant'});
    // Only an actual non-submit button can receive native Enter activation.
    const native=e=>e instanceof HTMLButtonElement&&e.type==='button'&&!e.disabled&&
      e.getAttribute('aria-disabled')!=='true'&&!e.closest('[inert]');
    if(${focus}){
      const e=a[selection.index];
      if(native(e))e.focus({preventScroll:true});
    }
    const focused=descriptors.find(d=>d.next&&a[d.index]===document.activeElement&&native(a[d.index]));
    if(focused){result.focused=true;result.focusTarget={index:focused.index,report:focused.report,action:focused.pagination,nativeButton:true};}
    // All explicit mirrors already passed the same-report/action gate.
    for(const d of descriptors.filter(d=>d.next)){
      const x=a[d.index],b=x.getBoundingClientRect(),cx=b.left+b.width/2,cy=b.top+b.height/2,hit=document.elementFromPoint(cx,cy);
      if(hit&&(hit===x||x.contains(hit))){result.hittable=true;result.target={index:d.index,report:d.report,action:d.pagination,x:cx,y:cy};break;}
    }
    return result})()`);
  const before=await inspectTarget(true);
  if(!before?.unambiguous)throw new Error('target inspection unavailable or ambiguous');
  let previous=null,after=before,confirmed=false;
  const hitPoll={attempts:0,hittable:0,stablePairs:0,ambiguous:0};
  for(let i=0;i<12;i++){
    await sleep(150);
    after=await inspectTarget(false);
    hitPoll.attempts++;
    if(!after?.unambiguous||after.matchingNext!==before.matchingNext){hitPoll.ambiguous++;break;}
    if(after.hittable)hitPoll.hittable++;
    if(stableTarget(previous,after)){hitPoll.stablePairs++;confirmed=true;break;}
    previous=after;
  }
  console.log(JSON.stringify({...base,status:'UI_CONTROL_SHAPE_ONLY',fetchedAt:new Date().toISOString(),
    firstRange:first,controlCounts:{enabled:before.enabled,explicitNext:before.explicitNext,hasPaginationData:before.hasPaginationData,rowSelects:before.rowSelects,matchingNext:before.matchingNext,unambiguous:before.unambiguous},
    beforeHittable:before.hittable,afterHittable:!!after?.hittable,hitPoll,paginationProtocolConfirmed:false}));
  const target=after?.target;
  let activation='NATIVE_MOUSE';
  if(!confirmed||!target){
    // No fallback after ambiguity. A single native Enter is permitted only
    // when the same exact report/action remains focused over passive samples.
    if(hitPoll.ambiguous||!after?.unambiguous)throw new Error('ambiguous next button');
    const f0=await inspectTarget(false,true);
    await sleep(150);
    const f1=await inspectTarget(false);
    await sleep(150);
    const f2=await inspectTarget(false);
    const focusConfirmed=f0?.matchingNext===before.matchingNext&&stableFocus(f0,f1)&&stableFocus(f1,f2);
    console.log(JSON.stringify({...base,status:'UI_NATIVE_FOCUS_ONLY',fetchedAt:new Date().toISOString(),
      focusedSamples:[f0,f1,f2].filter(f=>f?.focused).length,focusConfirmed,paginationProtocolConfirmed:false}));
    if(!focusConfirmed)throw new Error('no stable native focused next button');
    activation='NATIVE_KEYBOARD_ENTER';
    status='NEXT_TARGET_CONFIRMED';
    capture=true;
    await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13,text:'\r'});
    await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
  }else{
    status='NEXT_TARGET_CONFIRMED';
    capture=true;
    await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:target.x,y:target.y});
    await cdp('Input.dispatchMouseEvent',{type:'mousePressed',x:target.x,y:target.y,button:'left',buttons:1,clickCount:1});
    await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',x:target.x,y:target.y,button:'left',buttons:0,clickCount:1});
  }
  status='NEXT_CLICKED';
  let second;
  for(let i=0;i<80;i++){const s=await snapshot();const b=range(s?.text);if(s?.url===URL0&&nextRange(first,b)){second=b;break;}await sleep(250);}
  if(!second)throw new Error('contiguous next range not observed');
  status='NEXT_RANGE_CONFIRMED';
  await sleep(500);
  const ids=[...responses.keys()].filter(k=>finished.has(k));
  if(ids.length!==1 || requests.size!==1)throw new Error('ambiguous official ajax request');
  const response=await cdp('Network.getResponseBody',{requestId:ids[0]});
  const bytes=response.base64Encoded?Buffer.from(response.body,'base64'):Buffer.from(response.body,'utf8');
  if(!bytes.length||bytes.length>=2000000)throw new Error('response size outside diagnostic bound');
  const mime=responses.get(ids[0]).mimeType.toLowerCase();
  if(!['text/html','application/json','text/plain'].includes(mime))throw new Error('unrecognized response media');
  console.log(JSON.stringify({...base,status:'UI_NEXT_RANGE_AND_OFFICIAL_AJAX_OBSERVED',counters,
    fetchedAt:new Date().toISOString(),firstRange:first,secondRange:second,
    activation,endpointClass:'SAME_ORIGIN_WWV_FLOW_AJAX',method:'POST',httpStatus:200,
    contentType:mime,cdpDecodedBodySha256:sha(bytes),decodedBodyBytes:bytes.length,
    rawByteIdentityProven:false,paginationProtocolConfirmed:false}));
} catch(e) {
  // No exception messages or arbitrary server values: could contain session data.
  console.log(JSON.stringify({...base,status:'UI_PROTOCOL_DIAGNOSTIC_FAIL_CLOSED',stage:status,counters,
    fetchedAt:new Date().toISOString(),paginationProtocolConfirmed:false}));
  process.exitCode=2;
} finally {
  try{ws?.close();}catch{}
  try{chrome?.kill('SIGKILL');}catch{}
  if(dir)await rm(dir,{recursive:true,force:true,maxRetries:3}).catch(()=>{});
}

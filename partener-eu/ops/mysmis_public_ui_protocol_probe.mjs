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
if (process.argv.includes('--self-test')) {
  assert.deepEqual(range('1 - 50 of 1,002'),{first:1,last:50,total:1002});
  assert.equal(range('1 - 50 of 1002 51 - 100 of 1002'),null);
  assert.equal(range('1 - 50 of 10'),null);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 100 of 1002')),true);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 100 of 1003')),false);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('1 - 50 of 1002')),false);
  assert.equal(officialAjax(origin+'/ords/wwv_flow.ajax?session=secret'),true);
  assert.equal(officialAjax('https://example.org/ords/wwv_flow.ajax'),false);
  console.log('PASS: public UI protocol diagnostic range and endpoint guards');
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
  chrome=spawn(process.env.CHROME_BIN || 'google-chrome',[
    '--headless=new','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',
    '--disable-background-networking','--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0','--user-data-dir='+dir,'about:blank'
  ],{stdio:'ignore'});
  let spawnError=false; chrome.on('error',()=>{spawnError=true;});
  let port;
  for(let i=0;i<40&&!port&&!spawnError;i++){
    try {port=Number((await readFile(join(dir,'DevToolsActivePort'),'utf8')).split('\n')[0]);}catch{}
    if(!port) await sleep(250);
  }
  if(!port) throw new Error('browser unavailable');
  const tabs=await (await fetch('http://127.0.0.1:'+port+'/json/list',{signal:AbortSignal.timeout(3000)})).json();
  const tab=tabs.find(t=>t.type==='page');
  if(!tab?.webSocketDebuggerUrl) throw new Error('no page');
  ws=new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{
    ws.addEventListener('open',resolve,{once:true});
    ws.addEventListener('error',reject,{once:true});
    setTimeout(reject,3000).unref();
  });
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
  await cdp('Page.navigate',{url:URL0});
  const snapshot=()=>evaluate("({url:location.origin+location.pathname,text:[...document.querySelectorAll('.a-IRR-pagination')].map(e=>e.innerText).join(' '),ready:document.readyState==='complete'&&typeof window.apex?.jQuery==='function'&&typeof window.apex?.server?.plugin==='function'})");
  let first;
  for(let i=0;i<40;i++){const s=await snapshot();if(s?.url===URL0&&s.ready&&range(s.text)){first=range(s.text);break;}await sleep(250);}
  if(!first||first.first!==1||first.last>=first.total)throw new Error('first page range missing');
  status='FIRST_PAGE_CONFIRMED';
  // Do not click a generic enabled button. Require an explicit accessible
  // next label, then verify the hit target after scrolling into view.
  // Report only bounded structural counts, never attributes, labels or session data.
  // Resolve the accessible label from standard DOM mechanisms, including nested
  // SVG titles and aria-labelledby. A data-pagination attribute alone is not proof.
  const inspectTarget = scroll => evaluate(`(()=>{if(location.origin+location.pathname!==${JSON.stringify(URL0)})return null;
    const a=[...document.querySelectorAll('.a-IRR-button--pagination:not([disabled]):not([aria-disabled=true])')].filter(e=>e.getClientRects().length>0);
    const label=e=>[e.getAttribute('aria-label'),e.getAttribute('title'),e.innerText,
      ...[...(e.getAttribute('aria-labelledby')||'').split(/\\s+/)].filter(Boolean).map(id=>document.getElementById(id)?.textContent),
      ...[...e.querySelectorAll('[title], [aria-label], svg title')].map(x=>[x.getAttribute('title'),x.getAttribute('aria-label'),x.textContent].join(' '))].filter(Boolean).join(' ');
    const next=a.filter(e=>/\\bnext\\b|următoar/i.test(label(e)));
    const result={enabled:a.length,explicitNext:next.length,hasPaginationData:a.filter(e=>e.hasAttribute('data-pagination')).length,
      rowSelects:[...document.querySelectorAll('select')].filter(e=>e.getClientRects().length>0&&/rows|rânduri/i.test([e.getAttribute('aria-label'),e.getAttribute('title'),...[...e.labels||[]].map(l=>l.textContent)].join(' '))).length,
      hittable:false,target:null};
    if(next.length!==1)return result;
    const x=next[0];if(${scroll})x.scrollIntoView({block:'center',inline:'center',behavior:'instant'});
    const b=x.getBoundingClientRect(),cx=b.left+b.width/2,cy=b.top+b.height/2,hit=document.elementFromPoint(cx,cy);
    result.hittable=!!hit&&(hit===x||x.contains(hit));if(result.hittable)result.target={x:cx,y:cy};return result})()`);
  const before=await inspectTarget(true);
  await sleep(350);
  const after=await inspectTarget(false);
  if(!before||!after)throw new Error('target inspection unavailable');
  console.log(JSON.stringify({...base,status:'UI_CONTROL_SHAPE_ONLY',fetchedAt:new Date().toISOString(),
    firstRange:first,controlCounts:{enabled:after.enabled,explicitNext:after.explicitNext,hasPaginationData:after.hasPaginationData,rowSelects:after.rowSelects},
    beforeHittable:before.hittable,afterHittable:after.hittable,paginationProtocolConfirmed:false}));
  const target=after.target;
  if(before.explicitNext!==1||after.explicitNext!==1||!target||!Number.isFinite(target.x)||!Number.isFinite(target.y))throw new Error('no unambiguous hittable next button');
  status='NEXT_TARGET_CONFIRMED';
  capture=true;
  await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:target.x,y:target.y});
  await cdp('Input.dispatchMouseEvent',{type:'mousePressed',x:target.x,y:target.y,button:'left',buttons:1,clickCount:1});
  await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',x:target.x,y:target.y,button:'left',buttons:0,clickCount:1});
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
    endpointClass:'SAME_ORIGIN_WWV_FLOW_AJAX',method:'POST',httpStatus:200,
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

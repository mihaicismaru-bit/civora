#!/usr/bin/env node
// At most two public, anonymous UI pagination clicks. Diagnostic only: no session
// material, request values, HTML or reconstructed DOM is logged or persisted.
// This is NOT an immutable raw receipt or an acquisition adapter.
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
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
  return !!a && !!b && [a.first,a.last,a.total,b.first,b.last,b.total].every(Number.isSafeInteger) &&
    a.first > 0 && a.first <= a.last && a.last < a.total && b.first === a.last+1 && b.total === a.total &&
    b.last === Math.min(a.total,a.last+(a.last-a.first+1));
}
function sameReportIdentity(a,b) {
  return Number.isSafeInteger(a) && a > 0 && a === b;
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
// Bind every observation to the initial report/action, not just mirror count.
function sameControlIdentity(initial, observed) {
  const a=initial?.controlIdentity,b=observed?.controlIdentity;
  return !!initial?.unambiguous && !!observed?.unambiguous &&
    initial.matchingNext===observed.matchingNext && initial.matchingNext>0 &&
    !!a?.report && !!a?.action && !!b &&
    a.report===b.report && a.action===b.action;
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
// In-memory response/DOM concordance only. Reuse the existing Python
// table parser and strict Info-link resolver; never print rows, links or HTML.
// A decoded AJAX fragment and a rendered DOM are not immutable raw receipts.
const tableCheckPython = String.raw`
import json, re, sys
sys.path.insert(0, sys.argv[1])
from mysmis_call_inventory_scout import ReportTableParser, HEADER_ALIASES, MATERIAL_FIELDS, OPERATIONAL_FIELDS, key_text, replay_info_code, decode_js_unicode, clean
payload = json.load(sys.stdin)
required = ("programme", "callType", "callTitle", "status", "callBudgetRon", "info")
def extract(raw):
    parser = ReportTableParser()
    parser.feed(raw)
    header = None
    rows = []
    for row in parser.rows:
        names = [HEADER_ALIASES.get(key_text(c["text"])) for c in row]
        if all(name in names for name in required):
            if header is not None or any(names.count(n) != 1 for n in set(names) if n):
                raise ValueError("AMBIGUOUS_HEADER")
            header = names
            continue
        if header is None or not all(c["tag"] == "td" for c in row):
            continue
        if len(row) != len(header):
            raise ValueError("ROW_WIDTH_MISMATCH")
        if not row[header.index("programme")]["text"] or not row[header.index("callTitle")]["text"]:
            raise ValueError("MISSING_IDENTITY_FIELDS")
        hrefs = row[header.index("info")]["hrefs"]
        codes = [replay_info_code(h) for h in hrefs]
        if any(not code and re.search(r"[?&]p201_cod_apel=", decode_js_unicode(h), re.I) for h,code in zip(hrefs,codes)):
            raise ValueError("INVALID_IDENTITY_LINK")
        identities = {c for c in codes if c}
        if len(identities) != 1:
            raise ValueError("AMBIGUOUS_IDENTITY")
        rows.append((next(iter(identities)), tuple((n,c["text"]) for n,c in zip(header,row) if n and n != "info")))
    if header is None or not rows:
        raise ValueError("NO_REPORT_TABLE")
    return rows
def summary(raw):
    try:
        rows = extract(raw)
        return rows, {"tableParsed":True,"rowCount":len(rows),"uniqueIdentityCount":len({r[0] for r in rows})}
    except (ValueError, RuntimeError, UnicodeError) as exc:
        # Only fixed reason codes may cross the diagnostic output boundary.
        allowed = {"AMBIGUOUS_HEADER","ROW_WIDTH_MISMATCH","MISSING_IDENTITY_FIELDS","INVALID_IDENTITY_LINK","AMBIGUOUS_IDENTITY","NO_REPORT_TABLE"}
        reason = str(exc) if str(exc) in allowed else "PARSER_ERROR"
        return None, {"tableParsed":False,"reason":reason}
def duplicates(rows):
    # Same full normalized material + operational row as the replay contract.
    # Return only counts: no identities, text, links or session material.
    seen = {}
    mirrored = conflicts = 0
    for code, pairs in rows:
        fields = dict(pairs)
        fingerprint = tuple(clean(fields.get(n, "")) for n in (*MATERIAL_FIELDS[1:], *OPERATIONAL_FIELDS))
        if code in seen:
            if seen[code] == fingerprint:
                mirrored += 1
            else:
                conflicts += 1
        else:
            seen[code] = fingerprint
    return {"rowCount":len(rows),"uniqueIdentityCount":len(seen),"mirroredDuplicateRowCount":mirrored,
            "conflictingDuplicateRowCount":conflicts,"exactIdentityComplete":conflicts == 0}
body, dom = payload["body"], payload["dom"]
a, sa = summary(body)
b, sb = summary(dom)
shape = "FULL_HTML_DOCUMENT" if re.search(r"<html(?:\s|>)",body,re.I) and re.search(r"</html>\s*$",body,re.I) else "HTML_FRAGMENT_OR_OTHER"
expected = payload["expected"]
match = a is not None and b is not None and len(a) == expected and len(b) == expected and a == b
out = {"responseShape":shape,"response":sa,"rendered":sb,"expectedRows":expected,"orderedExactRowsMatch":match}
if match:
    out["secondPageDuplicateDiagnostic"] = duplicates(a)
    first_raw = payload.get("firstDom")
    if first_raw is not None:
        first_rows, first_summary = summary(first_raw)
        first_ok = first_rows is not None and len(first_rows) == payload["firstExpected"]
        out["firstPageDiagnostic"] = {**first_summary,"expectedRows":payload["firstExpected"],"exactRowCountMatch":first_ok}
        if first_ok:
            combined = duplicates(first_rows + a)
            combined["firstPageDuplicateDiagnostic"] = duplicates(first_rows)
            combined["crossPageIdentityOverlapCount"] = len({r[0] for r in first_rows} & {r[0] for r in a})
            out["twoPageDuplicateDiagnostic"] = combined
print(json.dumps(out))
`;
function compareDecodedTable(body,dom,expected,firstDom=null,firstExpected=null) {
  if(typeof body!=='string'||typeof dom!=='string'||!Number.isSafeInteger(expected)||expected<1||
      Buffer.byteLength(body)>=2000000||Buffer.byteLength(dom)>=2000000||
      (firstDom!==null&&(typeof firstDom!=='string'||Buffer.byteLength(firstDom)>=2000000||
        !Number.isSafeInteger(firstExpected)||firstExpected<1)))
    return {status:'TABLE_COMPARISON_UNAVAILABLE'};
  const result=spawnSync('python',['-c',tableCheckPython,fileURLToPath(new URL('../ingest',import.meta.url))],
    {input:JSON.stringify({body,dom,expected,firstDom,firstExpected}),encoding:'utf8',timeout:5000,maxBuffer:16000});
  if(result.status!==0)return {status:'TABLE_COMPARISON_UNAVAILABLE'};
  try {
    const parsed=JSON.parse(result.stdout);
    return {status:parsed.orderedExactRowsMatch?'DECODED_TABLE_CONCORDANT':'DECODED_TABLE_UNVERIFIED',...parsed};
  } catch { return {status:'TABLE_COMPARISON_UNAVAILABLE'}; }
}
// A later DOM observation of the previous range must still agree with its
// previously captured decoded response. Matching range/count alone is not
// a snapshot guarantee. Keep the prior fragment in memory only.
function previousPageConcordance(previousBody,currentDom,expected) {
  const proof=compareDecodedTable(previousBody,currentDom,expected);
  return proof.orderedExactRowsMatch===true &&
    proof.secondPageDuplicateDiagnostic?.exactIdentityComplete===true;
}
function singleAjaxExchange(counters,requestCount,matchedCount) {
  return requestCount===1&&matchedCount===1&&counters.sameOriginPosts===1&&
    counters.officialAjaxPosts===1&&counters.officialAjax200===1&&
    counters.officialAjaxFinished===1&&counters.redirects===0;
}
if (process.argv.includes('--self-test')) {
  assert.deepEqual(range('1 - 50 of 1,002'),{first:1,last:50,total:1002});
  assert.equal(range('1 - 50 of 1002 51 - 100 of 1002'),null);
  assert.equal(range('1 - 50 of 10'),null);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 100 of 1002')),true);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 100 of 1003')),false);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('1 - 50 of 1002')),false);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 51 of 1002')),false);
  assert.equal(nextRange(range('1 - 50 of 1002'),range('51 - 101 of 1002')),false);
  assert.equal(nextRange(range('1 - 50 of 52'),range('51 - 52 of 52')),true);
  assert.equal(nextRange(range('1 - 50 of 52'),range('51 - 51 of 52')),false);
  assert.equal(nextRange(range('51 - 100 of 1002'),range('101 - 150 of 1002')),true);
  assert.equal(nextRange(range('51 - 100 of 1002'),range('151 - 200 of 1002')),false);
  assert.equal(nextRange(range('51 - 100 of 1002'),range('101 - 149 of 1002')),false);
  assert.equal(nextRange(range('51 - 100 of 1002'),range('101 - 150 of 1003')),false);
  assert.equal(nextRange(range('951 - 1000 of 1002'),range('1001 - 1002 of 1002')),true);
  assert.equal(sameReportIdentity(1,1),true);
  assert.equal(sameReportIdentity(1,2),false);
  assert.equal(sameReportIdentity(0,0),false);
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
  const initial={unambiguous:true,matchingNext:2,controlIdentity:{report:1,action:next.pagination}};
  assert.equal(sameControlIdentity(initial,{...initial}),true);
  assert.equal(sameControlIdentity(initial,{...initial,controlIdentity:{...initial.controlIdentity,report:2}}),false);
  assert.equal(sameControlIdentity(initial,{...initial,controlIdentity:{...initial.controlIdentity,action:next.pagination.replace('rows_fetched=50','rows_fetched=49')}}),false);
  assert.equal(sameControlIdentity(initial,{...initial,matchingNext:1}),false);
  assert.equal(sameControlIdentity(initial,{...initial,unambiguous:false}),false);
  assert.equal(sameControlIdentity(initial,{...initial,controlIdentity:null}),false);
  assert.equal(sameControlIdentity(initial,null),false);
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
  const counts={sameOriginPosts:1,officialAjaxPosts:1,officialAjax200:1,officialAjaxFinished:1,redirects:0};
  assert.equal(singleAjaxExchange(counts,1,1),true);
  for(const key of Object.keys(counts))assert.equal(singleAjaxExchange({...counts,[key]:counts[key]+1},1,1),false);
  assert.equal(singleAjaxExchange(counts,2,1),false);
  assert.equal(singleAjaxExchange(counts,1,0),false);
  const href='/ords/repo_bo/r/mysmis-2021/detaliu-apel?p201_cod_apel=PRT%2F1';
  const fixture='<table><tr>'+['Program operațional','Tip apel','Apel','Stare apel','Buget nerambursabil apel','Info'].map(x=>'<th>'+x+'</th>').join('')+'</tr><tr><td>P</td><td>T</td><td>A</td><td>S</td><td>1</td><td><a href="'+href+'">i</a></td></tr></table>';
  const document='<html><body>'+fixture+'</body></html>';
  const good=compareDecodedTable(fixture,document,1);
  assert.equal(good.status,'DECODED_TABLE_CONCORDANT');
  assert.equal(good.responseShape,'HTML_FRAGMENT_OR_OTHER');
  assert.equal(compareDecodedTable(document,document,1).responseShape,'FULL_HTML_DOCUMENT');
  assert.equal(compareDecodedTable(fixture,document,2).orderedExactRowsMatch,false);
  assert.equal(compareDecodedTable(fixture,document.replace('<td>S</td>','<td>X</td>'),1).orderedExactRowsMatch,false);
  assert.equal(compareDecodedTable(fixture.replace(href,'https://example.invalid/?p201_cod_apel=PRT%2F1'),document,1).orderedExactRowsMatch,false);
  assert.equal(compareDecodedTable(fixture+fixture,document,1).orderedExactRowsMatch,false);
  assert.equal(compareDecodedTable(fixture,document+document,1).rendered.reason,'AMBIGUOUS_HEADER');
  assert.equal(compareDecodedTable(fixture,document.replace('<td>S</td>',''),1).rendered.reason,'ROW_WIDTH_MISMATCH');
  assert.equal(compareDecodedTable(fixture,document.replace(href,'https://example.invalid/?p201_cod_apel=PRT%2F1'),1).rendered.reason,'INVALID_IDENTITY_LINK');
  assert.equal(compareDecodedTable(fixture,'<html><body></body></html>',1).rendered.reason,'NO_REPORT_TABLE');
  // A duplicated header in the outer document is not a second report data table.
  // The scoped table itself still has to pass the exact same strict parser.
  const headerOnly=fixture.slice(0,fixture.indexOf('</tr>')+5)+'</table>';
  assert.equal(compareDecodedTable(fixture,headerOnly+fixture,1).rendered.reason,'AMBIGUOUS_HEADER');
  assert.equal(compareDecodedTable(fixture,fixture,1).orderedExactRowsMatch,true);
  assert.equal(compareDecodedTable('',document,1).orderedExactRowsMatch,false);
  assert.equal(compareDecodedTable(fixture,document,0).status,'TABLE_COMPARISON_UNAVAILABLE');
  const row=fixture.slice(fixture.indexOf('<tr><td>'),fixture.lastIndexOf('</table>'));
  const repeated=fixture.replace('</table>',row+'</table>');
  const conflicting=fixture.replace('</table>',row.replace('<td>S</td>','<td>X</td>')+'</table>');
  assert.deepEqual(compareDecodedTable(repeated,repeated,2).secondPageDuplicateDiagnostic,
    {rowCount:2,uniqueIdentityCount:1,mirroredDuplicateRowCount:1,conflictingDuplicateRowCount:0,exactIdentityComplete:true});
  assert.equal(compareDecodedTable(conflicting,conflicting,2).secondPageDuplicateDiagnostic.conflictingDuplicateRowCount,1);
  assert.equal(compareDecodedTable(conflicting,conflicting,2).secondPageDuplicateDiagnostic.exactIdentityComplete,false);
  const pair=compareDecodedTable(fixture,fixture,1,fixture,1).twoPageDuplicateDiagnostic;
  assert.equal(pair.crossPageIdentityOverlapCount,1);
  assert.equal(pair.mirroredDuplicateRowCount,1);
  assert.equal(pair.exactIdentityComplete,true);
  assert.equal(compareDecodedTable(fixture,fixture,1,fixture.replace('<td>S</td>','<td>X</td>'),1).twoPageDuplicateDiagnostic.conflictingDuplicateRowCount,1);
  assert.equal(compareDecodedTable(fixture,fixture,1,fixture.replace(href,href.replace('PRT%2F1','PRT%2F2')),1).twoPageDuplicateDiagnostic.uniqueIdentityCount,2);
  assert.equal(compareDecodedTable(fixture,fixture,1,fixture,2).twoPageDuplicateDiagnostic,undefined);
  assert.equal(compareDecodedTable(fixture,fixture,1,'<html></html>',1).firstPageDiagnostic.exactRowCountMatch,false);
  assert.equal(compareDecodedTable(fixture,fixture.replace('<td>S</td>','<td>X</td>'),1,fixture,1).twoPageDuplicateDiagnostic,undefined);
  assert.equal(compareDecodedTable(fixture,fixture,1,fixture,0).status,'TABLE_COMPARISON_UNAVAILABLE');
  assert.equal(previousPageConcordance(fixture,document,1),true);
  assert.equal(previousPageConcordance(fixture,document.replace('<td>S</td>','<td>X</td>'),1),false);
  assert.equal(previousPageConcordance(fixture,document.replace(href,href.replace('PRT%2F1','PRT%2F2')),1),false);
  assert.equal(previousPageConcordance(repeated,repeated,2),true);
  assert.equal(previousPageConcordance(conflicting,conflicting,2),false);
  assert.equal(previousPageConcordance(repeated,fixture,2),false);
  assert.equal(previousPageConcordance(null,fixture,1),false);
  assert.equal(previousPageConcordance(fixture,fixture,0),false);
  console.log('PASS: public UI protocol diagnostic range, endpoint, native-control equivalence, stable hit, native focus, decoded table and prior-page concordance guards');
  process.exit(0);
}
let dir, chrome, ws;
const base = {schema:'MYSMIS_UI_PROTOCOL_DISCOVERY_V1',canonicalUrl:URL0,
  runId:process.env.GITHUB_RUN_ID || 'local',parserVersion:'MYSMIS_UI_PROTOCOL_DISCOVERY_V3',
  sourceFamily:'ROMANIA_MIPE_MYSMIS',programmeFamily:'ROMANIA_MULTI_PROGRAMME',
  authorityClass:'T1_OFFICIAL_MYSMIS_REPORTING',observationState:'PROTOCOL_DISCOVERY_ONLY',
  rawPersisted:false,immutableReceipt:false,materialFactUse:false,publishAuthorized:false,
  openCallAuthorized:false,deadlineAuthorized:false,budgetAuthorized:false,eligibilityAuthorized:false,
  publicationEffect:'NONE'};
let status='NOT_STARTED';
const browserStartup={polls:0,spawnError:false,exited:false,portReady:false};
const counters={sameOriginPosts:0,officialAjaxPosts:0,officialAjax200:0,officialAjaxFinished:0,redirects:0};
try {
  dir=await mkdtemp(join(tmpdir(),'mysmis-public-ui-'));
  status='PROFILE_CREATED';
  chrome=spawn(process.env.CHROME_BIN || 'google-chrome',[
    '--headless=new','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',
    '--disable-background-networking','--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0','--user-data-dir='+dir,'about:blank'
  ],{stdio:'ignore'});
  status='BROWSER_SPAWN_REQUESTED';
  chrome.on('error',()=>{browserStartup.spawnError=true;});
  chrome.on('exit',()=>{browserStartup.exited=true;});
  let port;
  for(let i=0;i<40&&!port&&!browserStartup.spawnError&&!browserStartup.exited;i++){
    browserStartup.polls++;
    try {
      const p=Number((await readFile(join(dir,'DevToolsActivePort'),'utf8')).split('\n')[0]);
      if(Number.isInteger(p)&&p>0&&p<=65535)port=p;
    }catch{}
    if(!port) await sleep(250);
  }
  browserStartup.portReady=!!port;
  if(!port||browserStartup.spawnError||browserStartup.exited) throw new Error('browser unavailable');
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
      if(m.method==='Network.requestWillBeSent' && p.redirectResponse && (requests.has(p.requestId)||officialAjax(p.request?.url)))counters.redirects++;
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
  // Bounded repeatability experiment: second transition only after the first
  // has exact ordered concordance and no conflicting duplicates. Each exchange
  // gets its own counters; no request values, HTML, or identities are emitted.
  let reportOrdinal=null, initialDom=null, initialRange=first, previousBody=null;
  for(let transition=1;transition<=2 && first.last<first.total;transition++){
  capture=false;
  requests.clear();responses.clear();finished.clear();
  for(const key of Object.keys(counters))counters[key]=0;
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
      matchingNext:selection.count,unambiguous:selection.index!==null,controlIdentity:null,hittable:false,target:null,focused:false,focusTarget:null};
    if(selection.index===null)return result;
    const selected=descriptors[selection.index];
    result.controlIdentity={report:selected.report,action:selected.pagination};
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
  if(reportOrdinal===null)reportOrdinal=before.controlIdentity.report;
  if(!sameReportIdentity(reportOrdinal,before.controlIdentity.report))throw new Error('report identity changed');
  const observeReportTable=reportOrdinal=>evaluate(`(()=>{
    const reports=[...document.querySelectorAll('.a-IRR')];
    const report=reports[${reportOrdinal-1}];
    const tables=report?[...report.querySelectorAll('table.a-IRR-table')].filter(t=>t.closest('.a-IRR')===report):[];
    const data=tables.filter(t=>[...t.rows].some(r=>[...r.cells].some(c=>c.tagName==='TD')));
    const chosen=data.length===1?data[0]:null;
    return {url:location.origin+location.pathname,
      text:report?[...report.querySelectorAll('.a-IRR-pagination')].filter(e=>e.closest('.a-IRR')===report).map(e=>e.innerText).join(' '):'',
      reportCount:reports.length,tableCount:tables.length,dataTableCount:data.length,
      html:chosen?chosen.outerHTML:null};
  })()`);
  // Take a separate, bounded first-page DOM observation before native activation.
  // This does not turn either DOM observation into an immutable receipt.
  const firstRendered=await observeReportTable(before.controlIdentity.report);
  const firstDom=firstRendered?.url===URL0&&JSON.stringify(range(firstRendered?.text))===JSON.stringify(first)&&
    typeof firstRendered.html==='string'&&Buffer.byteLength(firstRendered.html)<2000000
    ? firstRendered.html : null;
  if(firstDom===null)throw new Error('first table unavailable');
  if(transition===1)initialDom=firstDom;
  if(transition>1){
    status='PRIOR_PAGE_REOBSERVATION';
    const previousPageStillConcordant=previousPageConcordance(previousBody,firstDom,first.last-first.first+1);
    console.log(JSON.stringify({...base,status:'UI_PRIOR_PAGE_CONCORDANCE_ONLY',transition,
      fetchedAt:new Date().toISOString(),firstRange:first,previousPageStillConcordant,paginationProtocolConfirmed:false}));
    if(!previousPageStillConcordant)throw new Error('prior page drift or unavailable proof');
  }
  let previous=null,after=before,confirmed=false;
  const hitPoll={attempts:0,hittable:0,stablePairs:0,ambiguous:0};
  for(let i=0;i<12;i++){
    await sleep(150);
    after=await inspectTarget(false);
    hitPoll.attempts++;
    if(!sameControlIdentity(before,after)){hitPoll.ambiguous++;break;}
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
    const focusConfirmed=[f0,f1,f2].every(f=>sameControlIdentity(before,f))&&stableFocus(f0,f1)&&stableFocus(f1,f2);
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
  if(!singleAjaxExchange(counters,requests.size,ids.length))throw new Error('ambiguous official ajax exchange');
  const response=await cdp('Network.getResponseBody',{requestId:ids[0]});
  const bytes=response.base64Encoded?Buffer.from(response.body,'base64'):Buffer.from(response.body,'utf8');
  if(!bytes.length||bytes.length>=2000000)throw new Error('response size outside diagnostic bound');
  const mime=responses.get(ids[0]).mimeType.toLowerCase();
  if(!['text/html','application/json','text/plain'].includes(mime))throw new Error('unrecognized response media');
  // The rendered document is observed independently from the decoded response,
  // still in this same session. Never persist or log either HTML representation.
  // APEX can render layout/sticky-header tables outside the actual report.
  // Limit the second observation to the unique data-bearing report table
  // inside the same report ordinal that owned the native pagination control.
  // No fallback to the network fragment or generic page-wide HTML.
  const rendered=await observeReportTable(before.controlIdentity.report);
  const observedRange=range(rendered?.text);
  const concordance=rendered?.url===URL0&&JSON.stringify(observedRange)===JSON.stringify(second)&&mime==='text/html'
    ? compareDecodedTable(bytes.toString('utf8'),rendered.html,second.last-second.first+1,firstDom,first.last-first.first+1)
    : {status:'TABLE_COMPARISON_UNAVAILABLE'};
  if(!singleAjaxExchange(counters,requests.size,[...responses.keys()].filter(k=>finished.has(k)).length))throw new Error('ambiguous late official ajax exchange');
  // Also compare page 3 against page 1, not merely its immediate predecessor.
  const nonAdjacent=transition===2&&concordance.orderedExactRowsMatch
    ? compareDecodedTable(bytes.toString('utf8'),rendered.html,second.last-second.first+1,
        initialDom,initialRange.last-initialRange.first+1) : null;
  if(!singleAjaxExchange(counters,requests.size,[...responses.keys()].filter(k=>finished.has(k)).length))throw new Error('ambiguous late official ajax exchange');
  console.log(JSON.stringify({...base,status:'UI_NEXT_RANGE_AND_OFFICIAL_AJAX_OBSERVED',transition,counters,
    fetchedAt:new Date().toISOString(),firstRange:first,secondRange:second,
    activation,endpointClass:'SAME_ORIGIN_WWV_FLOW_AJAX',method:'POST',httpStatus:200,
    contentType:mime,cdpDecodedBodySha256:sha(bytes),decodedBodyBytes:bytes.length,
    renderedTableScope:{reportCount:rendered?.reportCount??0,tableCount:rendered?.tableCount??0,dataTableCount:rendered?.dataTableCount??0},
    decodedTableConcordance:concordance,
    nonAdjacentDuplicateDiagnostic:nonAdjacent?.twoPageDuplicateDiagnostic??null,
    rawByteIdentityProven:false,paginationProtocolConfirmed:false}));
  if(!concordance.orderedExactRowsMatch||!concordance.twoPageDuplicateDiagnostic?.exactIdentityComplete||
    (transition===2&&!nonAdjacent?.twoPageDuplicateDiagnostic?.exactIdentityComplete))
    throw new Error('transition semantic guard failed');
  // Retain only the bounded decoded fragment for the next observation.
  previousBody=bytes.toString('utf8');
  capture=false;
  first=second;
  }
} catch(e) {
  // No exception messages or arbitrary server values: could contain session data.
  console.log(JSON.stringify({...base,status:'UI_PROTOCOL_DIAGNOSTIC_FAIL_CLOSED',stage:status,counters,browserStartup,
    fetchedAt:new Date().toISOString(),paginationProtocolConfirmed:false}));
  process.exitCode=2;
} finally {
  try{ws?.close();}catch{}
  try{chrome?.kill('SIGKILL');}catch{}
  if(dir)await rm(dir,{recursive:true,force:true,maxRetries:3}).catch(()=>{});
}

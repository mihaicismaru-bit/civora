#!/usr/bin/env node
// At most six public, anonymous UI pagination activations. Diagnostic only: no session
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
// Startup is local and passive; a slow runner is not evidence of source failure.
// Keep the existing outer workflow timeout and never restart or navigate here.
const STARTUP_POLLS=60, STARTUP_INTERVAL_MS=250;
const MAX_TRANSITIONS=6, MAX_DIAGNOSTIC_BYTES=8000000;
function parseDevToolsPort(contents) {
  const first=String(contents).split(/\r?\n/)[0];
  if(!/^[1-9]\d{0,4}$/.test(first))return null;
  const port=Number(first);
  return port<=65535?port:null;
}
async function pollDevToolsPort(readPort,pause,state) {
  for(let i=0;i<STARTUP_POLLS&&!state.spawnError&&!state.exited;i++){
    state.polls++;
    let port=null;
    try{port=parseDevToolsPort(await readPort());}catch{}
    if(state.spawnError||state.exited)return null;
    if(port)return port;
    if(i+1<STARTUP_POLLS)await pause(STARTUP_INTERVAL_MS);
  }
  return null;
}
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
// Keyboard activation is native, never a synthetic DOM click.
function stableFocus(a,b) {
  if(!a?.unambiguous||!b?.unambiguous||!a.focused||!b.focused||
     !a.focusTarget||!b.focusTarget||a.matchingNext!==b.matchingNext)return false;
  const x=a.focusTarget,y=b.focusTarget;
  return x.index===y.index&&x.report===y.report&&x.action===y.action&&
    x.nativeButton===true&&y.nativeButton===true;
}
// Exactly three independent focus observations must also bind the focused
// native control to the initial report/action, not merely to each other.
function confirmedNativeFocus(initial,samples) {
  return samples.length===3 && samples.every(f=>sameControlIdentity(initial,f) &&
    f.focused===true && f.focusTarget?.nativeButton===true &&
    f.focusTarget.report===initial.controlIdentity.report &&
    f.focusTarget.action===initial.controlIdentity.action) &&
    stableFocus(samples[0],samples[1]) && stableFocus(samples[1],samples[2]);
}
// In-memory response/DOM concordance only. Reuse the existing Python
// table parser and strict Info-link resolver; never print rows, links or HTML.
// A decoded AJAX fragment and a rendered DOM are not immutable raw receipts.
const tableCheckPython = String.raw`
import hashlib, json, re, sys
sys.path.insert(0, sys.argv[1])
from mysmis_call_inventory_scout import ReportTableParser, HEADER_ALIASES, MATERIAL_FIELDS, OPERATIONAL_FIELDS, key_text, replay_info_code, decode_js_unicode, clean, semantic_sha
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
# A scoped fingerprint over exact normalized rows, not the volatile APEX
# response/session wrapper. Deduplicate only identical rows, never conflicts.
# Keep raw text and identities in memory; only aggregate digests may leave.
def scoped_fingerprints(rows):
    if not duplicates(rows)["exactIdentityComplete"]:
        return None
    unique = {}
    for code, pairs in rows:
        fields = dict(pairs)
        unique[code] = {"callCode":code, **{n:clean(fields.get(n, "")) for n in (*MATERIAL_FIELDS[1:], *OPERATIONAL_FIELDS)}}
    ordered = [unique[code] for code in sorted(unique)]
    operational = [{n:r[n] for n in ("callCode", *OPERATIONAL_FIELDS)} for r in ordered]
    digest = hashlib.sha256(json.dumps(operational, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    identity_digest = hashlib.sha256(json.dumps(sorted(unique), ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"identitySetSha256":identity_digest,"uniqueIdentityCount":len(unique),
            "materialSha256":semantic_sha(ordered),"operationalSha256":digest}
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
    history = payload.get("history")
    if history is not None:
        accumulated = []
        valid = True
        for page in history:
            prior_rows, _ = summary(page["html"])
            if prior_rows is None or len(prior_rows) != page["expected"]:
                valid = False
                break
            accumulated.extend(prior_rows)
        if valid:
            cumulative = duplicates(accumulated + a)
            cumulative["pageCount"] = len(history) + 1
            cumulative["crossHistoryIdentityOverlapCount"] = len({r[0] for r in accumulated} & {r[0] for r in a})
            out["cumulativeDuplicateDiagnostic"] = cumulative
            if cumulative["exactIdentityComplete"]:
                out["boundedSemanticFingerprints"] = scoped_fingerprints(accumulated + a)
print(json.dumps(out))
`;
// History contains only bounded in-memory observations, contiguous from row 1.
// It is not proof of source-wide temporal consistency or immutable raw bytes.
function validDiagnosticHistory(history, currentRange) {
  if(!Array.isArray(history)||history.length<1||history.length>MAX_TRANSITIONS||
      history[0]?.range?.first!==1)return false;
  let totalBytes=0;
  for(let i=0;i<history.length;i++){
    const page=history[i], r=page?.range;
    if(!r||![r.first,r.last,r.total].every(Number.isSafeInteger)||
        r.first<1||r.last<r.first||r.last>r.total||
        typeof page.html!=='string'||!page.html.length||
        Buffer.byteLength(page.html)>=2000000||
        (i>0&&!nextRange(history[i-1].range,r)))return false;
    totalBytes+=Buffer.byteLength(page.html);
  }
  return totalBytes<MAX_DIAGNOSTIC_BYTES&&nextRange(history.at(-1).range,currentRange);
}
function compareDecodedTable(body,dom,expected,firstDom=null,firstExpected=null,history=null,currentRange=null) {
  if(typeof body!=='string'||typeof dom!=='string'||!Number.isSafeInteger(expected)||expected<1||
      Buffer.byteLength(body)>=2000000||Buffer.byteLength(dom)>=2000000||
      (firstDom!==null&&(typeof firstDom!=='string'||Buffer.byteLength(firstDom)>=2000000||
        !Number.isSafeInteger(firstExpected)||firstExpected<1))||
      (history!==null&&(!validDiagnosticHistory(history,currentRange)||
        expected!==currentRange.last-currentRange.first+1)))
    return {status:'TABLE_COMPARISON_UNAVAILABLE'};
  const result=spawnSync('python',['-c',tableCheckPython,fileURLToPath(new URL('../ingest',import.meta.url))],
    {input:JSON.stringify({body,dom,expected,firstDom,firstExpected,history:history?.map(p=>({html:p.html,expected:p.range.last-p.range.first+1}))??null}),encoding:'utf8',timeout:5000,maxBuffer:16000});
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
// Bind initial network document to the actual top-level navigation.
// No session values leave memory.
function initialDocumentId(documents,navigation) {
  if(!navigation?.frameId||!navigation?.loaderId)return null;
  const candidates=[...documents.entries()].filter(([,d])=>d.frameId===navigation.frameId&&d.loaderId===navigation.loaderId);
  if(candidates.length!==1)return null;
  const [id,d]=candidates[0];
  return d.requestCount===1&&d.requestExact===true&&d.method==='GET'&&
    d.responseCount===1&&d.responseExact===true&&d.status===200&&
    d.mimeType==='text/html'&&d.finishedCount===1&&!d.failed&&!d.redirected&&!d.cached?id:null;
}
function initialDocumentConcordance(body,dom,expected) {
  const proof=compareDecodedTable(body,dom,expected);
  return proof.responseShape==='FULL_HTML_DOCUMENT'&&proof.orderedExactRowsMatch===true&&
    proof.secondPageDuplicateDiagnostic?.exactIdentityComplete===true;
}
// A transition is a diagnostic observation only after all semantic gates pass.
function acceptedTransition(concordance, second, transition, nonAdjacent) {
  const c=concordance?.cumulativeDuplicateDiagnostic;
  return concordance?.orderedExactRowsMatch===true &&
    concordance.twoPageDuplicateDiagnostic?.exactIdentityComplete===true &&
    c?.exactIdentityComplete===true && c.rowCount===second.last &&
    c.pageCount===transition+1 &&
    (transition!==2||nonAdjacent?.twoPageDuplicateDiagnostic?.exactIdentityComplete===true);
}
// Terminal summaries are deliberately not full-inventory or immutable-receipt claims.
// The initial page may have a separately bound decoded document observation.
// Neither that representation nor later fragments proves raw-byte identity.
function terminalCoverage(history, last, diagnostic, terminalStable, initialDocumentVerified=false) {
  if(!terminalStable||!Array.isArray(history)||history.length<2||
    !last||JSON.stringify(history.at(-1)?.range)!==JSON.stringify(last)||
    !validDiagnosticHistory(history.slice(0,-1),last)||
    typeof history.at(-1)?.html!=='string'||!history.at(-1).html.length||
    Buffer.byteLength(history.at(-1).html)>=2000000||
    history.reduce((n,p)=>n+Buffer.byteLength(p.html),0)>=MAX_DIAGNOSTIC_BYTES||
    diagnostic?.exactIdentityComplete!==true||diagnostic.pageCount!==history.length||
    diagnostic.rowCount!==last.last||
    !Number.isSafeInteger(diagnostic.uniqueIdentityCount)||diagnostic.uniqueIdentityCount<1||
    !Number.isSafeInteger(diagnostic.mirroredDuplicateRowCount)||diagnostic.mirroredDuplicateRowCount<0||
    diagnostic.uniqueIdentityCount+diagnostic.mirroredDuplicateRowCount!==diagnostic.rowCount||
    diagnostic.conflictingDuplicateRowCount!==0)return null;
  return {pageCount:history.length,observedRows:last.last,totalRows:last.total,
    uniqueIdentityCount:diagnostic.uniqueIdentityCount,mirroredDuplicateRowCount:diagnostic.mirroredDuplicateRowCount,
    conflictingDuplicateRowCount:0,initialPageObservation:initialDocumentVerified?'CDP_DECODED_DOCUMENT_CONCORDANT':'DOM_ONLY',
    decodedAjaxFragmentCount:history.length-1,terminalPageStillConcordant:true,
    sourceRangeExhausted:last.last===last.total,fullInventoryProven:false};
}
// Ordered, hash-only diagnostic manifest. This is deliberately NOT the V1
// immutable raw handoff: the decoded entity might have been re-encoded by CDP.
// It binds all accepted observations to one run attempt without retaining
// HTML, request values, session identifiers or arbitrary server URLs.
function diagnosticManifest(records, coverage, runId, runAttempt, fingerprints) {
  if(!Array.isArray(records)||records.length<2||records.length>MAX_TRANSITIONS+1||
    coverage?.pageCount!==records.length||coverage.initialPageObservation!=='CDP_DECODED_DOCUMENT_CONCORDANT'||
    coverage.terminalPageStillConcordant!==true||coverage.fullInventoryProven!==false||
    !fingerprints||!['identitySetSha256','materialSha256','operationalSha256'].every(k=>typeof fingerprints[k]==='string'&&/^[a-f0-9]{64}$/.test(fingerprints[k]))||
    !Number.isSafeInteger(fingerprints.uniqueIdentityCount)||fingerprints.uniqueIdentityCount<1||
    fingerprints.uniqueIdentityCount!==coverage.uniqueIdentityCount||
    typeof runId!=='string'||!(/^(?:[1-9]\d*|local)$/).test(runId)||
    typeof runAttempt!=='string'||!(/^[1-9]\d*$/).test(runAttempt))return null;
  const pages=[],seen=new Set();
  let previous=null,previousTime='',totalBytes=0;
  for(let i=0;i<records.length;i++){
    const p=records[i],r=p?.range;
    if(!r||![r.first,r.last,r.total].every(Number.isSafeInteger)||
      r.first<1||r.last<r.first||r.last>r.total||
      (i===0?r.first!==1:!nextRange(previous,r))||
      typeof p.fetchedAt!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(p.fetchedAt)||
      !Number.isFinite(Date.parse(p.fetchedAt))||new Date(p.fetchedAt).toISOString()!==p.fetchedAt||
      p.fetchedAt<previousTime||
      typeof p.cdpDecodedBodySha256!=='string'||!/^[a-f0-9]{64}$/.test(p.cdpDecodedBodySha256)||
      seen.has(p.cdpDecodedBodySha256)||!Number.isSafeInteger(p.decodedBodyBytes)||
      p.decodedBodyBytes<1||p.decodedBodyBytes>=2000000||
      !['CDP_BASE64_DECODED_ENTITY','CDP_TEXT_UTF8_REENCODED'].includes(p.representation)||
      p.method!==(i===0?'GET':'POST')||
      p.endpointClass!==(i===0?'EXACT_CANONICAL_DOCUMENT':'SAME_ORIGIN_WWV_FLOW_AJAX')||
      p.httpStatus!==200||p.contentType!=='text/html'||p.orderedExactRowsMatch!==true)return null;
    seen.add(p.cdpDecodedBodySha256); totalBytes+=p.decodedBodyBytes;
    pages.push({pageOrdinal:i+1,range:{first:r.first,last:r.last,total:r.total},
      fetchedAt:p.fetchedAt,method:p.method,endpointClass:p.endpointClass,httpStatus:200,
      contentType:'text/html',cdpDecodedBodySha256:p.cdpDecodedBodySha256,
      decodedBodyBytes:p.decodedBodyBytes,representation:p.representation,orderedExactRowsMatch:true});
    previous=r;previousTime=p.fetchedAt;
  }
  if(totalBytes>=MAX_DIAGNOSTIC_BYTES||previous.last!==coverage.observedRows||
    previous.total!==coverage.totalRows)return null;
  const manifest={schema:'MYSMIS_DECODED_OBSERVATION_MANIFEST_V3',canonicalUrl:URL0,runId,runAttempt,
    parserVersion:'MYSMIS_UI_PROTOCOL_DISCOVERY_V12',sourceFamily:'ROMANIA_MIPE_MYSMIS',
    programmeFamily:'ROMANIA_MULTI_PROGRAMME',authorityClass:'T1_OFFICIAL_MYSMIS_REPORTING',
    observationState:'PROTOCOL_DISCOVERY_ONLY',pages,totalDecodedBytes:totalBytes,
    observedRows:coverage.observedRows,totalRows:coverage.totalRows,
    boundedSemanticFingerprints:{schema:'MYSMIS_BOUNDED_NORMALIZED_FINGERPRINTS_V2',
      scope:'OBSERVED_EXACT_ID_SET_ONLY',identitySetSha256:fingerprints.identitySetSha256,
      uniqueIdentityCount:fingerprints.uniqueIdentityCount,materialSha256:fingerprints.materialSha256,
      operationalSha256:fingerprints.operationalSha256},
    rawPersisted:false,rawByteIdentityProven:false,immutableReceipt:false,fullInventoryProven:false,
    materialFactUse:false,publishAuthorized:false,openCallAuthorized:false,deadlineAuthorized:false,
    budgetAuthorized:false,eligibilityAuthorized:false,publicationEffect:'NONE'};
  return {...manifest,manifestSha256:sha(JSON.stringify(manifest))};
}
function singleAjaxExchange(counters,requestCount,matchedCount) {
  return requestCount===1&&matchedCount===1&&counters.sameOriginPosts===1&&
    counters.officialAjaxPosts===1&&counters.officialAjax200===1&&
    counters.officialAjaxFinished===1&&counters.redirects===0&&
    counters.officialAjaxNon200===0&&counters.officialAjaxFailed===0;
}
// Fixed vocabulary only; no request IDs, URLs, raw errors or response contents.
function ajaxObservation(counters,requestCount,matchedCount,rangeObserved) {
  if(counters.redirects||counters.sameOriginPosts>1||counters.officialAjaxPosts>1||requestCount>1)return 'AMBIGUOUS_EXCHANGE';
  if(counters.officialAjaxNon200)return 'HTTP_NON_200';
  if(counters.officialAjaxFailed)return 'NETWORK_LOADING_FAILED';
  if(counters.officialAjaxPosts===0)return 'OFFICIAL_POST_UNOBSERVED';
  if(counters.officialAjax200===0)return 'HTTP_RESPONSE_UNOBSERVED';
  if(!singleAjaxExchange(counters,requestCount,matchedCount))return 'HTTP_COMPLETION_UNOBSERVED';
  return rangeObserved?'EXCHANGE_AND_RANGE_OBSERVED':'DOM_RANGE_UNOBSERVED';
}
if (process.argv.includes('--self-test')) {
  assert.equal(parseDevToolsPort('9222\n/devtools/browser/example'),9222);
  assert.equal(parseDevToolsPort('65535\r\n/path'),65535);
  for(const invalid of ['','0','65536','1e3',' 9222','9222.5','-1'])
    assert.equal(parseDevToolsPort(invalid),null);
  const startupState=()=>({polls:0,spawnError:false,exited:false});
  let startup=startupState(), waits=0;
  assert.equal(await pollDevToolsPort(async()=>startup.polls===45?'9222\n/path':'',
    async ms=>{assert.equal(ms,250);waits++;},startup),9222);
  assert.equal(startup.polls,45);
  assert.equal(waits,44);
  startup=startupState();waits=0;
  assert.equal(await pollDevToolsPort(async()=>{throw Error('not ready');},
    async()=>{waits++;},startup),null);
  assert.equal(startup.polls,60);
  assert.equal(waits,59);
  startup=startupState();
  assert.equal(await pollDevToolsPort(async()=>{startup.exited=true;return '9222';},
    async()=>{throw Error('must not wait');},startup),null);
  assert.equal(startup.polls,1);
  startup=startupState();startup.spawnError=true;
  assert.equal(await pollDevToolsPort(async()=>{throw Error('must not read');},
    async()=>{throw Error('must not wait');},startup),null);
  assert.equal(startup.polls,0);
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
  const boundFocus={...focus,controlIdentity:initial.controlIdentity};
  assert.equal(confirmedNativeFocus(initial,[boundFocus,boundFocus,boundFocus]),true);
  assert.equal(confirmedNativeFocus(initial,[boundFocus,boundFocus]),false);
  assert.equal(confirmedNativeFocus(initial,[boundFocus,boundFocus,boundFocus,boundFocus]),false);
  for(const delta of [{report:2},{action:'other'},{nativeButton:false}]) {
    const changed={...boundFocus,focusTarget:{...boundFocus.focusTarget,...delta}};
    assert.equal(confirmedNativeFocus(initial,[changed,changed,changed]),false);
  }
  assert.equal(confirmedNativeFocus(initial,[boundFocus,{...boundFocus,focused:false},boundFocus]),false);
  assert.equal(confirmedNativeFocus(initial,[boundFocus,{...boundFocus,controlIdentity:{report:2,action:next.pagination}},boundFocus]),false);
  assert.equal(confirmedNativeFocus(initial,[boundFocus,{...boundFocus,focusTarget:{...boundFocus.focusTarget,index:1}},boundFocus]),false);
  const counts={sameOriginPosts:1,officialAjaxPosts:1,officialAjax200:1,officialAjaxFinished:1,redirects:0,officialAjaxNon200:0,officialAjaxFailed:0};
  assert.equal(singleAjaxExchange(counts,1,1),true);
  for(const key of Object.keys(counts))assert.equal(singleAjaxExchange({...counts,[key]:counts[key]+1},1,1),false);
  assert.equal(singleAjaxExchange(counts,2,1),false);
  assert.equal(singleAjaxExchange(counts,1,0),false);
  assert.equal(ajaxObservation(counts,1,1,true),'EXCHANGE_AND_RANGE_OBSERVED');
  assert.equal(ajaxObservation(counts,1,1,false),'DOM_RANGE_UNOBSERVED');
  assert.equal(ajaxObservation({...counts,officialAjax200:0,officialAjaxFinished:0},1,0,false),'HTTP_RESPONSE_UNOBSERVED');
  assert.equal(ajaxObservation({...counts,officialAjaxFinished:0},1,0,true),'HTTP_COMPLETION_UNOBSERVED');
  assert.equal(ajaxObservation({...counts,officialAjaxNon200:1},1,0,false),'HTTP_NON_200');
  assert.equal(ajaxObservation({...counts,officialAjaxFailed:1},1,0,false),'NETWORK_LOADING_FAILED');
  assert.equal(ajaxObservation({...counts,officialAjaxPosts:2},2,1,true),'AMBIGUOUS_EXCHANGE');
  assert.equal(ajaxObservation({...counts,redirects:1},1,1,true),'AMBIGUOUS_EXCHANGE');
  assert.equal(ajaxObservation({...counts,officialAjaxPosts:0,officialAjax200:0,officialAjaxFinished:0},0,0,false),'OFFICIAL_POST_UNOBSERVED');
  const href='/ords/repo_bo/r/mysmis-2021/detaliu-apel?p201_cod_apel=PRT%2F1';
  const fixture='<table><tr>'+['Program operațional','Tip apel','Apel','Stare apel','Buget nerambursabil apel','Info'].map(x=>'<th>'+x+'</th>').join('')+'</tr><tr><td>P</td><td>T</td><td>A</td><td>S</td><td>1</td><td><a href="'+href+'">i</a></td></tr></table>';
  const document='<html><body>'+fixture+'</body></html>';
  const nav={frameId:'main',loaderId:'loader'};
  const docMeta={...nav,requestCount:1,requestExact:true,method:'GET',responseCount:1,responseExact:true,status:200,mimeType:'text/html',finishedCount:1,failed:false,redirected:false,cached:false};
  const docs=d=>new Map([['request',d]]);
  assert.equal(initialDocumentId(docs(docMeta),nav),'request');
  for(const delta of [{frameId:'iframe'},{loaderId:'other'},{requestCount:2},{requestExact:false},{method:'POST'},{responseCount:2},{responseExact:false},{status:302},{mimeType:'application/json'},{finishedCount:0},{failed:true},{redirected:true},{cached:true}])
    assert.equal(initialDocumentId(docs({...docMeta,...delta}),nav),null);
  assert.equal(initialDocumentId(new Map([['one',docMeta],['two',docMeta]]),nav),null);
  assert.equal(initialDocumentId(docs(docMeta),{frameId:'main'}),null);
  assert.equal(initialDocumentConcordance(document,fixture,1),true);
  assert.equal(initialDocumentConcordance(fixture,fixture,1),false);
  assert.equal(initialDocumentConcordance(document,fixture.replace('<td>S</td>','<td>X</td>'),1),false);
  assert.equal(initialDocumentConcordance(document,fixture,2),false);
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
  const r1={first:1,last:1,total:5},r2={first:2,last:2,total:5},r3={first:3,last:3,total:5},r4={first:4,last:4,total:5};
  const distinct=n=>fixture.replace(href,href.replace('PRT%2F1','PRT%2F'+n));
  const history=[{range:r1,html:fixture},{range:r2,html:distinct(2)},{range:r3,html:distinct(3)}];
  assert.equal(validDiagnosticHistory(history,r4),true);
  assert.equal(validDiagnosticHistory(history,r3),false);
  assert.equal(validDiagnosticHistory(history.slice(1),r4),false);
  assert.equal(validDiagnosticHistory([history[0],history[2]],r4),false);
  assert.equal(validDiagnosticHistory(history,{...r4,total:6}),false);
  assert.equal(validDiagnosticHistory([{...history[0],html:''}],r2),false);
  assert.equal(validDiagnosticHistory([{...history[0],html:'x'.repeat(2000000)}],r2),false);
  const full=compareDecodedTable(distinct(4),distinct(4),1,null,null,history,r4).cumulativeDuplicateDiagnostic;
  assert.deepEqual(full,{rowCount:4,uniqueIdentityCount:4,mirroredDuplicateRowCount:0,conflictingDuplicateRowCount:0,exactIdentityComplete:true,pageCount:4,crossHistoryIdentityOverlapCount:0});
  assert.equal(compareDecodedTable(fixture,fixture,1,null,null,history,r4).cumulativeDuplicateDiagnostic.mirroredDuplicateRowCount,1);
  const distantConflict=fixture.replace('<td>S</td>','<td>X</td>');
  assert.equal(compareDecodedTable(distantConflict,distantConflict,1,null,null,history,r4).cumulativeDuplicateDiagnostic.exactIdentityComplete,false);
  assert.equal(compareDecodedTable(distinct(4),distinct(4),1,null,null,[history[0],{...history[1],html:'<html></html>'},history[2]],r4).cumulativeDuplicateDiagnostic,undefined);
  assert.equal(compareDecodedTable(distinct(4),distinct(4),1,null,null,history,r3).status,'TABLE_COMPARISON_UNAVAILABLE');
  const accepted={orderedExactRowsMatch:true,twoPageDuplicateDiagnostic:{exactIdentityComplete:true},cumulativeDuplicateDiagnostic:full};
  assert.equal(acceptedTransition(accepted,r4,3,null),true);
  assert.equal(acceptedTransition({...accepted,orderedExactRowsMatch:false},r4,3,null),false);
  assert.equal(acceptedTransition(accepted,r4,2,null),false);
  assert.equal(acceptedTransition({...accepted,cumulativeDuplicateDiagnostic:{...full,pageCount:3,rowCount:3}},r3,2,null),false);
  const completeHistory=[...history,{range:r4,html:distinct(4)}];
  assert.deepEqual(terminalCoverage(completeHistory,r4,full,true),{pageCount:4,observedRows:4,totalRows:5,
    uniqueIdentityCount:4,mirroredDuplicateRowCount:0,conflictingDuplicateRowCount:0,initialPageObservation:'DOM_ONLY',
    decodedAjaxFragmentCount:3,terminalPageStillConcordant:true,sourceRangeExhausted:false,fullInventoryProven:false});
  assert.equal(terminalCoverage(completeHistory,r4,full,true,true).initialPageObservation,'CDP_DECODED_DOCUMENT_CONCORDANT');
  assert.equal(terminalCoverage(completeHistory,r4,full,false),null);
  assert.equal(terminalCoverage(completeHistory,r4,{...full,uniqueIdentityCount:5},true),null);
  assert.equal(terminalCoverage(completeHistory,r4,{...full,conflictingDuplicateRowCount:1},true),null);
  assert.equal(terminalCoverage(completeHistory,r3,full,true),null);
  assert.equal(terminalCoverage([history[0],history[2],completeHistory.at(-1)],r4,full,true),null);
  const cov=terminalCoverage(completeHistory,r4,full,true,true);
  const records=completeHistory.map((p,i)=>({range:p.range,fetchedAt:'2026-11-25T08:00:0'+i+'.000Z',
    method:i?'POST':'GET',endpointClass:i?'SAME_ORIGIN_WWV_FLOW_AJAX':'EXACT_CANONICAL_DOCUMENT',
    httpStatus:200,contentType:'text/html',cdpDecodedBodySha256:sha(p.html),
    decodedBodyBytes:Buffer.byteLength(p.html),representation:'CDP_TEXT_UTF8_REENCODED',orderedExactRowsMatch:true}));
  const bounded=(body,prior)=>compareDecodedTable(body,body,1,null,null,prior,r4).boundedSemanticFingerprints;
  const fingerprints=bounded(distinct(4),history);
  assert.match(fingerprints.identitySetSha256,/^[a-f0-9]{64}$/);
  assert.equal(fingerprints.uniqueIdentityCount,4);
  assert.match(fingerprints.materialSha256,/^[a-f0-9]{64}$/);
  assert.match(fingerprints.operationalSha256,/^[a-f0-9]{64}$/);
  assert.deepEqual(bounded('<html><body>'+distinct(4)+'</body></html>',history),fingerprints);
  // Changes in row order must not change the scoped ID-set hash.
  const reordered=history.map((p,i)=>({...p,html:history[2-i].html}));
  assert.deepEqual(bounded(distinct(4),reordered),fingerprints);
  const materialChange=bounded(distinct(4).replace('<td>S</td>','<td>X</td>'),history);
  assert.notEqual(materialChange.materialSha256,fingerprints.materialSha256);
  assert.equal(materialChange.operationalSha256,fingerprints.operationalSha256);
  assert.equal(materialChange.identitySetSha256,fingerprints.identitySetSha256);
  const membershipChange=bounded(distinct(5),history);
  assert.equal(membershipChange.uniqueIdentityCount,fingerprints.uniqueIdentityCount);
  assert.notEqual(membershipChange.identitySetSha256,fingerprints.identitySetSha256);
  const withCounter=(html,value)=>html.replace('<th>Info</th>','<th>Nr contracte</th><th>Info</th>').replace('<td><a href=','<td>'+value+'</td><td><a href=');
  const operationalChange=bounded(withCounter(distinct(4),'2'),history);
  assert.equal(operationalChange.materialSha256,fingerprints.materialSha256);
  assert.notEqual(operationalChange.operationalSha256,fingerprints.operationalSha256);
  assert.equal(operationalChange.identitySetSha256,fingerprints.identitySetSha256);
  assert.equal(bounded(distantConflict,history),undefined);
  const manifest=diagnosticManifest(records,cov,'123','1',fingerprints);
  assert.ok(manifest);
  const {manifestSha256,...manifestBody}=manifest;
  assert.equal(manifestSha256,sha(JSON.stringify(manifestBody)));
  assert.deepEqual(diagnosticManifest(records,cov,'123','1',fingerprints),manifest);
  assert.notEqual(diagnosticManifest(records,cov,'123','2',fingerprints).manifestSha256,manifestSha256);
  assert.equal(manifest.immutableReceipt,false);
  assert.equal(manifest.openCallAuthorized,false);
  assert.equal(manifest.pages.length,4);
  assert.equal(diagnosticManifest(records.slice(1),cov,'123','1',fingerprints),null);
  assert.equal(diagnosticManifest([records[0],records[2],records[1],records[3]],cov,'123','1',fingerprints),null);
  const bad=(i,patch)=>records.map((p,j)=>i===j?{...p,...patch}:p);
  for(const patch of [{method:'GET'},{endpointClass:'OTHER'},{httpStatus:302},{contentType:'text/plain'},
    {cdpDecodedBodySha256:records[0].cdpDecodedBodySha256},{decodedBodyBytes:2000000},
    {representation:'RAW'},{orderedExactRowsMatch:false},{fetchedAt:'2026-11-25T07:59:00.000Z'},
    {fetchedAt:'2026-02-30T08:00:00.000Z'}])
    assert.equal(diagnosticManifest(bad(1,patch),cov,'123','1',fingerprints),null);
  assert.equal(diagnosticManifest(records,{...cov,observedRows:99},'123','1',fingerprints),null);
  assert.equal(diagnosticManifest(records,{...cov,fullInventoryProven:true},'123','1',fingerprints),null);
  assert.equal(diagnosticManifest(records,cov,'123','0',fingerprints),null);
  assert.equal(diagnosticManifest(bad(1,{sessionToken:'do-not-emit'}),cov,'123','1',fingerprints).manifestSha256,manifestSha256);
  assert.equal(diagnosticManifest(records,cov,'123','1',null),null);
  assert.equal(diagnosticManifest(records,cov,'123','1',{...fingerprints,materialSha256:'invalid'}),null);
  assert.notEqual(diagnosticManifest(records,cov,'123','1',materialChange).manifestSha256,manifestSha256);
  assert.equal(manifest.boundedSemanticFingerprints.scope,'OBSERVED_EXACT_ID_SET_ONLY');
  assert.equal(manifest.boundedSemanticFingerprints.identitySetSha256,fingerprints.identitySetSha256);
  assert.equal(diagnosticManifest(records,cov,'123','1',{...fingerprints,identitySetSha256:'invalid'}),null);
  assert.equal(diagnosticManifest(records,cov,'123','1',{...fingerprints,uniqueIdentityCount:5}),null);
  assert.notEqual(diagnosticManifest(records,cov,'123','1',membershipChange).manifestSha256,manifestSha256);
  // Expanded bounded coverage: six transitions, seven pages; no full inventory claim.
  const seven=Array.from({length:7},(_,i)=>({range:{first:i+1,last:i+1,total:8},html:distinct(i+1)}));
  const seventh=seven.at(-1), six=seven.slice(0,-1);
  const sevenResult=compareDecodedTable(seventh.html,seventh.html,1,null,null,six,seventh.range);
  assert.equal(sevenResult.cumulativeDuplicateDiagnostic.uniqueIdentityCount,7);
  const sevenCoverage=terminalCoverage(seven,seventh.range,sevenResult.cumulativeDuplicateDiagnostic,true,true);
  assert.equal(sevenCoverage.observedRows,7);
  assert.equal(sevenCoverage.fullInventoryProven,false);
  const sevenRecords=seven.map((p,i)=>({...records[0],range:p.range,fetchedAt:'2026-11-25T08:00:0'+i+'.000Z',method:i?'POST':'GET',endpointClass:i?'SAME_ORIGIN_WWV_FLOW_AJAX':'EXACT_CANONICAL_DOCUMENT',cdpDecodedBodySha256:sha(p.html),decodedBodyBytes:Buffer.byteLength(p.html)}));
  assert.equal(diagnosticManifest(sevenRecords,sevenCoverage,'123','1',sevenResult.boundedSemanticFingerprints).pages.length,7);
  assert.equal(validDiagnosticHistory(seven,{first:8,last:8,total:8}),false);
  console.log('PASS: public UI protocol diagnostic range, endpoint, native-control equivalence, stable hit, native focus, decoded table, prior-page, cumulative and terminal concordance guards');
  process.exit(0);
}
let dir, chrome, ws;
const base = {schema:'MYSMIS_UI_PROTOCOL_DISCOVERY_V1',canonicalUrl:URL0,
  runId:process.env.GITHUB_RUN_ID || 'local',parserVersion:'MYSMIS_UI_PROTOCOL_DISCOVERY_V12',
  sourceFamily:'ROMANIA_MIPE_MYSMIS',programmeFamily:'ROMANIA_MULTI_PROGRAMME',
  authorityClass:'T1_OFFICIAL_MYSMIS_REPORTING',observationState:'PROTOCOL_DISCOVERY_ONLY',
  rawPersisted:false,immutableReceipt:false,materialFactUse:false,publishAuthorized:false,
  openCallAuthorized:false,deadlineAuthorized:false,budgetAuthorized:false,eligibilityAuthorized:false,
  publicationEffect:'NONE'};
let status='NOT_STARTED', activationAttempted=null, activeTransition=null;
const browserStartup={polls:0,maxPolls:STARTUP_POLLS,intervalMs:STARTUP_INTERVAL_MS,elapsedMs:null,spawnError:false,exited:false,portReady:false};
const counters={sameOriginPosts:0,officialAjaxPosts:0,officialAjax200:0,officialAjaxFinished:0,redirects:0,officialAjaxNon200:0,officialAjaxFailed:0};
let exchangeObservation=null, rangeObserved=false;
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
  const startupStarted=performance.now();
  const port=await pollDevToolsPort(()=>readFile(join(dir,'DevToolsActivePort'),'utf8'),sleep,browserStartup);
  browserStartup.elapsedMs=Math.round(performance.now()-startupStarted);
  browserStartup.portReady=!!port;
  if(!port||browserStartup.spawnError||browserStartup.exited) throw new Error('browser unavailable');
  status='DEVTOOLS_PORT_READY';
  console.log(JSON.stringify({...base,status:'UI_BROWSER_STARTUP_ONLY',browserStartup,fetchedAt:new Date().toISOString(),paginationProtocolConfirmed:false}));
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
  const documents=new Map();let documentCapture=true,documentOverflow=false;
  ws.addEventListener('message',e=>{
    try {
      const m=JSON.parse(e.data);
      if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error('CDP error')):p.resolve(m.result);}return;}
      const p=m.params||{};
      if(documentCapture){
        if(m.method==='Network.requestWillBeSent'&&p.type==='Document'){
          if(!documents.has(p.requestId)&&documents.size>=16)documentOverflow=true;
          else {
            const d=documents.get(p.requestId)||{requestCount:0,responseCount:0,finishedCount:0};
            Object.assign(d,{frameId:p.frameId,loaderId:p.loaderId,requestExact:p.request?.url===URL0,method:p.request?.method,
              requestCount:d.requestCount+1,redirected:!!d.redirected||!!p.redirectResponse});
            documents.set(p.requestId,d);
          }
        }
        const d=documents.get(p.requestId);
        if(d&&m.method==='Network.responseReceived'){
          d.responseCount++;
          Object.assign(d,{responseExact:p.response?.url===URL0,status:p.response?.status,
            mimeType:String(p.response?.mimeType||'').split(';')[0].toLowerCase(),
            cached:!!d.cached||!!p.response?.fromDiskCache||!!p.response?.fromServiceWorker||!!p.response?.fromPrefetchCache});
        }
        if(d&&m.method==='Network.requestServedFromCache')d.cached=true;
        if(d&&m.method==='Network.loadingFinished')d.finishedCount++;
        if(d&&m.method==='Network.loadingFailed')d.failed=true;
      }
      if(!capture)return;
      if(m.method==='Network.requestWillBeSent' && p.redirectResponse && (requests.has(p.requestId)||officialAjax(p.request?.url)))counters.redirects++;
      if(m.method==='Network.requestWillBeSent' && p.request?.method==='POST') {
        try {if(new URL(p.request.url).origin===origin)counters.sameOriginPosts++;}catch{}
        if(officialAjax(p.request.url)){requests.set(p.requestId,true);counters.officialAjaxPosts++;}
      }
      if(m.method==='Network.responseReceived' && requests.has(p.requestId) && officialAjax(p.response?.url)){
        if(p.response.status===200){responses.set(p.requestId,{mimeType:String(p.response.mimeType||'').split(';')[0]});counters.officialAjax200++;}
        else counters.officialAjaxNon200++;
      }
      if(m.method==='Network.loadingFailed' && requests.has(p.requestId))counters.officialAjaxFailed++;
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
  // Bounded repeatability experiment: each transition requires exact ordered
  // concordance and no conflicting duplicates across all observed pages. Each exchange
  // gets its own counters; no request values, HTML, or identities are emitted.
  let reportOrdinal=null, initialDom=null, initialRange=first, previousBody=null;
  const history=[],diagnosticRecords=[];
  for(let transition=1;transition<=MAX_TRANSITIONS && first.last<first.total;transition++){
  capture=false;
  requests.clear();responses.clear();finished.clear();
  for(const key of Object.keys(counters))counters[key]=0;
   activationAttempted=null;activeTransition=transition;exchangeObservation=null;rangeObserved=false;
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
  if(transition===1){
    status='INITIAL_DOCUMENT_CONCORDANCE';
    const documentId=documentOverflow?null:initialDocumentId(documents,navigation);
    if(!documentId)throw new Error('initial document transport unverified');
    const decoded=await cdp('Network.getResponseBody',{requestId:documentId});
    if(typeof decoded?.body!=='string'||typeof decoded.base64Encoded!=='boolean')throw new Error('initial body unavailable');
    const documentBytes=decoded.base64Encoded?Buffer.from(decoded.body,'base64'):Buffer.from(decoded.body,'utf8');
    const documentText=new TextDecoder('utf-8',{fatal:true}).decode(documentBytes);
    if(!documentBytes.length||documentBytes.length>=2000000||
      !initialDocumentConcordance(documentText,firstDom,first.last-first.first+1)||
      documentOverflow||initialDocumentId(documents,navigation)!==documentId)
      throw new Error('initial document semantic guard failed');
    documentCapture=false;documents.clear();
    const initialRecord={range:first,fetchedAt:new Date().toISOString(),method:'GET',
      endpointClass:'EXACT_CANONICAL_DOCUMENT',httpStatus:200,contentType:'text/html',
      cdpDecodedBodySha256:sha(documentBytes),decodedBodyBytes:documentBytes.length,
      representation:decoded.base64Encoded?'CDP_BASE64_DECODED_ENTITY':'CDP_TEXT_UTF8_REENCODED',
      orderedExactRowsMatch:true};
    diagnosticRecords.push(initialRecord);
    console.log(JSON.stringify({...base,...initialRecord,status:'UI_INITIAL_DECODED_DOCUMENT_CONCORDANT',
      firstRange:first,rawByteIdentityProven:false,paginationProtocolConfirmed:false}));
    initialDom=firstDom;history.push({range:first,html:firstDom});
  }
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
  // Controlled diagnostic: only the previously observed successful native
   // keyboard path. Mouse hit geometry remains observational; do not send
   // mouse events, nor retry after any ambiguous exchange. The observed
   // double POST after a stable hit does not establish its cause.
   if(hitPoll.ambiguous||!after?.unambiguous)throw new Error('ambiguous next button');
   const f0=await inspectTarget(false,true);
   await sleep(150);
   const f1=await inspectTarget(false);
   await sleep(150);
   const f2=await inspectTarget(false);
   const focusConfirmed=confirmedNativeFocus(before,[f0,f1,f2]);
   console.log(JSON.stringify({...base,status:'UI_NATIVE_FOCUS_ONLY',transition,fetchedAt:new Date().toISOString(),
     focusedSamples:[f0,f1,f2].filter(f=>f?.focused).length,focusConfirmed,paginationProtocolConfirmed:false}));
   if(!focusConfirmed)throw new Error('no stable native focused next button');
   const activation='NATIVE_KEYBOARD_ENTER';
   status='NEXT_TARGET_CONFIRMED';
   activationAttempted=activation;
   activeTransition=transition;
   capture=true;
   await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13,text:'\r'});
   await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
   status='NEXT_CLICKED';
  let second;
  // Wait passively for both the current DOM range and the completed exchange.
  // No repeated activation, no enlarged polling budget, no status promotion.
  for(let i=0;i<80;i++){
    const s=await snapshot();const b=range(s?.text);
    rangeObserved=s?.url===URL0&&nextRange(first,b);
    exchangeObservation=ajaxObservation(counters,requests.size,[...responses.keys()].filter(k=>finished.has(k)).length,rangeObserved);
    if(exchangeObservation==='EXCHANGE_AND_RANGE_OBSERVED'){second=b;break;}
    if(['AMBIGUOUS_EXCHANGE','HTTP_NON_200','NETWORK_LOADING_FAILED'].includes(exchangeObservation))break;
    await sleep(250);
  }
  if(!second)throw new Error('completed official exchange and contiguous next range not jointly observed');
  status='NEXT_RANGE_CONFIRMED';
  await sleep(500);
  const ids=[...responses.keys()].filter(k=>finished.has(k));
  if(!singleAjaxExchange(counters,requests.size,ids.length))throw new Error('ambiguous official ajax exchange');
  const response=await cdp('Network.getResponseBody',{requestId:ids[0]});
  if(typeof response?.body!=='string'||typeof response.base64Encoded!=='boolean')throw new Error('response body unavailable');
  const bytes=response.base64Encoded?Buffer.from(response.body,'base64'):Buffer.from(response.body,'utf8');
  if(!bytes.length||bytes.length>=2000000)throw new Error('response size outside diagnostic bound');
  const decodedText=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
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
    ? compareDecodedTable(decodedText,rendered.html,second.last-second.first+1,firstDom,first.last-first.first+1,history,second)
    : {status:'TABLE_COMPARISON_UNAVAILABLE'};
  if(!singleAjaxExchange(counters,requests.size,[...responses.keys()].filter(k=>finished.has(k)).length))throw new Error('ambiguous late official ajax exchange');
  // Also compare page 3 against page 1, not merely its immediate predecessor.
  const nonAdjacent=transition===2&&concordance.orderedExactRowsMatch
    ? compareDecodedTable(decodedText,rendered.html,second.last-second.first+1,
        initialDom,initialRange.last-initialRange.first+1) : null;
  if(!singleAjaxExchange(counters,requests.size,[...responses.keys()].filter(k=>finished.has(k)).length))throw new Error('ambiguous late official ajax exchange');
  if(!acceptedTransition(concordance,second,transition,nonAdjacent))
    throw new Error('transition semantic guard failed');
  const nextRecord={range:second,fetchedAt:new Date().toISOString(),method:'POST',
    endpointClass:'SAME_ORIGIN_WWV_FLOW_AJAX',httpStatus:200,contentType:mime,
    cdpDecodedBodySha256:sha(bytes),decodedBodyBytes:bytes.length,
    representation:response.base64Encoded?'CDP_BASE64_DECODED_ENTITY':'CDP_TEXT_UTF8_REENCODED',
    orderedExactRowsMatch:true};
  diagnosticRecords.push(nextRecord);
  console.log(JSON.stringify({...base,...nextRecord,status:'UI_NEXT_RANGE_AND_OFFICIAL_AJAX_OBSERVED',transition,counters,
    firstRange:first,secondRange:second,activation,
    renderedTableScope:{reportCount:rendered?.reportCount??0,tableCount:rendered?.tableCount??0,dataTableCount:rendered?.dataTableCount??0},
    decodedTableConcordance:concordance,
    nonAdjacentDuplicateDiagnostic:nonAdjacent?.twoPageDuplicateDiagnostic??null,
    rawByteIdentityProven:false,paginationProtocolConfirmed:false}));
  // Retain only the bounded decoded fragment for the next observation.
  previousBody=decodedText;
  history.push({range:second,html:previousBody});
  if(transition===MAX_TRANSITIONS||second.last===second.total){
    status='TERMINAL_PAGE_REOBSERVATION';
    const terminal=await observeReportTable(before.controlIdentity.report);
    const stable=terminal?.url===URL0&&JSON.stringify(range(terminal?.text))===JSON.stringify(second)&&
      previousPageConcordance(previousBody,terminal.html,second.last-second.first+1);
    const coverage=terminalCoverage(history,second,concordance.cumulativeDuplicateDiagnostic,stable,true);
    if(!coverage||!singleAjaxExchange(counters,requests.size,[...responses.keys()].filter(k=>finished.has(k)).length))
      throw new Error('terminal coverage or exchange unverified');
    const manifest=diagnosticManifest(diagnosticRecords,coverage,base.runId,process.env.GITHUB_RUN_ATTEMPT||'1',concordance.boundedSemanticFingerprints);
    if(!manifest)throw new Error('ordered diagnostic manifest unverified');
    console.log(JSON.stringify({...base,status:'UI_BOUNDED_DIAGNOSTIC_COMPLETE',fetchedAt:new Date().toISOString(),
      coverage,diagnosticManifest:manifest,rawByteIdentityProven:false,paginationProtocolConfirmed:false}));
  }
  capture=false;
  first=second;
  }
} catch(e) {
  // No exception messages or arbitrary server values: could contain session data.
  console.log(JSON.stringify({...base,status:'UI_PROTOCOL_DIAGNOSTIC_FAIL_CLOSED',stage:status,counters,browserStartup,activationAttempted,activeTransition,exchangeObservation,
    fetchedAt:new Date().toISOString(),paginationProtocolConfirmed:false}));
  process.exitCode=2;
} finally {
  try{ws?.close();}catch{}
  try{chrome?.kill('SIGKILL');}catch{}
  if(dir)await rm(dir,{recursive:true,force:true,maxRetries:3}).catch(()=>{});
}

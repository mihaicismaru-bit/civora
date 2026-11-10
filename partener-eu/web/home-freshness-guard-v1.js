(()=>{
'use strict';
const P=window.PARTENER_DECISION_PRODUCTS;
if(!P||!Array.isArray(P.dossiers)||!P.home)return;

const PREPARE_STATUSES=new Set(['EXPECTED','ANNOUNCED','PUBLIC_CONSULTATION','REVIEW','PREPARE_NOW','UPCOMING']);
const PUBLICATION_OPEN_STATES=new Set(['PUBLISHABLE']);
// Publication evidence can become stale, but wall-clock time cannot. Never
// replay a historical generation/ingestion timestamp as the current date:
// expired OPEN must fail closed even when upstream refreshes are blocked.
const clock=new Date(Date.now());
const currentYear=clock.getUTCFullYear();
const currentYearStart=Date.UTC(currentYear,0,1);
const byId=new Map(P.dossiers.map(d=>[String(d?.id||''),d]));

// Official Romanian local deadlines need their actual clock time, not UTC EOD.
function bucharestLocalMs(year,month,day,hour,minute,second=0,millis=0){
  const normalized=new Date(Date.UTC(year,month,day,hour,minute,second,millis));
  if(normalized.getUTCFullYear()!==year||normalized.getUTCMonth()!==month||normalized.getUTCDate()!==day||normalized.getUTCHours()!==hour||normalized.getUTCMinutes()!==minute||normalized.getUTCSeconds()!==second)return null;
  const lastSunday=(m)=>{const last=new Date(Date.UTC(year,m+1,0));return last.getUTCDate()-last.getUTCDay();};
  const march=lastSunday(2),october=lastSunday(9);
  // 03:xx local is absent at the March DST switch and ambiguous in October.
  // Without an explicit offset neither can authorize a current OPEN state.
  if(hour===3&&((month===2&&day===march)||(month===9&&day===october)))return null;
  const summer=(month>2&&month<9)||(month===2&&(day>march||(day===march&&hour>=4)))||(month===9&&(day<october||(day===october&&hour<3)));
  return normalized.getTime()-(summer?3:2)*60*60*1000;
}

function toTimestamp(value){
  if(value==null||value==='')return null;
  if(typeof value==='number')return Number.isFinite(value)?value:null;
  if(typeof value==='object'){
    for(const key of ['closes_at','closes','deadline_at','close','end','submission_end','opens_at','opens','open','start','publishedAt','published_at']){
      if(value[key]!=null){const nested=toTimestamp(value[key]);if(nested!=null)return nested;}
    }
    return null;
  }
  const raw=String(value).trim();
  if(!raw||/neconfirmat|necunoscut|unknown/i.test(raw))return null;
  // AFIR's official counters use Romanian DD.MM.YYYY HH:mm:ss (or
  // DD/MM/YYYY). Date.parse interprets these inconsistently as US/UTC dates,
  // potentially keeping a component OPEN past its local midnight cutoff.
  const dmyLocal=raw.match(/^(\d{1,2})[./](\d{1,2})[./](20\d{2})(?:\s*,?\s*(?:(?:la\s+)?ora\s*)?(\d{1,2})[:.](\d{2})(?::(\d{2}))?)?$/i);
  if(dmyLocal){
    const [,day,month,year,hour,minute,second]=dmyLocal;
    return bucharestLocalMs(Number(year),Number(month)-1,Number(day),
      hour==null?23:Number(hour),minute==null?59:Number(minute),second==null?59:Number(second),
      hour==null?999:0);
  }
  // Never fall back to the host engine's lenient date parser when an
  // official-looking Romanian date has an unsupported/ambiguous clock.
  if(/^\d{1,2}[./]\d{1,2}[./]20\d{2}/.test(raw))return null;
  const iso=Date.parse(raw);
  if(!Number.isNaN(iso))return iso;
  const ymd=raw.match(/\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b/);
  if(ymd)return Date.UTC(Number(ymd[1]),Number(ymd[2])-1,Number(ymd[3]),23,59,59,999);
  const dmy=raw.match(/\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b/);
  if(dmy)return Date.UTC(Number(dmy[3]),Number(dmy[2])-1,Number(dmy[1]),23,59,59,999);
  const folded=raw.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  const months={ianuarie:0,februarie:1,martie:2,aprilie:3,mai:4,iunie:5,iulie:6,august:7,septembrie:8,octombrie:9,noiembrie:10,decembrie:11};
  const ro=folded.match(/\b(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})\b/);
  if(ro){
    const year=Number(ro[3]),month=months[ro[2]],day=Number(ro[1]);
    const tail=folded.slice(ro.index+ro[0].length);
    const timed=tail.match(/^\s*,?\s*(?:la\s+)?(?:ora\s+)?(\d{1,2})[:.](\d{2})(?::(\d{2}))?/);
    if(timed)return bucharestLocalMs(year,month,day,Number(timed[1]),Number(timed[2]),Number(timed[3]||0));
    // An unparseable explicit clock cannot silently become 23:59:59.
    if(/^\s*,?\s*(?:(?:la\s+)?ora\b|(?:la\s+)?\d{1,2}[:.])/.test(tail))return null;
    return bucharestLocalMs(year,month,day,23,59,59,999);
  }
  return null;
}

function explicitYears(d){
  const text=[d?.title,d?.standfirst,d?.summary,d?.decisionAction].filter(Boolean).join(' ');
  return [...text.matchAll(/\b(20\d{2})\b/g)].map(m=>Number(m[1]));
}

function lifecycleTimestamps(d){
  const values=[];
  for(const key of ['openFrom','opensAt','openAt','deadline','closesAt','closeAt','consultationDeadline','publishedAt','publicationDate']){
    if(d?.[key]!=null)values.push(d[key]);
  }
  for(const fact of d?.quickFacts||[]){
    const label=String(fact?.label||'').toLowerCase();
    if(/termen|deschidere|depunere|consult|publicare|calendar/.test(label))values.push(fact?.value);
  }
  return values.map(toTimestamp).filter(v=>v!=null&&Number.isFinite(v));
}

function isCurrentPrepareDossier(d){
  if(!d||!PREPARE_STATUSES.has(String(d.status||'').toUpperCase()))return false;
  const dates=lifecycleTimestamps(d);
  if(dates.some(ts=>ts>=currentYearStart))return true;
  const years=explicitYears(d);
  if(years.some(year=>year>=currentYear))return true;
  return false;
}

function confirmedFact(d,label){
  return (d?.quickFacts||[]).find(f=>String(f?.label||'').toLowerCase()===label&&String(f?.confidence||'').toUpperCase()==='CONFIRMED');
}

function closeTimestamp(d){
  const values=[];
  for(const key of ['deadline','closesAt','closeAt'])if(d?.[key]!=null)values.push(d[key]);
  const deadline=confirmedFact(d,'termen');
  if(deadline?.value!=null)values.push(deadline.value);
  // Every present cutoff must parse and reconcile. Silently dropping an
  // unparseable (potentially newer) deadline would authorize a false OPEN.
  const timestamps=values.map(toTimestamp);
  return timestamps.length&&timestamps.every(ts=>ts!=null&&Number.isFinite(ts)&&ts===timestamps[0])?timestamps[0]:null;
}

function currentOpenState(d){
  if(!d||String(d.status||'').toUpperCase()!=='OPEN')return null;
  if(!PUBLICATION_OPEN_STATES.has(String(d.publicationState||'').toUpperCase()))return 'REVIEW';
  const status=confirmedFact(d,'status');
  if(String(status?.value||'').trim().toUpperCase()!=='OPEN'||!confirmedFact(d,'termen'))return 'REVIEW';
  const closesAt=closeTimestamp(d);
  if(closesAt==null)return 'REVIEW';
  // Passage of time alone is not authority to assert the official CLOSED state.
  return closesAt<=clock.getTime()?'REVIEW':'OPEN';
}

const originalOpenIds=Array.isArray(P.home.openDossierIds)?P.home.openDossierIds.map(String):[];
const currentOpenIds=P.dossiers.filter(d=>currentOpenState(d)==='OPEN').map(d=>String(d.id));
const currentOpenSet=new Set(currentOpenIds);
const removedOpenIds=originalOpenIds.filter(id=>!currentOpenSet.has(id));
P.home.openDossierIds=originalOpenIds.filter(id=>currentOpenSet.has(id));
const originalPrepareIds=Array.isArray(P.home.prepareDossierIds)?P.home.prepareDossierIds.map(String):[];
const currentPrepareIds=originalPrepareIds.filter(id=>isCurrentPrepareDossier(byId.get(id)));
const removedIds=originalPrepareIds.filter(id=>!currentPrepareIds.includes(id));
P.home.prepareDossierIds=currentPrepareIds;

const currentPrepareCount=P.dossiers.filter(isCurrentPrepareDossier).length;
if(P.summary&&typeof P.summary==='object'){
  P.summary.openCount=currentOpenIds.length;
  P.summary.prepareCount=currentPrepareCount;
}

const dossierStatusOverrides=Object.fromEntries(P.dossiers.map(d=>[String(d?.id||''),currentOpenState(d)]).filter(([,state])=>state&&state!=='OPEN'));

P.freshnessGuard={
  version:'home-freshness-guard-v1.3',
  state:removedIds.length||removedOpenIds.length?'DEGRADED':'PASS',
  asOf:clock.toISOString(),
  currentYear,
  currentOpenDossierIds:currentOpenIds,
  removedOpenDossierIds:removedOpenIds,
  removedPrepareDossierIds:removedIds,
  dossierStatusOverrides,
  rule:'Homepage OPEN requires publishable state plus confirmed status and unexpired deadline; PREPARE requires current/future lifecycle evidence. Ambiguous records fail closed.'
};
})();

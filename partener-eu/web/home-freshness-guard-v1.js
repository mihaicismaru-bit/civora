(()=>{
'use strict';
const P=window.PARTENER_DECISION_PRODUCTS;
if(!P||!Array.isArray(P.dossiers)||!P.home)return;

const PREPARE_STATUSES=new Set(['EXPECTED','ANNOUNCED','PUBLIC_CONSULTATION','REVIEW','PREPARE_NOW','UPCOMING']);
const generatedAt=new Date(P.generatedAt||'');
const clock=Number.isNaN(generatedAt.getTime())?new Date():generatedAt;
const currentYear=clock.getUTCFullYear();
const currentYearStart=Date.UTC(currentYear,0,1);
const byId=new Map(P.dossiers.map(d=>[String(d?.id||''),d]));

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
  const iso=Date.parse(raw);
  if(!Number.isNaN(iso))return iso;
  const ymd=raw.match(/\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b/);
  if(ymd)return Date.UTC(Number(ymd[1]),Number(ymd[2])-1,Number(ymd[3]));
  const dmy=raw.match(/\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b/);
  if(dmy)return Date.UTC(Number(dmy[3]),Number(dmy[2])-1,Number(dmy[1]));
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

const originalPrepareIds=Array.isArray(P.home.prepareDossierIds)?P.home.prepareDossierIds.map(String):[];
const currentPrepareIds=originalPrepareIds.filter(id=>isCurrentPrepareDossier(byId.get(id)));
const removedIds=originalPrepareIds.filter(id=>!currentPrepareIds.includes(id));
P.home.prepareDossierIds=currentPrepareIds;

const currentPrepareCount=P.dossiers.filter(isCurrentPrepareDossier).length;
if(P.summary&&typeof P.summary==='object')P.summary.prepareCount=currentPrepareCount;

P.freshnessGuard={
  version:'home-freshness-guard-v1',
  state:removedIds.length?'DEGRADED':'PASS',
  asOf:P.generatedAt||clock.toISOString(),
  currentYear,
  removedPrepareDossierIds:removedIds,
  rule:'Homepage PREPARE requires lifecycle evidence in the current or a future year; ambiguous records fail closed.'
};
})();

(()=>{
const D=window.PARTENER_DATA;
if(!D||!Array.isArray(D.calls)||!Array.isArray(D.mipeNews))return;
const ids=[];
for(const n of D.mipeNews.slice(0,60)){
  const id='mipe-news-'+String(n.id||'').replace(/[^a-z0-9-]/gi,'-').toLowerCase();
  const u=String(n.url||'');
  const official=/^https:\/\/(?:www\.)?(?:mfe\.gov\.ro|fonduri-ue\.gov\.ro|fonduri-ue\.ro|oportunitati-ue\.gov\.ro)\//i.test(u)||/^https:\/\/reporting\.mysmis2021\.gov\.ro\//i.test(u);
  if(!official)continue;
  if(D.calls.some(c=>c.id===id))continue;
  const explicitOpen=n.kind==='CALL_OPENED';
  const docs=Array.isArray(n.documents)?n.documents:[];
  const c={
    id,
    newsOnly:true,
    programme:`MIPE / ${n.tag||'MIPE'}`,
    code:'MIPE OFFICIAL UPDATE',
    title:n.title||'Actualizare MIPE',
    status:explicitOpen?'OPEN':'NEWS',
    category:'Funding News',
    region:'România',
    applicant:[],applicantKeys:[],objectiveKeys:[],
    open:explicitOpen?(n.dateLabel||'Confirmat de MIPE'):'—',
    close:'—',budget:'—',grant:'—',cofinancing:'—',
    summary:n.summary||'Actualizare publicată pe o proprietate web oficială MIPE.',
    eligibility:['Verifică ghidul/apelul oficial înainte de orice decizie de eligibilitate.'],
    activities:['Actualizare informativă MIPE.'],costs:[],
    documents:docs.map(d=>d.name||d.url).filter(Boolean),scoring:[],indicators:[],
    risks:['Știrea nu modifică automat statusul unui apel canonic fără reconciliere cu sursa specifică a apelului.'],
    sourceFacts:[{label:`MIPE — ${n.title||'actualizare oficială'}`,url:n.url,tier:n.tier||'T1',transport:n.retrievalTransport||'direct'}],
    changes:[{date:n.dateLabel||'Data neconfirmată',kind:n.kind||'OFFICIAL_UPDATE',before:'—',after:n.summary||'Actualizare oficială MIPE'}]
  };
  D.calls.push(c);ids.push(id);
}
D.__mipeNewsPseudoIds=ids;
})();

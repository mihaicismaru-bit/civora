(()=>{
const D=window.PARTENER_DATA;
if(!D||!Array.isArray(D.calls))return;
const genericTitle=/ministerul investi(?:ți|t)iilor și proiectelor europene.*bine a(?:ți|ti) venit|bine a(?:ți|ti) venit pe site-ul ministerului/i;
const navigationSummary=/search\s+acas(?:ă|a)\s+minister\s+despre\s+minister|politica de coeziune 2028-2034.*organizare.*carier(?:ă|a)/i;
const listingUrl=/[?&]display=(?:cards|table)(?:&|$)|\/page\/\d+\/?(?:\?|$)/i;
const rejected=[];
D.calls=D.calls.filter(call=>{
  if(!call?.newsOnly||!String(call.id||'').startsWith('mipe-news-'))return true;
  const title=String(call.title||'').trim();
  const summary=String(call.summary||'').trim();
  const url=String(call.sourceFacts?.[0]?.url||'');
  const valid=title.length>=12&&!genericTitle.test(title)&&summary.length>=70&&!navigationSummary.test(summary)&&!listingUrl.test(url);
  if(!valid)rejected.push({id:call.id,title,url});
  return valid;
});
D.__mipeNewsQualityRejected=rejected;
})();

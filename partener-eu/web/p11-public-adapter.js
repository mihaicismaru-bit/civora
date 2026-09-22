(()=>{
  'use strict';
  const D=window.PARTENER_DATA,P=window.PARTENER_P11;
  if(!D||!Array.isArray(D.calls)||!P||!Array.isArray(P.opportunities))return;
  const aliases={'PEO-STEP-LLL-ADULTI-2026':'peo-step-lll-adulti'};
  const byId=new Map(D.calls.map(call=>[call.id,call]));
  const unknown=['Informația materială este în verificare documentară.'];
  const textValue=value=>{
    if(value===null||value===undefined)return null;
    if(typeof value==='string'||typeof value==='number')return String(value);
    return null;
  };
  const deadlineValue=value=>{
    if(!value)return null;
    if(typeof value==='string')return value;
    return value.closes||value.close||value.deadline_at||null;
  };
  const roMonths={ianuarie:0,februarie:1,martie:2,aprilie:3,mai:4,iunie:5,iulie:6,august:7,septembrie:8,octombrie:9,noiembrie:10,decembrie:11};
  const deadlineTimestamp=value=>{
    if(!value)return NaN;
    const direct=Date.parse(value);
    if(Number.isFinite(direct))return direct;
    const text=String(value).toLowerCase().replace(/\s+/g,' ').trim();
    const match=text.match(/(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})(?:[^0-9]+(\d{1,2}):(\d{2}))?/i);
    if(!match)return NaN;
    return new Date(Number(match[3]),roMonths[match[2]],Number(match[1]),Number(match[4]||23),Number(match[5]||59),59).getTime();
  };
  const hasCurrentVerifiedOpen=call=>{
    if(call.status!=='OPEN')return false;
    const verified=call.p11VerifiedFactClasses||[];
    if(!verified.includes('status')||!verified.includes('deadline'))return false;
    const deadline=deadlineTimestamp(call.close);
    return Number.isFinite(deadline)&&deadline>=Date.now();
  };
  for(const item of P.opportunities){
    const uiId=aliases[item.id]||item.id;
    let call=byId.get(uiId);
    if(!call){
      call={
        id:uiId,programme:item.programme||'Program de finanțare',code:item.code||'—',title:item.title,
        status:'DISCOVERED',category:'În verificare',region:'România',applicant:[],applicantKeys:[],objectiveKeys:[],
        open:'Neconfirmat',close:'Neconfirmat',budget:'În verificare',grant:'În verificare',cofinancing:'În verificare',
        summary:'Oportunitate oficială identificată și aflată în verificare documentară. Nu este prezentată ca apel deschis.',
        eligibility:[...unknown],activities:[...unknown],costs:[...unknown],documents:[...unknown],scoring:[...unknown],indicators:[...unknown],risks:['Nu lua o decizie de depunere înainte de confirmarea statutului și a ghidului aplicabil.'],sourceFacts:[],changes:[]
      };
      D.calls.push(call);byId.set(uiId,call);
    }
    call.p11CanonicalId=item.id;
    call.p11PublicationState=item.publicationState;
    call.p11VerifiedFactClasses=item.verifiedFactClasses||[];
    call.p11VerificationEvidence=item.verificationEvidence||[];
    call.p11VerificationSourceCoverage=item.verificationSourceCoverage||null;
    call.sourceFacts=call.p11VerificationEvidence.map(evidence=>({
      label:`Evidență verificată ${evidence.sourceHost||'sursă oficială'} pentru ${(evidence.supportedFactClasses||[]).join(', ')} · observată ${String(evidence.observedAt||'necunoscut').slice(0,10)}`,
      url:evidence.sourceUrl,
      sourceHost:evidence.sourceHost,
      tier:evidence.sourceTier,
      checkedAt:evidence.observedAt,
      ageSecondsAtProjection:evidence.ageSecondsAtProjection
    }));
    call.status=item.status;
    const facts=item.materialFacts||{};
    const deadline=deadlineValue(facts.deadline)||item.deadline_at;
    if(deadline)call.close=deadline;
    if(!item.verifiedFactClasses.includes('deadline')){call.open='Neconfirmat';call.close='Neconfirmat';}
    if(!item.verifiedFactClasses.includes('budget'))call.budget='În verificare';
    else call.budget=textValue(facts.budget)||call.budget;
    if(!item.verifiedFactClasses.includes('grant'))call.grant='În verificare';
    else call.grant=textValue(facts.grant)||call.grant;
    if(!item.verifiedFactClasses.includes('eligibility'))call.eligibility=[...unknown];
    if(!item.verifiedFactClasses.includes('scoring'))call.scoring=[...unknown];
    if(item.status!=='PUBLIC_CONSULTATION')delete call.consultation;
  }

  // The critical boot dataset is deliberately static and can lag the live
  // decision products. Never allow a historical OPEN marker to survive merely
  // because the legacy snapshot still says OPEN. If current status + deadline
  // evidence is missing, unparseable or already expired, demote the runtime
  // projection to DISCOVERED until a current authoritative projection restores it.
  for(const call of D.calls){
    if(call.status!=='OPEN'||hasCurrentVerifiedOpen(call))continue;
    call.status='DISCOVERED';
    call.p11RuntimeGuard='OPEN_FAIL_CLOSED_NO_CURRENT_VERIFIED_DEADLINE';
    call.risks=[...new Set([...(call.risks||[]),'Statutul OPEN necesită reconfirmare din evidența autoritativă curentă.'])];
  }

  D.calls.sort((a,b)=>{
    const rank={OPEN:0,EXPECTED:1,PUBLIC_CONSULTATION:2,DISCOVERED:3,CLOSED:4};
    return (rank[a.status]??5)-(rank[b.status]??5)||String(a.title).localeCompare(String(b.title),'ro');
  });
  D.asOf=P.asOf||D.asOf;
  const liveOpenVerifiedCount=D.calls.filter(hasCurrentVerifiedOpen).length;
  D.intelligenceSummary={...(P.summary||{}),openVerifiedCount:liveOpenVerifiedCount,reviewCount:D.calls.filter(call=>call.status!=='OPEN').length};
})();

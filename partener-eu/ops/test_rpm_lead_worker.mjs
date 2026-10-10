#!/usr/bin/env node
// Contract simulation only: never sends PII or writes to a real D1 database.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';

const source = await fs.readFile(new URL('../lead-api/src/worker.js', import.meta.url), 'utf8');
const url = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const {default: worker} = await import(url);
const BASE = 'https://partener-rpm-leads.example.test/';

function request(method, path='/', body=null, origin='https://partener.eu'){
  const headers={'Origin':origin,'User-Agent':'PARTENER-RPM-CONTRACT/1.0'};
  if (body!==null) headers['Content-Type']='application/json';
  return new Request(new URL(path, BASE), {method, headers,
    ...(body!==null ? {body:typeof body==='string'?body:JSON.stringify(body)} : {})});
}

let inserted=[];
const DB={
  prepare(query){
    if(query.startsWith('SELECT')) return {all:async()=>({results:[]})};
    assert.match(query,/INSERT INTO rpm_leads/);
    return {bind(...params){return {run:async()=>{
      inserted.push(params);
      return {success:true};
    }}}};
  }
};
const good={DB,IP_SALT:'only-a-test-salt'};
const missing={IP_SALT:'only-a-test-salt'};
const failed={DB:{prepare(query){
  if(query.startsWith('SELECT'))return {all:async()=>{throw Error('simulated D1 failure')}};
  return {bind(){return {run:async()=>{throw Error('simulated D1 failure')}}}};
}},IP_SALT:'only-a-test-salt'};
async function call(method,path,body,env=good,origin='https://partener.eu'){
  const r=await worker.fetch(request(method,path,body,origin),env);
  const data=r.status===204?null:await r.json();
  return {r,data};
}

// Safe read-only health checks do not write a row.
let {r,data}=await call('GET','/health',null,good);
assert.equal(r.status,200);assert.equal(data.status,'READY');assert.equal(inserted.length,0);
({r,data}=await call('GET','/health',null,missing));
assert.equal(r.status,503);assert.equal(data.status,'PERSISTENCE_UNAVAILABLE');
({r,data}=await call('GET','/health',null,failed));
assert.equal(r.status,503);assert.equal(data.status,'PERSISTENCE_UNAVAILABLE');
({r,data}=await call('GET','/',null,good));
assert.equal(r.status,405);assert.equal(data.error,'METHOD_NOT_ALLOWED');
({r,data}=await call('OPTIONS','/',null,good));
assert.equal(r.status,204);
({r,data}=await call('POST','/','{',good));
assert.equal(r.status,400);assert.equal(data.error,'INVALID_JSON');
({r,data}=await call('POST','/',{},good));
assert.equal(r.status,422);assert.equal(data.error,'VALIDATION_ERROR');

// A synthetic unit fixture, NOT an actual customer/production submission.
const synthetic={company:'FAKE-CONTRACT-ONLY',name:'NO REAL CONTACT',
  contact:'not-a-person@example.invalid',employees:3,format:'Hibrid'};
({r,data}=await call('POST','/',synthetic,good));
assert.equal(r.status,201);assert.equal(data.ok,true);
assert.equal(inserted.length,1);
assert.equal(inserted[0][2],synthetic.company);
assert.match(inserted[0][15],/^[a-f0-9]{64}$/);
assert.equal(inserted[0][15].includes('1.2.3.4'),false);

({r,data}=await call('POST','/',synthetic,missing));
assert.equal(r.status,503);assert.deepEqual(data,{ok:false,error:'PERSISTENCE_UNAVAILABLE'});
({r,data}=await call('POST','/',synthetic,failed));
assert.equal(r.status,503);assert.equal(data.error,'PERSISTENCE_UNAVAILABLE');
assert.equal(JSON.stringify(data).includes(synthetic.contact),false);
// A honeypot must NOT hit D1 or claim a stored lead ID.
const before=inserted.length;
({r,data}=await call('POST','/',{...synthetic,website:'bot-honeypot'},good));
assert.equal(r.status,200);assert.deepEqual(data,{ok:true});
assert.equal(inserted.length,before);
console.log('PASS RPM lead: mock D1 insert, health, missing/broken binding, invalid input, CORS and honeypot');

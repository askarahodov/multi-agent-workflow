import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateTraceability } from './check-requirements.js';

const SHA = /^[a-f0-9]{40}$/;
const RISK = /^RISK-[0-9]{3,}$/;
const RFC = /^RFC-[0-9]{3,}$/;
const EXCEPTION = /^EXC-[0-9]{3,}$/;
const KINDS = new Set(['requirements','adr','contract','model','skill','permissions','dependency','infrastructure']);
const ROLES = new Set(['product-owner','architecture','tester','reviewer','security','operator']);
const OWNERS = new Set(['orchestration-server','agent-management','quality-gates','runtime-hardening','frontend','developer-tooling','cross-service','platform','operations','documentation','security']);
const LEVELS = new Set(['low','medium','high','critical']);
const actor = s => typeof s === 'string' && /^[a-z0-9](?:[a-z0-9-]{0,38})$/i.test(s);
const text = s => typeof s === 'string' && s.trim().length > 0;
const positive = n => Number.isSafeInteger(n) && n > 0;
const sha = s => typeof s === 'string' && SHA.test(s) && !/^0+$/.test(s);
const date = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) &&
  Number.isFinite(Date.parse(s+'T00:00:00Z')) && new Date(s+'T00:00:00Z').toISOString().slice(0,10) === s;
const reference = s => typeof s === 'string' && /^https:\/\/github\.com\/askarahodov\/multi-agent-workflow\/(?:issues|pull)\/[1-9]\d*#(?:issuecomment|pullrequestreview)-[1-9]\d*$/.test(s);
const safePath = p => typeof p === 'string' && /^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(p) &&
  p.split('/').every(s => s !== '.' && s !== '..');
function fail(message) { throw new Error(message); }
function expect(ok, message) { if (!ok) fail(message); }
function exact(obj, fields, where) {
  expect(obj && typeof obj === 'object' && !Array.isArray(obj) &&
    Object.keys(obj).length === fields.length && fields.every(k => Object.hasOwn(obj,k)), 'invalid fields: '+where);
}
function unique(values, predicate, name, required = true) {
  expect(Array.isArray(values) && (!required || values.length > 0) &&
    values.every(predicate) && new Set(values).size === values.length, 'invalid/duplicate '+name);
}
function paths(values, tracked, name, required = true) {
  unique(values, p => safePath(p) && tracked.has(p), name, required);
}
function index(items, key, label) {
  expect(Array.isArray(items) && items.length > 0, 'missing '+label);
  const map = new Map();
  for (const item of items) {
    const id = item?.[key];
    expect(text(id) && !map.has(id), 'duplicate or missing '+label+' id');
    map.set(id,item);
  }
  return map;
}
const sorted = values => [...new Set(values)].sort();

export function buildImpact(proposal, context) {
  const contracts = index(context.contracts,'id','contract');
  const reqs = index(context.requirements,'id','requirement');
  // Traverse the finite CT/RTM graph to a fixed point: explicit requirements,
  // changed paths, and explicit CTs are all seeds. Inferred architecture
  // references are documentation outputs, not new affected-path seeds.
  const contractIds = new Set(proposal.contracts);
  const requirementIds = new Set(proposal.requirements);
  const components = new Set(), tests = new Set(proposal.test_refs), docs = new Set(proposal.doc_refs);
  const sources = new Set(proposal.paths);
  const issues = new Set([proposal.issue]);
  const trace = index(context.traceability,'requirement_id','traceability');
  const expandedContracts = new Set(), expandedRequirements = new Set();
  for (const id of requirementIds) expect(trace.has(id), 'missing requirement trace '+id);
  let changed = true;
  while (changed) {
    changed = false;
    for (const c of contracts.values()) {
      if ((c.sources ?? []).some(p => sources.has(p)) || sources.has(c.runtime_authority)) {
        if (!contractIds.has(c.id)) { contractIds.add(c.id); changed = true; }
      }
    }
    for (const id of contractIds) {
      if (expandedContracts.has(id)) continue;
      const c = contracts.get(id);
      expect(c, 'unknown contract '+id);
      expect(text(c.producer) && Array.isArray(c.consumers) && c.consumers.every(text) &&
        Array.isArray(c.sources) && Array.isArray(c.related_tests), 'incomplete contract mapping '+id);
      components.add(c.producer);
      for (const consumer of c.consumers) components.add(consumer);
      for (const p of c.sources) sources.add(p);
      if (c.runtime_authority !== null && c.runtime_authority !== undefined) sources.add(c.runtime_authority);
      for (const p of c.related_tests) tests.add(p);
      expandedContracts.add(id); changed = true;
    }
    for (const row of trace.values()) {
      expect(Array.isArray(row.contract_refs) && Array.isArray(row.architecture_refs), 'invalid traceability refs');
      if (requirementIds.has(row.requirement_id) ||
          [...row.contract_refs,...row.architecture_refs].some(p=>sources.has(p))) {
        requirementIds.add(row.requirement_id);
        if (expandedRequirements.has(row.requirement_id)) continue;
        for (const p of row.contract_refs) sources.add(p);
        for (const p of row.architecture_refs) docs.add(p);
        expandedRequirements.add(row.requirement_id); changed = true;
      }
    }
  }
  for (const id of requirementIds) {
    const req = reqs.get(id);
    expect(req && positive(req.issue), 'unknown requirement '+id);
    issues.add(req.issue);
  }
  for (const path of sources) {
    const parts = path.split('/');
    if (parts[0] === 'services' || parts[0] === 'packages') components.add(parts[1]);
    else if (parts[0] === 'apps') components.add(parts[1]);
    else if (parts[0] === 'deploy') components.add('deployment');
    else if (parts[0] === 'docs') components.add('documentation');
    else components.add('repository-tooling');
  }
  for (const id of proposal.risks) for (const issue of context.risks.get(id).issues) issues.add(issue.number);
  paths([...sources],context.tracked,'impact source');
  paths([...tests],context.tracked,'impact test');
  paths([...docs],context.tracked,'impact doc');
  return {
    proposal_id:proposal.id, contract_ids:sorted(contractIds), requirement_ids:sorted(requirementIds),
    components:sorted(components), test_refs:sorted(tests), doc_refs:sorted(docs),
    source_refs:sorted(sources), related_issues:[...issues].sort((a,b)=>a-b),
    suggested_tasks:sorted(components).map(component=>({component,action:'review-impact-and-verify',status:'proposed'})),
    decision_status:proposal.status, approval_provenance:'NOT_VERIFIED', authorization:false,
    scope_expansion_authorized:false, production_authorized:false
  };
}

function plan(planValue, fields, tracked, name) {
  exact(planValue,fields,name);
  expect(text(planValue[fields[0]]), 'missing '+name+' rationale');
  unique(planValue.steps,text,name+' steps');
  paths([planValue.verify],tracked,name+' verification');
}
function validateApprovals(p, asOf) {
  expect(Array.isArray(p.approvals), 'invalid approvals');
  const actors = new Set(), roles = new Set(), refs = new Set();
  for (const a of p.approvals) {
    exact(a,['role','actor','decision','candidate_sha','decided_on','reference'],'approval');
    expect(p.review_roles.includes(a.role) && actor(a.actor) && actor(p.author) &&
      a.actor.toLowerCase() !== p.author.toLowerCase() &&
      !actors.has(a.actor.toLowerCase()) && !roles.has(a.role) && !refs.has(a.reference) &&
      sha(p.candidate_sha) && a.candidate_sha === p.candidate_sha && date(a.decided_on) &&
      a.decided_on <= asOf && reference(a.reference) &&
      ['approved','rejected'].includes(a.decision), 'invalid, stale or self approval record');
    actors.add(a.actor.toLowerCase()); roles.add(a.role); refs.add(a.reference);
  }
  if (p.status === 'decision_recorded') {
    expect(['approved','rejected'].includes(p.decision) && p.approvals.length > 0,'decision lacks records');
    if (p.decision === 'approved') {
      expect(p.review_roles.every(r => roles.has(r)) && p.approvals.every(a=>a.decision==='approved'),
        'missing or contradictory approval records');
    } else expect(p.approvals.some(a=>a.decision==='rejected'),'missing rejection record');
  } else expect(p.decision === null,'decision outside decision_recorded');
  if (p.status === 'draft') expect(p.approvals.length === 0,'draft cannot claim approvals');
}
function validateExceptions(p, risks, asOf) {
  expect(Array.isArray(p.exceptions), 'invalid exceptions');
  const seen = new Set();
  for (const e of p.exceptions) {
    exact(e,['id','risk_id','scope','reason','owner','status','expires_on','candidate_sha','approval_reference'],'exception');
    expect(EXCEPTION.test(e.id) && !seen.has(e.id) && risks.has(e.risk_id) && p.risks.includes(e.risk_id) &&
      text(e.scope) && text(e.reason) && OWNERS.has(e.owner) && date(e.expires_on) &&
      ['requested','recorded','revoked','expired'].includes(e.status), 'invalid/duplicate exception');
    seen.add(e.id);
    if (e.status === 'requested') {
      expect(e.approval_reference === null && e.candidate_sha === null && e.expires_on > asOf,'invalid exception request');
    } else {
      expect(sha(p.candidate_sha) && e.candidate_sha === p.candidate_sha && reference(e.approval_reference),
        'exception missing candidate/reference');
      const approval = p.approvals.find(a=>a.reference === e.approval_reference && a.role === 'security' &&
        a.decision === 'approved' && a.candidate_sha === p.candidate_sha);
      expect(approval && approval.decided_on < e.expires_on,'missing security decision record');
      if (e.status === 'recorded') {
        expect(p.status === 'decision_recorded' && p.decision === 'approved' && e.expires_on > asOf,
          'expired or unapproved exception record');
      }
      if (e.status === 'expired') expect(e.expires_on <= asOf,'exception not expired');
    }
  }
}

export function validateGovernance(register, changes, context, asOf) {
  exact(register,['schema_version','baseline_sha','observed_on','risks'],'risk register');
  exact(changes,['schema_version','baseline_sha','proposals'],'change register');
  expect(register.schema_version===1 && changes.schema_version===1 &&
    sha(register.baseline_sha) && register.baseline_sha===changes.baseline_sha &&
    date(register.observed_on) && date(asOf),'invalid register version/baseline/date');
  expect(context.tracked instanceof Set,'missing tracked paths');
  const risks = index(register.risks,'id','risk');
  const observed = new Map();
  for (const r of risks.values()) {
    exact(r,['id','title','owner','status','impact','likelihood','mitigation','residual','issues','evidence_paths'],'risk '+r.id);
    expect(RISK.test(r.id) && text(r.title) && OWNERS.has(r.owner) &&
      ['open','restricted','mitigating'].includes(r.status) &&
      LEVELS.has(r.impact) && LEVELS.has(r.likelihood) &&
      text(r.mitigation) && text(r.residual),'invalid risk metadata '+r.id);
    expect(Array.isArray(r.issues) && r.issues.length > 0,'risk lacks issue references');
    const issueIds=new Set();
    for(const i of r.issues) {
      exact(i,['number','state'],'issue snapshot');
      expect(positive(i.number) && !issueIds.has(i.number) && ['open','closed'].includes(i.state) &&
        (!observed.has(i.number)||observed.get(i.number)===i.state),'invalid or contradictory issue snapshot');
      issueIds.add(i.number); observed.set(i.number,i.state);
    }
    paths(r.evidence_paths,context.tracked,'risk evidence '+r.id);
  }
  for (const n of [3,209,323,324,327]) expect(observed.has(n),'missing required risk issue '+n);
  const proposals=index(changes.proposals,'id','proposal');
  const contracts=index(context.contracts,'id','contract');
  const reqs=index(context.requirements,'id','requirement');
  const results=[];
  for(const p of proposals.values()) {
    exact(p,['id','issue','title','summary','status','decision','author','candidate_sha','change_kinds','breaking','paths','contracts','requirements','risks','test_refs','doc_refs','migration','rollback','review_roles','approvals','exceptions'],'proposal '+p.id);
    expect(RFC.test(p.id) && positive(p.issue) && text(p.title) && text(p.summary) &&
      ['draft','in_review','decision_recorded','withdrawn'].includes(p.status) &&
      (p.author===null||actor(p.author)) && (p.candidate_sha===null||sha(p.candidate_sha)) &&
      typeof p.breaking==='boolean','invalid proposal metadata '+p.id);
    if(p.status==='in_review'||p.status==='decision_recorded') expect(actor(p.author)&&sha(p.candidate_sha),'review requires exact candidate and author');
    unique(p.change_kinds,k=>KINDS.has(k),'change kinds');
    paths(p.paths,context.tracked,'affected paths');
    unique(p.contracts,id=>contracts.has(id),'contract ids',p.breaking||p.change_kinds.includes('contract'));
    unique(p.requirements,id=>reqs.has(id),'requirement ids');
    unique(p.risks,id=>risks.has(id),'risk ids');
    paths(p.test_refs,context.tracked,'test refs');
    paths(p.doc_refs,context.tracked,'doc refs');
    expect(p.doc_refs.every(x=>x.startsWith('docs/')&&x.endsWith('.md')),'invalid doc reference');
    plan(p.migration,['strategy','steps','verify'],context.tracked,'migration');
    plan(p.rollback,['trigger','steps','verify'],context.tracked,'rollback');
    unique(p.review_roles,r=>ROLES.has(r),'review roles');
    const requiredRoles=['product-owner','reviewer','tester'];
    if(p.breaking||p.change_kinds.some(k=>['contract','adr'].includes(k))) requiredRoles.push('architecture');
    if(p.breaking||p.change_kinds.some(k=>['model','skill','permissions','dependency','infrastructure'].includes(k))) requiredRoles.push('security');
    if(p.breaking||p.change_kinds.includes('infrastructure')) requiredRoles.push('operator');
    expect(requiredRoles.every(r=>p.review_roles.includes(r)),'required review role missing');
    validateApprovals(p,asOf);
    validateExceptions(p,risks,asOf);
    results.push(buildImpact(p,{...context,risks}));
  }
  return {
    baseline_sha:register.baseline_sha, observed_on:register.observed_on,
    risk_count:risks.size, issue_snapshots:[...observed].map(([number,state])=>({number,state})),
    plans:results, authorization:false, live_evidence:'NOT_VERIFIED'
  };
}

export function trackedFiles(root=process.cwd()) {
  const raw=execFileSync('git',['ls-files','--stage','-z'],{cwd:root,encoding:'utf8'});
  const paths=new Set();
  for(const entry of raw.split('\0').filter(Boolean)) {
    const match=entry.match(/^(100644|100755) [a-f0-9]{40} 0\t(.+)$/);
    if(match&&safePath(match[2])) paths.add(match[2]);
  }
  return paths;
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const read=p=>JSON.parse(readFileSync(p,'utf8'));
    const requirements=read('docs/product/requirements.json');
    const rtm=read('docs/product/traceability.json');
    validateTraceability(requirements,rtm);
    const context={tracked:trackedFiles(),requirements:requirements.requirements,
      contracts:read('docs/architecture/contract-registry.json').contracts,traceability:rtm.records};
    const report=validateGovernance(read('docs/governance/risk-register.json'),
      read('docs/governance/change-proposals.json'),context,new Date().toISOString().slice(0,10));
    console.log(JSON.stringify(report,null,2));
  } catch(error) {
    console.error(error.message);
    process.exitCode=1;
  }
}

// Operator-only, read-only evidence inspection. Never execute this script
// from an untrusted PR with a privileged token. No record is promoted by it.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateTraceability } from './check-requirements.js';

const REPO = 'askarahodov/multi-agent-workflow';
const ROOT = '/repos/' + REPO;
const WEB = 'https://github.com/' + REPO;
const SHA = /^[a-f0-9]{40}$/;
const login = s => typeof s === 'string' ? s.trim().toLowerCase() : '';
const id = n => Number.isSafeInteger(n) && n > 0;
const deny = reason => { throw Error(reason); };
const passing = x => x?.status === 'completed' && x.conclusion === 'success';
const positiveId = s => {
  const n = Number(s);
  if (!id(n) || String(n) !== s) deny('Invalid evidence identifier');
  return n;
};
function exactMatch(value, pattern, reason) {
  const match = typeof value === 'string' && value.match(pattern);
  if (!match) deny(reason);
  return match;
}
const escapeRx = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const ciRef = new RegExp('^'+escapeRx(WEB)+'/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)$');
const reviewRef = new RegExp('^'+escapeRx(WEB)+'/pull/([1-9][0-9]*)#pullrequestreview-([1-9][0-9]*)$');

// Bound pagination, response size and call count. The origin and API paths
// are generated here, not extracted from user-supplied evidence URLs.
export function githubReader(token, fetcher = fetch) {
  let calls = 0;
  return async path => {
    if (typeof path !== 'string' || !path.startsWith(ROOT+'/') ||
        path.includes('..') || path.includes('\\') || ++calls > 250) deny('GitHub evidence request rejected');
    const headers = {Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'};
    if (token) headers.Authorization = 'Bearer '+token;
    const response = await fetcher('https://api.github.com'+path, {
      method:'GET', headers, redirect:'error', signal:AbortSignal.timeout(10000),
    });
    if (!response.ok) deny('GitHub evidence API unavailable: HTTP '+response.status);
    const body = await response.text();
    if (body.length > 8_000_000) deny('GitHub evidence response too large');
    return JSON.parse(body);
  };
}
async function pages(get, path, key) {
  const result = [];
  for(let page=1;page<=10;page++) {
    const raw = await get(path+'?per_page=100&page='+page);
    const items = key ? raw?.[key] : raw;
    if (!Array.isArray(items) || items.length > 100) deny('Incomplete GitHub evidence page');
    result.push(...items);
    if (items.length < 100) {
      if (key && (!Number.isSafeInteger(raw.total_count) || raw.total_count !== result.length))
        deny('Incomplete GitHub evidence result');
      return result;
    }
  }
  deny('GitHub evidence pagination bound exceeded');
}
function assertPR(pr, row) {
  if (pr?.number !== row.pull_request || pr.base?.repo?.full_name !== REPO ||
      pr.head?.repo?.full_name !== REPO || pr.head?.sha !== row.candidate_sha ||
      !SHA.test(pr.head.sha) || pr.draft !== false || !login(pr.user?.login) ||
      !(pr.state==='open' || pr.merged===true)) deny('Missing, foreign, draft or stale PR candidate');
}
function assertRun(run, pr, row, runId) {
  if (run?.id !== runId || !passing(run) || run.head_sha !== row.candidate_sha ||
      run.repository?.full_name !== REPO || run.head_repository?.full_name !== REPO ||
      run.event !== 'pull_request' || !id(run.run_attempt) ||
      !Array.isArray(run.pull_requests) ||
      !run.pull_requests.some(p => p.number===pr.number &&
        p.head?.sha===row.candidate_sha && p.base?.repo?.id===pr.base.repo.id))
    deny('Missing, foreign, stale or unsuccessful PR workflow run');
}
async function inspectCI(get, row, pr, e) {
  const [,r,j] = exactMatch(e.reference,ciRef,'CI reference must be canonical repository run/job URL');
  const runId=positiveId(r), jobId=positiveId(j);
  const [,testJob,step]=exactMatch(e.test_id,/^job:([1-9][0-9]*)\/step:([1-9][0-9]*)$/,
    'Individual test result not proven by GitHub job/step metadata');
  if (positiveId(testJob)!==jobId) deny('CI test identity does not match job URL');
  const run=await get(ROOT+'/actions/runs/'+runId);
  assertRun(run,pr,row,runId);
  const jobs=await pages(get,ROOT+'/actions/runs/'+runId+'/attempts/'+run.run_attempt+'/jobs','jobs');
  const matches=jobs.filter(j=>j.id===jobId);
  if (matches.length!==1 || !passing(matches[0]) || matches[0].run_id!==runId ||
      matches[0].head_sha!==row.candidate_sha ||
      matches[0].run_attempt!==run.run_attempt) deny('Missing, stale or unsuccessful CI job');
  const steps=matches[0].steps?.filter(s=>s.number===positiveId(step));
  if (steps?.length!==1 || !passing(steps[0]) || !steps[0].name) deny('Missing or unsuccessful CI step');
  const again=await get(ROOT+'/actions/runs/'+runId);
  assertRun(again,pr,row,runId);
  if(again.run_attempt!==run.run_attempt) deny('CI run changed during inspection');
  return {kind:'ci',reference:e.reference,step:steps[0].name,run_attempt:run.run_attempt,
    case_id:e.case_id??null,status:'JOB_STEP_CONFIRMED',scenario_semantics:'NOT_VERIFIED'};
}
async function inspectApproval(get,row,pr,e) {
  const [,p,r]=exactMatch(e.reference,reviewRef,'Approval reference must be canonical PR review URL');
  if(positiveId(p)!==pr.number) deny('Approval belongs to another PR');
  const reviewId=positiveId(r);
  const reviews=await pages(get,ROOT+'/pulls/'+pr.number+'/reviews');
  const matches=reviews.filter(x=>x.id===reviewId);
  const reviewer=login(e.reviewer);
  if(matches.length!==1 || matches[0].state!=='APPROVED' ||
      matches[0].commit_id!==row.candidate_sha || login(matches[0].user?.login)!==reviewer ||
      matches[0].user?.type!=='User' || !reviewer ||
      reviewer===login(row.implementer) || reviewer===login(pr.user.login))
    deny('Missing, stale, non-human or self approval');
  // A later non-comment disposition supersedes that review. Reject any
  // current unresolved change request, even from another reviewer.
  const latest=new Map();
  for(const review of reviews) {
    const who=login(review.user?.login);
    if(!who || !id(review.id) || !['APPROVED','CHANGES_REQUESTED','DISMISSED','COMMENTED','PENDING'].includes(review.state))
      deny('Incomplete review history');
    if(review.state==='COMMENTED') continue;
    if(review.state==='PENDING') deny('Pending review');
    if(!latest.has(who) || latest.get(who).id<review.id) latest.set(who,review);
  }
  if(latest.get(reviewer)?.id!==reviewId ||
      [...latest.values()].some(x=>x.state==='CHANGES_REQUESTED'))
    deny('Approval superseded or changes requested');
  const role=await get(ROOT+'/collaborators/'+encodeURIComponent(reviewer)+'/permission');
  if(login(role?.user?.login)!==reviewer || !['write','maintain','admin'].includes(role.permission))
    deny('Reviewer permission not confirmed');
  return {kind:'approval',reference:e.reference,reviewer,status:'GITHUB_APPROVAL_CONFIRMED',
    independence_beyond_author:'NOT_VERIFIED'};
}

// No URL is fetched from the RTM itself. Claimed per-test assertions and
// release semantics require separately trusted artifacts/operator evidence.
export async function inspectRequirementEvidence(requirements,matrix,get) {
  validateTraceability(requirements,matrix);
  const results=[];
  for(const row of matrix.records) {
    if(['planned','blocked'].includes(row.status)) {
      results.push({requirement_id:row.requirement_id,status:'NO_CLAIM',receipts:[]});
      continue;
    }
    const pr=await get(ROOT+'/pulls/'+row.pull_request);
    assertPR(pr,row);
    const receipts=[];
    for(const e of row.evidence) {
      if(e.kind==='ci') {
        if(e.verdict!=='pass') deny('Non-passing CI receipt');
        receipts.push(await inspectCI(get,row,pr,e));
      } else if(e.kind==='approval') {
        if(e.verdict!=='pass') deny('Non-passing approval receipt');
        receipts.push(await inspectApproval(get,row,pr,e));
      } else if(e.kind==='pr' && e.reference===WEB+'/pull/'+pr.number && e.verdict==='pass') {
        receipts.push({kind:'pr',reference:e.reference,status:'PR_CANDIDATE_CONFIRMED'});
      } else deny('Unsupported evidence type or reference');
    }
    const final=await get(ROOT+'/pulls/'+row.pull_request);
    assertPR(final,row);
    if(final.base?.sha!==pr.base?.sha) deny('PR base changed during inspection');
    results.push({requirement_id:row.requirement_id,status:'RECEIPTS_INSPECTED_NOT_ACCEPTED',receipts,
      release:row.release===null?'NO_CLAIM':'NOT_VERIFIED'});
  }
  return results;
}

if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const requirements=JSON.parse(readFileSync('docs/product/requirements.json','utf8'));
    const matrix=JSON.parse(readFileSync('docs/product/traceability.json','utf8'));
    const results=await inspectRequirementEvidence(requirements,matrix,githubReader(process.env.GITHUB_TOKEN));
    console.log(JSON.stringify({status:'RECEIPT_INSPECTION_ONLY',results},null,2));
  } catch(error) {
    console.error('Evidence inspection BLOCKED:',error.message);
    process.exitCode=1;
  }
}

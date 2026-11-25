'use strict';
let state, currentJob, accessKey = '', selectedPreviewId = '', selectedJobPreviewId = '';
const $ = id => document.getElementById(id);
const money = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
function toast(message){$('toast').textContent=message;$('toast').classList.remove('hidden');setTimeout(()=>$('toast').classList.add('hidden'),6500);}
async function api(path,body){const opts=body?{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+accessKey},body:JSON.stringify(body)}:{headers:accessKey?{'Authorization':'Bearer '+accessKey}:{}};const res=await fetch(path,opts);const data=await res.json();if(!res.ok)throw new Error(data.error||'Request failed');return data;}
function textNode(tag,text,cls){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;}
function sourceLink(source){const link=document.createElement('a');let parsed;try{parsed=new URL(source.url);}catch{return textNode('p','Source unavailable');}if(parsed.protocol!=='https:'||parsed.username||parsed.password)return textNode('p','Source unavailable');link.href=parsed.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent=source.title||source.url;return link;}
function controls(){const locked=!accessKey||!currentJob||currentJob.state!=='HUMAN_REVIEW';['approve','revise','reject'].forEach(id=>$(id).disabled=locked);['save-script','script-edit','feedback'].forEach(id=>$(id).disabled=!accessKey||!currentJob);$('job-select').disabled=!accessKey||!state?.jobs?.length;$('kill').disabled=!accessKey;}
function renderPreview(){
  const preview=state.previews.find(p=>p.id===selectedPreviewId)||state.previews[0];
  if(!preview)return;
  selectedPreviewId=preview.id;$('preview-select').value=preview.id;
  $('preview-lane').textContent=preview.lane.toUpperCase();$('preview-title').textContent=preview.title;$('preview-heading').textContent=preview.title;
  $('preview-audio').textContent=preview.audio_label;$('preview-label').textContent=preview.review_label;
  const duration=typeof preview.duration_seconds==='number'?`${preview.duration_seconds.toFixed(1)} sec · `:'';
  $('video-details').textContent=duration+preview.dimensions.join(' × ')+' · '+preview.lane;
  $('preview-limits').textContent=preview.factual_caveat||(preview.id==='human'?'Educational viewing only. Commercial reuse permissions remain unresolved.':'This local sample has not been approved for release.');
  $('preview-script-label').textContent=preview.id.startsWith('study')?'On-screen script · this cut has no narration':preview.id==='clip_progress'?'Source transcript + original on-screen editorial note':preview.id==='human'?'Original source transcript':preview.id==='original_narrated'?'Original narration script':'Archived narration script';
  $('preview-script').textContent=preview.script||'The verified script will appear when this preview is ready.';
  $('recording-script').textContent=preview.human_recording_script;$('recording-brief').classList.toggle('hidden',!preview.human_recording_script);
  const sources=[textNode('span','EVIDENCE & CONTEXT','eyebrow')];
  for(const source of preview.sources){const entry=textNode('div','','source-entry');entry.append(sourceLink(source));if(source.design)entry.append(textNode('p',source.design));if(source.scope)entry.append(textNode('p',source.scope));sources.push(entry);}
  if(preview.source_interval)sources.push(textNode('p',`Original source interval: ${preview.source_interval.start.toFixed(2)}–${preview.source_interval.end.toFixed(2)} seconds.`));
  if(!preview.sources.length)sources.push(textNode('p','Source details are pending.'));
  $('preview-sources').replaceChildren(...sources);
  if(preview.available){
    if($('sample-video')?.dataset.previewId!==preview.id){const video=document.createElement('video');video.id='sample-video';video.dataset.previewId=preview.id;video.controls=true;video.preload='metadata';video.playsInline=true;video.src=preview.video_url;video.poster=preview.poster_url;video.setAttribute('aria-label',preview.title+' local preview');$('preview').replaceChildren(video);}
  }else{const empty=textNode('div','','video-placeholder');empty.append(textNode('span','COMING INTO VIEW'),textNode('strong','REP.'),textNode('p','This local preview is not ready yet.'));$('preview').replaceChildren(empty);}
}
function renderJob(){
  if(currentJob){
    $('job-select').value=currentJob.id;$('job-state').textContent=currentJob.state.replaceAll('_',' ');$('revision').textContent='REVISION '+String(currentJob.revision).padStart(2,'0');$('job-title').textContent=currentJob.title;$('brief').textContent=currentJob.brief||'';$('script').textContent=currentJob.script||'';$('script-edit').value=currentJob.script||'';
    $('review-target').textContent=`Decision target: “${currentJob.title}” · revision ${currentJob.revision} · job ${currentJob.id}. Attached video controls below refer only to this job and revision.`;
    $('sources').replaceChildren(textNode('span','THIS JOB’S EVIDENCE','eyebrow'),...(currentJob.sources||[]).map(sourceLink));
  }else{
    $('job-state').textContent=accessKey?'NO SAVED JOB':'LOCKED';$('revision').textContent='NO JOB SELECTED';$('job-title').textContent=accessKey?'No saved script to review':'Unlock saved script review';$('brief').textContent=accessKey?'Create or import a job to begin script review.':'Use the local access key to inspect saved jobs and make decisions.';$('script').textContent='';$('script-edit').value='';$('sources').replaceChildren();$('review-target').textContent='Unlock and select a job to inspect its revision-bound video.';
  }
  controls();renderJobArtifact();
}
function currentArtifact(){return (currentJob?.previews||[]).find(p=>p.id===selectedJobPreviewId&&p.revision===currentJob.revision);}
function renderJobArtifact(){
  const previews=(currentJob?.previews||[]).filter(p=>p.revision===currentJob.revision);
  const selected=previews.find(p=>p.id===selectedJobPreviewId)||previews.find(p=>p.id===currentJob?.active_preview_id)||previews[0];
  selectedJobPreviewId=selected?.id||'';
  $('artifact-select').replaceChildren(...(previews.length?previews.map((p,i)=>{const o=textNode('option',`Video ${previews.length-i} · ${p.artifact_sha256.slice(0,12)}`);o.value=p.id;return o;}):[textNode('option','No video for this revision')]));
  $('artifact-select').value=selectedJobPreviewId;$('artifact-select').disabled=!accessKey||!previews.length;
  const q=selected?.qc;const selectedActive=selected&&currentJob?.active_preview_id===selected.id;
  $('artifact-status').textContent=!selected?'Import a rendered review artifact to attach an exact video to this script revision.':currentJob.release_sha256===selected.artifact_sha256&&selectedActive?'This exact final video is approved. Publication is still separately controlled.':`Revision ${selected.revision} · technical QC ${q?.technical_passed?'passed':'needs review'} · source rights ${q?.checks?.rights?'documented':'blocked or incomplete'}. ${q?.rights_blockers?.join(' ')||''}`;
  $('artifact-hash').textContent=selected?'Exact video SHA-256: '+selected.artifact_sha256:'';
  if(selected&&accessKey){
    if($('job-video')?.dataset.previewId!==selected.id){const video=document.createElement('video');video.id='job-video';video.dataset.previewId=selected.id;video.controls=true;video.playsInline=true;video.preload='metadata';video.src=`/api/previews/${selected.id}/video`;video.setAttribute('aria-label',currentJob.title+' revision '+currentJob.revision);$('artifact-player').replaceChildren(video);}
  }else $('artifact-player').replaceChildren();
  const stopped=state?.status?.kill_switch;
  $('artifact-qc').disabled=!accessKey||!selected;
  $('artifact-stage').disabled=!accessKey||!selected||stopped||!q?.technical_passed||currentJob?.approved_revision!==currentJob?.revision||!['APPROVED','QC'].includes(currentJob?.state);
  $('artifact-release').disabled=!accessKey||!selected||stopped||!selectedActive||currentJob?.state!=='QC'||!currentJob?.qc?.passed||currentJob?.release_sha256===selected.artifact_sha256;
}
function renderServices(){
  $('setup-authorization').textContent='SETUP AUTHORIZED · '+state.setup_authorized_at;
  $('service-grid').replaceChildren(...state.services.map((service,index)=>{const card=document.createElement('article');card.append(textNode('span',String(index+1).padStart(2,'0')),textNode('h3',service.title),textNode('p',service.detail),textNode('b',service.status.replaceAll('_',' ').toUpperCase()));if(service.url)card.append(sourceLink({url:service.url,title:'Open service page ↗'}));return card;}));
}
async function refresh(){
  const previousJobId=currentJob?.id;
  state=accessKey?await api('/api/state'):await api('/api/preview');state.jobs=state.jobs||[];state.events=state.events||[];state.previews=state.previews||[];state.services=state.services||[];
  currentJob=state.jobs.find(j=>j.id===previousJobId)||state.jobs.find(j=>j.state==='HUMAN_REVIEW')||state.jobs[0];
  const s=state.status;$('review-count').textContent=s.counts.HUMAN_REVIEW||0;$('published-count').textContent=(s.counts.PUBLISHED||0)+(s.counts.ANALYZED||0);$('budget').textContent=money(s.costs.approved_usd);$('connection').textContent=s.kill_switch?'EMERGENCY STOP':s.publication_enabled?'PUBLICATION AUTHORIZED':'PUBLICATION DISABLED';$('kill').textContent=s.kill_switch?'Resume approved work':'Stop all work';$('kill-status').textContent=s.kill_switch?'All new work is stopped. Existing provider submissions require separate cancellation.':'Blocks paid work, rendering and new submissions.';
  $('preview-select').replaceChildren(...state.previews.map(preview=>{const option=textNode('option',preview.lane+' · '+preview.title+(preview.available?'':' · pending'));option.value=preview.id;return option;}));
  if(!selectedPreviewId)selectedPreviewId=state.default_preview_id;
  $('job-select').replaceChildren(...(state.jobs.length?state.jobs.map(job=>{const option=textNode('option',job.title+' · revision '+job.revision);option.value=job.id;return option;}):[textNode('option',accessKey?'No saved jobs':'Unlock to load saved jobs')]));
  renderPreview();renderJob();renderServices();
  $('library').replaceChildren(...state.jobs.map(j=>{const el=textNode('div','','record');el.append(textNode('strong',j.title),textNode('small',`${j.state.replaceAll('_',' ')} · revision ${j.revision}`));return el;}));
  $('events').replaceChildren(...state.events.map(e=>{const el=textNode('div','','record');el.append(textNode('span',e.event.replaceAll('_',' ')),textNode('small',new Date(e.at*1000).toLocaleString()+' · '+e.actor));return el;}));$('updated').textContent='UPDATED '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
}
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.view').forEach(v=>v.classList.add('hidden'));$(b.dataset.view+'-view').classList.remove('hidden');document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n===b));}));
$('preview-select').addEventListener('change',()=>{selectedPreviewId=$('preview-select').value;renderPreview();});
$('job-select').addEventListener('change',()=>{currentJob=state.jobs.find(job=>job.id===$('job-select').value);$('feedback').value='';renderJob();});
$('unlock').addEventListener('click',()=>$('unlock-dialog').showModal());$('close-dialog').addEventListener('click',()=>$('unlock-dialog').close());
$('unlock-form').addEventListener('submit',async e=>{e.preventDefault();try{const file=$('key-file').files[0];if(!file||file.size>200)throw new Error('Choose the local access key file');accessKey=(await file.text()).trim();await api('/api/unlock',{});$('unlock-dialog').close();$('unlock').textContent='Review unlocked';await refresh();toast('Review controls unlocked for this tab.');}catch(e){accessKey='';currentJob=undefined;controls();toast(e.message);}});
for(const [id,decision] of [['approve','approve'],['reject','reject'],['revise','revise']])$(id).addEventListener('click',async()=>{try{if(!currentJob||!accessKey)throw new Error('Select a saved job after unlocking.');if(decision==='revise'&&!$('feedback').value.trim())throw new Error('Add a note describing the revision you want.');const target={id:currentJob.id,revision:currentJob.revision};await api('/api/review',{...target,decision,feedback:$('feedback').value});toast(decision==='approve'?'Selected script approved. Its attached video still needs a separate final review.':decision==='reject'?'Selected script rejected.':'Revision request recorded.');await refresh();}catch(e){toast(e.message);}});
$('save-script').addEventListener('click',async()=>{try{if(!currentJob||!accessKey)throw new Error('Select a saved job after unlocking.');await api('/api/revise',{id:currentJob.id,revision:currentJob.revision,script:$('script-edit').value});await refresh();toast('New revision saved and returned to review.');}catch(e){toast(e.message);}});
$('artifact-select').addEventListener('change',()=>{selectedJobPreviewId=$('artifact-select').value;renderJobArtifact();});
for(const [button,path] of [['artifact-qc','/api/preview-qc'],['artifact-stage','/api/stage-preview'],['artifact-release','/api/approve-release']])$(button).addEventListener('click',async()=>{
  const selected=currentArtifact();if(!selected||!currentJob||!accessKey)return;
  const target={id:currentJob.id,revision:currentJob.revision,preview_id:selected.id,artifact_sha256:selected.artifact_sha256};
  $(button).disabled=true;
  try{await api(path,target);await refresh();toast(button==='artifact-release'?'Exact final video approved. Publishing remains separately disabled.':button==='artifact-stage'?'Video prepared for final review. No release approval was created.':'Video QC updated; no approval was created.');}catch(e){toast(e.message);renderJobArtifact();}
});
$('kill').addEventListener('click',async()=>{try{await api('/api/kill',{enabled:!state.status.kill_switch});await refresh();toast(state.status.kill_switch?'Emergency stop is active.':'Approved work may resume. Publishing remains separately controlled.');}catch(e){toast(e.message);}});
refresh().catch(e=>toast(e.message));

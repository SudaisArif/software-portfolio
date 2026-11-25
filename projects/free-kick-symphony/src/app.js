import {DEFAULTS,clamp,flightDuration,positionAt,makeEvents,isGoal} from './engine/physics.mjs';
import {sanitizeConfig,readMidi} from './engine/session.mjs';
import {referencePhrase,editedPhrase} from './engine/phrase.mjs';
import {makeCamera,goalTargetAtPixel} from './engine/camera.mjs';
import {noteName,parseWrittenNotes,inScale,clipDocument,readSession,midiBytes,PITCH_NAMES} from './engine/music.mjs';
import {StringVoice} from './engine/dsp.mjs';
import {PitchScene} from './scene.mjs';
const $=id=>document.getElementById(id);
let presets=[],selected,params={...DEFAULTS,timing:'tempo',pitchMode:'stable',expression:true};
let notes=[],beats=8,takes=[],active=null,pending=null,lastAudition=null,customTitle=null,currentSource='reference';
let noteCount=16,phraseSelection=null,editBank=null,customDraft=null;
let demoExamples=[];
let audioContext,audioReady,starting=false,worklet,analyser,audioStart=0,shotSerial=0,comparisonTimer,kickTimer,recording=null,sketchNode=null;
const canvas=$('pitch'),scene=new PitchScene(canvas);let width=800,height=550,viewMode='kick';
const sceneSettings={muted:{decay:.7,brightness:.29,pluck:.13,space:.04,doppler:1,transpose:-12},singing:{decay:2.8,brightness:.65,pluck:.23,space:.18,doppler:3,transpose:0},space:{decay:5.7,brightness:.87,pluck:.39,space:.59,doppler:6,transpose:0}};
function toast(message){$('toast').textContent=message;$('toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').classList.remove('show'),4000);}
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);}
function rawConfig(){return {...params,notes,beats,title:customTitle||selected?.title||'My melody',slug:editBank?'my-melody':selected?.slug||'custom',source:currentSource};}
function currentConfig(){return sanitizeConfig(rawConfig());}
function formatControl(k,v){if(k==='distance')return v+' m';if(k==='loft')return v.toFixed(1)+' m';if(k==='power')return Math.round(v)+'%';if(k==='curl')return(v>=0?'+':'')+v.toFixed(2);if(k==='doppler')return v.toFixed(1).replace('.0','')+'×';if(k==='decay')return v.toFixed(1)+' s';return Math.round(v*100)+'%';}
function syncControls(){document.querySelectorAll('[data-scene]').forEach(b=>b.classList.toggle('active',Object.entries(sceneSettings[b.dataset.scene]).every(([k,v])=>Math.abs(params[k]-v)<.0001)));document.querySelectorAll('[data-control]').forEach(el=>{el.value=params[el.dataset.control];const out=$(el.id+'-out');if(out)out.value=formatControl(el.id,Number(el.value));});
  $('timing').value=params.timing;$('bpm').value=params.bpm;$('bars').value=params.bars;$('pitch-mode').value=params.pitchMode;$('key-root').value=params.root;$('scale').value=params.scale;
  $('bpm').disabled=params.timing!=='tempo';$('bars').disabled=params.timing!=='tempo';$('doppler').disabled=params.pitchMode==='stable';
  $('clock-info').textContent=params.timing==='tempo'?params.bars+' bars · '+flightDuration(rawConfig()).toFixed(2)+' seconds per shot':'Free flight · distance and power shape duration';
  $('pitch-help').textContent=params.pitchMode==='stable'?'Stable pitch keeps the written notes in tune. Power, loft, curl, distance and ambience remain expressive.':'Moving pitch enables Doppler. Its amount changes the pitch bend; try it for transitions and effects.';
  updatePhraseInfo();}
function updatePhraseInfo(){const c=active?active.config:rawConfig();$('phrase-info').textContent=c.notes.length+' NOTES / '+(c.timing==='tempo'?c.bars+' BARS / '+c.bpm+' BPM':flightDuration(c).toFixed(1)+' SEC');}
function selectNoteCount(requested){
  if(editBank){const count=clamp(Math.round(requested),1,Math.max(1,editBank.notes.length));
    phraseSelection=params.timing==='tempo'?{notes:editBank.notes.slice(0,count).map(n=>[...n]),beats:editBank.beats,phraseScale:editBank.phraseScale,maxNotes:editBank.notes.length}:editedPhrase(editBank,count);
  }else phraseSelection=referencePhrase(selected,Math.max(4,requested));
  notes=phraseSelection.notes;beats=phraseSelection.beats;params.phraseScale=phraseSelection.phraseScale;noteCount=notes.length;
  updateNoteCount();updateScore();updateEditor();renderGrid();saveDraft();
}
function updateNoteCount(){const max=editBank?editBank.notes.length:phraseSelection?.maxNotes||64;$('note-count').min=editBank?'1':'4';$('note-count').max=Math.max(1,max);$('note-count').value=Math.max(1,notes.length);$('note-count').disabled=max===0;$('note-count-out').value=notes.length+' / '+max;$('note-count-help').textContent=editBank?'Your written notes':params.timing==='tempo'?'Excerpt fits the chosen bars':'More notes · more flight time';}
function updateScore(){const shown=active?active.config.notes:notes,transpose=active?active.config.transpose:params.transpose;
  $('score').replaceChildren();$('score').classList.toggle('dense',shown.length>24);$('score').classList.toggle('very-dense',shown.length>40);
  shown.forEach((n,i)=>{const item=document.createElement('div');item.className='note';item.dataset.index=i;item.title=noteName(n[1]+transpose)+' · note '+(i+1);const bar=document.createElement('div');bar.className='note-bar';bar.style.height=clamp(7+(n[1]-48)*.65,4,33)+'px';const label=document.createElement('span');label.textContent=noteName(n[1]+transpose);item.append(bar,label);$('score').append(item);});updatePhraseInfo();}
function updateEditor(){
  $('note-editor').value=notes.map(n=>n.map((x,i)=>i===1?x:Number(x.toFixed(3))).join(', ')).join('\n');
  $('source-label').textContent=editBank?'Your editable phrase · '+notes.length+' notes':'Instrumental study · no vocals';
  if(editBank){$('source-note').textContent=currentSource==='original'?'Your original note sequence. Key and scale are guides; pitches are saved exactly as written.':currentSource;return;}
  $('source-note').replaceChildren();const link=document.createElement('a');link.href=selected.source_url;link.target='_blank';link.rel='noopener';link.textContent=selected.title+' — reference';$('source-note').append(link,document.createTextNode(' · Preview '+phraseSelection.sourceStart.toFixed(2)+'–'+phraseSelection.sourceEnd.toFixed(2)+' s. Automatic pitch study, not a verified transcription.'));
}
function selectPreset(slug){
  if(slug==='custom'){if(customDraft){loadDraft(customDraft);}else newMelody();return;}
  if(editBank)customDraft={notes:editBank.notes.map(n=>[...n]),beats:editBank.beats,title:customTitle,source:currentSource};
  selected=presets.find(p=>p.slug===slug)||presets[0];customTitle=null;editBank=null;currentSource=selected.source_url;
  $('song').value=selected.slug;$('song-artist').textContent=selected.artist;$('melody-name').value='';selectNoteCount(noteCount);
}
function useNotes(input,title,source='original',length=params.bars*4){
  notes=input.map(n=>[...n]).sort((a,b)=>a[0]-b[0]);beats=length;params.phraseScale=1;
  editBank={notes:notes.map(n=>[...n]),beats,phraseScale:1};customTitle=title||'My melody';currentSource=source;noteCount=notes.length;
  customDraft={notes:notes.map(n=>[...n]),beats,title:customTitle,source};$('song').value='custom';$('song-artist').textContent=source==='original'?'Your written notes':'Custom phrase · source recorded below';$('melody-name').value=customTitle;
  updateNoteCount();updateScore();updateEditor();renderGrid();saveDraft();
}
function newMelody(){useNotes([],'My melody','original',params.bars*4);$('write-status').textContent='Blank score ready. Add notes on the grid or write their names below.';}
function loadDraft(d){useNotes(d.notes,d.title,d.source,d.beats);}
function saveDraft(){if(!selected)return;try{localStorage.setItem('n5-draft-v2',JSON.stringify({params,notes,beats,title:customTitle,source:currentSource,preset:selected.slug,custom:!!editBank,customDraft}));}catch{}}
function renderGrid(){
  const root=$('piano-roll'),step=Number($('grid-step').value),total=params.bars*4,count=Math.round(total/step),base=(Number($('grid-octave').value)+1)*12;
  root.replaceChildren();root.style.setProperty('--steps',count);
  const blank=document.createElement('span');blank.className='piano-key roll-beat';blank.textContent='4 / 4';root.append(blank);
  for(let i=0;i<count;i++){const cell=document.createElement('span');cell.className='roll-beat';cell.textContent=i*step%4===0?String(1+Math.floor(i*step/4)):i*step%1===0?'·':'';root.append(cell);}
  let visible=0;
  for(let midi=base+23;midi>=base;midi--){const key=document.createElement('button');key.className='piano-key'+([1,3,6,8,10].includes(midi%12)?' black':'')+(midi%12===params.root?' tonic':'');key.textContent=noteName(midi);key.setAttribute('aria-label','Audition '+noteName(midi));key.onclick=()=>previewNote(midi);root.append(key);
    for(let i=0;i<count;i++){const beat=i*step,cell=document.createElement('button');const found=notes.some(n=>n[1]===midi&&Math.abs(n[0]/beats*total-beat)<step*.48);if(found)visible++;
      cell.className='roll-cell'+(inScale(midi,params.root,params.scale)?' in-scale':'')+(beat%4===0?' bar-start':'')+(found?' active':'');cell.setAttribute('aria-pressed',String(found));cell.setAttribute('aria-label',noteName(midi)+', bar '+(Math.floor(beat/4)+1)+', beat '+(beat%4+1));cell.title=noteName(midi)+' · beat '+(beat+1);cell.onclick=()=>{
        const normalized=notes.map(n=>[n[0]/beats*total,n[1],n[2]]),idx=normalized.findIndex(n=>n[1]===midi&&Math.abs(n[0]-beat)<step*.48);
        if(idx>=0)normalized.splice(idx,1);else{if(normalized.length>=64){toast('A phrase can contain up to 64 notes.');return;}normalized.push([beat,midi,.75]);previewNote(midi);}
        useNotes(normalized,$('melody-name').value||'My melody',editBank?currentSource:'Edited reference: '+selected.title+' · '+selected.source_url,total);
        $('write-status').textContent=active?'Melody changes apply to the next shot.':normalized.length+' notes ready for your next shot.';
      };root.append(cell);
    }
  }
  $('grid-info').textContent=notes.length+' notes · '+Math.max(0,notes.length-visible)+' outside this grid view';
}
async function previewNote(midi){if(active)return;try{await initAudio();const v=new StringVoice(audioContext.sampleRate,midi,.65,params,params.seed);const buffer=audioContext.createBuffer(1,Math.round(audioContext.sampleRate*.8),audioContext.sampleRate),data=buffer.getChannelData(0);for(let i=0;i<data.length;i++)data[i]=v.sample()*.5*Math.min(1,(data.length-i)/(audioContext.sampleRate*.08));const src=audioContext.createBufferSource();src.buffer=buffer;src.connect(audioContext.destination);src.start();}catch(e){toast(e.message);}}
async function initAudio(){
  if(!audioReady){audioReady=(async()=>{const AudioContextClass=window.AudioContext||window.webkitAudioContext;if(!AudioContextClass)throw new Error('This browser needs Web Audio support.');audioContext=new AudioContextClass({sampleRate:48000,latencyHint:'interactive'});
    if(!audioContext.audioWorklet)throw new Error('Launch the local server; AudioWorklet needs localhost or HTTPS.');
    await audioContext.audioWorklet.addModule('./engine/audio-worklet.js');worklet=new AudioWorkletNode(audioContext,'free-kick-processor',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2]});analyser=audioContext.createAnalyser();analyser.fftSize=1024;worklet.connect(analyser);analyser.connect(audioContext.destination);
    worklet.port.onmessage=({data})=>{if(data.type==='started'&&active){audioStart=data.audioTime;active.started=true;}if(data.type==='applied'&&active?.started){for(const [key,value]of Object.entries(data.params))if(['decay','brightness','pluck','space','doppler'].includes(key))active.config.automation.push({time:data.time,key,value});}if(data.type==='meter'&&active?.started&&!data.active)finishShot();};
  })().catch(error=>{audioContext?.close();audioContext=null;audioReady=null;throw error;});}await audioReady;await audioContext.resume();
}
function elapsed(){return active&&audioContext?Math.max(0,audioContext.currentTime-audioStart):0;}
function updateAudition(){const ready=!!pending&&!active;$('keep-shot').disabled=!ready||pending?.saved;$('keep-shot').textContent=pending?.saved?'Shot kept ✓':'Keep this shot +';$('discard-shot').disabled=!pending||!!active;
  if(active)$('audition-status').textContent='Listen through the performance. You can keep it when it finishes.';
  else if(pending)$('audition-status').textContent=pending.saved?'Kept in your session below. Try another shot or export this one.':pending.config.notes.length+' notes · '+flightDuration(pending.config).toFixed(2)+' s phrase. Keep this performance or try another.';
  else $('audition-status').textContent='Try a shot. Keep it when it feels right.';
}
function stopShot(){clearTimeout(comparisonTimer);clearTimeout(kickTimer);if(worklet)worklet.port.postMessage({type:'stop'});if(active){lastAudition=structuredClone(active.take);active=null;pending=null;}
  $('shoot').disabled=false;$('stop').disabled=true;$('field-status').textContent='READY WHEN YOU ARE';$('goal-callout').textContent='';$('field-hint').textContent='Click the goal to aim';$('audio-status').textContent='Audition stopped. Complete a shot to keep its full performance.';updateAudition();updateScore();persist();}
function finishShot(){pending=structuredClone(active.take);lastAudition=structuredClone(pending);active=null;$('shoot').disabled=false;$('stop').disabled=true;$('field-status').textContent='KEEP THIS ONE?';$('audio-status').textContent='Performance complete. Keep it below, or take another shot.';$('clip-name').value=pending.config.title;updateAudition();persist();updateScore();}
async function shoot(config=null){if(starting)return;starting=true;try{
  clearTimeout(comparisonTimer);if(active)stopShot();if(!config&&!notes.length)throw new Error('Add a note to your melody before taking a shot.');$('shoot').disabled=true;await initAudio();
  const c=sanitizeConfig(config||currentConfig()),take={id:++shotSerial,config:c,name:c.title,created:new Date().toISOString()};pending=null;
  active={config:c,take,goalShown:false,events:makeEvents(c),started:false,runup:performance.now()};lastAudition=structuredClone(take);audioStart=audioContext.currentTime+.7;
  kickTimer=setTimeout(()=>{if(active?.take===take)worklet.port.postMessage({type:'shot',config:c});},700);
  $('stop').disabled=false;$('replay').disabled=false;$('field-status').textContent='PHRASE IN FLIGHT';$('field-hint').textContent='Your shot. Your expression.';$('goal-callout').textContent='';$('shot-count').textContent='SHOT '+String(take.id).padStart(2,'0');$('audio-status').textContent='Live synthesis · '+(audioContext.sampleRate/1000)+' kHz stereo';updateAudition();updateScore();persist();
}catch(e){$('shoot').disabled=false;$('audio-status').textContent=e.message;toast(e.message);}finally{starting=false;}}
function persist(){try{localStorage.setItem('n5-session-v2',JSON.stringify({version:2,takes,pending,shotSerial}));}catch{toast('Browser storage is full. Download your session to keep a backup.');}}
function renderTakes(){
  $('takes-empty').hidden=takes.length>0;$('save-session').disabled=!takes.length;$('takes').replaceChildren();
  for(const take of [...takes].reverse()){
    const row=document.createElement('div');row.className='take';const num=document.createElement('span');num.className='take-num';num.textContent=String(take.id).padStart(2,'0');
    const name=document.createElement('div');name.className='take-title';const input=document.createElement('input');input.value=take.name||take.config.title;input.maxLength=120;input.setAttribute('aria-label','Name saved shot '+take.id);input.onchange=()=>{take.name=input.value.trim()||take.config.title;persist();};name.append(input);
    const c=take.config,info=document.createElement('small');info.textContent=c.notes.length+' notes · '+(c.timing==='tempo'?c.bars+' bars / '+c.bpm+' BPM':flightDuration(c).toFixed(2)+' s')+' · '+PITCH_NAMES[c.root]+' '+c.scale+' guide · '+(c.pitchMode==='stable'?'stable pitch':'moving pitch')+' · '+(c.automation?.length||0)+' live changes'+(take.stoppedAt?' · legacy partial audition; WAV renders full shot':'');name.append(info);
    const actions=document.createElement('div');actions.className='take-actions';const button=(text,fn)=>{const b=document.createElement('button');b.textContent=text;b.onclick=()=>fn(b);actions.append(b);return b;};
    button('Play ↗',()=>shoot(take.config));button('Edit',()=>loadTake(take));button('WAV ↓',b=>exportTake(take,b)).className='export';button('Shot ↓',()=>download(new Blob([JSON.stringify(clipDocument(take),null,2)],{type:'application/json'}),'N5-shot-'+take.id+'.json'));button('MIDI ↓',()=>download(new Blob([midiBytes(c)],{type:'audio/midi'}),'N5-notes-'+take.id+'.mid'));
    const remove=button('×',()=>{takes=takes.filter(t=>t!==take);renderTakes();persist();});remove.className='remove';remove.setAttribute('aria-label','Delete saved shot '+take.id);row.append(num,name,actions);$('takes').append(row);
  }
}
function loadTake(take,{announce=true}={}){if(active)stopShot();params={...take.config};delete params.automation;useNotes(take.config.notes,take.name||take.config.title,take.config.source,take.config.beats);params.phraseScale=take.config.phraseScale;editBank.phraseScale=params.phraseScale;syncControls();renderGrid();saveDraft();if(announce){toast('Loaded the notes and settings. This starts a fresh performance; the saved shot is unchanged.');$('shoot').scrollIntoView({behavior:'smooth',block:'center'});}}
function loadDemo(index){
  const take=demoExamples[index];if(!take)return;
  if(active||starting){toast('Let the current shot finish before choosing an example.');return;}
  loadTake(take,{announce:false});
  $('grid-step').value='1';$('grid-octave').value='3';
  $('written-notes').value=index===0?'A3 - C4 - E4 - G4 -':'';
  $('write-status').textContent=index===0?'Prepared note names match this four-note phrase. Take a shot to hear it.':'The prepared notes are already on the grid. Take a shot to hear them.';
  $('view-kick').onclick();$('show-gates').checked=true;renderGrid();
  $('demo-status').textContent=take.name+' loaded. Press Take the shot.';
  toast(take.name+' is ready. All note and sound settings are loaded.');
}
async function initDemos(loadFirst){
  try{
    const response=await fetch('./assets/demo-session.json');if(!response.ok)throw new Error('Example file unavailable');
    demoExamples=readSession(await response.json());
    const descriptions=['Four notes · short decay · stable pitch','Layered chords · ringing strings · stable pitch','Reference study · Doppler · open-air echoes'];
    demoExamples.forEach((take,index)=>{
      const button=document.createElement('button');button.className='demo-example';
      const title=document.createElement('b');title.textContent=take.name;
      const detail=document.createElement('span');detail.textContent=descriptions[index]||'Prepared notes and sound settings';
      button.append(title,detail);button.onclick=()=>loadDemo(index);$('demo-examples').append(button);
    });
    $('demo-status').textContent='Choose an example, then take the shot. Everything is set for you.';
    if(loadFirst)loadDemo(0);
  }catch{$('demo-status').textContent='Examples could not load. Refresh the page, or open assets/demo-session.json using Open session.';}
}
function exportTake(take,button){button.disabled=true;button.textContent='Rendering…';const worker=new Worker('./engine/export-worker.js',{type:'module'});worker.onmessage=({data})=>{worker.terminate();button.disabled=false;button.textContent='WAV ↓';if(data.error){toast(data.error);return;}download(new Blob([data.bytes],{type:'audio/wav'}),'N5-'+take.config.slug+'-shot-'+take.id+'.wav');toast('48 kHz stereo WAV · phrase starts at 0 · release tail included');};worker.onerror=()=>{worker.terminate();button.disabled=false;button.textContent='WAV ↓';toast('Export failed. Try the Node renderer.');};worker.postMessage({config:take.config});}
function draw(){
  width=canvas.clientWidth;height=canvas.clientHeight;if(!selected){requestAnimationFrame(draw);return;}
  const c=active?active.config:rawConfig(),T=flightDuration(c),t=active?(active.started?elapsed():(performance.now()-active.runup)/1000-.7):0;
  const p=scene.render(c,t,!!active,viewMode,$('show-gates').checked);$('height-readout').textContent=Math.max(0,p.z-.11).toFixed(1)+' m';
  if(active&&!active.goalShown&&t>=T){active.goalShown=true;$('goal-callout').textContent=isGoal(c)?(c.aimZ>1.7?'Top bins.':'Beautiful finish.'):'Just wide. Still your sound.';$('field-status').textContent='LET IT RING';}
  const events=active?.events||[],last=events.findLastIndex(ev=>t>=ev.time);document.querySelectorAll('#score .note').forEach((el,i)=>{el.classList.toggle('played',i<=last);el.classList.toggle('current',i===last&&t-events[i]?.time<.4);});
  const playhead=$('roll-playhead');playhead.hidden=!active||t<0||t>T;if(!playhead.hidden)playhead.style.left=(58+(t/T)*($('piano-roll').scrollWidth-58))+'px';
  requestAnimationFrame(draw);
}
function aim(event){if(active)return;const rect=canvas.getBoundingClientRect(),point=goalTargetAtPixel(event.clientX-rect.left,event.clientY-rect.top,makeCamera(width,height,params.distance,viewMode));if(!point)return;params.aimX=clamp(point.x,-5,5);params.aimZ=clamp(point.z,.15,3.3);saveDraft();}
canvas.addEventListener('pointerdown',e=>{canvas.setPointerCapture(e.pointerId);aim(e);});canvas.addEventListener('pointermove',e=>{if(e.buttons)aim(e);});
canvas.addEventListener('keydown',e=>{if(active)return;if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();params.aimX=clamp(params.aimX+(e.key==='ArrowRight'?.2:e.key==='ArrowLeft'?-.2:0),-5,5);params.aimZ=clamp(params.aimZ+(e.key==='ArrowUp'?.1:e.key==='ArrowDown'?-.1:0),.15,3.3);saveDraft();}});
$('reset-aim').onclick=()=>{params.aimX=DEFAULTS.aimX;params.aimZ=DEFAULTS.aimZ;saveDraft();};
for(const mode of ['kick','tactical'])$('view-'+mode).onclick=()=>{viewMode=mode;for(const name of ['kick','tactical']){$('view-'+name).classList.toggle('active',name===mode);$('view-'+name).setAttribute('aria-pressed',String(name===mode));}};
$('note-count').oninput=()=>{selectNoteCount(Number($('note-count').value));if(active)toast('Note changes apply to the next shot.');};
document.querySelectorAll('[data-control]').forEach(el=>el.addEventListener('input',()=>{const key=el.dataset.control;params[key]=Number(el.value);syncControls();if(key==='transpose')updateScore();
  if(active&&['decay','brightness','pluck','space','doppler'].includes(key)){if(active.started)worklet.port.postMessage({type:'params',params:{[key]:params[key]}});else active.config.automation.push({time:0,key,value:params[key]});}else if(active)$('audio-status').textContent='Geometry and register changes apply to the next shot. Sound controls are live.';saveDraft();
}));
for(const tab of ['flight','sound'])$('tab-'+tab).onclick=()=>{for(const name of ['flight','sound']){$('tab-'+name).classList.toggle('active',name===tab);$('tab-'+name).setAttribute('aria-selected',String(name===tab));$(name+'-controls').hidden=name!==tab;}};
document.querySelectorAll('[data-scene]').forEach(button=>button.onclick=()=>{Object.assign(params,sceneSettings[button.dataset.scene]);syncControls();updateScore();document.querySelectorAll('[data-scene]').forEach(b=>b.classList.toggle('active',b===button));if(active){if(active.started)worklet.port.postMessage({type:'params',params:sceneSettings[button.dataset.scene]});else for(const key of ['decay','brightness','pluck','space','doppler'])active.config.automation.push({time:0,key,value:params[key]});}saveDraft();toast('Sound set: '+button.querySelector('b').textContent);});
$('song').onchange=()=>{selectPreset($('song').value);if(active)toast('New phrase selected for the next shot.');};
$('shoot').onclick=()=>shoot();$('stop').onclick=stopShot;$('replay').onclick=()=>{const t=lastAudition||takes.at(-1);if(t)shoot(t.config);};
$('keep-shot').onclick=()=>{if(!pending||active||pending.saved)return;if(takes.length>=200){toast('Download a session backup before clearing space (200 saved shots).');return;}const kept=structuredClone(pending);kept.name=$('clip-name').value.trim()||kept.config.title;delete kept.saved;takes.push(kept);pending.saved=true;pending.name=kept.name;persist();renderTakes();updateAudition();toast('Shot kept with its notes, sound, trajectory and live changes.');};
$('discard-shot').onclick=()=>{pending=null;updateAudition();persist();};
window.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','TEXTAREA','SELECT','BUTTON','SUMMARY'].includes(document.activeElement?.tagName)&&!$('about').open){e.preventDefault();active?stopShot():shoot();}});
for(const id of ['timing','bpm','bars','pitch-mode','key-root','scale'])$(id).onchange=()=>{
  const key={timing:'timing',bpm:'bpm',bars:'bars','pitch-mode':'pitchMode','key-root':'root',scale:'scale'}[id];params[key]=['bpm','bars','root'].includes(key)?Number($(id).value):$(id).value;params.bpm=clamp(params.bpm||140,60,180);syncControls();updateNoteCount();renderGrid();saveDraft();if(active)toast('Musical settings apply to the next shot.');
};
for(const id of ['grid-step','grid-octave'])$(id).onchange=renderGrid;
$('new-melody').onclick=newMelody;$('write-melody').onclick=()=>{if(!editBank){if(customDraft)loadDraft(customDraft);else newMelody();}$('composer').scrollIntoView({behavior:'smooth',block:'start'});};
$('melody-name').onchange=()=>{if(editBank){customTitle=$('melody-name').value.trim()||'My melody';if(customDraft)customDraft.title=customTitle;saveDraft();}};
$('apply-written').onclick=()=>{try{const parsed=parseWrittenNotes($('written-notes').value,Number($('grid-step').value));if(parsed.beats>params.bars*4){const needed=[1,2,4].find(b=>b*4>=parsed.beats);if(!needed)throw new Error('This phrase exceeds 4 bars. Use a smaller grid step or fewer notes.');params.bars=needed;}
  const min=Math.min(...parsed.notes.map(n=>n[1]));$('grid-octave').value=clamp(Math.floor(min/12)-1,2,5);useNotes(parsed.notes,$('melody-name').value||'My melody','original',params.bars*4);syncControls();$('write-status').textContent='Your '+notes.length+' notes are ready. Take a shot to hear the full phrase.';
}catch(e){$('write-status').textContent=e.message;}};

$('about-open').onclick=async()=>{$('about').showModal();try{$('dsp-source').textContent=await(await fetch('./engine/dsp.mjs')).text();}catch{$('dsp-source').textContent='Open src/engine/dsp.mjs in your editor.';}};$('about-close').onclick=()=>$('about').close();
$('about').addEventListener('click',e=>{if(e.target===$('about')){const r=$('about').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('about').close();}});
// Display capture and microphone access only occur after the user's own click.
$('record-demo').onclick=async()=>{
  if(recording){recording.recorder.stop();return;}
  let screen,microphone;
  try{
    if(!navigator.mediaDevices?.getDisplayMedia||!window.MediaRecorder)throw new Error('Screen recording is unavailable here. Use OBS or Zoom and capture system audio + your voice.');
    screen=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:30},audio:false});
    microphone=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
    await initAudio();const destination=audioContext.createMediaStreamDestination();
    worklet.connect(destination);const mic=audioContext.createMediaStreamSource(microphone);mic.connect(destination);
    if(!sketchNode){sketchNode=audioContext.createMediaElementSource($('sketch-player'));sketchNode.connect(audioContext.destination);}sketchNode.connect(destination);
    const stream=new MediaStream([...screen.getVideoTracks(),...destination.stream.getAudioTracks()]);
    const mime=['video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
    const recorder=new MediaRecorder(stream,{...(mime?{mimeType:mime}:{}),videoBitsPerSecond:1800000,audioBitsPerSecond:128000});
    const chunks=[],started=performance.now();
    const cleanup=()=>{screen.getTracks().forEach(t=>t.stop());microphone.getTracks().forEach(t=>t.stop());worklet.disconnect(destination);mic.disconnect();sketchNode.disconnect(destination);clearTimeout(recording?.timeout);recording=null;$('record-demo').textContent='Record your demo';};
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    recorder.onstop=()=>{const seconds=(performance.now()-started)/1000;const type=recorder.mimeType;cleanup();download(new Blob(chunks,{type}),'N5-demo.'+(type.includes('mp4')?'mp4':'webm'));$('record-status').textContent='Saved '+Math.round(seconds)+' seconds. '+(seconds<120?'This is shorter than the required 2 minutes. ':seconds>300?'This exceeds 5 minutes. ':'')+'Use tools/package.py to convert and package the recording.';};
    recorder.onerror=()=>{cleanup();toast('Recording failed. Use OBS or Zoom.');};
    recording={recorder,timeout:setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},295000)};
    screen.getVideoTracks()[0].onended=()=>{if(recorder.state==='recording')recorder.stop();};
    recorder.start(1000);$('record-demo').textContent='Stop & save recording';$('record-status').textContent='Recording your selected screen, instrument audio, and microphone. Use headphones. Stops automatically before 5 minutes.';
  }catch(error){screen?.getTracks().forEach(t=>t.stop());microphone?.getTracks().forEach(t=>t.stop());$('record-status').textContent=error.message;}
};
$('comparison').onclick=async()=>{
  $('about').close();const base={...currentConfig(),notes:[[0,57,.9],[1,57,.7],[2,57,.8],[3,57,.8]],beats:4,phraseScale:1,pitchMode:'moving',timing:'flight',expression:false,space:0,decay:4,brightness:.85,distance:36,power:75};
  await shoot({...base,doppler:0,title:'Doppler A — stationary propagation'});toast('A: Doppler off. The same phrase with motion follows.');
  comparisonTimer=setTimeout(async()=>{await shoot({...base,doppler:8,title:'Doppler B — moving propagation'});toast('B: Doppler 8×. Listen for the pitch falling past the microphone.');},(flightDuration(base)+7.4)*1000);
};
function applyEditor(addOne=false){try{
  const parsed=$('note-editor').value.trim().split('\n').filter(Boolean).map(line=>line.split(',').map(Number));if(addOne){if(parsed.length>=64)throw new Error('Maximum 64 notes.');const last=parsed.at(-1)||[0,60,.7];parsed.push([Number(last[0])+.5,Number(last[1]),.7]);}
  const c=sanitizeConfig({...rawConfig(),notes:parsed,beats:Math.max(beats,...parsed.map(n=>n[0]+.5))});useNotes(c.notes,$('melody-name').value||'Edited melody',editBank?currentSource:'Edited reference: '+selected.source_url,c.beats);$('editor-status').textContent='Phrase applied.';
}catch(e){$('editor-status').textContent=e.message;}}
$('apply-notes').onclick=()=>applyEditor();$('add-note').onclick=()=>applyEditor(true);$('restore-notes').onclick=()=>selectPreset(selected.slug);
$('import-midi').onclick=()=>$('midi-file').click();$('midi-file').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;const imported=readMidi(await f.arrayBuffer());useNotes(imported,f.name.replace(/\.(mid|midi)$/i,''),'Imported MIDI: '+f.name,Math.max(params.bars*4,imported.at(-1)[0]+.5));$('editor-status').textContent='Imported '+notes.length+' notes. Credit the MIDI source if it is not your own.';}catch(err){$('editor-status').textContent=err.message;}e.target.value='';};
$('save-session').onclick=()=>download(new Blob([JSON.stringify({version:2,takes},null,2)],{type:'application/json'}),'N5-session.json');
$('load-session').onclick=()=>$('session-file').click();$('session-file').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;const imported=readSession(JSON.parse(await f.text()));if(takes.length+imported.length>200)throw new Error('This would exceed 200 saved shots. Download a backup before clearing space.');takes.push(...imported.map(t=>({...t,id:++shotSerial})));persist();renderTakes();$('replay').disabled=!takes.length;toast('Imported '+imported.length+' saved shots.');}catch(err){toast(err.message);}e.target.value='';};
async function init(){try{
  const response=await fetch('./presets.json');if(!response.ok)throw new Error('Could not load presets.');presets=await response.json();
  for(const p of presets){const opt=document.createElement('option');opt.value=p.slug;opt.textContent=p.title;$('song').append(opt);}const custom=document.createElement('option');custom.value='custom';custom.textContent='My own melody';$('song').append(custom);
  let draft;try{draft=JSON.parse(localStorage.getItem('n5-draft-v2'));}catch{}
  selectPreset(presets[0].slug);
  if(draft&&Array.isArray(draft.notes)){try{if(draft.customDraft?.notes?.length<=64)customDraft=draft.customDraft;noteCount=draft.notes.length||16;const checked=sanitizeConfig({...draft.params,notes:draft.notes.length?draft.notes:[[0,60,.7]],beats:draft.beats});params={...checked};if(draft.custom)useNotes(draft.notes,draft.title,draft.source,draft.beats);else selectPreset(draft.preset);}catch{}}
  syncControls();renderGrid();
  try{const raw=localStorage.getItem('n5-session-v2'),stored=JSON.parse(raw||localStorage.getItem('n5-session-v1'));if(stored){takes=readSession(stored).map((t,i)=>({...t,id:i+1}));shotSerial=Math.max(takes.length,Number(stored.shotSerial)||0);if(stored.pending?.config){pending={...stored.pending,config:sanitizeConfig(stored.pending.config)};lastAudition=structuredClone(pending);$('clip-name').value=pending.name||pending.config.title;}}}catch{toast('Saved data could not be read. It has been left untouched; use Open session for a backup.');}
  renderTakes();updateAudition();$('replay').disabled=!(takes.length||lastAudition);requestAnimationFrame(draw);
  await initDemos(!draft&&!takes.length&&!pending);
}catch(e){$('audio-status').textContent=e.message+' Start the local server before opening this page.';console.error(e);}}
init();

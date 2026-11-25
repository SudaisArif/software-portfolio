import {clamp,flightDuration} from './physics.mjs';
import {sanitizeConfig} from './session.mjs';
export const PITCH_NAMES=['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'];
export const noteName=m=>PITCH_NAMES[((m%12)+12)%12]+(Math.floor(m/12)-1);
export function inScale(m,root,scale){return scale==='chromatic'||(scale==='major'?[0,2,4,5,7,9,11]:[0,2,3,5,7,8,10]).includes(((m-root)%12+12)%12);}
export function parseWrittenNotes(text,step=.5){
  const tokens=text.trim().split(/\s+/).filter(Boolean),notes=[];
  if(!tokens.length)throw new Error('Write a few notes first, such as A3 C4 E4 - G4.');
  tokens.forEach((token,i)=>{
    if(token==='-'||token==='_')return;
    const chord=token.split('+');
    for(const name of chord){
      const match=/^([A-Ga-g])([#b♯♭]?)([2-7])$/.exec(name);
      if(!match)throw new Error('Use note names with octaves (C4, F#4, Bb3), + for chords, and - for rests.');
      const midi=(Number(match[3])+1)*12+{C:0,D:2,E:4,F:5,G:7,A:9,B:11}[match[1].toUpperCase()]+(['#','♯'].includes(match[2])?1:['b','♭'].includes(match[2])?-1:0);
      if(midi<36||midi>96)throw new Error('Use notes from C2 to C7.');
      notes.push([i*step,midi,.75]);
    }
  });
  if(!notes.length||notes.length>64)throw new Error('Write 1–64 notes.');
  return {notes,beats:tokens.length*step};
}
export function clipDocument(take){
  const config=sanitizeConfig(take.config);
  return {version:2,kind:'n5-shot',takes:[{...take,config}],
    musical:{bpm:config.timing==='tempo'?config.bpm:null,bars:config.timing==='tempo'?config.bars:null,
      key:PITCH_NAMES[config.root]+' '+config.scale,phraseSeconds:flightDuration(config),
      phraseFrames:Math.round(flightDuration(config)*48000),sampleRate:48000,pitchMode:config.pitchMode,
      placement:'Align WAV start to the bar. The remaining audio is a release tail; overlap it with the next clip.'}};
}
export function readSession(data){
  if(!data||![1,2].includes(data.version)||!Array.isArray(data.takes)||data.takes.length>200)throw new Error('Use an N5 shot/session JSON file (up to 200 saved shots).');
  return data.takes.map(t=>{
    if(!t||typeof t!=='object')throw new Error('Invalid saved shot.');
    return {config:sanitizeConfig(t.config),name:String(t.name||t.config?.title||'Saved shot').slice(0,120),
      created:typeof t.created==='string'?t.created:new Date().toISOString(),
      ...(Number.isFinite(t.stoppedAt)?{stoppedAt:t.stoppedAt}:{})};
  });
}
// Type-0 MIDI: notes and tempo, without the synthesized timbre or continuous motion.
export function midiBytes(config){
  const c=sanitizeConfig(config),ppq=480,bpm=c.timing==='tempo'?c.bpm:120;
  const scale=c.timing==='tempo'?c.bars*4/c.beats:flightDuration(c)*bpm/60/c.beats;
  const events=[];for(const n of c.notes){const start=Math.round(n[0]*scale*ppq),pitch=clamp(n[1]+c.transpose,0,127);
    events.push({tick:start,bytes:[0x90,pitch,Math.round(n[2]*127)]},{tick:start+Math.round(ppq*.45),bytes:[0x80,pitch,0]});}
  events.sort((a,b)=>a.tick-b.tick||a.bytes[0]-b.bytes[0]);
  const vlq=n=>{const a=[n&127];while(n>>=7)a.unshift((n&127)|128);return a;};
  const us=Math.round(60000000/bpm),track=[0,255,81,3,(us>>16)&255,(us>>8)&255,us&255,0,255,88,4,4,2,24,8];let last=0;
  for(const ev of events){track.push(...vlq(ev.tick-last),...ev.bytes);last=ev.tick;}
  track.push(0,255,47,0);const len=track.length;
  return new Uint8Array([77,84,104,100,0,0,0,6,0,0,0,1,ppq>>8,ppq&255,77,84,114,107,(len>>>24)&255,(len>>>16)&255,(len>>>8)&255,len&255,...track]);
}

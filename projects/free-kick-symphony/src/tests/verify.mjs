import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {Engine,StringVoice,FractionalDelay,renderShot,wavBytes,midiHz} from '../engine/dsp.mjs';
import {DEFAULTS,flightDuration,makeEvents} from '../engine/physics.mjs';
import {sanitizeConfig,readMidi} from '../engine/session.mjs';
const fsamp=48000;
function rms(x,a=0,b=x.length){let s=0;for(let i=a;i<b;i++)s+=x[i]*x[i];return Math.sqrt(s/(b-a));}
function estimatePitch(x,target){
  const start=2400,n=Math.min(12000,x.length-start-1000);
  const lo=Math.floor(fsamp/target*.9),hi=Math.ceil(fsamp/target*1.1),corr=[];
  for(let lag=lo-1;lag<=hi+1;lag++){let s=0,a=0,b=0;for(let i=start;i<start+n;i++){s+=x[i]*x[i+lag];a+=x[i]**2;b+=x[i+lag]**2;}corr.push(s/Math.sqrt(a*b));}
  let best=1;for(let i=2;i<corr.length-1;i++)if(corr[i]>corr[best])best=i;
  const delta=.5*(corr[best-1]-corr[best+1])/(corr[best-1]-2*corr[best]+corr[best+1]);
  return fsamp/(lo-1+best+delta);
}
function assertFinite(x){for(const v of x)assert(Number.isFinite(v)&&Math.abs(v)<=1,'Finite bounded output');}
const results=[];
for(const midi of [48,60,69,72,84]){
  const voice=new StringVoice(fsamp,midi,.8,{...DEFAULTS,brightness:.9,decay:4},42);
  const data=Float32Array.from({length:24000},()=>voice.sample());
  const measured=estimatePitch(data,midiHz(midi)),cents=1200*Math.log2(measured/midiHz(midi));
  assert(Math.abs(cents)<8,'String tuning within 8 cents: '+midi+' error '+cents);
  results.push('Tuning '+midi+': '+cents.toFixed(2)+' cents');
}
// A moving read head must produce the predicted frequency change, not merely gain changes.
for(const slope of [-.08,0,.08]){
  const delay=new FractionalDelay(fsamp),data=new Float32Array(fsamp);
  for(let i=0;i<data.length;i++){data[i]=delay.read(8000+slope*i);delay.write(Math.sin(2*Math.PI*440*i/fsamp));}
  const part=data.slice(12000),pitch=estimatePitch(part,440*(1-slope));
  assert(Math.abs(pitch-440*(1-slope))<.5,'Moving-delay Doppler frequency');
  results.push('Doppler slope '+slope+': '+pitch.toFixed(2)+' Hz');
}
function stringData(p){const v=new StringVoice(fsamp,57,.8,{...DEFAULTS,...p},42);return Float32Array.from({length:fsamp*2},()=>v.sample());}
const short=stringData({decay:.4}),long=stringData({decay:5});
assert(rms(long,fsamp,fsamp*2)>rms(short,fsamp,fsamp*2)*3,'Decay audibly changes late energy');
const dark=stringData({brightness:.1}),bright=stringData({brightness:.95});
function differenceEnergy(x){let s=0;for(let i=1;i<12000;i++)s+=(x[i]-x[i-1])**2;return s;}
assert(differenceEnergy(bright)>differenceEnergy(dark)*1.3,'Brightness increases high-frequency energy');
const pluckA=stringData({pluck:.1}),pluckB=stringData({pluck:.48});
assert(rms(pluckA.map((x,i)=>x-pluckB[i]))>.01,'Pluck position changes excitation');
results.push('Decay, brightness, pluck-position sensitivity: passed');
const presets=JSON.parse(fs.readFileSync(new URL('../presets.json',import.meta.url),'utf8'));
for(const preset of presets){
  const c=sanitizeConfig({...DEFAULTS,...preset});const a=renderShot(c);
  assertFinite(a.left);assertFinite(a.right);assert(rms(a.left)>.001,'Non-silent preset');
  assert(makeEvents(c).at(-1).time<flightDuration(c),'All notes inside flight');
  const bytes=wavBytes(a),v=new DataView(bytes);assert.equal(v.getUint16(22,true),2);assert.equal(v.getUint32(24,true),48000);assert.equal(bytes.byteLength,44+a.left.length*4);
  results.push(preset.slug+': audible, stereo WAV, bounded');
}
const c={...DEFAULTS,...presets[0],automation:[{time:1,key:'brightness',value:.2},{time:2,key:'doppler',value:8}]};
const a=renderShot(c),b=renderShot(c);assert.deepEqual(a.left,b.left,'Seeded exports are deterministic');
const manual=new Engine(fsamp);manual.reset({...c,automation:[]});
for(let i=0;i<a.left.length;i++){if(i===fsamp)manual.setParams({brightness:.2});if(i===2*fsamp)manual.setParams({doppler:8});const sample=manual.tick();assert.equal(Math.fround(sample[0]),a.left[i],'Automation reproduces live parameter timing');}
results.push('Deterministic export and live-automation replay: passed');
assert.throws(()=>sanitizeConfig({...c,notes:[[0,NaN,1]]}));
assert.throws(()=>sanitizeConfig({...c,notes:new Array(65).fill([0,60,1])}));
// Minimal valid MIDI: note on C4, 480 ticks later E4, end track.
const midi=new Uint8Array([77,84,104,100,0,0,0,6,0,0,0,1,1,224,77,84,114,107,0,0,0,13,0,144,60,100,131,96,144,64,90,0,255,47,0]);
assert.deepEqual(readMidi(midi.buffer).map(n=>n.slice(0,2)),[[0,60],[1,64]]);
results.push('Session validation and MIDI import: passed');
console.log(results.join('\n'));console.log('All signal and data checks passed.');

import assert from 'node:assert/strict';
import {DEFAULTS,flightDuration,makeEvents,expressionAt,listenerGeometry} from '../engine/physics.mjs';
import {renderShot,Engine} from '../engine/dsp.mjs';
import {sanitizeConfig,readMidi} from '../engine/session.mjs';
import {parseWrittenNotes,clipDocument,readSession,midiBytes} from '../engine/music.mjs';
const phrase=parseWrittenNotes('A3 C4 E4 - G4 E4 D4 C4',.5);
assert.deepEqual(phrase.notes.map(n=>n[1]),[57,60,64,67,64,62,60]);
assert.equal(phrase.notes[3][0],2,'Written rests keep their timing');
assert.deepEqual(parseWrittenNotes('C4+E4+G4 F#4 Bb3').notes.map(n=>n[1]),[60,64,67,66,58]);
assert.throws(()=>parseWrittenNotes('H4'));assert.throws(()=>parseWrittenNotes('- -'));
const base=sanitizeConfig({...DEFAULTS,...phrase,beats:8,timing:'tempo',bpm:120,bars:2,expression:true,pitchMode:'stable',source:'original'});
for(const bpm of [60,120,180])for(const bars of [1,2,4]){
  const c={...base,bpm,bars};assert.equal(flightDuration(c),bars*4*60/bpm);
  const events=makeEvents(c);assert.equal(events[0].time,0);assert(events.at(-1).time<flightDuration(c));
  for(const power of [20,100])for(const distance of [18,36])assert.deepEqual(makeEvents({...c,power,distance}),events,'Shot expression cannot move musical onsets');
}
const low=expressionAt(2,{...base,loft:.4}),high=expressionAt(2,{...base,loft:5});assert(high.brightness>low.brightness&&high.space>low.space);
assert(expressionAt(0,{...base,power:100}).brightness>expressionAt(0,{...base,power:20}).brightness);
assert(listenerGeometry(2,{...base,aimX:0,curl:-1}).pan<0);assert(listenerGeometry(2,{...base,aimX:0,curl:1}).pan>0);
const stableA=renderShot({...base,doppler:0}),stableB=renderShot({...base,doppler:8});assert.deepEqual(stableA.left,stableB.left,'Stable pitch ignores Doppler amount');
const moving=renderShot({...base,pitchMode:'moving',doppler:8});assert.notDeepEqual(stableA.left,moving.left);
for(const tweak of [{power:20},{loft:5},{curl:-1},{distance:36}]){const a=renderShot({...base,...tweak});let energy=0,delta=0;for(let i=0;i<a.left.length;i++){assert(Number.isFinite(a.left[i])&&Math.abs(a.left[i])<1);energy+=a.left[i]**2;delta+=(a.left[i]-stableA.left[i])**2;}assert(energy>.01&&delta>.01,'Shot controls have audible consequences');}
const take={id:1,name:'Original hook',created:'2026-11-16T00:00:00Z',config:{...base,automation:[{time:1,key:'brightness',value:.2},{time:2,key:'space',value:.4}]}};
const doc=clipDocument(take),roundTrip=readSession(JSON.parse(JSON.stringify(doc)))[0];assert.deepEqual(roundTrip.config,take.config);assert.equal(doc.musical.phraseFrames,192000);assert.equal(roundTrip.name,take.name);
const a=renderShot(take.config),b=renderShot(roundTrip.config);assert.deepEqual(a.left,b.left);assert.deepEqual(a.right,b.right);
const manual=new Engine();manual.reset({...take.config,automation:[]});for(let i=0;i<a.left.length;i++){if(i===48000)manual.setParams({brightness:.2});if(i===96000)manual.setParams({space:.4});assert.equal(Math.fround(manual.tick()[0]),a.left[i]);}
const midi=readMidi(midiBytes(base).buffer);assert.deepEqual(midi.map(n=>n.slice(0,2)),base.notes.map(n=>n.slice(0,2)));
const legacy=readSession({version:1,takes:[{config:{notes:[[0,60,.8]],power:50}}]})[0];assert.equal(legacy.config.timing,'flight');assert.equal(legacy.config.expression,false);assert.equal(legacy.config.pitchMode,'moving');
assert.throws(()=>readSession({version:9,takes:[]}));
console.log('Written notes/chords/rests, exact bar timing, all four shot-expression controls, stable/moving pitch, MIDI, legacy sessions, saved-shot reproducibility and live automation passed.');

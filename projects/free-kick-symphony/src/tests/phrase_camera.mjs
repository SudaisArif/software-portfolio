import assert from 'node:assert/strict';
import fs from 'node:fs';
import {referencePhrase,editedPhrase} from '../engine/phrase.mjs';
import {makeCamera,projectPoint,goalTargetAtPixel,clipLine,clipPolygon,depthOf} from '../engine/camera.mjs';
import {DEFAULTS,flightDuration,positionAt,makeEvents} from '../engine/physics.mjs';
import {sanitizeConfig} from '../engine/session.mjs';
import {renderShot} from '../engine/dsp.mjs';
const presets=JSON.parse(fs.readFileSync(new URL('../presets.json',import.meta.url),'utf8'));
for(const preset of presets){
  const cap=Math.min(64,preset.phraseLibrary.events.length);let previousDuration=0;
  for(let count=4;count<=cap;count++){
    const phrase=referencePhrase(preset,count),config=sanitizeConfig({...DEFAULTS,...preset,...phrase});
    assert.equal(phrase.notes.length,count);
    const bank=preset.phraseLibrary.events;
    const first=Math.min(preset.phraseLibrary.anchor,bank.length-count);
    assert.deepEqual(phrase.notes.map(n=>n[1]),bank.slice(first,first+count).map(n=>n.midi),'No invented/looped pitches');
    for(let i=1;i<phrase.notes.length;i++)assert(phrase.notes[i][0]>phrase.notes[i-1][0],'Strictly ordered events');
    const duration=flightDuration(config);assert(duration>=previousDuration-1e-4,'Longer phrase does not accelerate the flight');previousDuration=duration;
    assert(makeEvents(config).at(-1).time<duration);
    assert.equal(sanitizeConfig(JSON.parse(JSON.stringify(config))).phraseScale,config.phraseScale);
  }
  const full={...DEFAULTS,...preset,...referencePhrase(preset,cap)};
  const audio=renderShot(full);let energy=0;
  for(const ch of [audio.left,audio.right])for(const x of ch){assert(Number.isFinite(x)&&Math.abs(x)<=1);energy+=x*x;}
  assert(energy>1);
  console.log(preset.slug+': 4–'+cap+' genuine extracted events; longest take '+audio.duration.toFixed(1)+'s renders cleanly.');
}
const bank={notes:[[0,60,.8],[1,64,.7],[2,67,.7],[3,69,.6]],beats:4,phraseScale:2};
const original=JSON.stringify(bank);editedPhrase(bank,1);assert.equal(JSON.stringify(bank),original);assert.equal(editedPhrase(bank,4).notes.length,4);
assert.equal(sanitizeConfig({...DEFAULTS,notes:[[0,60,.8]],automation:[{time:45,key:'brightness',value:.4}]}).automation.length,1);
for(const mode of ['kick','tactical'])for(const distance of [18,24,36])for(const [w,h]of [[360,350],[1000,600]]){
  const camera=makeCamera(w,h,distance,mode);
  for(const x of [-3.66,0,3.66])for(const z of [0,1.2,2.44]){
    const pixel=projectPoint({x,y:0,z},camera),inverse=goalTargetAtPixel(pixel.x,pixel.y,camera);
    assert(Math.abs(inverse.x-x)<1e-9&&Math.abs(inverse.z-z)<1e-9,'Click-to-aim matches projection');
  }
  assert(projectPoint({x:0,y:12,z:4},camera).y<projectPoint({x:0,y:12,z:0},camera).y,'Height reads upwards');
  if(mode==='kick'){
    assert(projectPoint({x:0,y:distance,z:0},camera).s>projectPoint({x:0,y:0,z:0},camera).s,'Near objects appear larger');
    const line=clipLine({x:1,y:camera.y+2,z:0},{x:1,y:0,z:0},camera);
    assert(line&&line.every(p=>depthOf(p,camera)>=camera.near-1e-9));
    const poly=clipPolygon([{x:-1,y:0,z:0},{x:1,y:0,z:0},{x:1,y:camera.y+4,z:0},{x:-1,y:camera.y+4,z:0}],camera);
    assert(poly.length>=3&&poly.every(p=>depthOf(p,camera)>=camera.near-1e-9));
  }
}
const low={...DEFAULTS,loft:.4},high={...DEFAULTS,loft:5};
assert(positionAt(flightDuration(high)/2,high).z>positionAt(flightDuration(low)/2,low).z+4);
console.log('Editable note bank, long-take automation, perspective aim inversion, depth clipping, and loft checks passed.');

// Integration of the real processor module with 128-frame worklet callbacks.
// This does not replace a live browser/device test.
import assert from 'node:assert/strict';
import {renderShot} from '../engine/dsp.mjs';
import {DEFAULTS} from '../engine/physics.mjs';
globalThis.sampleRate=48000;globalThis.currentTime=0;
let Processor;const messages=[];
globalThis.AudioWorkletProcessor=class {constructor(){this.port={postMessage:m=>messages.push(m),onmessage:null};}};
globalThis.registerProcessor=(name,p)=>{assert.equal(name,'free-kick-processor');Processor=p;};
await import('../engine/audio-worklet.js');
const p=new Processor(),config={...DEFAULTS,notes:[[0,57,.8],[1,64,.7],[2,60,.8]],beats:3};
const expected=renderShot({...config,automation:[{time:1,key:'brightness',value:.2}]});
p.port.onmessage({data:{type:'shot',config}});
for(let base=0;base<expected.left.length;base+=128){
  globalThis.currentTime=base/48000;
  if(base===48000)p.port.onmessage({data:{type:'params',params:{brightness:.2}}});
  const l=new Float32Array(128),r=new Float32Array(128);
  assert.equal(p.process([],[[l,r]]),true);
  for(let i=0;i<Math.min(128,expected.left.length-base);i++){
    assert.equal(l[i],expected.left[base+i]);assert.equal(r[i],expected.right[base+i]);
  }
}
assert(messages.some(m=>m.type==='started'));
assert(messages.some(m=>m.type==='applied'&&m.time===1&&m.params.brightness===.2),'Live automation records the actual audio boundary');
p.port.onmessage({data:{type:'shot',config}});p.port.onmessage({data:{type:'stop'}});
for(let i=0;i<3;i++)p.process([],[[new Float32Array(128),new Float32Array(128)]]);
assert.equal(p.engine.active,false);
console.log('AudioWorklet block rendering exactly matches offline stereo output, including a live control change. Graceful stop passed.');

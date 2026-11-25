// Original low-level DSP. No synthesizer, reverb, or pitch-shift libraries.
// Shared by AudioWorklet (live), browser export, and Node (offline/tests).
import {clamp, DEFAULTS, flightDuration, listenerGeometry, makeEvents, expressionAt} from './physics.mjs';
export const midiHz = m => 440 * 2 ** ((m-69)/12);
export function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => {s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return (s >>> 0)/4294967296;};
}

export class FractionalDelay {
  constructor(size) { this.data = new Float64Array(Math.ceil(size)+4); this.head=0; }
  read(delay) {
    const n=this.data.length;
    let p=this.head-clamp(delay, 1, n-2); if(p<0) p+=n;
    const i=Math.floor(p), a=p-i;
    return this.data[i]*(1-a)+this.data[(i+1)%n]*a;
  }
  write(x) {this.data[this.head]=x; this.head=(this.head+1)%this.data.length;}
}

export class StringVoice {
  constructor(fs, midi, velocity, p, seed) {
    this.fs=fs; this.f=midiHz(midi); this.velocity=velocity;
    this.line=new FractionalDelay(fs/16+4); this.age=0; this.last=0;
    this.dcX=0; this.dcY=0; this.energy=0;
    this.setParams(p, true);
    const random=rng(seed), period=Math.ceil(fs/this.f);
    const noise=new Float64Array(period);
    let mean=0; for(let i=0;i<period;i++){noise[i]=random()*2-1;mean+=noise[i]/period;}
    // Difference of shifted noise models the spectral notches of pluck position.
    const offset=Math.max(1,Math.round(period*p.pluck));
    const excite=new Float64Array(period); let peak=0;
    for(let i=0;i<period;i++) {excite[i]=(noise[i]-mean)-(noise[(i+offset)%period]-mean);peak=Math.max(peak,Math.abs(excite[i]));}
    for(let i=0;i<period;i++) this.line.write(excite[i]/Math.max(peak,0.01)*0.46);
  }
  setParams(p, immediate=false) {
    this.targetA=0.04+(1-clamp(p.brightness,0.05,0.98))*0.60;
    // Approximate T60: filter loss makes actual upper partials decay faster.
    this.targetG=Math.exp(-6.907755/(this.f*clamp(p.decay,0.2,7)));
    this.targetG=Math.min(this.targetG,0.9998);
    if(immediate){this.a=this.targetA;this.g=this.targetG;}
    const w=2*Math.PI*this.f/this.fs;
    const phaseDelay=Math.atan2(this.targetA*Math.sin(w),1-this.targetA*Math.cos(w))/w;
    this.targetDelay=this.fs/this.f-phaseDelay;
    if(immediate) this.delay=this.targetDelay;
  }
  sample() {
    // Smooth changing loss/brightness/delay to avoid zipper noise.
    this.a+=(this.targetA-this.a)*0.001;
    this.g+=(this.targetG-this.g)*0.001;
    this.delay+=(this.targetDelay-this.delay)*0.001;
    const wave=this.line.read(this.delay);
    this.last=(1-this.a)*wave+this.a*this.last;
    this.line.write(this.g*this.last);
    // Remove the DC component left by a finite excitation buffer.
    const y=wave-this.dcX+0.995*this.dcY; this.dcX=wave;this.dcY=y;
    const attack=Math.min(1,this.age/(this.fs*0.003));
    this.age++;this.energy=0.999*this.energy+0.001*y*y;
    return y*this.velocity*attack;
  }
  get alive(){return this.age<this.fs*10 && (this.age<this.fs*0.12||this.energy>1e-10);}
}

class Comb {
  constructor(n,g){this.b=new Float64Array(n);this.i=0;this.g=g;this.lp=0;}
  tick(x){const y=this.b[this.i];this.lp=0.6*y+0.4*this.lp;this.b[this.i]=x+this.g*this.lp;this.i=(this.i+1)%this.b.length;return y;}
}
class Stadium {
  constructor(fs){this.left=[.0437,.0593,.0719].map((t,i)=>new Comb(Math.round(t*fs),.70-i*.04));this.right=[.0479,.0617,.0781].map((t,i)=>new Comb(Math.round(t*fs),.69-i*.04));}
  tick(x){return [this.left.reduce((s,c)=>s+c.tick(x),0)/3,this.right.reduce((s,c)=>s+c.tick(x),0)/3];}
}

export class Engine {
  constructor(fs=48000){this.fs=fs;this.active=false;this.reset(DEFAULTS);}
  reset(config){
    this.config={...DEFAULTS,...config};this.p={...this.config};this.t=0;this.n=0;
    this.voices=[];this.events=makeEvents(this.config);this.next=0;
    this.flight=flightDuration(this.config);this.duration=this.flight+Math.min(8,this.p.decay+2.5);
    this.motion=new FractionalDelay(this.fs*2);
    this.room=new Stadium(this.fs);this.air=0;this.active=true;
    this.motionScale=this.p.doppler;this.space=this.p.space;
    this.automation=[...(config.automation||[])].sort((a,b)=>a.time-b.time);this.autoIndex=0;
    this.peak=0;this.notesFired=0;this.stopRemaining=null;
  }
  setParams(params){Object.assign(this.p,params);const shaped={...this.p,...expressionAt(this.t,this.config,this.p)};for(const v of this.voices)v.setParams(shaped);}
  stop(){this.stopRemaining=256;}
  tick(){
    if(!this.active)return [0,0];
    this.t=this.n/this.fs;
    while(this.autoIndex<this.automation.length && this.automation[this.autoIndex].time<=this.t){const a=this.automation[this.autoIndex++];this.setParams({[a.key]:a.value});}
    while(this.next<this.events.length && this.events[this.next].time<=this.t){
      const ev=this.events[this.next++];
      const shaped={...this.p,...expressionAt(this.t,this.config,this.p)};
      this.voices.push(new StringVoice(this.fs,ev.midi,ev.velocity*(.5+this.config.power*.007),shaped,(this.config.seed||15322)+ev.index*7919));
      this.notesFired++;
    }
    let dry=0;
    if(this.config.expression&&this.n%128===0){const shaped={...this.p,...expressionAt(this.t,this.config,this.p)};for(const v of this.voices)v.setParams(shaped);}
    for(const v of this.voices) dry+=v.sample();
    if(this.n%256===0)this.voices=this.voices.filter(v=>v.alive);
    dry*=1.65;
    const geo=listenerGeometry(this.t,this.config);
    // Retarded-time delay: d/c seconds. Its changing slope shifts frequency.
    // 'doppler' scales propagation time for a deliberately exaggerated effect.
    this.motionScale+=(this.p.doppler-this.motionScale)*0.0002;
    const delay=this.config.pitchMode==='stable'?2:2+geo.distance/343*this.fs*this.motionScale;
    const moved=this.motion.read(delay);this.motion.write(dry);
    const cutoff=clamp(14500/(1+geo.distance*0.07),1700,16000);
    const alpha=Math.exp(-2*Math.PI*cutoff/this.fs);
    this.air=(1-alpha)*moved+alpha*this.air;
    const attenuation=1/Math.sqrt(1+(geo.distance/11)**2);
    const audible=this.air*attenuation;
    const angle=(geo.pan+1)*Math.PI/4;
    const room=this.room.tick(audible);
    const targetSpace=this.config.expression?expressionAt(this.t,this.config,this.p).space:this.p.space;
    this.space+=(targetSpace-this.space)*0.001;
    let fade=clamp((this.duration-this.t)/0.25,0,1);
    if(this.stopRemaining!==null){fade*=this.stopRemaining/256;if(--this.stopRemaining<=0)this.active=false;}
    const l=(audible*Math.cos(angle)*(1-this.space*.35)+room[0]*this.space)*fade;
    const r=(audible*Math.sin(angle)*(1-this.space*.35)+room[1]*this.space)*fade;
    this.peak=Math.max(this.peak,Math.abs(l),Math.abs(r));
    this.n++;if(this.t>=this.duration)this.active=false;
    // Bounded output is a final protection, not automatic loudness normalization.
    return [Math.tanh(l*1.5)*0.85,Math.tanh(r*1.5)*0.85];
  }
}

export function renderShot(config,fs=48000){
  const e=new Engine(fs);e.reset(config);const frames=Math.ceil(e.duration*fs);
  const left=new Float32Array(frames),right=new Float32Array(frames);
  for(let i=0;i<frames;i++){const [l,r]=e.tick();left[i]=l;right[i]=r;}
  return {left,right,sampleRate:fs,duration:frames/fs};
}
export function wavBytes(audio){
  const {left,right,sampleRate}=audio, frames=left.length;
  const bytes=new ArrayBuffer(44+frames*4),v=new DataView(bytes);
  function text(at,s){for(let i=0;i<s.length;i++)v.setUint8(at+i,s.charCodeAt(i));}
  text(0,'RIFF');v.setUint32(4,36+frames*4,true);text(8,'WAVE');text(12,'fmt ');
  v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,2,true);
  v.setUint32(24,sampleRate,true);v.setUint32(28,sampleRate*4,true);v.setUint16(32,4,true);v.setUint16(34,16,true);
  text(36,'data');v.setUint32(40,frames*4,true);
  for(let i=0;i<frames;i++){v.setInt16(44+i*4,Math.round(clamp(left[i],-1,1)*32767),true);v.setInt16(46+i*4,Math.round(clamp(right[i],-1,1)*32767),true);}
  return bytes;
}


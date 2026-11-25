import {Engine} from './dsp.mjs';
class FreeKickProcessor extends AudioWorkletProcessor {
  constructor(){super();this.engine=new Engine(sampleRate);this.engine.active=false;this.blocks=0;
    this.port.onmessage=({data})=>{
      if(data.type==='shot'){this.engine.reset(data.config);this.port.postMessage({type:'started',audioTime:currentTime});}
      if(data.type==='params'){
        this.engine.setParams(data.params);
        // Acknowledge the actual processor boundary, not the UI's wall-clock guess.
        if(this.engine.active)this.port.postMessage({type:'applied',time:this.engine.n/sampleRate,params:data.params});
      }
      if(data.type==='stop')this.engine.stop();
    };
  }
  process(inputs,outputs){const out=outputs[0];
    for(let i=0;i<out[0].length;i++){const [l,r]=this.engine.tick();out[0][i]=l;if(out[1])out[1][i]=r;}
    if(++this.blocks%20===0)this.port.postMessage({type:'meter',time:this.engine.t,active:this.engine.active,notes:this.engine.notesFired,peak:this.engine.peak});
    return true;
  }
}
registerProcessor('free-kick-processor',FreeKickProcessor);


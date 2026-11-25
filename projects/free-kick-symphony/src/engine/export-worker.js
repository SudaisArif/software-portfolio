import {renderShot,wavBytes} from './dsp.mjs';
self.onmessage=({data})=>{
  try{const audio=renderShot(data.config,48000);const bytes=wavBytes(audio);
    self.postMessage({bytes,duration:audio.duration},[bytes]);
  }catch(error){self.postMessage({error:String(error)});}
};

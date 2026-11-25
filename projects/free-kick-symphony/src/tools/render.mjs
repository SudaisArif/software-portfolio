// Dependency-free offline renderer. The browser uses this exact DSP module.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {renderShot,wavBytes} from '../engine/dsp.mjs';
import {DEFAULTS} from '../engine/physics.mjs';
import {sanitizeConfig} from '../engine/session.mjs';
import {referencePhrase} from '../engine/phrase.mjs';
import {readSession} from '../engine/music.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const presets=JSON.parse(fs.readFileSync(path.join(root,'presets.json'),'utf8'));
const args=process.argv.slice(2);
const opt=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const scenes={muted:{decay:.7,brightness:.29,pluck:.13,space:.04,doppler:1,transpose:-12},singing:{decay:2.8,brightness:.65,pluck:.23,space:.18,doppler:3,transpose:0},space:{decay:5.7,brightness:.87,pluck:.39,space:.59,doppler:6,transpose:0}};
const output=path.resolve(opt('--out','outputs'));
fs.mkdirSync(output,{recursive:true});
function render(c,name){
  const config=sanitizeConfig(c),start=performance.now(),audio=renderShot(config);
  fs.writeFileSync(path.join(output,name+'.wav'),new Uint8Array(wavBytes(audio)));
  fs.writeFileSync(path.join(output,name+'.json'),JSON.stringify(config,null,2)+'\n');
  let peak=0,sum=0;for(let i=0;i<audio.left.length;i++){peak=Math.max(peak,Math.abs(audio.left[i]),Math.abs(audio.right[i]));sum+=(audio.left[i]**2+audio.right[i]**2)/2;}
  console.log(name+': '+audio.duration.toFixed(2)+' s, peak '+(20*Math.log10(peak)).toFixed(1)+' dBFS, RMS '+(20*Math.log10(Math.sqrt(sum/audio.left.length))).toFixed(1)+' dBFS, rendered in '+((performance.now()-start)/1000).toFixed(2)+' s');
}
if(args.includes('--session')){
  const data=JSON.parse(fs.readFileSync(opt('--session'),'utf8'));
  readSession(data).forEach((t,i)=>render(t.config,'take-'+String(i+1).padStart(2,'0')));
}else if(args.includes('--demos')){
  render({...DEFAULTS,...presets[0],...scenes.muted},'01-close-control');
  render({...DEFAULTS,...presets[2],...scenes.singing,distance:28},'02-after-the-whistle');
  render({...DEFAULTS,...presets[1],...scenes.space,distance:36,curl:-.65},'03-floodlights');
  const comparison={...DEFAULTS,...presets[0],notes:[[0,57,.9],[1,57,.7],[2,57,.8],[3,57,.8]],beats:4,space:0,decay:4,brightness:.85,distance:36,power:75};
  render({...comparison,doppler:0},'04-doppler-off');render({...comparison,doppler:8},'05-doppler-on');
  presets.forEach(p=>render({...DEFAULTS,...p},'study-'+p.slug));
}else{
  const preset=presets.find(p=>p.slug===opt('--preset','declan-rice'));
  if(!preset)throw new Error('Unknown preset. Choose '+presets.map(p=>p.slug).join(', '));
  const phrase=args.includes('--notes')?referencePhrase(preset,Number(opt('--notes'))):{};
  const loft=args.includes('--loft')?{loft:Number(opt('--loft'))}:{};
  render({...DEFAULTS,...preset,...(scenes[opt('--scene','singing')]||{}),...phrase,...loft},preset.slug);
}

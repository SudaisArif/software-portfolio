import {DEFAULTS, clamp} from './physics.mjs';
export function sanitizeConfig(input) {
  if(!input||typeof input!=='object')throw new Error('Expected a shot object.');
  const c={...DEFAULTS};
  const limits={distance:[18,36],power:[20,100],curl:[-1,1],aimX:[-5,5],aimZ:[0.1,3.4],decay:[.3,6],brightness:[.05,.98],pluck:[.05,.5],doppler:[0,8],space:[0,.65],transpose:[-12,12],seed:[1,4294967295],phraseScale:[.25,6],loft:[.4,5],bpm:[60,180],bars:[1,4],root:[0,11]};
  for(const [key,[lo,hi]]of Object.entries(limits)){const n=Number(input[key]);if(Number.isFinite(n))c[key]=clamp(n,lo,hi);}
  c.seed=Math.floor(c.seed);c.transpose=Math.round(c.transpose);
  c.bars=[1,2,4].includes(c.bars)?c.bars:2;c.root=Math.round(c.root);
  c.timing=input.timing==='tempo'?'tempo':'flight';
  c.pitchMode=input.pitchMode==='stable'?'stable':'moving';c.expression=input.expression===true;
  c.scale=['minor','major','chromatic'].includes(input.scale)?input.scale:'minor';
  c.source=String(input.source||'reference').slice(0,300);
  c.renderer='n5-2';
  // Old saved takes preserve the original power-dependent flight height.
  if(input.loft===undefined)c.loft=1.4+c.power/100*1.4;
  if(!Array.isArray(input.notes)||input.notes.length<1||input.notes.length>64)throw new Error('A phrase needs 1–64 notes.');
  c.notes=input.notes.map(n=>{
    if(!Array.isArray(n)||n.length<2||n.some(v=>!Number.isFinite(Number(v))))throw new Error('Invalid note.');
    if(n[0]<0||n[0]>128||n[1]<36||n[1]>96)throw new Error('Use beats 0–128 and MIDI pitches 36–96.');
    return [Number(n[0]),Math.round(n[1]),clamp(Number(n[2]??.7),0.05,1)];
  }).sort((a,b)=>a[0]-b[0]);
  c.beats=clamp(Number(input.beats)||c.notes.at(-1)[0]+.5,c.notes.at(-1)[0]+.05,129);
  c.title=String(input.title||'Untitled phrase').slice(0,120);c.slug=String(input.slug||'custom').slice(0,64);
  c.automation=(Array.isArray(input.automation)?input.automation:[]).slice(0,3000).filter(a=>a&&['decay','brightness','pluck','doppler','space'].includes(a.key)&&Number.isFinite(a.time)&&a.time>=0&&a.time<=72&&Number.isFinite(a.value)).map(a=>({time:a.time,key:a.key,value:clamp(a.value,...limits[a.key])}));
  return c;
}

// Small Standard MIDI File reader: type 0/1, PPQ timing, note-on events.
// It intentionally imports a single melodic track, not a whole arrangement.
export function readMidi(buffer){
  const v=new DataView(buffer);let p=0;
  const str=n=>{let s='';for(let i=0;i<n;i++)s+=String.fromCharCode(v.getUint8(p++));return s;};
  const u16=()=>{const x=v.getUint16(p);p+=2;return x;};const u32=()=>{const x=v.getUint32(p);p+=4;return x;};
  const vlq=()=>{let x=0,b;for(let k=0;k<4;k++){b=v.getUint8(p++);x=(x<<7)|(b&127);if(!(b&128))return x;}throw new Error('Invalid MIDI delta.');};
  if(str(4)!=='MThd')throw new Error('Not a Standard MIDI file.');
  const len=u32(),format=u16(),tracks=u16(),division=u16();
  if(format>1||(division&0x8000)||division===0)throw new Error('Use a type 0/1 MIDI file with PPQ timing.');p+=len-6;
  const melodies=[];
  for(let track=0;track<tracks;track++){
    if(str(4)!=='MTrk')throw new Error('Missing MIDI track.');
    const size=u32(),end=p+size;let tick=0,running=0;const notes=[];
    while(p<end){tick+=vlq();let status=v.getUint8(p++);
      if(status<0x80){p--;status=running;}else if(status<0xf0)running=status;
      if(!status)throw new Error('Invalid running status.');
      if(status===0xff){p++;const n=vlq();p+=n;continue;}
      if(status===0xf0||status===0xf7){const n=vlq();p+=n;continue;}
      const kind=status&0xf0,a=v.getUint8(p++),b=(kind===0xc0||kind===0xd0)?0:v.getUint8(p++);
      if(kind===0x90&&b>0&&(status&15)!==9)notes.push([tick/division,a,b/127]);
    }
    if(notes.length)melodies.push(notes);p=end;
  }
  if(!melodies.length)throw new Error('No pitched notes found.');
  const notes=melodies.find(n=>n.length>=4)||melodies[0];const start=notes[0][0];
  return notes.slice(0,64).map(n=>[n[0]-start,clamp(n[1],36,96),n[2]]);
}

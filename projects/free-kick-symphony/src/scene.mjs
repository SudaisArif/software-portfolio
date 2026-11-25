// Procedural stadium and articulated players. Every visual is drawn by code.
import {makeCamera,projectPoint,clipLine,clipPolygon} from './engine/camera.mjs';
import {clamp,flightDuration,positionAt,makeEvents,isGoal} from './engine/physics.mjs';
import {noteName} from './engine/music.mjs';
export class PitchScene {
  constructor(canvas){this.canvas=canvas;this.ctx=canvas.getContext('2d');this.cache=document.createElement('canvas');this.key='';}
  project(p){return projectPoint(p,this.camera);}
  line(points,color,width=1,closed=false){const ctx=this.ctx;ctx.beginPath();const ps=closed?[...points,points[0]]:points;for(let i=1;i<ps.length;i++){const clipped=clipLine(ps[i-1],ps[i],this.camera);if(!clipped)continue;const a=this.project(clipped[0]),b=this.project(clipped[1]);ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
  poly(points,color){const ps=clipPolygon(points,this.camera);if(ps.length<3)return;const ctx=this.ctx;ctx.beginPath();ps.forEach((p,i)=>{const q=this.project(p);i?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y);});ctx.closePath();ctx.fillStyle=color;ctx.fill();}
  ellipse(p,rx,ry,color){const q=this.project(p);if(q.depth<this.camera.near)return;this.ctx.beginPath();this.ctx.ellipse(q.x,q.y,Math.max(.1,rx*q.s),Math.max(.1,ry*q.s),0,0,Math.PI*2);this.ctx.fillStyle=color;this.ctx.fill();}
  background(c,w,h){
    const ctx=this.ctx;
    const sky=ctx.createLinearGradient(0,0,0,h*.6);sky.addColorStop(0,'#14222e');sky.addColorStop(.7,'#49585b');sky.addColorStop(1,'#9ba390');ctx.fillStyle=sky;ctx.fillRect(0,0,w,h);
    // Continuous stands with terraces, fascia, roof and deterministic spectators.
    this.poly([{x:-70,y:-12,z:0},{x:70,y:-12,z:0},{x:70,y:-29,z:14},{x:-70,y:-29,z:14}],'#293439');
    for(let row=0;row<21;row++){
      const y=-12-row*.76,z=1+row*.57;
      this.poly([{x:-65,y,z},{x:65,y,z},{x:65,y:y-.55,z:z+.44},{x:-65,y:y-.55,z:z+.44}],row<10?(row%2?'#4b3434':'#5f3a39'):(row%2?'#384248':'#414a50'));
      for(let i=0;i<140;i++){
        const x=-64+i*.92,hash=Math.abs(Math.sin(i*127.1+row*311.7)*43758.5453)%1;
        const q=this.project({x,y:y-.1,z:z+.3});const r=Math.max(.45,q.s*.10);
        ctx.fillStyle=['#b9b8a6','#1c2428','#733337','#d0b8a3','#61717a'][Math.floor(hash*5)];ctx.fillRect(q.x-r,q.y-r,r*1.5,r*2.6);
      }
      if(row===9)this.poly([{x:-65,y,z},{x:65,y,z},{x:65,y,z:z+.65},{x:-65,y,z:z+.65}],'#a9b5b4');
    }
    this.line([{x:-65,y:-29,z:14},{x:65,y:-29,z:14}],'#bac2be',3);
    this.line([{x:-65,y:-31,z:17},{x:65,y:-31,z:17}],'#17252d',12);
    for(let x=-62;x<64;x+=8)this.line([{x,y:-29,z:14},{x:x+5,y:-31,z:17}],'#7b8b8d',1.2);
    // Stadium light banks; bloom is generated with radial gradients.
    for(const x of [-33,-15,15,33]){
      const q=this.project({x,y:-24,z:13.7}),glow=ctx.createRadialGradient(q.x,q.y,1,q.x,q.y,Math.max(30,q.s*2.7));glow.addColorStop(0,'#fffce29c');glow.addColorStop(.15,'#fffcea38');glow.addColorStop(1,'#ffffe700');ctx.fillStyle=glow;ctx.fillRect(q.x-100,q.y-100,200,200);
      ctx.fillStyle='#f6fff6';ctx.fillRect(q.x-16,q.y-2,32,4);for(let i=0;i<8;i++)ctx.fillRect(q.x-15+i*4,q.y+4,2,2);
    }
    this.poly([{x:-55,y:-5,z:0},{x:55,y:-5,z:0},{x:55,y:-5,z:1},{x:-55,y:-5,z:1}],'#78272e');
    for(const x of [-24,-13,0,13,24]){const q=this.project({x,y:-4.9,z:.38});ctx.font=`600 ${Math.max(7,q.s*.32)}px Arial`;ctx.textAlign='center';ctx.fillStyle='#ecddcb';ctx.fillText(x===0?'NORTH LONDON SOUND CLUB':'N5  /  MAKE YOUR OWN',q.x,q.y);}
    this.poly([{x:-60,y:-4,z:0},{x:60,y:-4,z:0},{x:60,y:c.distance+12,z:0},{x:-60,y:c.distance+12,z:0}],'#477448');
    for(let y=-4;y<c.distance+13;y+=3.5)this.poly([{x:-60,y,z:0},{x:60,y,z:0},{x:60,y:y+3.5,z:0},{x:-60,y:y+3.5,z:0}],Math.round((y+4)/3.5)%2?'#416e41':'#4c7a47');
    // World-space grass blades become smaller towards the goal; no flat noise overlay.
    let seed=2149;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
    for(let i=0;i<14500;i++){
      const p={x:(random()-.5)*80,y:-3+random()*(c.distance+12),z:.015};const q=this.project(p);if(q.depth<.5||q.x<0||q.x>w||q.y<0||q.y>h)continue;
      const blade=clamp(q.s*(.012+random()*.027),.3,3.4);ctx.strokeStyle=random()>.5?'#acd18535':'#163f2e35';ctx.lineWidth=clamp(q.s*.005,.35,.9);ctx.beginPath();ctx.moveTo(q.x,q.y);ctx.lineTo(q.x+blade*.35,q.y-blade);ctx.stroke();
    }
    const white='#e8eed5aa';
    this.line([{x:-34,y:0},{x:34,y:0}],white,1.5);
    this.line([{x:-20.15,y:0},{x:-20.15,y:16.5},{x:20.15,y:16.5},{x:20.15,y:0}],white,1.5);
    this.line([{x:-9.16,y:0},{x:-9.16,y:5.5},{x:9.16,y:5.5},{x:9.16,y:0}],white,1.3);
    this.line([{x:-34,y:0},{x:-34,y:55}],white,1.5);this.line([{x:34,y:0},{x:34,y:55}],white,1.5);
    const arc=[];for(let a=.645;a<=Math.PI-.645;a+=.025)arc.push({x:9.15*Math.cos(a),y:11+9.15*Math.sin(a)});this.line(arc,white,1.5);this.ellipse({x:0,y:11,z:.01},.12,.04,'#e8eed5');
    // Goal frame and net sit in actual world coordinates.
    this.poly([{x:-3.66,y:-2,z:0},{x:3.66,y:-2,z:0},{x:3.66,y:-2,z:2.44},{x:-3.66,y:-2,z:2.44}],'#e7eee209');
    for(let x=-3.66;x<3.7;x+=.305)this.line([{x,y:-2,z:0},{x,y:-2,z:2.44},{x,y:0,z:2.44}],'#e7eee269',.55);
    for(let z=0;z<2.5;z+=.203)this.line([{x:-3.66,y:0,z},{x:-3.66,y:-2,z},{x:3.66,y:-2,z},{x:3.66,y:0,z}],'#e7eee263',.55);
    this.line([{x:-3.66,y:-2,z:0},{x:-3.66,y:-2,z:2.44},{x:3.66,y:-2,z:2.44},{x:3.66,y:-2,z:0}],'#d0d6c8',1.2);
    this.line([{x:-3.66,y:0,z:0},{x:-3.66,y:0,z:2.44},{x:3.66,y:0,z:2.44},{x:3.66,y:0,z:0}],'#677960',5);
    this.line([{x:-3.66,y:0,z:0},{x:-3.66,y:0,z:2.44},{x:3.66,y:0,z:2.44},{x:3.66,y:0,z:0}],'#f2f5e9',3);
    // Small physical listening microphone, separated from the player camera.
    this.line([{x:6,y:10,z:0},{x:6,y:10,z:1.5}],'#252d2b',2);this.ellipse({x:6,y:10,z:1.5},.09,.16,'#171e1c');
    const shade=ctx.createLinearGradient(0,h*.35,0,h);shade.addColorStop(0,'#061d1000');shade.addColorStop(1,'#07241645');ctx.fillStyle=shade;ctx.fillRect(0,0,w,h);
  }
  limb(a,b,r,color){
    const x=this.project(a),y=this.project(b),ctx=this.ctx;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(x.x,x.y);ctx.lineTo(y.x,y.y);ctx.strokeStyle=color[0];ctx.lineWidth=Math.max(1,(x.s+y.s)*r);ctx.stroke();
    const grad=ctx.createLinearGradient(x.x-(x.s+y.s)*r,0,x.x+(x.s+y.s)*r,0);grad.addColorStop(0,color[0]);grad.addColorStop(.4,color[1]);grad.addColorStop(1,color[0]);ctx.strokeStyle=grad;ctx.lineWidth=Math.max(.8,(x.s+y.s)*r);ctx.stroke();ctx.lineCap='butt';
  }
  person(x,y,{kit='red',phase=0,kicker=false,keeper=false,time=0}={}){
    const ctx=this.ctx,breathe=Math.sin(time*1.8+x)*.012;
    const shirt=kit==='red'?['#6e1528','#d24249']:kit==='keeper'?['#b27b19','#e7cb56']:['#18324c','#3d627e'];
    const skin=['#5b392b','#ab795b'],white=['#919e9f','#e5e6da'],socks=kit==='red'?['#a7a999','#eff1dd']:shirt;
    const swing=kicker?Math.sin(clamp(phase,0,1)*Math.PI):0;
    const p=(dx,dy,z)=>({x:x+dx,y:y+dy,z:z+breathe});
    this.ellipse(p(.12,.14,.01),.53,.13,'#0b271f44');
    // Long soft cast shadow, diagonal under stadium light.
    this.poly([p(-.2,0,.005),p(.25,0,.005),p(1.2,2.2,.005),p(.8,2.2,.005)],'#0b211d25');
    const leftHip=p(-.14,0,.85),rightHip=p(.14,0,.85),leftKnee=p(-.16,-.10,.48),rightKnee=p(.2,-swing*.46,.48+swing*.20);
    const leftFoot=p(-.19,-.03,.08),rightFoot=p(.2,-swing*.9,.09+swing*.48);
    this.limb(leftHip,leftKnee,.085,skin);this.limb(rightHip,rightKnee,.085,skin);
    const shorts=kit==='red'?white:shirt;for(const [hip,knee]of [[leftHip,leftKnee],[rightHip,rightKnee]])this.limb(hip,{x:hip.x+(knee.x-hip.x)*.5,y:hip.y+(knee.y-hip.y)*.5,z:hip.z+(knee.z-hip.z)*.5},.10,shorts);
    this.limb(leftKnee,leftFoot,.071,socks);this.limb(rightKnee,rightFoot,.071,socks);
    this.limb(leftFoot,p(-.18,-.21,.06),.052,['#1f2727','#d2bd78']);this.limb(rightFoot,{...rightFoot,y:rightFoot.y-.19},.052,['#1f2727','#d2bd78']);
    this.poly([p(-.25,.02,.8),p(.25,.02,.8),p(.22,.02,1.08),p(-.22,.02,1.08)],kit==='red'?'#e6e5dc':'#18364d');
    const body=[p(-.21,0,1),p(.21,0,1),p(.31,-.02,1.49),p(-.31,-.02,1.49)];
    const q=this.project(p(0,0,1.2)),grad=ctx.createLinearGradient(q.x-q.s*.3,0,q.x+q.s*.3,0);grad.addColorStop(0,shirt[0]);grad.addColorStop(.43,shirt[1]);grad.addColorStop(1,shirt[0]);this.poly(body,grad);
    this.line([p(-.18,.015,1.08),p(-.12,.015,1.34)],'#ffffff16',1);this.line([p(.12,.015,1.05),p(.20,.015,1.33)],'#00000025',1);
    const spread=keeper?.18:0;
    for(const side of [-1,1]){const shoulder=p(side*.27,0,1.45),elbow=p(side*(.34+spread+swing*.1),.07-swing*.12,1.13),hand=p(side*(.30+spread+swing*.16),.03+swing*.2,.92+swing*.19);this.limb(shoulder,elbow,.087,kit==='red'?white:shirt);this.limb(elbow,hand,.055,skin);this.ellipse(hand,.065,.075,keeper?'#dbdfd1':'#9d6b51');}
    this.limb(p(0,0,1.45),p(0,0,1.59),.09,skin);
    const head=this.project(p(0,0,1.72)),r=head.s*.135;
    const face=ctx.createRadialGradient(head.x-r*.3,head.y-r*.3,r*.1,head.x,head.y,r*1.1);face.addColorStop(0,'#b58361');face.addColorStop(1,'#593b2c');ctx.fillStyle=face;ctx.beginPath();ctx.ellipse(head.x,head.y,r,r*1.15,0,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#232322';ctx.beginPath();ctx.ellipse(head.x,head.y-r*.4,r*.98,r*.76,0,Math.PI,Math.PI*2);ctx.fill();
    if(kicker){const num=this.project(p(0,.025,1.20)),name=this.project(p(0,.025,1.41));ctx.textAlign='center';ctx.fillStyle='#f3e8cf';ctx.font=`600 ${Math.max(7,num.s*.30)}px Arial`;ctx.fillText('09',num.x,num.y);ctx.font=`600 ${Math.max(4,name.s*.075)}px Arial`;ctx.fillText('NORTH LONDON',name.x,name.y);}
  }
  render(c,time,playing,mode='kick',gates=true){
    const canvas=this.canvas,ctx=this.ctx,w=canvas.clientWidth,h=canvas.clientHeight,dpr=Math.min(window.devicePixelRatio||1,2);
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
    ctx.setTransform(dpr,0,0,dpr,0,0);this.camera=makeCamera(w,h,c.distance,mode);
    const key=[w,h,dpr,c.distance,mode].join('/');if(key!==this.key){this.cache.width=canvas.width;this.cache.height=canvas.height;const real=this.ctx;this.ctx=this.cache.getContext('2d');this.ctx.setTransform(dpr,0,0,dpr,0,0);this.background(c,w,h);this.ctx=real;this.key=key;}
    ctx.drawImage(this.cache,0,0,w,h);
    const T=flightDuration(c),t=Math.max(0,time),wallY=Math.max(7,c.distance-9.15),now=performance.now()/1000;
    this.person(.4+Math.sin(now*.7)*.10,1,{kit:'keeper',keeper:true,time:now});
    for(let i=0;i<3;i++)this.person(-1.0+i*.52,wallY,{kit:'blue',time:now+i});
    const pts=[];for(let u=0;u<=1.001;u+=.02)pts.push(positionAt(u*T,c));
    if(gates){ctx.setLineDash([2,7]);this.line(pts,'#f6df9f66',1.2);ctx.setLineDash([]);
      const events=makeEvents(c),stride=Math.max(1,Math.ceil(events.length/12));
      for(const ev of events){const p=this.project(positionAt(ev.time,c)),hit=playing&&t>=ev.time&&t-ev.time<.28;
        if(p.depth<this.camera.near)continue;const r=clamp(p.s*.15,2,11);ctx.strokeStyle=hit?'#ffebae':'#e0d7aa66';ctx.lineWidth=hit?2:1;ctx.beginPath();ctx.ellipse(p.x,p.y,r,r*1.6,0,0,Math.PI*2);ctx.stroke();
        if(w>500&&ev.index%stride===0){ctx.font='9px Arial';ctx.textAlign='center';ctx.fillStyle='#f1e6c5aa';ctx.fillText(noteName(ev.midi),p.x,p.y-r*1.8-4);}
      }
    }
    const aim=this.project({x:c.aimX,y:0,z:c.aimZ});ctx.strokeStyle=isGoal(c)?'#fcf1c4':'#f7a49b';ctx.lineWidth=1;ctx.beginPath();ctx.arc(aim.x,aim.y,7,0,Math.PI*2);ctx.moveTo(aim.x-12,aim.y);ctx.lineTo(aim.x+12,aim.y);ctx.moveTo(aim.x,aim.y-12);ctx.lineTo(aim.x,aim.y+12);ctx.stroke();
    const run=playing?clamp((time+.7)/.7,0,1):0;
    this.person(-1.1+run*.82,c.distance+2.0-run*1.3,{kicker:true,phase:playing&&time>=0?clamp(time/.45,0,1):0,time:now});
    const p=positionAt(t,c);p.z+=.11;const q=this.project(p),ground=this.project({...p,z:0});
    this.ellipse({...p,z:.01},.16+p.z*.02,.055+p.z*.006,'#10231780');
    if(playing&&p.z>.4&&gates){ctx.setLineDash([2,4]);this.line([{...p,z:0},p],'#eef4d533',1);ctx.setLineDash([]);}
    const r=clamp(q.s*.112,2.4,18);ctx.save();ctx.translate(q.x,q.y);ctx.rotate(playing?t*4:0);
    const ball=ctx.createRadialGradient(-r*.35,-r*.4,0,0,0,r);ball.addColorStop(0,'#ffffff');ball.addColorStop(.6,'#e5e6d8');ball.addColorStop(1,'#798b80');ctx.fillStyle=ball;ctx.beginPath();ctx.arc(0,0,r,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#28343a';ctx.beginPath();for(let k=0;k<5;k++){const a=k*Math.PI*2/5;ctx.lineTo(Math.sin(a)*r*.37,Math.cos(a)*r*.37);}ctx.closePath();ctx.fill();for(let k=0;k<5;k++){const a=k*Math.PI*2/5;ctx.beginPath();ctx.arc(Math.sin(a)*r*.86,Math.cos(a)*r*.86,r*.18,0,Math.PI*2);ctx.fill();}ctx.restore();
    const vignette=ctx.createRadialGradient(w*.5,h*.5,h*.25,w*.5,h*.5,Math.max(w,h)*.65);vignette.addColorStop(0,'#07131700');vignette.addColorStop(1,'#0713178a');ctx.fillStyle=vignette;ctx.fillRect(0,0,w,h);
    return p;
  }
}

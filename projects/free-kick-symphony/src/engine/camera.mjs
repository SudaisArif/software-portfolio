// Canvas renderer with a true perspective projection. No 3D-library dependency.
// The camera stays behind the kick and looks towards the goal at y=0.
export function makeCamera(width,height,distance,mode='kick'){
  const y=distance+9.5,z=2.6,targetZ=1.1;
  const length=Math.hypot(y,z-targetZ),fy=-y/length,fz=(targetZ-z)/length;
  return {width,height,y,z,fy,fz,focal:Math.min(width*1.12,height*1.55),
    centreY:height*.4,near:.5,mode};
}
export function depthOf(p,c){return c.mode==='tactical'?1:(p.y-c.y)*c.fy+((p.z||0)-c.z)*c.fz;}
export function projectPoint(p,c){
  if(c.mode==='tactical'){
    const s=(c.width/48)*(.72+Math.max(0,p.y)/45*.38);
    return {x:c.width*.5+p.x*s,y:c.height*.18+p.y/42*c.height*.69-(p.z||0)*c.height*.035,s,depth:1};
  }
  const depth=depthOf(p,c),s=c.focal/Math.max(depth,c.near);
  const up=(p.y-c.y)*c.fz-((p.z||0)-c.z)*c.fy;
  return {x:c.width*.5+p.x*s,y:c.centreY-up*s,s,depth};
}
function interpolate(a,b,t){return {x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z:(a.z||0)+((b.z||0)-(a.z||0))*t};}
export function clipLine(a,b,c){
  const da=depthOf(a,c),db=depthOf(b,c);
  if(da<c.near&&db<c.near)return null;
  if(da<c.near)return [interpolate(a,b,(c.near-da)/(db-da)),b];
  if(db<c.near)return [a,interpolate(a,b,(c.near-da)/(db-da))];
  return [a,b];
}
export function clipPolygon(points,c){
  const result=[];
  for(let i=0;i<points.length;i++){
    const a=points[i],b=points[(i+1)%points.length],da=depthOf(a,c),db=depthOf(b,c);
    if(da>=c.near)result.push(a);
    if((da<c.near)!==(db<c.near))result.push(interpolate(a,b,(c.near-da)/(db-da)));
  }
  return result;
}
export function goalTargetAtPixel(x,y,c){
  if(c.mode==='tactical')return {x:(x-c.width*.5)/((c.width/48)*.72),z:(c.height*.18-y)/(c.height*.035)};
  const rx=(x-c.width*.5)/c.focal,ry=(c.centreY-y)/c.focal;
  const dy=c.fy+ry*c.fz,dz=c.fz-ry*c.fy;
  if(dy>=-.0001)return null;
  const t=-c.y/dy;
  return {x:rx*t,z:c.z+dz*t};
}

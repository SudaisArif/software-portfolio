// World coordinates in metres: goal centre (0, 0), kick (0, distance).
export const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
export const DEFAULTS = Object.freeze({distance: 24, power: 66, curl: 0.22,
  aimX: 1.6, aimZ: 1.25, decay: 2.8, brightness: 0.65, pluck: 0.23,
  doppler: 3, space: 0.18, transpose: 0, seed: 15322, phraseScale: 1, loft: 2.4,
  timing: 'flight', bpm: 140, bars: 2, pitchMode: 'moving', expression: false,
  root: 9, scale: 'minor', source: 'reference'});

export function flightDuration(c) {
  if(c.timing==='tempo')return clamp(c.bars??2,1,4)*4*60/clamp(c.bpm??140,60,180);
  // Slow motion makes a single ballistic gesture into a playable phrase.
  const speed = 14 + clamp(c.power, 20, 100) * 0.18;
  const scale=clamp(c.phraseScale??1,.25,6);
  return clamp(clamp(c.distance / speed * 5.2, 3.2, 10.5)*scale,1.6,63);
}
export function positionAt(time, c) {
  const T = flightDuration(c), u = clamp(time / T, 0, 1);
  // Ballistic vertical motion in musical time; lateral quadratic is a
  // controllable curve, not a claim to solve full aerodynamic Magnus forces.
  const apex = c.loft ?? (1.4 + c.power / 100 * 1.4);
  return {x: c.aimX * u + c.curl * 5 * 4 * u * (1-u),
    y: c.distance * (1-u), z: 4 * apex * u * (1-u) + c.aimZ * u};
}
export function listenerGeometry(time, c) {
  const p = positionAt(time, c);
  // A stationary touchline microphone, visible on the pitch.
  const dx = p.x - 6, dy = p.y - 10, dz = p.z - 1.5;
  return {distance: Math.sqrt(dx*dx + dy*dy + dz*dz),
    pan: c.expression?clamp(p.x/5,-.92,.92):clamp((10-p.y) / Math.sqrt(dx*dx+dy*dy), -0.95, 0.95), ...p};
}
export function makeEvents(c) {
  const T = flightDuration(c);
  const notes = c.notes || [[0, 57, 0.8], [1, 60, 0.6], [2, 64, 0.8], [3, 62, 0.7]];
  const end = c.beats || Math.max(...notes.map(n => n[0])) + 1;
  return notes.map((n, i) => ({time: c.timing==='tempo'?n[0]/end*T:0.12 + n[0] / end * (T-0.3),
    midi: n[1] + (c.transpose || 0), velocity: n[2] ?? 0.7, index: i}));
}
// Musical expression is explicit and reproducible, separate from visual animation.
export function expressionAt(time,c,p=c){
  if(!c.expression)return {brightness:p.brightness,space:p.space};
  const lift=clamp(positionAt(time,c).z/6,0,1);
  return {brightness:clamp(p.brightness+(c.power-66)*.003+lift*.22,.05,.98),
    space:clamp(p.space+lift*.12,0,.65)};
}
export function isGoal(c) { return Math.abs(c.aimX) < 3.66 && c.aimZ < 2.44; }


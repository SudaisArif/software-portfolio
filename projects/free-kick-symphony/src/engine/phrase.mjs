import {clamp} from './physics.mjs';

// Select a contiguous window from real extracted events. Continue after the
// original study first; near the preview's end, expand backwards as needed.
// Never invent notes or wrap the preview to make a longer sequence.
export function referencePhrase(preset, requested=16) {
  if(!Number.isFinite(Number(requested)))throw new Error('Note count must be a number.');
  const library=preset.phraseLibrary;
  if(!library?.events?.length) return {
    notes:preset.notes.map(n=>[...n]),beats:preset.beats,phraseScale:1,
    sourceStart:preset.preview_start_s,sourceEnd:preset.preview_end_s,
    maxNotes:preset.notes.length
  };
  const maxNotes=Math.min(64,library.events.length);
  const count=clamp(Math.round(requested),1,maxNotes);
  const first=clamp(library.anchor,0,library.events.length-count);
  const events=library.events.slice(first,first+count);
  const start=events[0].start,end=events.at(-1).end,span=end-start;
  return {notes:events.map((e,i)=>[(e.start-start)/span*8,e.midi,i%3===0?.8:.62]),
    beats:8,phraseScale:clamp(span/library.referenceDuration,.25,6),
    sourceStart:start,sourceEnd:end,maxNotes};
}

// Editing/MIDI creates a separate note bank. Shortening and re-expanding the
// slider preserves that bank until the user explicitly applies a new edit.
export function editedPhrase(bank,requested) {
  if(!Number.isFinite(Number(requested)))throw new Error('Note count must be a number.');
  const count=clamp(Math.round(requested),1,Math.min(64,bank.notes.length));
  const notes=bank.notes.slice(0,count).map(n=>[...n]);
  const end=count<bank.notes.length?bank.notes[count][0]:bank.beats;
  const start=notes[0][0],span=Math.max(.05,end-start);
  return {notes:notes.map(n=>[(n[0]-start)/span*8,n[1],n[2]]),beats:8,
    phraseScale:clamp(bank.phraseScale*span/bank.beats,.25,6),maxNotes:bank.notes.length};
}

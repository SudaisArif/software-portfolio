"""Arrange kept N5 shots with pq.Score, preserving their musical timing and tails.

This is a bridge into the final composition, not a complete Assignment 10 piece.
It does not add drums/bass or claim the final project's four-technique requirement.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir())/'n5-matplotlib'))
import numpy as np
import pyquist as pq
import soundfile as sf

ROOT = Path(__file__).resolve().parent
SR = 48000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True, help='Downloaded N5 shot or session JSON')
    parser.add_argument('--order', help='One-based shot positions, e.g. 1,2,1,3; default is saved order')
    parser.add_argument('--repeat', type=int, default=1, choices=range(1,9))
    parser.add_argument('--out', type=Path, default=ROOT.parent/'outputs'/'shot_sequence.wav')
    args = parser.parse_args()
    data = json.loads(args.session.read_text())
    if data.get('version') not in (1,2) or not isinstance(data.get('takes'), list) or not data['takes']:
        raise SystemExit('Use a downloaded N5 shot/session with at least one kept shot.')
    order = [int(n)-1 for n in args.order.split(',')] if args.order else list(range(len(data['takes'])))
    if not order or len(order)>200 or any(i<0 or i>=len(data['takes']) for i in order):
        raise SystemExit('--order must contain valid saved shot positions, e.g. 1,2,1,3.')
    score, placements = pq.Score(), []
    with tempfile.TemporaryDirectory(prefix='n5-arrangement-') as work:
        work = Path(work)
        subprocess.run(['node', str(ROOT/'tools'/'render.mjs'), '--session', str(args.session.resolve()), '--out', str(work)], check=True)
        audio, lengths = {}, {}
        for i in set(order):
            name = f'take-{i+1:02d}'
            samples, sr = sf.read(work/(name+'.wav'), dtype='float32', always_2d=True)
            assert sr == SR
            config = json.loads((work/(name+'.json')).read_text())
            if config['timing']=='tempo':
                phrase_seconds = config['bars']*4*60/config['bpm']
            else:
                speed = 14+config['power']*.18
                phrase_seconds = min(63,max(1.6,min(10.5,max(3.2,config['distance']/speed*5.2))*config['phraseScale']))
            audio[i], lengths[i] = pq.Audio(samples, SR), phrase_seconds
        cursor = 0.
        for repeat in range(args.repeat):
            for i in order:
                start = round(cursor*SR)/SR
                score.append((start, {'clip':i}))
                placements.append({'shot_position':i+1,'time':start,'phrase_seconds':lengths[i],
                                   'name':data['takes'][i].get('name',data['takes'][i]['config'].get('title','Shot'))})
                cursor += lengths[i]
        rendered = np.asarray(score.render(lambda clip:audio[clip]).samples)
        if rendered.ndim==2 and rendered.shape[0]==2:
            rendered = rendered.T
        # Overlapping tails can sum. Apply one global gain, preserving dynamics.
        peak = float(np.max(np.abs(rendered)))
        if peak>0:
            rendered *= 10**(-1.5/20)/peak
        args.out.parent.mkdir(parents=True,exist_ok=True)
        sf.write(args.out, rendered, SR, subtype='PCM_16')
        args.out.with_suffix('.json').write_text(json.dumps({'placements':placements,'score_events':len(score),
          'duration':len(rendered)/SR,'source_session':args.session.name,
          'note':'Phrase starts are beat-aligned; release tails overlap. Add your other course techniques and develop this into your final piece.'},indent=2)+'\n')
        print(f'Wrote {args.out}: {len(rendered)/SR:.2f}s, stereo 48kHz, PCM16, peak -1.5dBFS.')


if __name__=='__main__':
    main()

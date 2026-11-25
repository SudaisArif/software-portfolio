"""Render a 28-second Assignment 9 sketch with a reusable Pyquist Score workflow.

The string/Doppler audio comes from the shared JavaScript engine. Python adds
original FM bass and subtractive percussion and arranges the stems with pq.Score.
This is a sketch and bridge to the final project, not a complete final submission.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'n5-matplotlib'))
import numpy as np
import pyquist as pq
import soundfile as sf

ROOT = Path(__file__).resolve().parent
SR = 48000


def stereo(x):
    return np.column_stack((x, x)) if x.ndim == 1 else x


def fm_bass(pitch, duration=1.5, gain=0.13):
    t = np.arange(round(duration * SR)) / SR
    f = 440 * 2 ** ((pitch - 69) / 12)
    # A short glide settles into an original bass note. Phase is integrated.
    instantaneous = f * (1 + .17 * np.exp(-t / .035))
    phase = 2 * np.pi * np.cumsum(instantaneous) / SR
    index = 1.8 * np.exp(-t / .14)
    x = np.sin(phase + index * np.sin(2 * phase))
    env = np.minimum(t / .008, 1) * np.exp(-t / .65)
    env *= np.minimum((duration - t) / .045, 1)
    return pq.Audio(stereo(x * env * gain).astype(np.float32), SR)


def percussion(kind, seed=42, gain=.08):
    duration = .4 if kind == 'kick' else .15
    t = np.arange(round(duration * SR)) / SR
    if kind == 'kick':
        f = 49 + 115 * np.exp(-t / .022)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .08)
    else:
        noise = np.random.default_rng(seed).uniform(-1, 1, len(t))
        # FIR high-pass: subtraction shapes noise into a hat/snare transient.
        x = np.diff(np.r_[0, noise]) * np.exp(-t / (.018 if kind == 'hat' else .045))
        if kind == 'snare':
            x += .35 * np.sin(2 * np.pi * 185 * t) * np.exp(-t / .035)
    x *= np.minimum(t / .001, 1) * gain
    return pq.Audio(stereo(x).astype(np.float32), SR)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT.parent / 'outputs' / 'composition_sketch.wav')
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='n5-sketch-') as tmp:
        tmp = Path(tmp)
        cache = {}
        for scene in ('muted', 'singing', 'space'):
            dest = tmp / scene
            subprocess.run(['node', str(ROOT / 'tools' / 'render.mjs'), '--preset', 'declan-rice',
                            '--scene', scene, '--out', str(dest)], check=True)
            x, sr = sf.read(dest / 'declan-rice.wav', dtype='float32', always_2d=True)
            assert sr == SR
            # Match phrase loudness for arrangement while preserving dynamics.
            peak = np.max(np.abs(x))
            cache[scene] = pq.Audio(x / max(peak, 1e-6) * .28, SR)

        score = pq.Score()
        for time, scene in [(0., 'singing'), (8., 'muted'), (16., 'space')]:
            score.append((time, {'kind': 'phrase', 'scene': scene}))
        for beat in range(32):
            time = 8 + beat * .5
            if beat % 4 in (0, 3):
                score.append((time, {'kind': 'kick', 'seed': beat}))
            if beat % 4 == 2:
                score.append((time, {'kind': 'snare', 'seed': beat}))
            score.append((time + .25, {'kind': 'hat', 'seed': beat + 200}))
        for i, pitch in enumerate([45, 43, 41, 43, 45, 43, 41, 45]):
            score.append((8 + i * 2., {'kind': 'bass', 'pitch': pitch}))

        def instrument(kind, scene=None, pitch=45, seed=42):
            if kind == 'phrase':
                return cache[scene]
            if kind == 'bass':
                return fm_bass(pitch)
            return percussion(kind, seed)

        rendered = score.render(instrument)
        audio = np.asarray(rendered.samples)
        # Audio sample layout is (frames, channels) in this Pyquist version.
        if audio.ndim == 2 and audio.shape[0] == 2:
            audio = audio.T
        audio = stereo(audio)
        total = 28 * SR
        audio = np.pad(audio, ((0, max(0, total-len(audio))), (0, 0)))[:total]
        fade = np.ones(total)
        fade[:round(.02*SR)] = np.linspace(0, 1, round(.02*SR))
        fade[-2*SR:] = np.linspace(1, 0, 2*SR)
        audio *= fade[:, None]
        audio *= 10 ** (-1.5/20) / max(float(np.max(np.abs(audio))), 1e-9)
        sf.write(args.out, audio, SR, subtype='PCM_16')
        print(f'Wrote {args.out}: {len(audio)/SR:.1f}s, stereo 48kHz PCM16, peak -1.5dBFS')
        manifest = {'duration': 28, 'sections': [{'time': 0, 'sound': 'singing string motif'},
                    {'time': 8, 'sound': 'muted motif, FM bass and subtractive percussion'},
                    {'time': 16, 'sound': 'wide strings with exaggerated Doppler and stadium tail'}],
                    'techniques': ['physical modeling', 'variable delay/spatial audio', 'FM synthesis', 'subtractive percussion'],
                    'score_events': len(score), 'reference': 'Declan Rice, instrumental pitch study; see reference-provenance.json'}
        args.out.with_suffix('.json').write_text(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    main()

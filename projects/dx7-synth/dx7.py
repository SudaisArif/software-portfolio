"""Six-operator phase-modulation synthesizer, written in Python/NumPy.

Algorithm 5:  2 -> 1, 4 -> 3, 6 -> 5; output 1 + 3 + 5; feedback on 6.
Algorithm 16: 4 -> 3, 6 -> 5, (2 + 3 + 5) -> 1; feedback on 6.
"""
from functools import lru_cache
from pathlib import Path
import math

import numpy as np
import pyquist as pq

from sysex import VoicePatch, find_patch

SAMPLE_RATE = 44100
ASSETS = Path(__file__).resolve().parent / 'assets'


def operator(
    amp: float,
    env: np.ndarray,
    f_c: float,
    mod: np.ndarray,
    duration: float,
    feedback: float = 0.0,
    f_s: int = 44100,
) -> pq.Audio:
    """y[n] = amp*env[n]*sin(2*pi*f_c*n/f_s + mod[n] + feedback*y[n-1]).

    Modulation is PHASE in radians. The feedback history contains this
    operator's amplitude- and envelope-scaled output; y[-1] is zero.
    """
    if not isinstance(f_s, (int, np.integer)) or f_s <= 0:
        raise ValueError('f_s must be a positive integer.')
    if not all(math.isfinite(x) for x in (amp, f_c, duration, feedback)) or duration < 0:
        raise ValueError('Parameters must be finite and duration nonnegative.')
    n = math.floor(duration * f_s)
    env = np.asarray(env, dtype=np.float64)
    mod = np.asarray(mod, dtype=np.float64)
    if env.shape != (n,) or mod.shape != (n,):
        raise ValueError(f'env and mod must be 1-D arrays of length {n}.')
    if not (np.all(np.isfinite(env)) and np.all(np.isfinite(mod))):
        raise ValueError('Envelope and modulation must be finite.')
    phase = (2 * np.pi * f_c / f_s) * np.arange(n) + mod
    level = amp * env
    if feedback == 0:
        samples = level * np.sin(phase)
    else:
        samples = np.empty(n, dtype=np.float64)
        previous = 0.0
        for i in range(n):
            previous = level[i] * math.sin(phase[i] + feedback * previous)
            samples[i] = previous
    return pq.Audio(samples.astype(np.float32), sample_rate=f_s)


def _samples(audio: pq.Audio) -> np.ndarray:
    return audio.samples[:, 0]


def algorithm5(amps, envs, frequencies, duration, feedback=0.0, f_s=44100) -> pq.Audio:
    """Three two-operator stacks; all six call the required operator primitive."""
    zero = np.zeros(math.floor(duration * f_s))
    op6 = operator(amps[5], envs[5], frequencies[5], zero, duration, feedback, f_s)
    op5 = operator(amps[4], envs[4], frequencies[4], _samples(op6), duration, f_s=f_s)
    op4 = operator(amps[3], envs[3], frequencies[3], zero, duration, f_s=f_s)
    op3 = operator(amps[2], envs[2], frequencies[2], _samples(op4), duration, f_s=f_s)
    op2 = operator(amps[1], envs[1], frequencies[1], zero, duration, f_s=f_s)
    op1 = operator(amps[0], envs[0], frequencies[0], _samples(op2), duration, f_s=f_s)
    return pq.Audio(_samples(op1) + _samples(op3) + _samples(op5), sample_rate=f_s)


def algorithm16(amps, envs, frequencies, duration, feedback=0.0, f_s=44100) -> pq.Audio:
    """A single carrier receives three branches, two of which are nested."""
    zero = np.zeros(math.floor(duration * f_s))
    op6 = operator(amps[5], envs[5], frequencies[5], zero, duration, feedback, f_s)
    op5 = operator(amps[4], envs[4], frequencies[4], _samples(op6), duration, f_s=f_s)
    op4 = operator(amps[3], envs[3], frequencies[3], zero, duration, f_s=f_s)
    op3 = operator(amps[2], envs[2], frequencies[2], _samples(op4), duration, f_s=f_s)
    op2 = operator(amps[1], envs[1], frequencies[1], zero, duration, f_s=f_s)
    modulation = _samples(op2) + _samples(op3) + _samples(op5)
    return operator(amps[0], envs[0], frequencies[0], modulation, duration, f_s=f_s)


# OP1 ... OP6. Carrier amplitudes are audio gains, modulator amplitudes radians.
ORGAN_RATIOS = (1.0, 2.0, 2.0, 1.0, 3.0, 4.0)
ORGAN_LEVELS = (0.68, 1.10, 0.20, 0.55, 0.12, 0.22)
# Attack, decay, sustain, release (seconds except sustain).
ORGAN_ENVELOPES = (
    (0.004, 0.22, 0.58, 0.060), (0.002, 0.065, 0.18, 0.045),
    (0.004, 0.18, 0.44, 0.055), (0.002, 0.090, 0.12, 0.040),
    (0.003, 0.08, 0.16, 0.040), (0.002, 0.045, 0.05, 0.035),
)


def _note_args(pitch, velocity, duration):
    if not isinstance(pitch, (int, np.integer)) or not 0 <= pitch <= 127:
        raise ValueError('pitch must be an integer MIDI note, 0..127.')
    if not isinstance(velocity, (int, np.integer)) or not 0 <= velocity <= 127:
        raise ValueError('velocity must be an integer, 0..127.')
    if not math.isfinite(duration) or duration < 0:
        raise ValueError('duration must be finite and nonnegative.')
    return 440 * 2 ** ((pitch - 69) / 12), math.floor(duration * SAMPLE_RATE)


def adsr(duration, attack, decay, sustain, release, f_s=SAMPLE_RATE):
    """An exponential decay with a release contained inside the note duration."""
    n = math.floor(duration * f_s)
    t = np.arange(n) / f_s
    attack = min(attack, duration * 0.2)
    release = min(release, duration * 0.3)
    attack_curve = np.minimum(t / max(attack, 1 / f_s), 1)
    decay_curve = sustain + (1 - sustain) * np.exp(-np.maximum(t - attack, 0) * 4 / decay)
    envelope = attack_curve * decay_curve
    if n:
        start = max(0, n - max(2, round(release * f_s)))
        envelope[start:] *= np.linspace(1, 0, n - start) ** 1.4
    return envelope


def dx7_preset1(pitch: int, velocity: int, duration: float) -> pq.Audio:
    """House organ: quick chord stabs with a bright transient and warm body."""
    f0, n = _note_args(pitch, velocity, duration)
    if velocity == 0 or n == 0:
        return pq.Audio(np.zeros(n, np.float32), sample_rate=SAMPLE_RATE)
    envs = [adsr(duration, *values) for values in ORGAN_ENVELOPES]
    # Keep modulation independent of velocity, so level increases monotonically.
    result = algorithm5(ORGAN_LEVELS, envs, [f0 * r for r in ORGAN_RATIOS], duration, 0.18)
    result.samples *= 0.62 * (velocity / 127) ** 1.4
    return result


# The low end of Yamaha's envelope level scale is nonlinear; above 20 it is
# approximately level+28. The model is an analytic approximation to the
# logarithmic rate/level behavior described by the reference emulator.
_LOW_LEVEL = (0, 5, 9, 13, 17, 20, 23, 25, 27, 29, 31, 33, 35, 37, 39,
              41, 42, 43, 45, 46)


def _eg_target(level):
    return max(0, ((_LOW_LEVEL[level] if level < 20 else level + 28) * 32) - 224)


def dx7_envelope(duration, rates, levels, note_off, f_s=SAMPLE_RATE):
    """Four-rate/four-level envelope, evaluated in analytic segments.

    Rise follows a first-order approach; decay moves linearly in logarithmic
    level. R1/R2/R3 play while held, L3 sustains, R4/L4 apply at note-off.
    This is a documented approximation, not Yamaha's bit-exact EG hardware.
    """
    n = math.floor(duration * f_s)
    off = min(n, max(0, int(note_off * f_s)))
    curve = np.zeros(n)
    current = float(_eg_target(levels[3]))
    pos = 0

    def segment(stage, end):
        nonlocal current, pos
        target = _eg_target(levels[stage])
        qr = min(63, (int(rates[stage]) * 41) // 64)
        increment = 2 ** (qr / 4) / 2048 * 44100 / f_s
        available = end - pos
        if available <= 0:
            return
        if abs(target - current) < 1e-12:
            return
        if target > current:
            multiplier = 1 - increment / 256
            needed = max(1, math.ceil(math.log(512 / (target + 512 - current)) / math.log(multiplier)))
            count = min(available, needed)
            values = target + 512 + (current - target - 512) * multiplier ** np.arange(1, count + 1)
            values = np.minimum(values, target)
        else:
            needed = max(1, math.ceil((current - target) / increment))
            count = min(available, needed)
            values = np.maximum(target, current - increment * np.arange(1, count + 1))
        curve[pos:pos + count] = values
        pos += count
        current = float(values[-1])

    for stage in range(3):
        segment(stage, off)
    curve[pos:off] = current
    pos = off
    segment(3, n)
    curve[pos:] = current
    # 20^(dB/20) matches the supplied web reference's envelope scale.
    result = 20 ** (((curve - 3824) * 0.0235) / 20)
    return result


def output_level(level):
    """DX7 output level to phase depth; 8 level steps approximately double it."""
    return 0.0 if level == 0 else 13.12273 * 1.27 * 2 ** ((level - 99) / 8)


@lru_cache(maxsize=1)
def bass_patch() -> VoicePatch:
    return find_patch(ASSETS / 'rom1a.syx', 'BASS 1')


def render_patch(patch: VoicePatch, pitch: int, velocity: int, duration: float,
                 *, normalize_pitch=True, note_off=None, expressive=True) -> pq.Audio:
    """Use the imported values to configure every operator of algorithm 5 or 16.

    normalize_pitch=True makes pitch the sounding fundamental, removing the
    keyboard transpose and dividing ratios by the primary carrier's ratio.
    False honors the original keyboard transpose, for the bonus comparison.
    """
    f0, n = _note_args(pitch, velocity, duration)
    if patch.algorithm not in (5, 16):
        raise ValueError('This project implements algorithms 5 and 16 only.')
    if velocity == 0 or n == 0:
        return pq.Audio(np.zeros(n, np.float32), sample_rate=SAMPLE_RATE)
    base = f0 / patch.operators[0].ratio if normalize_pitch else f0 * 2 ** (patch.transpose / 12)
    off = max(0, duration - min(0.14, duration * 0.25)) if note_off is None else note_off
    envs, amps, freqs = [], [], []
    for op in patch.operators:
        envs.append(dx7_envelope(duration, op.rates, op.levels, off))
        gain = output_level(op.output_level)
        if expressive:
            gain *= 1 + (velocity / 127 - 1) * op.velocity_sensitivity / 7
        amps.append(gain)
        frequency = (10 ** ((op.coarse % 4) + op.fine / 100) if op.mode
                     else base * op.ratio * 2 ** (op.detune / 1024))
        freqs.append(frequency)
    # Our feedback uses the scaled y[n-1]; the reference's loop precedes its
    # output gain. Dividing by OP6 gain translates between these conventions.
    feedback = 0.0 if patch.feedback == 0 or amps[5] == 0 else 2 ** (patch.feedback - 7) / amps[5]
    algorithm = algorithm5 if patch.algorithm == 5 else algorithm16
    audio = algorithm(amps, envs, freqs, duration, feedback)
    # Global gain prevents a hot DX modulation-level scale from clipping audio.
    audio.samples *= 0.038 * (velocity / 127) ** 1.3
    # A 2ms edge taper only; the patch's own envelope controls the note body.
    edge = min(round(0.002 * SAMPLE_RATE), n // 2)
    if edge:
        audio.samples[:edge, 0] *= np.linspace(0, 1, edge)
        audio.samples[-edge:, 0] *= np.linspace(1, 0, edge)
    return audio


def dx7_preset2(pitch: int, velocity: int, duration: float) -> pq.Audio:
    """Yamaha factory BASS 1, imported from ROM1A and played at sounding pitch."""
    return render_patch(bass_patch(), pitch, velocity, duration, expressive=False)


def midi_to_dx7(pitch: int, velocity: int, duration: float, program: int = 0,
                is_drum: bool = False, **metadata) -> pq.Audio:
    """GM programs are ZERO based: 32..39 -> bass; every other program -> organ.

    Drum events are excluded from the required two-preset score before render.
    A silent fallback makes this function safe for unfiltered GM MIDI input.
    Extra fields from Pyquist (channel, mtype, duration_ticks) are accepted.
    """
    if is_drum:
        return pq.Audio(np.zeros(math.floor(duration * SAMPLE_RATE), np.float32), sample_rate=SAMPLE_RATE)
    preset = dx7_preset2 if 32 <= program <= 39 else dx7_preset1
    return preset(pitch, velocity, duration)

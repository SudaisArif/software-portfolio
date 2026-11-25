"""Read Yamaha DX7 32-voice (VMEM) and single-voice (VCED) SysEx dumps.

The parser follows the Yamaha byte layout, also documented by Matt Montag's
sysex-dx7.js. No sound is loaded: these files contain synthesizer parameters.
"""
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class OperatorPatch:
    rates: tuple[int, ...]
    levels: tuple[int, ...]
    breakpoint: int
    left_depth: int
    right_depth: int
    left_curve: int
    right_curve: int
    rate_scaling: int
    detune: int
    amplitude_mod_sensitivity: int
    velocity_sensitivity: int
    output_level: int
    mode: int
    coarse: int
    fine: int

    @property
    def ratio(self) -> float:
        return (self.coarse or 0.5) * (1 + self.fine / 100)


@dataclass(frozen=True)
class VoicePatch:
    name: str
    algorithm: int
    feedback: int
    oscillator_sync: int
    operators: tuple[OperatorPatch, ...]  # OP1 first, despite reversed file order
    pitch_rates: tuple[int, ...]
    pitch_levels: tuple[int, ...]
    lfo_speed: int
    lfo_delay: int
    pitch_mod_depth: int
    amplitude_mod_depth: int
    lfo_sync: int
    lfo_waveform: int
    pitch_mod_sensitivity: int
    transpose: int  # semitones relative to the keyboard, centered at byte 24

    def to_dict(self) -> dict:
        return asdict(self)


def _operator(data: bytes, packed: bool) -> OperatorPatch:
    if packed:
        return OperatorPatch(tuple(data[:4]), tuple(data[4:8]), *data[8:11],
                             data[11] & 3, (data[11] >> 2) & 3,
                             data[12] & 7, (data[12] >> 3) - 7,
                             data[13] & 3, (data[13] >> 2) & 7,
                             data[14], data[15] & 1, data[15] >> 1, data[16])
    return OperatorPatch(tuple(data[:4]), tuple(data[4:8]), *data[8:13],
                         data[13], data[20] - 7, data[14], data[15],
                         data[16], data[17], data[18], data[19])


def _voice(data: bytes, packed: bool) -> VoicePatch:
    width = 17 if packed else 21
    ops = tuple(_operator(data[j * width:(j + 1) * width], packed)
                for j in range(5, -1, -1))
    g = data[6 * width:]
    if packed:
        return VoicePatch(g[16:26].decode('ascii').strip(), g[8] + 1,
                          g[9] & 7, (g[9] >> 3) & 1, ops,
                          tuple(g[:4]), tuple(g[4:8]), *g[10:14],
                          g[14] & 1, (g[14] >> 1) & 7, g[14] >> 4,
                          g[15] - 24)
    return VoicePatch(g[19:29].decode('ascii').strip(), g[8] + 1,
                      g[9], g[10], ops, tuple(g[:4]), tuple(g[4:8]),
                      *g[11:18], g[18] - 24)


def load_sysex(path: str | Path) -> tuple[VoicePatch, ...]:
    """Validate framing, Yamaha ID, payload size and checksum before decoding."""
    data = Path(path).read_bytes()
    if len(data) < 8 or data[0] != 0xF0 or data[-1] != 0xF7 or data[1] != 0x43:
        raise ValueError('Expected a complete Yamaha SysEx message.')
    if data[2] > 15 or any(b > 127 for b in data[1:-1]):
        raise ValueError('Invalid MIDI data byte or unsupported SysEx message.')
    count = data[4] * 128 + data[5]
    body = data[6:-2]
    if len(body) != count:
        raise ValueError('SysEx byte count does not match its payload.')
    if (sum(body) + data[-2]) % 128:
        raise ValueError('DX7 SysEx checksum failed.')
    if data[3] == 9 and count == 4096:
        return tuple(_voice(body[i:i + 128], True) for i in range(0, 4096, 128))
    if data[3] == 0 and count == 155:
        return (_voice(body, False),)
    raise ValueError('Only DX7 VMEM banks and VCED single voices are supported.')


def find_patch(path: str | Path, name: str) -> VoicePatch:
    key = ' '.join(name.upper().split())
    for patch in load_sysex(path):
        if ' '.join(patch.name.upper().split()) == key:
            return patch
    raise ValueError(f'Patch {name!r} not found in {path}.')

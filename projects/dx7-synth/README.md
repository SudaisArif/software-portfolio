# DX7-style synthesis core

Python/NumPy implementation of six-operator phase modulation (Algorithms 5 and 16), envelopes, feedback and Yamaha SysEx voice parsing. Extracted from the After Hours audio project.

Install `requirements.txt` in a virtual environment. Read `dx7.py` for the operator and preset interfaces, and `sysex.py` for patch decoding. The source distribution excludes third-party music recordings, MIDI songs and Yamaha ROM patches. Presets that load a ROM patch require the original licensed input; this is a core-code sample, not the complete original audio demo. Third-party notices are retained under `licenses/`.

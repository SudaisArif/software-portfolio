"""Attach the complete extracted preview event banks to the five presets.

Input is the *-side-pitch-runs.json output of extract_reference.py; no audio
is copied into the app. Existing short studies remain for older renders.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-dir', type=Path, required=True)
    args = parser.parse_args()
    presets = json.loads((ROOT/'presets.json').read_text())
    provenance = json.loads((ROOT/'reference-provenance.json').read_text())
    for preset in presets:
        slug = preset['slug']
        runs = json.loads((args.reference_dir/f'{slug}-side-pitch-runs.json').read_text())
        anchor = min(range(len(runs)), key=lambda i: abs(runs[i]['start']-preset['preview_start_s']))
        events = [{**r, 'start': round(r['start'], 6), 'end': round(r['end'], 6)} for r in runs]
        library = {'anchor': anchor, 'referenceDuration': preset['preview_end_s']-preset['preview_start_s'],
                   'events': events}
        preset['phraseLibrary'] = library
        provenance[slug]['expanded_phrase_library'] = library
        print(f"{slug}: {len(events)} extracted events; slider up to {min(64,len(events))} notes")
    (ROOT/'presets.json').write_text(json.dumps(presets, indent=2)+'\n')
    (ROOT/'reference-provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')


if __name__ == '__main__':
    main()

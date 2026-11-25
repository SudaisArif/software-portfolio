"""Create an Assignment 9 ZIP, optionally converting a narrated screen recording.

Without --video, creates a clearly named source bundle (not submission-complete).
With --video, checks length/audio, converts to demo.mp4, then checks ZIP structure.
It cannot verify narration, three examples, or the student's understanding.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HEADINGS = ['## Project summary', '## Requirements', '## Code execution instructions',
            '## AI Workflow', '## Other tools', '## Citations',
            '## Additional comments for the instructor or TAs', '## Sharing']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    doc = (ROOT/'TECHNICAL.md').read_text()
    actual = [line for line in doc.splitlines() if line.startswith('## ')]
    if actual != HEADINGS:
        raise SystemExit('TECHNICAL.md section headings do not match the template.')
    target = args.out or ROOT/('assignment9.zip' if args.video else 'N5-source-bundle.zip')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='n5-package-') as temp:
        video = None
        if args.video:
            if not args.video.is_file():
                raise SystemExit('Video file does not exist.')
            for command in ('ffmpeg', 'ffprobe'):
                if not shutil.which(command):
                    raise SystemExit(f'{command} is needed to validate and convert the video.')
            info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format',
                         '-show_streams', '-of', 'json', str(args.video)]))
            duration = float(info['format']['duration'])
            if not 120 <= duration <= 300:
                raise SystemExit(f'Demo is {duration:.1f}s; assignment requires 120–300s.')
            if not any(s['codec_type']=='audio' for s in info['streams']):
                raise SystemExit('Demo needs an audio track with your narration and instrument sound.')
            video = Path(temp)/'demo.mp4'
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y', '-i', str(args.video),
              '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
              '-c:v', 'libx264', '-preset', 'medium', '-crf', '27', '-pix_fmt', 'yuv420p',
              '-c:a', 'aac', '-b:a', '112k', '-movflags', '+faststart', str(video)], check=True)
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(ROOT/'TECHNICAL.md', 'TECHNICAL.md')
            # Recording scripts are private preparation material, not submission files.
            for name in ('README.md','Start.command'):
                z.write(ROOT/name, name)
            for p in sorted((ROOT/'src').rglob('*')):
                if p.is_file() and not any(x in p.parts for x in ('__pycache__','exports','node_modules','.git','.DS_Store')) and p.suffix not in ('.pyc',):
                    z.write(p, p.relative_to(ROOT))
            if video:
                z.write(video, 'demo.mp4')
        with zipfile.ZipFile(target) as z:
            names=z.namelist()
            if z.testzip() is not None:
                raise SystemExit('ZIP integrity check failed.')
            if any(Path(name).name in ('DEMO_GUIDE.md','RECORDING_SCRIPT.md','RECORDING_SCRIPT.txt') for name in names):
                raise SystemExit('Recording script must stay outside the submission ZIP.')
            for required in ('TECHNICAL.md','src/index.html','src/engine/dsp.mjs','src/assets/composition-sketch.wav'):
                if required not in names:
                    raise SystemExit(f'Missing required project file: {required}')
            if video and 'demo.mp4' not in names:
                raise SystemExit('Missing root-level demo.mp4.')
        if target.stat().st_size >= 100_000_000:
            raise SystemExit(f'ZIP exceeds 100MB: {target}. Re-encode the video at lower bitrate.')
        print(f'Wrote {target} ({target.stat().st_size/1e6:.2f} MB)')
        if not video:
            print('SOURCE BUNDLE ONLY. Add your own narrated 2–5 minute demo before submitting.')
        else:
            print('Format and media duration checked. Review narration, R1–R5 evidence, and TECHNICAL.md before uploading to Gradescope.')


if __name__ == '__main__':
    main()

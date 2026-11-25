"""Reference-only dominant-pitch extraction. No claim of verified score transcription.
Pure NumPy FFT harmonic salience with Viterbi pitch continuity and run merging.
"""
import argparse, json, pathlib, wave
import numpy as np
R=pathlib.Path(__file__).parent
FS=22050; N=4096; H=256
MIDIS=np.arange(57,85); FREQ=440*2**((MIDIS-69)/12)

def extract(slug):
    with wave.open(str(R/(slug+'-side.wav'))) as w:
        x=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(float)/32768
    frames=np.lib.stride_tricks.sliding_window_view(x,N)[::H]
    mag=np.abs(np.fft.rfft(frames*np.hanning(N),axis=1))
    # Flatten broad spectral envelope. This suppresses speech formant weighting.
    broad=np.lib.stride_tricks.sliding_window_view(np.pad(mag,((0,0),(12,12)),mode='edge'),25,axis=1).mean(axis=-1)
    white=np.sqrt(mag / np.maximum(broad,0.03)) * np.sqrt(mag)
    white[:,:int(120*N/FS)]=0
    sal=np.zeros((len(frames),len(MIDIS)))
    for j,f in enumerate(FREQ):
        for harm in range(1,6):
            b=f*harm*N/FS
            if b+2>=white.shape[1]:continue
            i=int(round(b)); vals=white[:,max(0,i-1):i+2].max(axis=1)
            sal[:,j]+=vals/(harm**0.8)
    sal=sal/np.maximum(sal.max(axis=1,keepdims=True),1e-9)
    # Smooth short fluctuations without imposing a chosen key or invented notes.
    sal=np.lib.stride_tricks.sliding_window_view(np.pad(sal,((3,3),(0,0)),mode='edge'),7,axis=0).mean(axis=-1)
    dist=np.abs(MIDIS[:,None]-MIDIS[None,:])
    transition=0.11*(dist>0)+0.023*dist
    dp=sal[0].copy(); back=np.zeros(sal.shape,dtype=int)
    for t in range(1,len(sal)):
        opts=dp[:,None]-transition
        back[t]=opts.argmax(axis=0)
        dp=opts.max(axis=0)+sal[t]
    path=np.zeros(len(sal),dtype=int);path[-1]=dp.argmax()
    for t in range(len(sal)-1,0,-1):path[t-1]=back[t,path[t]]
    # Median filter and merge tiny runs into the best adjacent sustained pitch.
    path=np.median(np.lib.stride_tricks.sliding_window_view(np.pad(path,(4,4),mode='edge'),9),axis=1).astype(int)
    for _ in range(5):
        edges=np.r_[0,np.flatnonzero(np.diff(path))+1,len(path)]
        changed=False
        for a,b in zip(edges[:-1],edges[1:]):
            if b-a>=11:continue
            choices=[]
            if a>0:choices.append(path[a-1])
            if b<len(path):choices.append(path[b])
            if choices:
                best=max(choices,key=lambda p:sal[a:b,p].sum());path[a:b]=best;changed=True
        if not changed:break
    edges=np.r_[0,np.flatnonzero(np.diff(path))+1,len(path)]
    runs=[]
    for a,b in zip(edges[:-1],edges[1:]):
        runs.append({'start':float((a*H+N/2)/FS),'end':float((b*H+N/2)/FS),'midi':int(MIDIS[path[a]]),'salience':round(float(sal[a:b,path[a]].mean()),4)})
    candidates=[]
    for i in range(len(runs)):
        for count in range(8,13):
            rr=runs[i:i+count]
            if len(rr)!=count:continue
            duration=rr[-1]['end']-rr[0]['start'];notes=[z['midi'] for z in rr]
            if not 3<=duration<=6.5 or rr[0]['start']<0.4 or rr[-1]['end']>29:continue
            diversity=len(set(notes));jumps=np.abs(np.diff(notes))
            if diversity<3:continue
            score=np.mean([z['salience'] for z in rr]) - 0.02*np.mean(jumps) - 0.08*np.mean(jumps>9) - 0.015*abs(count-10) + 0.008*min(diversity,6)
            candidates.append((score,rr))
    if not candidates:raise RuntimeError('No candidate '+slug)
    score,rr=max(candidates,key=lambda z:z[0]);start=rr[0]['start'];end=rr[-1]['end']
    names=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    ev=[]
    for z in rr:
        m=z['midi'];ev.append({'time':round(z['start']-start,4),'duration':round(z['end']-z['start'],4),'midi':m,'note':names[m%12]+str(m//12-1),'salience':z['salience']})
    return {'slug':slug,'preview_start_s':round(start,4),'preview_end_s':round(end,4),'duration_s':round(end-start,4),'events':ev,'status':'automatic_dominant_pitch_study_unverified','warning':'Mixed recording: pitches may follow voice, bass or harmonics, not the hook. No ear verification. Times are relative to Apple 30s preview, not full song. Do not describe as an exact cover.','method':'Stereo difference (L-R)/2 to reduce centered vocals; 4096-sample Hann FFT at 22050Hz, hop256; envelope-whitened harmonic salience (5 partials), Viterbi continuity, 9-frame median filter, short-run merging. No manually invented notes.'},runs

def main():
    global R
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-dir', type=pathlib.Path, required=True, help='Analysis directory containing selected-metadata.json and decoded 22050Hz mono {slug}-side.wav files; recordings are not supplied.')
    R=parser.parse_args().reference_dir
    metadata=json.loads((R/'selected-metadata.json').read_text());out={}
    for slug in metadata:
        d,runs=extract(slug); d['source_url']=metadata[slug]['trackViewUrl'];d['preview_url']=metadata[slug]['previewUrl'];d['title']=metadata[slug]['trackName'];d['artist']=metadata[slug]['artistName'];out[slug]=d
        (R/(slug+'-side-pitch-runs.json')).write_text(json.dumps(runs,indent=2))
        print(slug, d['preview_start_s'],d['preview_end_s'],[(x['note'],x['duration']) for x in d['events']])
    (R/'extracted-side-motifs.json').write_text(json.dumps(out,indent=2))
if __name__=='__main__':main()

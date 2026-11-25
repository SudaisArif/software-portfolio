"""Local-only clipping contracts and a real generated-media FFmpeg round trip."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from clipping import ClipError, suggest_clips, validate_candidate, validate_rights, import_review, render_clip
from clipping.core import digest_json, file_hash, validate_transcript
from clipping.youtube import YouTubeMetadata
from integrations.http import IntegrationBlocked
from media_engine import Engine


def transcript(sha="a"*64, texts=None, start=0, step=5):
    texts=texts or ["Compare a claim with its source.","A study measured one specific outcome.","That result does not prove every claim.","Read the limitations before deciding."]
    return {"source_url":"https://example.test/owned-fixture","source_sha256":sha,"transcript_reviewed_by":"test-fixture-only","segments":[{"start":start+i*step,"end":start+(i+1)*step,"text":text} for i,text in enumerate(texts)]}


def rights(t):
    return {"source_url":t["source_url"],"source_sha256":t["source_sha256"],"rights_status":"original","rights_holder":"Generated test fixture","commercial_use_allowed":True,"adaptation_allowed":True,"source_audio_included":True,"third_party_elements_reviewed":True,"attribution":"Generated test fixture","reviewed_by":"test-fixture-only","owner_attestation":"Synthetic color/test-pattern and sine-wave fixture made by this test; no third-party content."}


class ClippingContracts(unittest.TestCase):
    def test_caveat_and_negation_stay_in_clip(self):
        t=transcript(texts=["A heavier weight is not the whole comparison.","A study compared athletes of different sizes.","The simple ratio can change the ranking.","But this does not prove which program works."],step=7)
        candidates=suggest_clips(t)["candidates"]
        self.assertTrue(candidates)
        for c in candidates:
            self.assertIn("But this does not prove",c["text"])
            self.assertIn("not the whole",c["text"])
            self.assertTrue(c["context_flags"])
            self.assertFalse(c["virality_verified"])
            self.assertFalse(c["publishable"])
            validate_candidate(t,c)

    def test_manually_trimmed_caveat_rejected(self):
        t=transcript(texts=["A study measured the training effect.","The groups showed different results.","The method explains the difference.","But this result may not apply to everyone."],step=7)
        c=suggest_clips(t)["candidates"][0]
        c.update(last_segment=2,end=21,text=" ".join(s["text"] for s in t["segments"][:3]))
        c["candidate_id"]=digest_json({k:c[k] for k in ("source_sha256","transcript_sha256","start","end")})[:24]
        with self.assertRaisesRegex(ClipError,"qualification"):validate_candidate(t,c)

    def test_suggestions_nonoverlapping_and_not_fake_metrics(self):
        t=transcript(texts=[f"Compare result {i} with the study methods." for i in range(36)])
        result=suggest_clips(t,limit=5)
        self.assertIsNone(result["source_metrics"])
        ordered=sorted(result["candidates"],key=lambda c:c["start"])
        self.assertGreater(len(ordered),1)
        for left,right in zip(ordered,ordered[1:]):self.assertLessEqual(left["end"],right["start"])
        for c in ordered:
            self.assertLessEqual(c["duration_seconds"],90);self.assertGreaterEqual(c["duration_seconds"],20)
            self.assertEqual(c["score_type"],"heuristic_editorial_not_measured_virality")
            self.assertIn(c["headline"],c["headline_proposals"])

    def test_timestamps_and_input_bounds(self):
        for value in (-1,float("nan"),True,"0"):
            t=transcript();t["segments"][0]["start"]=value
            with self.assertRaises(ClipError):suggest_clips(t)
        for minimum,maximum in ((19,60),(20,91),(50,30),(float("nan"),60),(True,50)):
            with self.assertRaises(ClipError):suggest_clips(transcript(),minimum,maximum)
        t=transcript();t["segments"][1]["start"]=1
        with self.assertRaises(ClipError):validate_transcript(t)
        t=transcript();t["transcript_reviewed_by"]=""
        with self.assertRaisesRegex(ClipError,"verify the transcript"):suggest_clips(t)

    def test_transcript_source_hook_and_candidate_binding(self):
        t=transcript();c=suggest_clips(t)["candidates"][0]
        for target,key,value in (("transcript","source_sha256","b"*64),("transcript","transcript_reviewed_by","changed"),("candidate","text","A deceptive rewrite."),("candidate","hook_quote","This proves everything."),("candidate","candidate_id","wrong"),("candidate","end",21)):
            tt,cc=copy.deepcopy(t),copy.deepcopy(c)
            (tt if target=="transcript" else cc)[key]=value
            with self.assertRaises(ClipError):validate_candidate(tt,cc)

    def test_unknown_rights_and_incomplete_permissions_fail_closed(self):
        t=transcript()
        for key,value in (("rights_status","unknown"),("rights_status","preview_only"),("commercial_use_allowed",False),("adaptation_allowed",False),("source_audio_included",False),("third_party_elements_reviewed",False),("owner_attestation",""),("source_sha256","b"*64)):
            r=rights(t);r[key]=value
            with self.assertRaises(ClipError):validate_rights(r,t)
        r=rights(t);r["rights_status"]="licensed"
        with self.assertRaisesRegex(ClipError,"evidence URL"):validate_rights(r,t)
        r["license_url"]="https://example.test/license";validate_rights(r,t)

    def test_review_import_never_approves_and_deduplicates_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/"test.sqlite")
            t=transcript();c=suggest_clips(t)["candidates"][0];r=rights(t)
            job=import_review(engine,t,c,r)
            self.assertEqual(job["state"],"HUMAN_REVIEW")
            self.assertIsNone(job["approved_revision"]);self.assertIsNone(job["release_sha256"])
            self.assertEqual(import_review(engine,t,c,r)["id"],job["id"])
            t["transcript_reviewed_by"]="second-test-verifier"
            self.assertEqual(import_review(engine,t,suggest_clips(t)["candidates"][0],r)["id"],job["id"])
            self.assertEqual(len(engine.list_jobs()),1)
            self.assertFalse(engine.status()["publication_enabled"])

    def test_source_mutation_and_existing_sidecar_block_before_render(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"source.mp4";source.write_bytes(b"fake source only")
            t=transcript(file_hash(source));c=suggest_clips(t)["candidates"][0];r=rights(t)
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(ClipError,"changed"):render_clip(source,t,c,r,Path(folder)/"out.mp4")
            t=transcript(file_hash(source));c=suggest_clips(t)["candidates"][0];r=rights(t)
            (Path(folder)/"out.json").write_text("preserve this review")
            with self.assertRaisesRegex(ClipError,"sidecar"):render_clip(source,t,c,r,Path(folder)/"out.mp4")
            self.assertEqual((Path(folder)/"out.json").read_text(),"preserve this review")

    def test_missing_source_audio_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"source.mp4";source.write_bytes(b"fixture")
            t=transcript(file_hash(source));c=suggest_clips(t)["candidates"][0]
            with patch("clipping.render._probe",return_value={"streams":[{"codec_type":"video"}],"format":{"duration":30}}):
                with self.assertRaisesRegex(ClipError,"original audio"):render_clip(source,t,c,rights(t),Path(folder)/"out.mp4")

    def test_official_api_discovery_is_metadata_only_and_keeps_unknown_counts(self):
        calls=[]
        def fetch(resource,params):
            calls.append((resource,params))
            if resource=="search":return {"items":[{"id":{"videoId":"abcdefghijk"}}]}
            return {"items":[{"id":"abcdefghijk","snippet":{"title":"Test interview","channelTitle":"Fixture"},"statistics":{"viewCount":"1024"},"contentDetails":{"duration":"PT45M"},"status":{"license":"creativeCommon"}}]}
        result=YouTubeMetadata(fetch).discover("fitness research")
        c=result["candidates"][0]
        self.assertEqual([x[0] for x in calls],["search","videos"])
        self.assertEqual(calls[0][1]["videoLicense"],"creativeCommon")
        self.assertEqual(c["measured_counts"]["viewCount"],1024)
        self.assertIsNone(c["measured_counts"]["likeCount"])
        self.assertEqual(c["rights_status"],"unverified");self.assertFalse(c["virality_verified"])

    def test_external_metadata_is_disabled_by_default(self):
        with patch.dict(os.environ,{"ALLOW_EXTERNAL_REQUESTS":"false"}):
            with self.assertRaises(IntegrationBlocked):YouTubeMetadata().discover("fitness")

    def test_cli_suggest_and_unknown_rights_block_import(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);t=transcript()
            (folder/"transcript.json").write_text(json.dumps(t))
            result=subprocess.run([sys.executable,"-m","clipping","suggest",str(folder/"transcript.json"),"--out",str(folder/"candidates.json")],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)["candidates"],1)
            (folder/"rights.json").write_text(json.dumps({"rights_status":"unknown"}))
            result=subprocess.run([sys.executable,"-m","clipping","import-review",str(folder/"transcript.json"),str(folder/"candidates.json"),str(folder/"rights.json"),"--db",str(folder/"test.sqlite")],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertIn("rights are unknown",result.stderr)
            self.assertEqual(Engine(folder/"test.sqlite").list_jobs(),[])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg is required")
class ClipFFmpegRoundTrip(unittest.TestCase):
    def test_real_source_audio_portrait_captions_and_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"generated-fixture.mp4";out=Path(folder)/"review.mp4"
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","testsrc2=size=640x360:rate=24","-f","lavfi","-i","sine=frequency=220:sample_rate=48000","-t","23","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p","-c:a","aac",str(source)],check=True,capture_output=True,timeout=45)
            t=transcript(file_hash(source),start=2)
            c=suggest_clips(t,min_seconds=20,max_seconds=20)["candidates"][0]
            result=render_clip(source,t,c,rights(t),out)
            self.assertEqual(result["source_interval"],{"start":2.0,"end":22.0})
            self.assertAlmostEqual(result["duration_seconds"],20,delta=.2)
            self.assertFalse(result["publishable"]);self.assertTrue(result["context_review_required"])
            self.assertEqual(result["captions"][0]["start"],0)
            self.assertEqual(result["captions"][-1]["end"],20)
            self.assertIn("does not prove",out.with_suffix(".srt").read_text())
            self.assertIn("00:00:00,000 --> 00:00:05,000",out.with_suffix(".srt").read_text())
            self.assertEqual(json.loads(out.with_suffix(".json").read_text())["sha256"],file_hash(out))
            info=json.loads(subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",str(out)],check=True,capture_output=True,text=True).stdout)
            video=next(s for s in info["streams"] if s["codec_type"]=="video")
            self.assertEqual((video["width"],video["height"]),(1080,1920))
            self.assertTrue(any(s["codec_type"]=="audio" for s in info["streams"]))
            self.assertTrue(out.with_suffix(".poster.jpg").is_file())
            import numpy as np
            pcm=subprocess.run(["ffmpeg","-v","error","-i",str(out),"-t","1","-f","f32le","-ac","1","-ar","8000","-"],check=True,capture_output=True).stdout
            samples=np.frombuffer(pcm,dtype=np.float32)
            frequency=np.argmax(np.abs(np.fft.rfft(samples)))*8000/len(samples)
            self.assertAlmostEqual(frequency,220,delta=3)


if __name__=="__main__":unittest.main()

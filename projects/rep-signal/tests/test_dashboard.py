import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
import shutil
from unittest.mock import patch
from media_engine.engine import file_hash
from preview_intake import import_review_artifact
from dashboard.server import make_server
from media_engine import Engine
from pipeline import ROOT


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.engine=Engine(Path(cls.temp.name)/"test.db")
        cls.root=Path(cls.temp.name)/"project"
        for folder in ("dashboard","output","config"):(cls.root/folder).mkdir(parents=True)
        for name in ("index.html","app.js","style.css"):shutil.copyfile(ROOT/"dashboard"/name,cls.root/"dashboard"/name)
        for stem,title in (("study-sample","Study fixture"),("human-clip-preview","Human fixture"),("sample","Archived fixture")):
            (cls.root/"output"/(stem+".mp4")).write_bytes(b"test-media"*100)
            (cls.root/"output"/(stem+".poster.jpg")).write_bytes(b"test-poster")
            (cls.root/"output"/(stem+".json")).write_text(json.dumps({"title":title,"duration_seconds":20,"script":"Public preview text only.","factual_caveat":"Fixture limits.","sources":[{"title":"Evidence","url":"https://example.org/study?api_key=private-query","claim_scope":"Small trial.","owner_attestation":"PRIVATE-ATTESTATION"},{"url":"https://user:private-pass@example.org/source"},{"url":"javascript:alert(1)"}],"api_key":"PRIVATE-KEY","assets":[{"local_path":"/private/secret.mp4"}],"owner_attestation":"PRIVATE-ATTESTATION","render_command":"PRIVATE-COMMAND","human_approved":True,"publishable":True,"video_url":"/private/secret.mp4"}))
        (cls.root/"config/service-status.json").write_text(json.dumps({"setup_authorized_at":"2026-11-15","account_email":"private@example.org","api_key":"PRIVATE-SERVICE-KEY","services":[{"id":"brand_email","status":"verified","detail":"Verified private@example.org","password":"PRIVATE-PASSWORD"},{"id":"youtube","status":"owner_step","detail":"Terms pending."},{"id":"unknown_service","status":"verified","detail":"PRIVATE-UNKNOWN"}]}))
        cls.server=make_server(cls.engine,port=0,token="isolated-test-key",root=cls.root)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()
    def request(self,path,body=None,token=None,origin=None,host=None,cookie=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        headers={"Content-Type":"application/json"}
        if token:headers["Authorization"]="Bearer "+token
        if origin:headers["Origin"]=origin
        if host:headers["Host"]=host
        if cookie:headers["Cookie"]=cookie
        connection.request("POST" if body is not None else "GET",path,json.dumps(body) if body is not None else None,headers)
        response=connection.getresponse();value=response.read();status=response.status;returned=dict(response.getheaders());connection.close()
        return status,value,returned
    def test_new_finished_review_videos_lead_public_catalog(self):
        folder=self.root/"output/review-2026-11-17";folder.mkdir(exist_ok=True)
        made=[]
        for stem in ("original-study","clip-progress-proof-v2"):
            for suffix,content in ((".mp4",b"fixture movie"),(".json",json.dumps({"title":"New review fixture","script":"Review script","sources":[{"url":"https://example.test/source"}],"human_approved":True,"secret":"DO-NOT-EXPOSE"}).encode())):
                file=folder/(stem+suffix);file.write_bytes(content);made.append(file)
        self.addCleanup(lambda:[file.unlink(missing_ok=True) for file in made])
        data=json.loads(self.request("/api/preview")[1])
        self.assertEqual([p["id"] for p in data["previews"][:2]],["original_narrated","clip_progress"])
        self.assertEqual(data["default_preview_id"],"original_narrated")
        self.assertFalse(data["previews"][0]["human_approved"])
        self.assertNotIn("DO-NOT-EXPOSE",json.dumps(data))
        self.assertEqual(self.request("/review-2026-11-17/clip-progress-proof-v2.mp4")[0],200)

    def test_linked_video_requires_private_session_and_separate_final_approval(self):
        source=self.root/"source-fixture.bin";source.write_bytes(b"isolated original source")
        video=self.root/"bound-film.mp4";video.write_bytes(b"isolated mock rendered video")
        manifest=video.with_suffix(".json")
        manifest.write_text(json.dumps({"title":"Bound review fixture","script":"A specific decision.","sources":[{"url":"https://example.test/research"}],"audio_mode":"source_audio","captions":[{"start":0,"end":20,"text":"A specific decision."}],"sha256":file_hash(video),"assets":[{"kind":kind,"local_path":str(source),"sha256":file_hash(source),"rights_status":"original","provenance":"Isolated fixture","license_url":""} for kind in ("visuals","narration","font")]}))
        def measured(*args,**kwargs):return {"checks":dict.fromkeys(("video","audio","duration","resolution","captions"),True)}
        with patch("media_engine.qc.inspect_media",side_effect=measured):
            result=import_review_artifact(self.engine,video,manifest,repository_root=self.root)
            j,p=result["job"],result["preview"];route="/api/previews/"+p["id"]+"/video"
            self.assertEqual(self.request(route)[0],401)
            status,_,headers=self.request("/api/unlock",{},token="isolated-test-key")
            self.assertEqual(status,200);cookie=headers["Set-Cookie"].split(";",1)[0]
            self.assertIn("HttpOnly",headers["Set-Cookie"]);self.assertIn("SameSite=Strict",headers["Set-Cookie"])
            self.assertEqual(self.request(route,cookie=cookie)[1],video.read_bytes())
            self.assertEqual(self.request("/api/state",cookie=cookie)[0],401)
            body={"id":j["id"],"revision":j["revision"],"preview_id":p["id"],"artifact_sha256":p["artifact_sha256"]}
            self.assertEqual(self.request("/api/stage-preview",body,cookie=cookie)[0],401)
            self.assertEqual(self.request("/api/stage-preview",body,token="isolated-test-key")[0],400)
            self.assertEqual(self.request("/api/approve-release",body,token="isolated-test-key")[0],400)
            self.assertEqual(self.request("/api/review",{"id":j["id"],"revision":j["revision"],"decision":"approve"},token="isolated-test-key")[0],200)
            self.assertEqual(self.request("/api/stage-preview",body,token="isolated-test-key")[0],200)
            self.assertIsNone(self.engine.get_job(j["id"])["release_sha256"])
            self.assertEqual(self.request("/api/approve-release",{**body,"revision":0},token="isolated-test-key")[0],400)
            self.assertEqual(self.request("/api/approve-release",body,token="isolated-test-key")[0],200)
            self.assertFalse(self.engine.status()["publication_enabled"])
            self.assertEqual(self.engine.get_job(j["id"])["release_sha256"],p["artifact_sha256"])
            self.engine.set_script(j["id"],"Revised fixture")
            self.assertEqual(self.request(route,cookie=cookie)[0],409)

    def test_saved_jobs_require_auth_but_explicit_preview_is_available(self):
        self.assertEqual(self.request("/api/state")[0],401)
        self.assertEqual(self.request("/api/state",token="isolated-test-key")[0],200)
        self.assertEqual(self.request("/api/preview")[0],200)
    def test_cross_origin_and_dns_rebinding_rejected(self):
        self.assertEqual(self.request("/api/kill",{"enabled":True},token="isolated-test-key",origin="https://untrusted.example")[0],403)
        self.assertEqual(self.request("/health",host="untrusted.example")[0],403)
        self.assertFalse(self.engine.status()["kill_switch"])
    def test_unauthorized_review_never_changes_state(self):
        job=self.engine.create_job("Isolated fixture",sources=[{"url":"https://example.org/study"}]);job=self.engine.set_script(job["id"],"Test script")
        body={"id":job["id"],"decision":"approve","revision":job["revision"]}
        self.assertEqual(self.request("/api/review",body)[0],401)
        self.assertEqual(self.engine.get_job(job["id"])["state"],"HUMAN_REVIEW")
        self.assertEqual(self.request("/api/review",body,token="isolated-test-key")[0],200)
        self.assertEqual(self.request("/api/review",body,token="isolated-test-key")[0],400)
    def test_static_policy_and_path_allowlist(self):
        status,body,headers=self.request("/");self.assertEqual(status,200);self.assertIn(b"REP SIGNAL",body)
        self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])
        self.assertEqual(self.request("/../data/review-token")[0],404)
        for path in ("/output/study-sample.mp4","/study-sample.json","/human-clip-preview.json","/config/service-status.json","/%2e%2e/data/review-token","/sample.mp4/../../data/review-token"):
            self.assertEqual(self.request(path)[0],404,path)
        for path in ("/study-sample.mp4","/study-sample.jpg","/human-clip-preview.mp4","/human-clip-preview.jpg","/sample.mp4","/sample.jpg"):
            self.assertEqual(self.request(path)[0],200,path)

    def test_preview_catalog_is_sanitized_and_independent_of_private_jobs(self):
        job=self.engine.create_job("PRIVATE-JOB-TITLE",sources=[{"url":"https://example.org/private-research"}])
        self.engine.set_script(job["id"],"PRIVATE-JOB-SCRIPT")
        status,body,_=self.request("/api/preview?path=/private/secret.mp4")
        self.assertEqual(status,200);data=json.loads(body)
        self.assertEqual(data["default_preview_id"],"study")
        self.assertNotIn("jobs",data);self.assertNotIn("events",data)
        self.assertEqual([p["id"] for p in data["previews"]],["study","study_recovery","human","original"])
        study=data["previews"][0];self.assertEqual(study["script"],"Public preview text only.")
        self.assertEqual(study["video_url"],"/study-sample.mp4")
        self.assertEqual(study["sources"],[{"url":"https://example.org/study","title":"Evidence","scope":"Small trial.","design":""}])
        self.assertFalse(study["human_approved"]);self.assertFalse(study["publishable"])
        self.assertFalse(data["previews"][1]["available"])
        self.assertIn("COMMERCIAL RIGHTS NOT CLEARED",data["previews"][2]["review_label"])
        for private in (b"PRIVATE-",b"/private/",b"private@example.org",b"private-query",b"private-pass",b"owner_attestation",b"render_command"):
            self.assertNotIn(private,body)
        services={s["id"]:s for s in data["services"]}
        self.assertEqual(services["youtube"]["status"],"owner_step")
        self.assertNotIn("unknown_service",services)
        authenticated=json.loads(self.request("/api/state",token="isolated-test-key")[1])
        self.assertTrue(any(j["id"]==job["id"] for j in authenticated["jobs"]))
        self.assertEqual(authenticated["previews"],data["previews"])
        self.assertEqual(self.engine.get_job(job["id"])["state"],"HUMAN_REVIEW")

    def test_fixed_media_path_cannot_follow_a_symlink(self):
        target=self.root/"output/sample.mp4";saved=target.read_bytes()
        private=Path(self.temp.name)/"private-media";private.write_bytes(b"PRIVATE-SYMLINK-CONTENT")
        target.unlink();target.symlink_to(private)
        try:
            self.assertEqual(self.request("/sample.mp4")[0],404)
            previews=json.loads(self.request("/api/preview")[1])["previews"]
            self.assertFalse(next(p for p in previews if p["id"]=="original")["available"])
        finally:
            target.unlink();target.write_bytes(saved)
    def test_worker_cannot_publish(self):
        status,body,_=self.request("/api/worker",{},token="isolated-test-key")
        self.assertEqual(status,200);self.assertIn("dry_run",json.loads(body));self.assertFalse(self.engine.status()["publication_enabled"])
    def test_video_range_requests_support_browser_prefetch_and_suffixes(self):
        size=(self.root/"output/sample.mp4").stat().st_size
        for path in ("/sample.mp4","/study-sample.mp4","/human-clip-preview.mp4"):
            for header,expected_size in [("bytes=0-1",2),("bytes=-100",100),(f"bytes={size-100}-{size+100}",100)]:
                connection=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
                connection.request("GET",path,headers={"Range":header})
                response=connection.getresponse();self.assertEqual(response.status,206);self.assertEqual(len(response.read()),expected_size);connection.close()


if __name__=="__main__":unittest.main()

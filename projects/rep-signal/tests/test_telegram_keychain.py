"""Offline fixtures only: no real Keychain access, Telegram requests or process exec."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,Mock,patch
import urllib.error

SPEC=importlib.util.spec_from_file_location("telegram_keychain_helper",Path(__file__).resolve().parents[1]/"scripts/telegram-keychain.py")
helper=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
TOKEN="123456789:"+"a"*35
OTHER="123456789:"+"b"*35


class TelegramKeychainTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/"handoff"
        self.source.write_text(TOKEN+"\n");self.source.chmod(0o600)
        source_patch=patch.object(helper,"SOURCE",self.source);source_patch.start();self.addCleanup(source_patch.stop)
        self.candidate=Path(self.temp.name)/"owner-candidate.json"
        self.owner={"bot_username":"@repsignal_approval_bot","first_name":"Offline fixture","username":None,"start_date_utc":"2026-11-16T16:10:12+00:00","message_id":1,"update_id":10,"chat_id":"123456","user_id":"123456","private_nonbot_start_verified":True,"owner_confirmation_required":True,"bound":False}
        self.candidate.write_text(json.dumps(self.owner));self.candidate.chmod(0o600)
        candidate_patch=patch.object(helper,"OWNER_CANDIDATE",self.candidate);candidate_patch.start();self.addCleanup(candidate_patch.stop)
        for target,name in ((helper.subprocess,"run"),(helper.urllib.request,"build_opener"),(helper.os,"execve")):
            guard=patch.object(target,name,side_effect=AssertionError("Live operation forbidden in offline tests"))
            guard.start();self.addCleanup(guard.stop)

    def entry(self,args):
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):code=helper.entrypoint(args)
        output=stdout.getvalue()+stderr.getvalue()
        self.assertNotIn(TOKEN,output);self.assertNotIn(OTHER,output)
        return code,stdout.getvalue(),stderr.getvalue()

    def test_fixed_mapping_rejects_other_keychain_names(self):
        self.assertEqual(helper.SERVICES,{"TELEGRAM_BOT_TOKEN":"REP_SIGNAL_TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID":"REP_SIGNAL_TELEGRAM_CHAT_ID","TELEGRAM_USER_ID":"REP_SIGNAL_TELEGRAM_USER_ID"})
        with self.assertRaises(helper.SecureSetupError):helper.keychain_value("OPENAI_API_KEY")
        helper.subprocess.run.assert_not_called()

    def test_keychain_reads_only_fixed_account_and_never_echoes_output(self):
        with patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,(TOKEN+"\n").encode(),OTHER.encode())) as run:
            self.assertEqual(helper.keychain_value("TELEGRAM_BOT_TOKEN"),TOKEN)
        args=run.call_args.args[0]
        self.assertEqual(args,["/usr/bin/security","find-generic-password","-a","REP_SIGNAL","-s","REP_SIGNAL_TELEGRAM_BOT_TOKEN","-w"])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertNotIn(TOKEN," ".join(args))

    def test_missing_optional_key_is_distinct_from_access_denial(self):
        with patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],44,b"",b"")):
            self.assertIsNone(helper.keychain_value("TELEGRAM_CHAT_ID",optional=True))
            with self.assertRaises(helper.SecureSetupError):helper.keychain_value("TELEGRAM_BOT_TOKEN")
        with patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],1,TOKEN.encode(),OTHER.encode())):
            with self.assertRaises(helper.SecureSetupError):helper.keychain_value("TELEGRAM_CHAT_ID",optional=True)

    def test_store_uses_private_stdin_and_deletes_only_after_exact_round_trip(self):
        with patch.object(helper,"keychain_value",side_effect=[None,TOKEN]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,TOKEN.encode(),OTHER.encode())) as run:
            code,out,_=self.entry(["store-token"])
        self.assertEqual(code,0);self.assertFalse(self.source.exists())
        self.assertTrue(json.loads(out)["encrypted_store_verified"])
        self.assertEqual(run.call_args.args[0],["/usr/bin/security","-i","-q"])
        self.assertIn(TOKEN.encode(),run.call_args.kwargs["input"])
        self.assertNotIn(TOKEN," ".join(run.call_args.args[0]))
        self.assertNotIn("-A",run.call_args.kwargs["input"].decode().split())
        self.assertNotIn("-U",run.call_args.kwargs["input"].decode().split())

    def test_existing_different_secret_is_not_replaced_or_deleted(self):
        with patch.object(helper,"keychain_value",return_value=OTHER):
            code,_,error=self.entry(["store-token"])
        self.assertEqual(code,1);self.assertIn("different bot token",error)
        helper.subprocess.run.assert_not_called();self.assertTrue(self.source.exists())

    def test_failed_write_or_round_trip_retains_handoff(self):
        for status,stored in ((1,TOKEN),(0,OTHER)):
            with self.subTest(status=status),patch.object(helper,"keychain_value",side_effect=[None,stored]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],status,TOKEN.encode(),OTHER.encode())):
                code,_,_=self.entry(["store-token"])
            self.assertEqual(code,1);self.assertEqual(self.source.read_text(),TOKEN+"\n")

    def test_keychain_timeout_and_subprocess_failures_are_redacted(self):
        for error in (subprocess.TimeoutExpired(["security"],30,output=TOKEN,stderr=OTHER),subprocess.CalledProcessError(1,[TOKEN],output=OTHER),OSError(TOKEN)):
            with self.subTest(error_type=type(error).__name__),patch.object(helper.subprocess,"run",side_effect=error):
                code,_,_=self.entry(["store-token"])
            self.assertEqual(code,1);self.assertTrue(self.source.exists())

    def test_handoff_replacement_is_retained_after_store(self):
        def value(*args,**kwargs):
            if kwargs.get("optional"):return TOKEN
            self.source.rename(self.source.with_suffix(".old"))
            self.source.write_text(OTHER);self.source.chmod(0o600)
            return TOKEN
        with patch.object(helper,"keychain_value",side_effect=value):
            code,_,error=self.entry(["store-token"])
        self.assertEqual(code,1);self.assertIn("changed during storage",error)
        self.assertEqual(self.source.read_text(),OTHER)

    def test_symlink_and_world_readable_handoffs_block_before_keychain(self):
        target=self.source.with_suffix(".target");self.source.rename(target);self.source.symlink_to(target)
        with patch.object(helper,"keychain_value") as lookup:
            self.assertEqual(self.entry(["store-token"])[0],1);lookup.assert_not_called()
        self.source.unlink();target.rename(self.source);self.source.chmod(0o644)
        with patch.object(helper,"keychain_value") as lookup:
            self.assertEqual(self.entry(["store-token"])[0],1);lookup.assert_not_called()

    def test_malformed_or_oversized_handoff_is_not_imported(self):
        for value in (b"x"*257,b"\xff",b"bad-token",(TOKEN+"\nadd-generic-password").encode()):
            self.source.write_bytes(value)
            with self.subTest(size=len(value)),patch.object(helper,"keychain_value") as lookup:
                self.assertEqual(self.entry(["store-token"])[0],1);lookup.assert_not_called()

    def response(self,body):
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=json.dumps(body).encode()
        opener=Mock();opener.open.return_value=response
        return opener

    def test_identity_check_only_getme_and_sanitizes_success_payload(self):
        opener=self.response({"ok":True,"result":{"is_bot":True,"username":"repsignal_approval_bot","unwanted":TOKEN}})
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=opener) as build:
            code,out,_=self.entry(["verify-bot","--live"])
        self.assertEqual(code,0);result=json.loads(out)
        self.assertTrue(result["identity_verified"]);self.assertFalse(result["owner_binding_checked"])
        self.assertEqual(result["messages_sent"],0)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_method(),"GET")
        self.assertEqual(request.full_url,"https://api.telegram.org/bot"+TOKEN+"/getMe")
        self.assertIsNone(request.data)
        self.assertIs(build.call_args.args[0],helper.NoRedirect)
        context=build.call_args.args[1]._context
        self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        opener.open.assert_called_once()

    def test_missing_ca_paths_load_system_bundle_without_disabling_tls(self):
        context=Mock();opener=self.response({"ok":True,"result":{"is_bot":True,"username":"repsignal_approval_bot"}})
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.ssl,"create_default_context",return_value=context),patch.object(helper.ssl,"get_default_verify_paths",return_value=SimpleNamespace(cafile=None,capath=None)),patch.object(helper.urllib.request,"build_opener",return_value=opener):
            self.assertEqual(self.entry(["verify-bot","--live"])[0],0)
        context.load_verify_locations.assert_called_once_with(cafile="/etc/ssl/cert.pem")
        self.assertNotIn("check_hostname",context.__dict__);self.assertNotIn("verify_mode",context.__dict__)

    def test_http_transport_and_json_errors_never_expose_url_or_token(self):
        errors=(urllib.error.HTTPError("https://example.test/"+TOKEN,401,OTHER,{},None),urllib.error.URLError(TOKEN),OSError(TOKEN),ValueError(TOKEN))
        for error in errors:
            opener=Mock();opener.open.side_effect=error
            with self.subTest(kind=type(error).__name__),patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=opener):
                code,_,message=self.entry(["verify-bot","--live"])
            self.assertEqual(code,1);self.assertNotIn("https://",message)
            if isinstance(error,urllib.error.HTTPError):self.assertTrue(error.closed)

    def test_wrong_bot_invalid_response_and_redirect_fail_closed(self):
        for body in ([],{"ok":True,"result":[]},{"ok":True,"result":{"is_bot":True,"username":"different_bot"}},{"ok":False,"description":TOKEN}):
            with self.subTest(body_type=type(body).__name__),patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=self.response(body)):
                self.assertEqual(self.entry(["verify-bot","--live"])[0],1)
        with self.assertRaises(helper.SecureSetupError) as error:helper.NoRedirect().redirect_request(None,None,302,"",{},"https://example.test/"+TOKEN)
        self.assertNotIn(TOKEN,str(error.exception))

    def test_identity_check_requires_live_flag_before_any_access(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:helper.main(["verify-bot"])
        self.assertEqual(error.exception.code,2)
        helper.subprocess.run.assert_not_called();helper.urllib.request.build_opener.assert_not_called()

    def test_studio_maps_fixed_entries_without_flags_or_global_environment_changes(self):
        environment={"TELEGRAM_BOT_TOKEN":OTHER,"TELEGRAM_CHAT_ID":"999","TELEGRAM_USER_ID":"888","ALLOW_EXTERNAL_REQUESTS":"false","ALLOW_PAID_APIS":"false","ALLOW_PUBLISHING":"false","UNRELATED":"keep"}
        with patch.dict(os.environ,environment,clear=True),patch.object(helper,"keychain_value",side_effect=[TOKEN,None,None]) as lookup,patch.object(helper.os,"execve") as execute:
            before=dict(os.environ);helper.run_studio(["--","status"])
            self.assertEqual(dict(os.environ),before)
        executable,args,env=execute.call_args.args
        self.assertEqual(executable,helper.sys.executable)
        self.assertEqual(args,[helper.sys.executable,str(helper.ROOT/"studio.py"),"status"])
        self.assertEqual(env["TELEGRAM_BOT_TOKEN"],TOKEN)
        self.assertNotIn("TELEGRAM_CHAT_ID",env);self.assertNotIn("TELEGRAM_USER_ID",env)
        self.assertEqual({k:env[k] for k in environment if k.startswith("ALLOW_")},{k:environment[k] for k in environment if k.startswith("ALLOW_")})
        self.assertEqual(env["UNRELATED"],"keep");self.assertNotIn(TOKEN," ".join(args))
        self.assertEqual([call.args[0] for call in lookup.call_args_list],list(helper.SERVICES))

    def test_complete_owner_identifiers_are_mapped_without_printing(self):
        with patch.object(helper,"keychain_value",side_effect=[TOKEN,"123","456"]),patch.object(helper.os,"execve") as execute:
            self.assertEqual(self.entry(["studio","--","status"])[0],0)
        self.assertEqual(execute.call_args.args[2]["TELEGRAM_CHAT_ID"],"123")
        self.assertEqual(execute.call_args.args[2]["TELEGRAM_USER_ID"],"456")

    def test_partial_or_malformed_owner_entries_block_studio(self):
        for values in ((TOKEN,"123",None),(TOKEN,"not-an-id","456"),(TOKEN,"123","-456"),(TOKEN,"123","0"),(TOKEN,"123",str(2**63)),("bad-token",None,None)):
            with self.subTest(values_valid=values[0]==TOKEN),patch.object(helper,"keychain_value",side_effect=values):
                self.assertEqual(self.entry(["studio","--","status"])[0],1)
            helper.os.execve.assert_not_called()

    def test_exec_failure_is_redacted(self):
        with patch.object(helper,"keychain_value",side_effect=[TOKEN,None,None]),patch.object(helper.os,"execve",side_effect=OSError(TOKEN)):
            code,_,error=self.entry(["studio","--","status"])
        self.assertEqual(code,1);self.assertIn("Studio could not start",error)

    def bind_args(self):
        return ["bind-owner","--confirm-message-id","1","--confirm-start-utc",self.owner["start_date_utc"]]

    def test_owner_pair_uses_one_stdin_batch_and_private_round_trip(self):
        with patch.object(helper,"keychain_value",side_effect=[None,None,"123456","123456"]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,b"123456",b"123456")) as run:
            code,out,error=self.entry(self.bind_args())
        self.assertEqual(code,0);self.assertNotIn("123456",out+error)
        self.assertTrue(json.loads(out)["owner_pair_verified"])
        commands=run.call_args.kwargs["input"].decode()
        self.assertEqual(commands.count("add-generic-password"),2)
        self.assertNotIn("-U",commands.split());self.assertNotIn("-A",commands.split())
        self.assertNotIn("123456"," ".join(run.call_args.args[0]))
        self.assertTrue(json.loads(self.candidate.read_text())["bound"])
        self.assertEqual(self.candidate.stat().st_mode&0o777,0o600)
        helper.urllib.request.build_opener.assert_not_called()

    def test_different_owner_entry_aborts_pair_before_any_write(self):
        with patch.object(helper,"keychain_value",side_effect=[None,"987654"]):
            code,out,error=self.entry(self.bind_args())
        self.assertEqual(code,1);self.assertNotIn("987654",out+error)
        helper.subprocess.run.assert_not_called()
        self.assertFalse(json.loads(self.candidate.read_text())["bound"])

    def test_retry_completes_only_missing_matching_owner_entry(self):
        with patch.object(helper,"keychain_value",side_effect=["123456",None,"123456","123456"]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,b"",b"")) as run:
            self.assertEqual(self.entry(self.bind_args())[0],0)
        commands=run.call_args.kwargs["input"].decode()
        self.assertEqual(commands.count("add-generic-password"),1)
        self.assertIn("REP_SIGNAL_TELEGRAM_USER_ID",commands)
        self.assertNotIn("REP_SIGNAL_TELEGRAM_CHAT_ID",commands)

    def test_existing_matching_owner_pair_is_idempotent(self):
        with patch.object(helper,"keychain_value",return_value="123456"):
            self.assertEqual(self.entry(self.bind_args())[0],0)
        helper.subprocess.run.assert_not_called()
        self.assertTrue(json.loads(self.candidate.read_text())["bound"])

    def test_failed_write_or_partial_verification_never_marks_bound(self):
        with patch.object(helper,"keychain_value",side_effect=[None,None]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],1,b"123456",b"123456")):
            self.assertEqual(self.entry(self.bind_args())[0],1)
        self.assertFalse(json.loads(self.candidate.read_text())["bound"])
        with patch.object(helper,"keychain_value",side_effect=[None,None,"123456",helper.SecureSetupError("Access not granted")]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,b"",b"")):
            self.assertEqual(self.entry(self.bind_args())[0],1)
        self.assertFalse(json.loads(self.candidate.read_text())["bound"])
        helper.urllib.request.build_opener.assert_not_called()

    def test_candidate_must_match_confirmed_private_start(self):
        for key,value in (("message_id",True),("message_id",2),("start_date_utc","changed"),("chat_id","999"),("user_id","-123456"),("bot_username","@different_bot"),("private_nonbot_start_verified",False)):
            candidate={**self.owner,key:value};self.candidate.write_text(json.dumps(candidate))
            with self.subTest(key=key),patch.object(helper,"keychain_value") as lookup:
                self.assertEqual(self.entry(self.bind_args())[0],1);lookup.assert_not_called()

    def test_unsafe_candidate_file_is_rejected_before_keychain(self):
        self.candidate.chmod(0o644)
        with patch.object(helper,"keychain_value") as lookup:
            self.assertEqual(self.entry(self.bind_args())[0],1);lookup.assert_not_called()
        target=self.candidate.with_suffix(".other");self.candidate.rename(target);target.chmod(0o600);self.candidate.symlink_to(target)
        with patch.object(helper,"keychain_value") as lookup:
            self.assertEqual(self.entry(self.bind_args())[0],1);lookup.assert_not_called()


if __name__=="__main__":unittest.main()

"""Offline Buffer setup tests. Keychain and HTTPS calls are mocked and guarded."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock,Mock,patch
import urllib.error
from integrations import keychain as shared

SPEC=importlib.util.spec_from_file_location("buffer_keychain_helper",Path(__file__).resolve().parents[1]/"scripts/buffer-keychain.py")
helper=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(helper)
TOKEN="buffer_fixture_"+"a"*40
OTHER="buffer_fixture_"+"b"*40


class BufferKeychainTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/"buffer-api-key";self.source.write_text(TOKEN+"\n");self.source.chmod(0o600)
        self.receipt=Path(self.temp.name)/"buffer-connection.json"
        for target,value in (("SOURCE",self.source),("RECEIPT",self.receipt)):
            item=patch.object(helper,target,value);item.start();self.addCleanup(item.stop)
        for target,name in ((helper.subprocess,"run"),(helper.urllib.request,"build_opener")):
            guard=patch.object(target,name,side_effect=AssertionError("Unmocked live operation forbidden"));guard.start();self.addCleanup(guard.stop)
        self.organizations={"data":{"account":{"organizations":[{"id":"org-other","name":"Other private organization"},{"id":"org-repsignal","name":"REP SIGNAL","apiKey":TOKEN}]},"ownerEmail":"private@example.test"}}
        self.channels={"data":{"channels":[{"id":identity,"name":"REP SIGNAL "+service,"service":service,"isDisconnected":False,"isLocked":False,"isQueuePaused":False,"access_token":TOKEN} for service,identity in helper.EXPECTED_CHANNELS.items()]}}

    def entry(self,args):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=helper.entrypoint(args)
        text=out.getvalue()+err.getvalue();self.assertNotIn(TOKEN,text);self.assertNotIn(OTHER,text)
        return code,out.getvalue(),err.getvalue()

    def opener(self,bodies=None):
        responses=[]
        for body in bodies or [self.organizations,self.channels]:
            response=MagicMock();response.__enter__.return_value=response;response.read.return_value=json.dumps(body).encode();responses.append(response)
        opener=Mock();opener.open.side_effect=responses
        return opener

    def test_lookup_is_fixed_to_rep_signal_buffer_entry(self):
        with patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,(TOKEN+"\n").encode(),b"")) as run:
            self.assertEqual(helper.keychain_value(),TOKEN)
        self.assertEqual(run.call_args.args[0],["/usr/bin/security","find-generic-password","-a","REP_SIGNAL","-s","REP_SIGNAL_BUFFER_API_KEY","-w"])
        self.assertNotIn(TOKEN," ".join(run.call_args.args[0]))

    def test_store_private_stdin_verified_roundtrip_then_removal(self):
        with patch.object(helper,"keychain_value",side_effect=[None,TOKEN]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,TOKEN.encode(),OTHER.encode())) as run:
            code,out,_=self.entry(["store-token"])
        self.assertEqual(code,0);self.assertTrue(json.loads(out)["encrypted_store_verified"]);self.assertFalse(self.source.exists())
        self.assertEqual(run.call_args.args[0],["/usr/bin/security","-i","-q"])
        command=run.call_args.kwargs["input"].decode();self.assertIn(TOKEN,command)
        self.assertNotIn("-U",command.split());self.assertNotIn("-A",command.split())

    def test_different_existing_key_and_failed_verification_preserve_file(self):
        with patch.object(helper,"keychain_value",return_value=OTHER):self.assertEqual(self.entry(["store-token"])[0],1)
        helper.subprocess.run.assert_not_called();self.assertTrue(self.source.exists())
        with patch.object(helper,"keychain_value",side_effect=[None,OTHER]),patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],0,b"",b"")):
            self.assertEqual(self.entry(["store-token"])[0],1)
        self.assertTrue(self.source.exists())

    def test_permission_symlink_injection_and_size_rejected_before_keychain(self):
        self.source.chmod(0o644)
        with patch.object(helper,"keychain_value") as lookup:self.assertEqual(self.entry(["store-token"])[0],1);lookup.assert_not_called()
        self.source.chmod(0o600)
        for value in ((TOKEN+'\nadd-generic-password').encode(),(TOKEN+'"').encode(),b"x"*4098,b"\xff"):
            self.source.write_bytes(value)
            with patch.object(helper,"keychain_value") as lookup:self.assertEqual(self.entry(["store-token"])[0],1);lookup.assert_not_called()
        target=self.source.with_suffix(".target");self.source.rename(target);self.source.symlink_to(target)
        with patch.object(helper,"keychain_value") as lookup:self.assertEqual(self.entry(["store-token"])[0],1);lookup.assert_not_called()

    def test_changed_handoff_is_not_deleted(self):
        def lookup(optional=False):
            if optional:return TOKEN
            self.source.rename(self.source.with_suffix(".old"));self.source.write_text(OTHER);self.source.chmod(0o600)
            return TOKEN
        with patch.object(helper,"keychain_value",side_effect=lookup):self.assertEqual(self.entry(["store-token"])[0],1)
        self.assertEqual(self.source.read_text(),OTHER)

    def test_masked_ui_value_cannot_be_stored_as_a_token(self):
        self.source.write_text("•"*39+"1234")
        with patch.object(helper,"keychain_value") as lookup:
            code,_,error=self.entry(["store-token"])
        self.assertEqual(code,1);lookup.assert_not_called()
        helper.subprocess.run.assert_not_called()
        self.assertIn("unexpected bearer-key format",error)
        self.assertTrue(self.source.exists())

    def test_fresh_handoff_created_during_atomic_claim_is_preserved(self):
        replace=os.replace
        def race(source,target):
            replace(source,target)
            if Path(source)==self.source:
                self.source.write_text(OTHER);self.source.chmod(0o600)
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(shared.os,"replace",side_effect=race):
            code,out,_=self.entry(["store-token"])
        self.assertEqual(code,0);self.assertEqual(self.source.read_text(),OTHER)
        self.assertFalse(json.loads(out)["plaintext_handoff_removed"])
        self.assertTrue(json.loads(out)["fresh_handoff_preserved"])

    def test_changed_claim_content_is_retained_even_if_metadata_is_restored(self):
        original=self.source.stat();expected=self.source.read_bytes()
        self.source.write_bytes((OTHER+"\n").encode());os.utime(self.source,ns=(original.st_atime_ns,original.st_mtime_ns))
        with self.assertRaises(helper.SecureSetupError):shared.remove_unchanged(self.source,original,expected)
        self.assertEqual(self.source.read_text(),OTHER+"\n")

    def test_optional_missing_is_not_access_denial_and_errors_are_redacted(self):
        with patch.object(helper.subprocess,"run",return_value=subprocess.CompletedProcess([],44,b"",b"")):
            self.assertIsNone(helper.keychain_value(optional=True))
            with self.assertRaises(helper.SecureSetupError):helper.keychain_value()
        for failure in (subprocess.CompletedProcess([],1,TOKEN.encode(),OTHER.encode()),subprocess.TimeoutExpired(["security"],30,output=TOKEN,stderr=OTHER)):
            options={"side_effect":failure} if isinstance(failure,Exception) else {"return_value":failure}
            with patch.object(helper.subprocess,"run",**options):self.assertEqual(self.entry(["store-token"])[0],1)
        self.assertTrue(self.source.exists())

    def test_exact_read_queries_sanitized_receipt_and_unchanged_environment(self):
        opener=self.opener();before=dict(os.environ)
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=opener) as build:
            code,out,_=self.entry(["verify-connection","--live"])
        self.assertEqual(code,0);data=json.loads(out)
        self.assertEqual(data["organization"],{"id":"org-repsignal","name":"REP SIGNAL"})
        self.assertTrue(data["expected_channels_present"]);self.assertTrue(data["expected_channels_connected"])
        self.assertEqual(data["mutations_requested"],0);self.assertFalse(data["credential_scopes_introspected"])
        self.assertNotIn("private@example.test",out);self.assertNotIn("Other private organization",out)
        self.assertEqual(json.loads(self.receipt.read_text()),data);self.assertEqual(self.receipt.stat().st_mode&0o777,0o600)
        self.assertEqual(dict(os.environ),before)
        requests=[call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(len(requests),2)
        for request in requests:
            self.assertEqual(request.full_url,"https://api.buffer.com");self.assertEqual(request.get_method(),"POST")
            self.assertEqual(request.get_header("Authorization"),"Bearer "+TOKEN)
        self.assertEqual(json.loads(requests[0].data),{"query":helper.ORGANIZATIONS,"variables":{}})
        self.assertEqual(json.loads(requests[1].data),{"query":helper.CHANNELS,"variables":{"input":{"organizationId":"org-repsignal"}}})
        context=build.call_args.args[1]._context
        self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertIs(build.call_args.args[0],helper.NoRedirect)

    def test_arbitrary_query_and_identifier_injection_block_before_network(self):
        for operation,organization in (("mutation{createPost}",None),("organizations","unexpected"),("channels",'id\"}mutation')):
            with self.assertRaises(helper.SecureSetupError):helper.readonly_request(TOKEN,operation,organization)
        helper.urllib.request.build_opener.assert_not_called()

    def test_nonunique_brand_org_stops_before_channel_request(self):
        self.organizations["data"]["account"]["organizations"].append({"id":"other-brand","name":"REP SIGNAL"})
        opener=self.opener([self.organizations])
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=opener):
            self.assertEqual(self.entry(["verify-connection","--live"])[0],1)
        self.assertEqual(opener.open.call_count,1);self.assertFalse(self.receipt.exists())

    def test_missing_channels_unknown_flags_and_connection_failures_are_honest(self):
        self.channels["data"]["channels"].pop()
        self.channels["data"]["channels"][0]["isDisconnected"]=None
        self.channels["data"]["channels"][1]["isLocked"]=True
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=self.opener()):
            code,out,_=self.entry(["verify-connection","--live"])
        self.assertEqual(code,0);data=json.loads(out)
        self.assertFalse(data["expected_channels_present"]);self.assertFalse(data["expected_channels_connected"])
        self.assertIsNone(data["channels"][0]["isDisconnected"]);self.assertTrue(data["channels"][1]["isLocked"])

    def test_provider_errors_and_secret_metadata_never_reach_receipt_or_output(self):
        error=urllib.error.HTTPError("https://api.buffer.com/"+TOKEN,401,OTHER,{},None)
        opener=Mock();opener.open.side_effect=error
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=opener):self.assertEqual(self.entry(["verify-connection","--live"])[0],1)
        self.assertTrue(error.closed)
        for body in ({"errors":[{"message":TOKEN}]},{"data":None}):
            with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=self.opener([body])):self.assertEqual(self.entry(["verify-connection","--live"])[0],1)
        self.channels["data"]["channels"][0]["name"]=TOKEN
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=self.opener()):self.assertEqual(self.entry(["verify-connection","--live"])[0],1)
        self.assertFalse(self.receipt.exists())

    def test_unsafe_receipt_target_and_redirect_are_rejected(self):
        target=self.receipt.with_suffix(".target");target.write_text("keep");self.receipt.symlink_to(target)
        with patch.object(helper,"keychain_value",return_value=TOKEN),patch.object(helper.urllib.request,"build_opener",return_value=self.opener()):self.assertEqual(self.entry(["verify-connection","--live"])[0],1)
        self.assertEqual(target.read_text(),"keep")
        with self.assertRaises(helper.SecureSetupError):helper.NoRedirect().redirect_request(None,None,302,"",{},"https://other.test")

    def test_live_flag_is_required_without_any_keychain_or_http_access(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):helper.main(["verify-connection"])
        helper.subprocess.run.assert_not_called();helper.urllib.request.build_opener.assert_not_called()


if __name__=="__main__":unittest.main()

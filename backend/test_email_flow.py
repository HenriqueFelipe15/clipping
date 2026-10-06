import json
import threading
import unittest
import tempfile
from pathlib import Path
import urllib.request
from unittest.mock import patch
import server


class AutoEmailTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for name,file in (("DELIVERY_FILE","history.json"),("SETTINGS_FILE","mode.json"),("REVIEW_FILE","review.json"),("AUTO_SEND_FILE","auto.json")):
            patcher=patch.object(server,name,Path(folder.name)/file)
            patcher.start();self.addCleanup(patcher.stop)

    def test_test_mode_never_calls_real_transport(self):
        with patch.object(server,"send_email") as send,patch.object(server,"update_auto_send_status"),patch.dict(server.EMAIL_JOBS,{},clear=True):
            server.run_email_job("local-test",{"_modo":"teste","corpo":"Íntegra"})
            send.assert_not_called()
            self.assertEqual(server.delivery_history()["local-test"]["status"],"capturado_teste")

    def test_test_and_real_deduplication_are_independent(self):
        record={"processo":"123","conteudo":"Texto"};client={"id":"c"}
        self.assertNotEqual(server.auto_send_key(client,record,"teste"),server.auto_send_key(client,record,"real"))

    def test_queued_mode_is_preserved_after_setting_changes(self):
        with patch.object(server.EMAIL_EXECUTOR,"submit") as submit:
            server.SETTINGS_FILE.write_text('{"modo":"real"}',encoding="utf-8")
            job_id=server.queue_email({"para":"test@example.invalid","corpo":"Teste"})
            server.SETTINGS_FILE.write_text('{"modo":"teste"}',encoding="utf-8")
            self.assertEqual(submit.call_args.args[2]["_modo"],"real")
            self.assertEqual(server.delivery_history()[job_id]["modo"],"real")

    def test_test_capture_is_persisted_before_return(self):
        with patch.object(server,'send_email') as send,patch.object(server.EMAIL_EXECUTOR,'submit') as submit:
            job=server.queue_email({'_modo':'teste','corpo':'Publicação completa'})
            self.assertEqual(server.delivery_history()[job]['status'],'capturado_teste')
            send.assert_not_called();submit.assert_not_called()

    def test_recover_test_jobs_preserves_real_jobs_and_content(self):
        server.write_delivery('test',{'modo':'teste','status':'na_fila','payload':{'corpo':'Íntegra','_modo':'real'}})
        server.write_delivery('real',{'modo':'real','status':'na_fila','payload':{'corpo':'Real'}})
        with patch.object(server,'send_email') as send:
            server.recover_test_jobs();server.recover_test_jobs()
            send.assert_not_called()
        history=server.delivery_history()
        self.assertEqual(history['test']['status'],'capturado_teste')
        self.assertEqual(history['test']['payload']['corpo'],'Íntegra')
        self.assertEqual(history['real']['status'],'na_fila')

    def test_stuck_outlook_message_is_reactivated_without_new_copy(self):
        job={"status":"aguardando_outlook","outlook_token":"unique-token","submetido_em":1}
        with patch.object(server.subprocess,"run") as run,patch.object(server,"update_auto_send_status"),patch.dict(server.OUTLOOK_CHECK_CACHE,{},clear=True),patch.dict(server.EMAIL_JOBS,{},clear=True):
            run.return_value.returncode=0
            run.return_value.stdout="REATIVADO"
            result=server.confirm_outlook_sent("stuck",job)
            self.assertEqual(result["tentativas_recuperacao"],1)
            self.assertEqual(result["status"],"aguardando_outlook")
            self.assertTrue(json.loads(run.call_args.kwargs["input"])["recuperar"])
            script=run.call_args.args[0][-1]
            self.assertIn("$item.Send()",script)
            self.assertNotIn("CreateItem",script)
            self.assertIn('prop.Value -eq $payload.outlook_token',script)

    def test_recovery_is_bounded_and_never_claims_unconfirmed_delivery(self):
        job={"status":"aguardando_outlook","submetido_em":1,"tentativas_recuperacao":3}
        with patch.object(server.subprocess,"run") as run,patch.object(server,"update_auto_send_status"),patch.dict(server.OUTLOOK_CHECK_CACHE,{},clear=True),patch.dict(server.EMAIL_JOBS,{},clear=True):
            run.return_value.returncode=0
            run.return_value.stdout=""
            result=server.confirm_outlook_sent("stuck",job)
            self.assertFalse(json.loads(run.call_args.kwargs["input"])["recuperar"])
            self.assertEqual(result["status"],"aguardando_outlook")
            self.assertIn("não confirmada",result["erro"])

    def test_background_monitor_recovers_persisted_jobs_after_restart(self):
        history={"key":{"envio_id":"old","status":"aguardando_outlook","submetido_em":1}}
        with patch.object(server,"load_auto_sends",return_value=history),patch.object(server,"confirm_outlook_sent") as confirm,patch.dict(server.EMAIL_JOBS,{},clear=True):
            server.reconcile_pending_emails()
            confirm.assert_called_once_with("old",history["key"])

    def test_outlook_card_transport_preserves_unicode(self):
        payload={"para":"test@example.invalid","assunto":"Publicação — teste","corpo":"Íntegra","html":"<p>● ⚖ → João</p>"}
        with patch.object(server.subprocess,"run") as run:
            run.return_value.returncode=0
            run.return_value.stdout="SUBMETIDO"
            server.send_via_outlook(payload)
            script=run.call_args.args[0][-1]
            self.assertIn("$session.SendAndReceive($false)",script)
            self.assertLess(script.index("$mail.Send()"),script.index("$session.SendAndReceive($false)"))
            wire=run.call_args.kwargs["input"]
            wire.encode("ascii")
            decoded=json.loads(wire)
            self.assertTrue(decoded.pop("outlook_token"))
            self.assertEqual(decoded,payload)

    def test_outlook_is_not_sent_until_confirmed(self):
        pending={"status":"aguardando_outlook","outlook_token":"test","submetido_em":1}
        with patch.object(server,"send_email",return_value=pending),patch.object(server,"update_auto_send_status"),patch.dict(server.EMAIL_JOBS,{},clear=True):
            server.run_email_job("job",{})
            self.assertEqual(server.EMAIL_JOBS["job"]["status"],"aguardando_outlook")
        with patch.object(server.subprocess,"run") as run,patch.object(server,"update_auto_send_status"),patch.dict(server.OUTLOOK_CHECK_CACHE,{},clear=True),patch.dict(server.EMAIL_JOBS,{},clear=True):
            run.return_value.returncode=0
            run.return_value.stdout=""
            self.assertEqual(server.confirm_outlook_sent("pending",pending)["status"],"aguardando_outlook")
            run.return_value.stdout="CONFIRMADO"
            self.assertEqual(server.confirm_outlook_sent("confirmed",pending)["status"],"enviado")
        with patch.dict(server.EMAIL_JOBS,{},clear=True):
            self.assertIsNotNone(server.existing_auto_send({"envio_id":"pending",**pending}))

    def test_sent_publication_cannot_be_discarded_or_sent_twice(self):
        server.save_reviews({"key":{"modo":"real"}})
        with patch.object(server,"load_auto_sends",return_value={"key":{"status":"enviado","envio_id":"sent"}}),patch.object(server,"queue_email") as queue:
            with self.assertRaises(ValueError): server.review_publication("key","bloquear")
            self.assertEqual(server.review_publication("key","enviar")["status"],"enviado")
            queue.assert_not_called()

    def test_threshold(self):
        for score in range(75,101):
            self.assertTrue(server.should_auto_send(score,"test@example.invalid",{"identificador_forte":True},{"confianca_estrutural":80}))
        self.assertTrue(server.should_auto_send(100,"test@example.invalid"))
        self.assertFalse(server.should_auto_send(74,"test@example.invalid"))
        self.assertFalse(server.should_auto_send(100,""))

    def test_failed_and_interrupted_jobs_can_retry(self):
        previous={"envio_id":"test","status":"erro"}
        with patch.dict(server.EMAIL_JOBS,{"test":{"status":"erro"}},clear=True):
            self.assertIsNone(server.existing_auto_send(previous))
        with patch.dict(server.EMAIL_JOBS,{},clear=True):
            self.assertIsNone(server.existing_auto_send({**previous,"status":"na_fila"}))
            self.assertIsNotNone(server.existing_auto_send({**previous,"status":"enviado"}))
        with patch.dict(server.EMAIL_JOBS,{"test":{"status":"enviando"}},clear=True):
            self.assertEqual(server.existing_auto_send(previous)["status"],"enviando")

    def test_analysis_in_test_mode_auto_sends(self):
        server.SETTINGS_FILE.write_text('{"modo":"teste"}',encoding="utf-8")
        self.test_analysis_auto_sends_75_and_100_without_duplicates_or_discarded()

    def test_analysis_auto_sends_75_and_100_without_duplicates_or_discarded(self):
        client={"id":"test","nome":"Cliente fictício","email":"test@example.invalid"}
        records=[{"processo":str(score),"conteudo":"Exemplo","score":score,"confianca_estrutural":80} for score in (74,75,100)]
        httpd=server.ThreadingHTTPServer(("localhost",0),server.Handler)
        thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(server,"parse_multipart",return_value=("teste.pdf",b"test")),patch.object(server,"extract_pages",return_value=[(1,"Texto do diário")]),patch.object(server,"split_publications",return_value=records),patch.object(server,"load_clients",return_value=[client]),patch.object(server,"matching_clients",side_effect=lambda r,c:[{"cliente":client,"score":r["score"],"motivos":[],"identificador_forte":True}]),patch.object(server.EMAIL_EXECUTOR,"submit") as queue,patch.dict(server.EMAIL_JOBS,{},clear=True):
                request=urllib.request.Request(f"http://localhost:{httpd.server_port}/api/analisar",data=b"test",method="POST")
                with urllib.request.urlopen(request) as response: result=json.load(response)
                self.assertEqual(queue.call_count,0 if server.delivery_mode()=="teste" else 2)
                self.assertEqual(result["envios_automaticos"],2)
                self.assertEqual(result["revisao_manual"],1)
                for call in queue.call_args_list:
                    self.assertEqual(call.args[2]["para"],server.DEFAULT_RECIPIENT)
                    self.assertEqual(call.args[2]["_modo"],server.delivery_mode())
                with urllib.request.urlopen(request) as response: repeated=json.load(response)
                self.assertEqual(repeated["envios_automaticos"],0)
                self.assertEqual(queue.call_count,0 if server.delivery_mode()=="teste" else 2)
                low,rejected,approved=result["registros"]
                with self.assertRaises(ValueError): server.review_publication(rejected["revisao_id"],"bloquear")
                # A failed attempt may be discarded, and reimport must not retry it.
                job_id=rejected["envio_automatico"]["envio_id"]
                server.EMAIL_JOBS[job_id]={"status":"erro"}
                server.update_auto_send_status(job_id,{"status":"erro"})
                server.review_publication(rejected["revisao_id"],"bloquear")
                with self.assertRaises(ValueError): server.review_publication(rejected["revisao_id"],"enviar")
                with urllib.request.urlopen(request) as response: blocked=json.load(response)
                self.assertTrue(blocked["registros"][1]["bloqueada"])
                self.assertEqual(blocked["envios_automaticos"],0)
                self.assertEqual(queue.call_count,0 if server.delivery_mode()=="teste" else 2)
                server.review_publication(rejected["revisao_id"],"restaurar")
                with urllib.request.urlopen(request) as response: restored=json.load(response)
                self.assertEqual(restored["envios_automaticos"],1)
                self.assertEqual(queue.call_count,0 if server.delivery_mode()=="teste" else 3)

        finally:
            httpd.shutdown();httpd.server_close();thread.join()


if __name__=="__main__": unittest.main()

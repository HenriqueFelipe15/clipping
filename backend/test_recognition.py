import unittest
import server


class RecognitionTests(unittest.TestCase):
    def test_interested_client_is_distinguished_from_relator(self):
        record={"conteudo":"INTERESSADOS:-ANTONIO EMILIO CALDEIRA JUNIOR", "interessados":"ANTONIO EMILIO CALDEIRA JUNIOR", "cabecalho":"Conselheiro CLAUDIO AUGUSTO KANIA"}
        match=server.evaluate_client(record,{"nome":"ANTONIO EMILIO CALDEIRA JUNIOR"})
        self.assertEqual(match["score"],75)
        self.assertIn("Nome completo no campo Interessados",match["motivos"])
        self.assertIsNone(server.evaluate_client(record,{"nome":"CLAUDIO AUGUSTO KANIA"}))

    def test_metadata_cannot_create_a_match(self):
        self.assertIsNone(server.evaluate_client(
            {"conteudo":"Texto sem partes", "arquivo_origem":"Maria da Silva.pdf",
             "motivos_confianca":["Maria da Silva"]}, {"nome":"Maria da Silva"}))

    def test_names_respect_word_boundaries(self):
        self.assertIsNone(server.evaluate_client({"conteudo":"Mariana"},{"nome":"Ana"}))

    def test_exact_name_qualifies_for_user_requested_delivery(self):
        record={"conteudo":"Maria da Silva, intimação urgente", "confianca_estrutural":100}
        match=server.evaluate_client(record,{"nome":"Maria da Silva", "termos":"intimação;urgente"})
        self.assertLess(match["score"],85)
        self.assertTrue(server.should_auto_send(match["score"],"test@example.invalid",match,record))

    def test_process_normalization_and_citations(self):
        client={"processos":"50123456720268240000"}
        match=server.evaluate_client({"processo":"5012345-67.2026.8.24.0000"},client)
        self.assertTrue(match["identificador_forte"])
        self.assertIsNone(server.evaluate_client({"processo":"0000000-00.2026.8.24.0000",
            "conteudo":"Cita 5012345-67.2026.8.24.0000"},client))

    def test_oab_requires_same_state_and_complete_number(self):
        client={"tipo":"Advogado","identificador":"OAB/SC 12345"}
        for text in ("ADV: SC12345", "ADV: 12.345/SC", "OAB/SC 12345"):
            self.assertTrue(server.evaluate_client({"conteudo":text},client)["identificador_forte"])
        for text in ("MT12345", "SC123456", "SC12345-A"):
            self.assertIsNone(server.evaluate_client({"conteudo":text},client))

    def test_formatted_document_identifier(self):
        self.assertTrue(server.evaluate_client({"conteudo":"CPF: 123.456.789-01"},
            {"identificador":"12345678901"})["identificador_forte"])
        self.assertIsNone(server.evaluate_client({"conteudo":"9123456789012"},
            {"identificador":"12345678901"}))

    def test_user_score_policy_does_not_gate_on_structure(self):
        match={"score":100,"identificador_forte":True}
        for record in ({"confianca_estrutural":70},
                       {"confianca_estrutural":90,"correspondencia_ambigua":True},
                       {"confianca_estrutural":90,"paginas_suspeitas":[2]}):
            self.assertTrue(server.should_auto_send(100,"test@example.invalid",match,record))

    def test_continuation_and_inline_process_reference(self):
        pages=[(1,"Processo: 1234567-89.2026.8.11.0001\nClasse: Ação\nPolo Ativo: Maria\nDecisão com referência ao Processo: 7654321-98.2026.8.11.0002\n123"),
               (2,"Continuação da decisão anterior.\nProcesso: 7654321-98.2026.8.11.0002\nClasse: Recurso")]
        records=server.split_publications(pages)
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]["paginas_origem"],[1,2])
        self.assertIn("Continuação da decisão",records[0]["conteudo_original"])
        self.assertIn("123",records[0]["conteudo_original"])
        self.assertNotIn("Classe: Recurso",records[0]["conteudo"])

    def test_blank_page_is_reported_inside_publication(self):
        records=server.split_publications([(1,"Processo: 1234567-89.2026.8.11.0001\nClasse: Ação"),
                                          (2,""),(3,"Continuação")])
        self.assertEqual(records[0]["paginas_suspeitas"],[2])
        self.assertLess(records[0]["confianca_estrutural"],80)


if __name__=="__main__":
    unittest.main()

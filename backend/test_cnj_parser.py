import unittest

import pymupdf as fitz

import server
from email_card import render_card


class CnjParserTests(unittest.TestCase):
    def make_pdf(self, content_pages):
        doc = fitz.open()
        cover = doc.new_page()
        cover.insert_text((50, 30), "DIÁRIO DA JUSTIÇA")
        cover.insert_text((50, 55), "CONSELHO NACIONAL DE JUSTIÇA")
        cover.insert_text((50, 80), "Edição nº 191/2026")
        for number, lines in enumerate(content_pages, 2):
            page = doc.new_page()
            page.insert_text((45, 38), "Edição nº 191/2026", fontsize=8)
            page.insert_text((300, 38), "Brasília - DF, disponibilização 13/08/2026", fontsize=8)
            page.insert_text((545, 820), str(number), fontsize=8)
            for i, (text, bold) in enumerate(lines):
                page.insert_text((50, 70 + i * 20), text, fontsize=8, fontname="hebo" if bold else "helv")
        data = doc.tobytes()
        doc.close()
        return server.extract_pages(data)

    def heading(self):
        return [(x, True) for x in ("Secretaria Geral", "Secretaria Processual", "PJE", "INTIMAÇÃO")]

    def test_pdf_layout_continuation_and_manual_format(self):
        pages = self.make_pdf([
            self.heading() + [("N. 0002245-03.2026.2.00.0000 - PEDIDO DE PROVIDÊNCIAS - A: Exemplo.", True),
                              ("Texto integral. Além", False)],
            [("disso, continuação. Corregedor Nacional de Justiça A16/S38", False),
             ("N. 0009859-06.2019.2.00.0000 - PEDIDO DE PROVIDÊNCIAS - A: Outro.", True),
             ("Decisão. Ministro Exemplo", False)]])
        records = server.split_publications(pages)
        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["paginas_origem"], [2, 3])
        self.assertEqual(first["cabecalho"], "Secretaria Geral\nSecretaria Processual\nPJE\nINTIMAÇÃO")
        self.assertIn("Edição nº 191/2026", first["conteudo"])
        self.assertTrue(first["conteudo"].endswith("A16/S38"))
        self.assertNotIn("Outro", first["conteudo"])
        self.assertEqual(first["limites"]["fim"]["pagina"], 3)
        self.assertEqual(first["parser"], "cnj_layout")
        self.assertTrue(first["publicacao_integral"].startswith(first["cabecalho"] + "\n\nN."))
        card = render_card({}, first)
        self.assertIn("Secretaria Geral<br>Secretaria Processual<br>PJE<br>INTIMAÇÃO", card)
        self.assertIn("A16/S38", card)
        self.assertIn(first["cabecalho"], server.publication_email({}, first)["corpo"])

    def test_body_words_and_references_do_not_split(self):
        pages = self.make_pdf([self.heading() + [
            ("N. 0001888-23.2026.2.00.0000 - PEDIDO DE PROVIDÊNCIAS", True),
            ("termos da jurisprudência deste Conselho antes referida.", False),
            ("edital específico da etapa psicotécnica.", False),
            ("portaria expedida pela Presidência do Conselho Nacional de Justiça.", False),
            ("PROCESSO: 0002245-03.2026.2.00.0000 é citado no corpo.", False),
            ("Ministro Exemplo", False)]])
        records = server.split_publications(pages)
        self.assertEqual(len(records), 1)
        self.assertIn("edital específico", records[0]["conteudo"])
        self.assertEqual(records[0]["processo"], "0001888-23.2026.2.00.0000")

    def test_portaria_and_section_transition_keep_signature(self):
        pages = self.make_pdf([
            [("Presidência", True), ("PORTARIA CONJUNTA GP Nº 6, DE 6 DE AGOSTO DE 2026.", True),
             ("Texto da portaria.", False)],
            [("Ministro Exemplo", True)] + self.heading() + [
                ("N. 0002245-03.2026.2.00.0000 - PEDIDO DE PROVIDÊNCIAS", True), ("Corregedor Exemplo", False)]])
        records = server.split_publications(pages)
        self.assertEqual(len(records), 2)
        self.assertTrue(records[0]["conteudo"].endswith("Ministro Exemplo"))
        self.assertNotIn("Secretaria Geral", records[0]["conteudo"])
        self.assertEqual(records[0]["paginas_origem"], [2, 3])

    def test_unconfirmed_end_retains_low_structure_score(self):
        record = server.split_publications(self.make_pdf([self.heading() + [
            ("N. 0002245-03.2026.2.00.0000 - PEDIDO DE PROVIDÊNCIAS", True),
            ("Texto interrompido antes da conclusão", False)]]))[0]
        self.assertLess(record["confianca_estrutural"], 80)

    def test_missing_text_in_middle_blocks_delivery_and_keeps_continuation(self):
        pages = self.make_pdf([self.heading() + [
            ("N. 0002245-03.2026.2.00.0000 - PEDIDO DE PROVIDÊNCIAS", True)], [],
            [("Continuação. Ministro Exemplo", False)]])
        pages[2] = (3, "")
        pages.layout[2]["lines"] = []
        record = server.split_publications(pages)[0]
        self.assertEqual(record["paginas_suspeitas"], [3])
        self.assertEqual(record["paginas_origem"], [2, 3, 4])
        self.assertLess(record["confianca_estrutural"], 80)


if __name__ == "__main__":
    unittest.main()

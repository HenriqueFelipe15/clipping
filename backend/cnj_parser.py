"""Perfil do Diário da Justiça do CNJ: limites editoriais com evidência visual."""
import re

VERSION = "cnj-1.0"
PROCESS = re.compile(r"^N\.\s*(\d{7}-\d{2}\.\d{4}\.2\.00\.\d{4})\s*-\s*(.*)")
ACT = re.compile(r"^(?:PORTARIA|RESOLUÇÃO|INSTRUÇÃO NORMATIVA|EDITAL|PROVIMENTO)\b.*\bN[º°.]\s*\d+", re.I)
HEADINGS = {"Presidência": 0, "Secretaria Geral": 0, "Secretaria Processual": 1, "PJE": 2, "INTIMAÇÃO": 3}


class Pages(list):
    """Mantém a interface de pares (página, texto) usada pelo parser legado."""
    def __init__(self, pairs, layout):
        super().__init__(pairs)
        self.layout = layout


def extract(doc):
    layout = []
    pairs = []
    for number, page in enumerate(doc, 1):
        pairs.append((number, page.get_text("text")))
        lines = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                lines.append({"text": "".join(s["text"] for s in line["spans"]).strip(),
                              "bbox": list(line["bbox"]),
                              "bold_start": "Bold" in spans[0]["font"],
                              "bold": all("Bold" in s["font"] for s in spans),
                              "white": all(s["color"]==16777215 for s in spans),
                              "size": max(s["size"] for s in spans)})
        layout.append({"number": number, "height": page.rect.height,
                       "lines": sorted(lines, key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))})
    return Pages(pairs, layout)


def recognizes(pages):
    first = pages[0][1] if pages else ""
    return bool(getattr(pages, "layout", None) and "CONSELHO NACIONAL DE JUSTIÇA" in first
                and "DIÁRIO DA JUSTIÇA" in first and "Edição" in first)


def split(pages):
    records = []
    context = []
    current = None
    blank = {n for n, text in pages if not text.strip()}

    def finish(reason):
        nonlocal current
        if current is None:
            return
        content = "\n".join(current.pop("_text")).strip()
        source = current.pop("_source")
        first, last = source[0]["pagina"], source[-1]["pagina"]
        suspicious = sorted(blank.intersection(range(first, last + 1)))
        warnings = current.pop("_warnings")
        if reason.startswith("Fim do documento") and not re.search(
                r"(?:Ministr[oa]|Conselheir[oa]|Relator[ae]?|Corregedor)\b", content[-3000:], re.I):
            warnings.append("Encerramento não confirmado no fim do documento")
        current.update(conteudo=content, conteudo_original=content,
                       paginas_origem=list(range(first, last + 1)), pagina=first,
                       paginas_suspeitas=suspicious, limites={"inicio": source[0], "fim": source[-1], "motivo_fim": reason},
                       trechos_origem=source, parser="cnj_layout", parser_version=VERSION,
                       confianca_estrutural=60 if suspicious or warnings or not current["cabecalho"] else 90,
                       motivos_estrutura=["Título identificado por texto e negrito", "Contexto editorial herdado", reason] + warnings)
        if suspicious:
            current["motivos_estrutura"].append("Página sem texto no intervalo: revisar continuidade")
        current["publicacao_integral"] = current["cabecalho"] + "\n\n" + content
        records.append(current)
        current = None

    for page in pages.layout:
        n = page["number"]
        # A capa é um sumário, não uma publicação.
        if n == 1:
            continue
        furniture = [l["text"] for l in page["lines"] if l["bbox"][1] < 45]
        continued = False
        for line in page["lines"]:
            text = line["text"]
            y = line["bbox"][1]
            if y < 45 or (y > page["height"] - 35 and text == str(n)):
                continue
            if text in HEADINGS and line["bold_start"]:
                finish("Mudança de seção editorial")
                depth = HEADINGS[text]
                context = context[:depth] + [text]
                continue
            process = PROCESS.match(text)
            act = ACT.match(text)
            is_start = line["bold_start"] and (process or act)
            if is_start:
                finish("Próximo título de publicação confirmado")
                current = {"processo": process[1] if process else text,
                           "classe": process[2].split(" - A:")[0] if process else "Portaria" if text.startswith("PORTARIA") else "Ato administrativo",
                           "tipo": "Intimação" if "INTIMAÇÃO" in context else "Ato administrativo",
                           "cabecalho": "\n".join(context), "orgao": "Conselho Nacional de Justiça",
                           "unidade": next((s for s in context if s == "Secretaria Processual"), context[0] if context else "Não identificado"),
                           "secao": context[-1] if context else "Não identificado",
                           "comarca": "Não consta", "vara": "Não consta", "partes": "", "advogados": "", "oabs": "",
                           "_text": [], "_source": [], "_warnings": []}
                continued = True
            if current is None:
                continue
            if (process or act) and not line["bold_start"]:
                current["_warnings"].append("Possível título sem confirmação visual: revisar limite")
            if not continued and current["_source"] and current["_source"][-1]["pagina"] != n:
                # Preserva edição/data/página entre continuações, conforme exemplo manual.
                current["_text"].extend(["", " ".join(furniture), "", str(n), ""])
                continued = True
            current["_text"].append(text)
            current["_source"].append({"pagina": n, "bbox": line["bbox"]})
    finish("Fim do documento; conferir encerramento e notas")
    for record in records:
        # Campos da abertura somente; referências no corpo não substituem o processo principal.
        opening = re.split(r"PODER JUDICIÁRIO|EMENTA|DECISÃO", record["conteudo"], maxsplit=1)[0]
        record["partes"] = " | ".join(re.findall(r"\b[ART]:\s*(.*?)(?=Adv\(s\)\.:|$)", opening, re.S))
        record["advogados"] = " | ".join(re.findall(r"Adv\(s\)\.:\s*(.*?)(?=\b[ART]:|$)", opening, re.S))
        record["oabs"] = ", ".join(dict.fromkeys(re.findall(r"\b[A-Z]{2}\d{3,7}(?:-[A-Z])?\b", opening)))
    return records

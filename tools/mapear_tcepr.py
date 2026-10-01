"""Mapeamento documental da edição 3753. Não importa clientes nem envia e-mail.

As coordenadas são pontos PDF, com origem no canto superior esquerdo.
Este é um instrumento de análise da amostra, não um parser de produção.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import pymupdf as fitz


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def key(text):
    text=unicodedata.normalize("NFKD",text)
    return re.sub(r"[^A-Z0-9]","",text.encode("ascii","ignore").decode().upper())


SECTIONS=["SECRETARIA DO TRIBUNAL PLENO","SECRETARIA DA 1ª CÂMARA",
          "SECRETARIA DA 2ª CÂMARA","ATOS DE RELATORIA","CORREGEDORIA-GERAL",
          "OUVIDORIA DE CONTAS","MINISTÉRIO PÚBLICO DE CONTAS","ATOS DIVERSOS",
          "COORDENADORIA-GERAL DE FISCALIZAÇÃO","ATOS NORMATIVOS",
          "GABINETE DA PRESIDÊNCIA","LICITAÇÕES E CONTRATOS","COMPOSIÇÃO BIÊNIO 2025/2026"]
SECTION_KEYS={key(s):s for s in SECTIONS}
PROCESS=re.compile(r"^PROCESSO\s*(?:N\s*[.º°o]*\s*)?[:\-\s]*([0-9]{1,7}/[0-9]{2})(?![0-9])",re.I)


def locate(line):
    return {k:line[k] for k in ("pagina","coluna","linha","bbox","texto")}


def extract(source):
    lines=[]; excluded=[]
    with fitz.open(source) as doc:
        for page_index,page in enumerate(doc):
            columns={"E":[],"D":[]}
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines",[]):
                    spans=[s for s in line["spans"] if s["text"].strip()]
                    if not spans: continue
                    text=norm("".join(s["text"] for s in spans))
                    bbox=[round(float(v),2) for v in line["bbox"]]
                    col="E" if spans[0]["bbox"][0]<300 else "D"
                    item={"pagina":page_index+1,"coluna":col,"bbox":bbox,"texto":text,
                          "bold":all("Bold" in s["font"] for s in spans),
                          "size":max(s["size"] for s in spans),
                          "white":all(s["color"]==16777215 for s in spans)}
                    if bbox[1]<(114 if page_index==0 else 40):
                        excluded.append({**item,"categoria":"cabeçalho institucional"});continue
                    if bbox[1]>=813:
                        excluded.append({**item,"categoria":"rodapé institucional"});continue
                    if page_index==0 and col=="E":
                        excluded.append({**item,"categoria":"sumário"});continue
                    columns[col].append(item)
            for col in ("E","D"):
                for row,item in enumerate(sorted(columns[col],key=lambda x:(x["bbox"][1],x["bbox"][0])),1):
                    lines.append({**item,"linha":row})
    return lines,excluded


def build_map(lines):
    records=[];headers=[];current=None
    context={"secao":"","subsecao":"","relator":"","classe":"","colegiado":"","sessao":"","data_sessao":""}

    def close(reason):
        nonlocal current
        if current:
            body=current.pop("_lines")
            current["fim"]=locate(body[-1])
            current["motivo_fim"]=reason
            current["conteudo"]="\n".join(l["texto"] for l in body)
            current["atravessa_pagina"]=current["inicio"]["pagina"]!=current["fim"]["pagina"]
            current["atravessa_coluna"]=len({(l["pagina"],l["coluna"]) for l in body})>1
            current["regioes"]=[]
            for group in dict.fromkeys((l["pagina"],l["coluna"]) for l in body):
                boxes=[l["bbox"] for l in body if (l["pagina"],l["coluna"])==group]
                current["regioes"].append({"pagina":group[0],"coluna":group[1],"y_inicio":min(b[1] for b in boxes),"y_fim":max(b[3] for b in boxes)})
            despacho=re.search(r"(?m)^DESPACHO\s*(?:N\s*[.º°]*\s*)?[:\-\s]*(\d+/\d+)",current["conteudo"])
            current["despacho"]=despacho.group(1) if despacho else None
            records.append(current);current=None

    for i,line in enumerate(lines):
        text=line["texto"]; compact=key(text)
        section=SECTION_KEYS.get(compact)
        # Banners têm texto branco (alguns com fonte minúscula sobre a imagem).
        # Nomes de conselheiros dentro de impedimentos/citações não são cabeçalhos.
        banner=line["white"] and line["size"]>=8
        counselor=(line["pagina"]<=9 and line["bold"] and text.startswith(("CONSELHEIRO ","CONSELHEIRA ")))
        class_heading=(line["pagina"]<=9 and line["bold"] and text==text.upper()
                       and ":" not in text and not PROCESS.match(text) and not counselor
                       and not banner and not section and len(text)>5)
        if section and (line["size"]<3 or line["white"]):
            close("Mudança de seção: "+section)
            context={"secao":section,"subsecao":"","relator":"","classe":"","colegiado":"","sessao":"","data_sessao":""}
            headers.append({**locate(line),"tipo":"seção","valor":section});continue
        if banner or counselor or class_heading:
            # Na página 9, depois das pautas, títulos em negrito já são metadados de atos.
            if class_heading and context["secao"]=="ATOS DE RELATORIA":
                class_heading=False
            if banner or counselor or class_heading:
                close("Novo cabeçalho editorial: "+text)
                field="relator" if counselor or text.startswith(("Conselheiro ","Conselheira ")) else "classe" if class_heading else "subsecao"
                if text in ("TRIBUNAL PLENO","PRIMEIRA CÂMARA","SEGUNDA CÂMARA"): field="colegiado"
                elif text.startswith("SESSÃO ORDINÁRIA"): field="sessao"
                elif re.match(r"^(?:EM|DE) \d+ DE ",text): field="data_sessao"
                context[field]=text
                if field in ("relator","subsecao"): context["classe"]=""
                headers.append({**locate(line),"tipo":field,"valor":text});continue
        process=PROCESS.match(text)
        if process:
            following="\n".join(item["texto"] for item in lines[i+1:i+7])
            has_fields=bool(re.search(r"(?im)^(?:ENTIDADE|ORIGEM|ASSUNTO|DATA E HORA DA DISTRIBUIÇÃO)\s*[:\-]",following))
            is_heading=(text.startswith("Processo:") and "Pautas" in context["subsecao"]) or line["bold"]
            if not (has_fields and is_heading): process=None
        term=text.startswith("TERMO DE DISTRIBUIÇÃO")
        alert=context["subsecao"]=="Atos de Alerta Municipais" and text.startswith("ENTIDADE:")
        notice=text.startswith("AVISO DE PREGÃO ELETRÔNICO")
        # No termo de distribuição, Processo é campo interno, não segundo registro.
        internal=bool(process and current and current["tipo"]=="Termo de distribuição"
                      and len(current["_lines"])==1)
        if internal:
            current["processo"]=process.group(1)
        elif process or term or alert or notice:
            close("Início da próxima publicação: "+text)
            kind=("Termo de distribuição" if term else "Alerta municipal" if alert else
                  "Aviso de licitação" if notice else "Pauta" if "Pautas" in context["subsecao"] else
                  "Ato de relatoria" if context["secao"]=="ATOS DE RELATORIA" else
                  "Despacho da Presidência" if context["secao"]=="GABINETE DA PRESIDÊNCIA" else "Despacho de atos diversos")
            current={"id":len(records)+1,"tipo":kind,"processo":process.group(1) if process else None,
                     "contexto":dict(context),"inicio":locate(line),"_lines":[]}
        if current: current["_lines"].append(line)
    close("Fim do conteúdo documental")
    return records,headers


def location(loc):
    return f"p. {loc['pagina']} {loc['coluna']} · linha {loc['linha']} · y={loc['bbox'][1]:.1f}"


def main():
    parser=argparse.ArgumentParser();parser.add_argument("pdf");parser.add_argument("--out",default="output/mapeamento-tcepr-3753")
    args=parser.parse_args();source=Path(args.pdf);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    lines,excluded=extract(source);records,headers=build_map(lines)
    counts=dict(Counter(r["tipo"] for r in records))
    result={"fonte":str(source.resolve()),"sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
            "edicao":"3753","data_visivel_no_cabecalho":"10/09/2026","paginas":39,
            "metodo":"Leitura por coluna e coordenadas; limites estruturais da amostra, sujeitos a revisão individual.",
            "contagem":counts,"publicacoes":records,"cabecalhos_editoriais":headers,
            "elementos_excluidos":excluded}
    (out/"mapa.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"linhas.json").write_text(json.dumps(lines,ensure_ascii=False,indent=2),encoding="utf-8")
    candidates=[l for l in lines if PROCESS.match(l["texto"])]
    ignored=[locate(l) for l in candidates if not l["bold"] and not l["texto"].startswith("Processo:")]
    result["referencias_que_nao_iniciam_publicacao"]=ignored
    (out/"mapa.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    md=["# Mapeamento do Diário Eletrônico do TCE-PR — edição 3753", "",
        "Fonte: 10 de setembro de 2026, 39 páginas. Mapeamento documental local; não houve importação no clipping nem envio de e-mail.","",
        "## Resultado e limites", "",
        f"Foram delimitados **{len(records)} blocos**, sendo **{sum(bool(r['processo']) for r in records)} com número de processo**. Contagem por tipo:","",
        *[f"- {kind}: {n}" for kind,n in counts.items()],"",
        "Os limites foram calculados pela estrutura e conferidos em exemplos representativos. Não houve conferência humana individual de todos os blocos. Este mapa não é um parser de produção.","",
        "## Ordem de leitura", "",
        "Leia toda a coluna esquerda, depois a direita e então a página seguinte. Na primeira página, a coluna esquerda é sumário; o conteúdo começa na direita. Ler por linhas horizontais mistura publicações. A página 39 contém a composição institucional, não processos.","",
        "## Cabeçalhos e rodapés", "",
        "- Cabeçalho institucional: nome do diário, ano XXI, edição 3753, data, dia da semana e página. Preservar como metadados. Na primeira página há uma faixa gráfica maior.",
        "- Geometria desta amostra: páginas 2–39, cabeçalho acima de y=40 pt; página 1, acima de y=114 pt. Corpo em duas colunas, dividido aproximadamente em x=300 pt. Rodapé abaixo de y=813 pt. Essas medidas não são regras universais.",
        "- Rodapé institucional: endereço, telefones e créditos técnicos/diagramação/imagens. Não pertence aos processos.",
        "- Banners de seção e faixas azuis: contexto editorial. Preservar seção, subseção e relator; não adicionar ao corpo do processo anterior.",
        "- Classe da pauta: título em negrito, às vezes compartilhado por vários processos. É contexto, não um processo autônomo.",
        "- Metadados internos como ENTIDADE, INTERESSADO, ASSUNTO e DESPACHO pertencem à publicação.",
        "- Nomes de conselheiros em listas de impedimentos não são cabeçalhos. A tipografia e a posição distinguem esses casos.",
        "- Alguns títulos de seção têm texto branco minúsculo sobre imagens, com espaços artificiais. A data completa também precisa de conferência visual.","",
        "## Regras de início e término", "",
        "| Família | Início | Término |", "|---|---|---|",
        "| Pautas (p. 1–9) | Processo: número/ano, herdando classe e relator | Antes do próximo Processo ou novo cabeçalho editorial |",
        "| Atos de relatoria (p. 9–23) | PROCESSO N.º:, Nº:-, N°: e variantes, seguido dos campos do ato | Antes de novo processo/cabeçalho, incluindo assinatura e notas do ato |",
        "| Distribuição (p. 24–25) | TERMO DE DISTRIBUIÇÃO Nº… | Antes do próximo TERMO ou da mudança de subseção |",
        "| Despachos de atos diversos (p. 25–27) | PROCESSO N º-… | Antes do próximo processo ou Informações |",
        "| Alertas municipais (p. 27) | ENTIDADE: dentro da subseção de alertas | Antes da próxima ENTIDADE ou nova seção |",
        "| Presidência (p. 27–38) | PROCESSO Nº:-… | Próximo processo ou GP - Termo de Ajuste de Gestão, preservando notas |",
        "| Licitações (p. 38) | AVISO DE PREGÃO ELETRÔNICO… | Final do aviso; imagens posteriores são material institucional |", "",
        "Quebra de página/coluna, número citado na fundamentação, Publique-se e assinatura não encerram sozinhos uma publicação. No termo de distribuição, a linha Processo Nº é um campo interno. O mesmo processo pode ter mais de um despacho nesta edição; não deduplicar apenas pelo processo.","",
        "## Exemplos conferidos visualmente", "",
        "- **456357/25:** página 1 direita até página 2 esquerda. A lista de interessados continua na página seguinte.",
        "- **486580/26 — despacho 1485/26:** página 9 esquerda até página 11 esquerda. O fim inclui notas explicativas anteriores ao início de 501104/26.",
        "- **502550/26 — termo 4187/2026:** fim da coluna esquerda da página 24 até a coluna direita. A lista de impedimentos pertence ao mesmo termo.",
        "- **482975/26 — despacho 4454/26:** página 29 esquerda até página 31 esquerda. A assinatura na página 30 não encerra as notas, que continuam na página 31.",
        "- **500639/26 — despacho 4529/26:** página 37 direita até página 38 esquerda, antes de GP - Termo de Ajuste de Gestão.",
        "- **326507/26:** dois atos distintos, despachos 1198/26 e 1273/26. Ambos são preservados.",
        "- **297763/26:** cinco citações no corpo de outros despachos (p. 35–36), sem cabeçalho processual em negrito e sem sequência própria de metadados. Não foram criados cinco processos novos.","",
        f"Os {sum(bool(r['processo']) for r in records)} blocos numerados correspondem a {len({r['processo'] for r in records if r['processo']})} números distintos. A identificação de início combina número/ano, tipografia ou padrão da pauta e campos seguintes. Foram examinados {len(candidates)} candidatos de linha e rejeitadas {len(ignored)} referências internas.","",
        "## Inventário completo", "",
        "E = esquerda; D = direita. As linhas contam o texto não vazio da coluna após retirar cabeçalho, rodapé e sumário. Coordenadas y em pontos PDF, a partir do topo. O fim indica a última linha incluída. O JSON contém texto integral, coordenadas e justificativa do limite.","",
        "| ID | Tipo | Processo / ato | Início | Fim |", "|---|---|---|---|---|"]
    for r in records:
        label=r["processo"] or r["inicio"]["texto"]
        if r["despacho"]: label+=" · despacho "+r["despacho"]
        md.append(f"| {r['id']} | {r['tipo']} | {label} | {location(r['inicio'])} | {location(r['fim'])} |")
    md.extend(["","## Cabeçalhos editoriais localizados","","| Local | Tipo | Texto |","|---|---|---|"])
    md.extend(f"| {location(h)} | {h['tipo']} | {h['valor']} |" for h in headers)
    (out/"mapeamento.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print(json.dumps({"blocos":len(records),"tipos":counts,"cabecalhos":len(headers),"com_processo":sum(bool(r['processo']) for r in records)},ensure_ascii=False))


if __name__=="__main__": main()

"""Reconhecimento do layout TCE-PR validado na edição 3753."""
import re
import unicodedata

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


def recognizes(pages):
    if not getattr(pages,"layout",None) or len(pages)!=39:return False
    cover=pages[0][1]
    return "3753" in cover and "SECRETARIA DO TRIBUNAL PLENO" in cover and "COMPOSIÇÃO BIÊNIO 2025/2026" in cover

def split(pages):
    lines=[]
    for page in pages.layout:
        n=page["number"]
        columns={"E":[],"D":[]}
        for raw in page["lines"]:
            box=raw["bbox"];col="E" if box[0]<300 else "D"
            if box[1]<(114 if n==1 else 40) or box[1]>=813 or (n==1 and col=="E"):continue
            columns[col].append({"pagina":n,"coluna":col,"bbox":box,"texto":norm(raw["text"]),"bold":raw["bold"],"white":raw["white"],"size":raw["size"]})
        for col in ("E","D"):
            for number,line in enumerate(sorted(columns[col],key=lambda x:(x["bbox"][1],x["bbox"][0])),1):
                lines.append({**line,"linha":number})
    blocks,headers=build_map(lines)
    records=[]
    for block in blocks:
        context=block["contexto"];body=block["conteudo"]
        def field(label):
            match=re.search(r"(?i)^"+label+r"\s*[:\-]+\s*(.*?)(?=\n[A-ZÁÉÍÓÚÃÕÇ ]{3,}\s*[:\-]|\nDESPACHO\b|\Z)",body,re.S|re.M)
            return norm(match[1]) if match else ""
        # O relator é cabeçalho; interessados e procuradores são metadados do corpo.
        heading=context["relator"] or "\n".join(x for x in (context["secao"],context["subsecao"],context["classe"]) if x)
        first,last=block["inicio"]["pagina"],block["fim"]["pagina"]
        records.append({"processo":block["processo"] or block["inicio"]["texto"],"classe":field("ASSUNTO") or context["classe"] or block["tipo"],
          "tipo":block["tipo"],"cabecalho":heading,"orgao":"Tribunal de Contas do Estado do Paraná","secao":context["secao"],"unidade":context["subsecao"],"relator":context["relator"],"contexto_editorial":context,
          "comarca":"Não consta","vara":"Não consta","partes":field("INTERESSADOS?") or field("Interessado"),"interessados":field("INTERESSADOS?") or field("Interessado"),"advogados":field("PROCURADORES?"),"entidade":field("ENTIDADE"),"oabs":"",
          "pagina":first,"paginas_origem":list(range(first,last+1)),"conteudo":body,"conteudo_original":body,"publicacao_integral":heading+"\n\n"+body,
          "parser":"tcepr_layout_3753","parser_version":"1.0","confianca_estrutural":90,"motivos_estrutura":["Leitura por coluna e cabeçalho editorial",block["motivo_fim"]],"paginas_suspeitas":[],
          "limites":{"inicio":block["inicio"],"fim":block["fim"],"motivo_fim":block["motivo_fim"]}})
    return records

"""DOM/SC: publicações numeradas e contexto editorial herdado."""
import re

def recognizes(pages):
    return bool(getattr(pages, 'layout', None) and pages and
                'diariomunicipal.sc.gov.br' in pages[0][1] and
                any('DOM/SC - Edição' in text for _, text in pages[:3]))

def split(pages):
    lines=[]; starts=[]; headings=[]
    for page in pages.layout:
        if page['number'] <= 2: continue
        for raw in page['lines']:
            text=re.sub(r'[\x00-\x1f]', '', raw['text']).strip()
            if not text or raw['bbox'][1]<30 or raw['bbox'][1]>page['height']-35: continue
            line={**raw,'text':text,'pagina':page['number']}
            i=len(lines);lines.append(line)
            if 16.8<line['size']<17.2 and line['white']:
                headings.append((i,'ente',text))
            elif 11.8<line['size']<12.2 and line['bold_start']:
                headings.append((i,'orgao',text))
            m=re.fullmatch(r'Publicação\s+N[º°o.]\s*(\d+)',text)
            if m:
                start=i
                while start and lines[start-1]['pagina']==page['number'] and lines[start-1]['bold'] and 9.8<lines[start-1]['size']<10.2:
                    start-=1
                starts.append((start,i,m[1]))
    result=[]
    for k,(start,marker,number) in enumerate(starts):
        end=starts[k+1][0] if k+1<len(starts) else len(lines)
        boundary=[i for i,_,_ in headings if start<i<end]
        if boundary:end=min(boundary)
        context={}
        for i,kind,text in headings:
            if i>=start:break
            if kind=='ente':context={'ente':text}
            else:context['orgao']=text
        ente=context.get('ente','');orgao=context.get('orgao','')
        comarca=ente if ente and ente!='Consórcios' else 'COMARCA NÃO INFORMADA'
        if ente=='Consórcios':ente=orgao
        header='\n'.join(dict.fromkeys(x for x in (ente,orgao) if x))
        title=' '.join(l['text'] for l in lines[start:marker])
        body='\n'.join(l['text'] for l in lines[start:end])
        first,last=lines[start]['pagina'],lines[end-1]['pagina']
        source=[{'pagina':l['pagina'],'bbox':l['bbox'],'texto':l['text']} for l in lines[start:end]]
        result.append(dict(numero_publicacao=number,titulo=title,assunto=title,
            processo='',classe=title,tipo='Publicação administrativa',cabecalho=header,
            ente=ente,orgao=orgao,comarca=comarca,vara='VARA NÃO INFORMADA',
            partes='',advogados='',oabs='',pagina=first,paginas_origem=list(range(first,last+1)),
            conteudo=body,conteudo_original=body,publicacao_integral=header+'\n\n'+body,
            parser='domsc_layout',parser_version='1.0',confianca_estrutural=90 if title and header else 60,
            motivos_estrutura=['Marcador Publicação Nº','Título editorial e cabeçalho herdado'],
            paginas_suspeitas=[],trechos_origem=source,
            limites={'inicio':source[0],'fim':source[-1],'motivo_fim':'Próximo título/cabeçalho ou fim do documento'}))
    return result

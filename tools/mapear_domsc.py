"""Mapeamento auditável do DOM/SC por marcadores editoriais, sem envio de e-mail."""
import sys, re, json, csv
from pathlib import Path
from collections import Counter
import pymupdf as fitz

def main(source, destination):
    out = Path(destination); out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(source)
    guide = []
    category = 'Municípios'
    for page in doc[:2]:
        for raw in page.get_text().splitlines():
            if raw.strip() == 'CONSÓRCIOS': category = 'Consórcios'
            m = re.match(r'^(.+?)\.{2,}\s*(\d+)\s*$', raw)
            if m: guide.append(dict(nome=m[1].strip(), pagina=int(m[2]), categoria=category))
    rows, markers, headings, empty = [], [], [], []
    for pi in range(2, len(doc)):
        page = doc[pi]
        lines = []
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                spans = line['spans']; text = re.sub(r'[\x00-\x1f]', '', ''.join(s['text'] for s in spans)).strip()
                if not text: continue
                x0,y0,x1,y1 = line['bbox']
                if y0 < 30 or y0 > page.rect.height-35: continue
                lines.append(dict(texto=text, pagina=pi+1, bbox=list(line['bbox']),
                                  tamanho=max(s['size'] for s in spans), fontes=list(set(s['font'] for s in spans))))
        lines.sort(key=lambda x:(round(x['bbox'][1],1),x['bbox'][0]))
        if not lines: empty.append(pi+1)
        for line in lines:
            idx = len(rows); rows.append(line)
            if 16.8 < line['tamanho'] < 17.2 and any('Tahoma' in f for f in line['fontes']):
                headings.append(dict(nome=line['texto'],pagina=pi+1,indice=idx,tipo='ente'))
            elif any('SC700' in f for f in line['fontes']) and 11.8 < line['tamanho'] < 12.2:
                headings.append(dict(nome=line['texto'],pagina=pi+1,indice=idx,tipo='orgao'))
            m = re.fullmatch(r'Publicação\s+N[º°o.]\s*(\d+)', line['texto'])
            if m:
                start = idx
                while start > 0:
                    prev = rows[start-1]
                    if prev['pagina'] != pi+1 or not (9.8 < prev['tamanho'] < 10.2) or not any('Tahoma-Bold' == f for f in prev['fontes']): break
                    start -= 1
                markers.append(dict(numero=m[1],indice=idx,inicio=start))
        if (pi+1)%200 == 0: print('Páginas lidas:',pi+1,flush=True)
    publications=[]
    for n, marker in enumerate(markers):
        start=marker['inicio']; end=markers[n+1]['inicio'] if n+1<len(markers) else len(rows)
        transitions=[h for h in headings if start<h['indice']<end]
        if transitions: end=min(h['indice'] for h in transitions)
        preceding=[h for h in headings if h['indice']<start]
        entities=[h for h in preceding if h['tipo']=='ente']
        entity=entities[-1] if entities else None
        organs=[h for h in preceding if h['tipo']=='orgao' and (not entity or h['indice']>entity['indice'])]
        organ=organs[-1]['nome'] if organs else ''
        segment=rows[start:end]
        title=' '.join(r['texto'] for r in rows[start:marker['indice']])
        warnings=[]
        if not title: warnings.append('Título editorial não identificado')
        if not entity: warnings.append('Ente não identificado')
        entity_name=entity['nome'] if entity else ''
        comarca=entity_name if entity_name and entity_name != 'Consórcios' else 'COMARCA NÃO INFORMADA'
        if entity_name == 'Consórcios': entity_name=organ
        publications.append(dict(numero_publicacao=marker['numero'],titulo=title,ente=entity_name,orgao=organ,
            cabecalho='\n'.join(dict.fromkeys(v for v in [entity_name,organ] if v)),
            comarca=comarca,vara='VARA NÃO INFORMADA',
            pagina_inicio=rows[start]['pagina'],pagina_fim=segment[-1]['pagina'],
            inicio_bbox=rows[start]['bbox'],fim_bbox=segment[-1]['bbox'],
            texto='\n'.join(r['texto'] for r in segment), alertas=warnings))
    comparisons=[]
    for g in guide:
        matches=[h for h in headings if h['tipo']==('orgao' if g['categoria']=='Consórcios' else 'ente') and h['nome'].casefold()==g['nome'].casefold()]
        comparisons.append(dict(**g,paginas_encontradas=[h['pagina'] for h in matches],confere=any(h['pagina']==g['pagina'] for h in matches)))
    counts=Counter(p['numero_publicacao'] for p in publications)
    summary=dict(arquivo=Path(source).name,paginas=len(doc),publicacoes=len(publications),
        numeros_unicos=len(counts),duplicados={k:v for k,v in counts.items() if v>1},
        publicacoes_multipagina=sum(p['pagina_fim']>p['pagina_inicio'] for p in publications),
        sem_titulo=sum(not p['titulo'] for p in publications),entradas_sumario=len(guide),
        entradas_sumario_confirmadas=sum(c['confere'] for c in comparisons),
        paginas_sem_texto_util=empty,orgaos=sorted(set(p['orgao'] for p in publications)))
    for name,data in [('publicacoes',publications),('conferencia-sumario',comparisons),('validacao',summary),('cabecalhos',headings)]:
        (out/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'mapa.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['numero_publicacao','ente','orgao','cabecalho','comarca','vara','titulo','pagina_inicio','pagina_fim','alertas']
        writer=csv.DictWriter(f,fields,extrasaction='ignore');writer.writeheader();writer.writerows(publications)
    report=['# Mapeamento DOM/SC — edição 5257','',f"{len(doc)} páginas; {len(publications)} publicações delimitadas.",'',
        '## Regras de separação','',
        '- O marcador editorial Publicação Nº identifica cada registro. As ocorrências do sumário (páginas 1–2) são excluídas.',
        '- O título em Tahoma-Bold 10 imediatamente acima do marcador pertence à nova publicação.',
        '- O bloco segue pelas páginas seguintes até o próximo título editorial ou mudança de ente/órgão.',
        '- Cabeçalho recorrente e rodapé do jornal são excluídos por posição. Cabeçalhos, tabelas e assinaturas internos são preservados na extração textual.',
        '- Ente: faixa editorial Tahoma 17. Órgão: cabeçalho Tahoma-Bold-SC700 12. Ambos são herdados até mudança explícita.',
        '- Conforme regra definida pelo usuário para este jornal, o município do cabeçalho preenche a comarca. Consórcios sem município identificado ficam com COMARCA NÃO INFORMADA.',
        '- A vara recebe VARA NÃO INFORMADA, pois este perfil não apresenta vara no cabeçalho. Número da publicação não é número processual.',
        '- O sumário serve de conferência de ente/página; sua ordem impressa não deve definir os cortes.',
        '', '## Conferência', '', '```json',json.dumps(summary,ensure_ascii=False,indent=2),'```','',
        '## Limites da análise','',
        'Mapeamento desta edição, sem integração ao importador e sem envio. A extração textual não garante preservar a disposição de tabelas, imagens ou anexos digitalizados. Campos de processo, partes e classificação do ato exigem etapa própria. Revisão visual por amostragem, não conferência manual integral.',
        '', '## Divergências do sumário','']
    report += [f"- {c['nome']}: sumário p. {c['pagina']}; cabeçalho encontrado em {c['paginas_encontradas']}" for c in comparisons if not c['confere']]
    (out/'mapeamento.md').write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__': main(*sys.argv[1:])

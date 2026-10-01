let dados=[],clientes=[],selecionado=-1,clienteAtivo=null,destinoPadrao="";const $=id=>document.getElementById(id);const norm=s=>String(s||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
async function init(){try{const[cr,hr]=await Promise.all([fetch("/api/clientes"),fetch("/api/health")]);clientes=(await cr.json()).clientes||[];const h=await hr.json();destinoPadrao=h.destino_padrao||"";renderClientes()}catch{$("smtpBadge").textContent="Servidor indisponível"}}
let analisandoPDF=false;
async function analisarPDF(){
 const file=$("pdf").files[0];if(!file||analisandoPDF)return;
 analisandoPDF=true;$("modoEnvio").disabled=true;$("pdf").disabled=true;$("analisarPDF").disabled=true;
 $("status").textContent=`Analisando ${file.name} e verificando a estrutura e as evidências das correspondências…`;
 const fd=new FormData();fd.append("pdf",file);
 try{
  const r=await fetch("/api/analisar",{method:"POST",body:fd}),data=await r.json();
  if(!r.ok)throw new Error(data.erro||"Erro no servidor.");
  dados=(data.registros||[]).map((x,i)=>({...x,_id:i}));
  clienteAtivo=null;selecionado=-1;$("filtro").value="";$("buscaCliente").value="";
  $("editor").classList.add("hidden");$("empty").classList.remove("hidden");
  dados.forEach(aplicarReconhecimento);$("arquivo").textContent=data.arquivo;
  $("paginas").textContent=data.paginas;$("publicacoes").textContent=data.publicacoes;
  $("result").classList.remove("hidden");
  $("status").textContent=`${data.arquivo}: ${data.envios_automaticos||0} novo(s) envio(s) na fila, ${dados.filter(p=>p.envio_automatico?.status==="enviado").length} já encaminhado(s) anteriormente e ${data.revisao_manual||0} para revisão.`;
  if(!dados.length)$("status").textContent=`${data.arquivo}: nenhuma correspondência com os clientes cadastrados. Nenhum e-mail enviado.`;
  else if(!dados.some(p=>p.envio_automatico))$("status").textContent=`${data.arquivo}: ${dados.length} correspondência(s) para conferência. Confira os motivos de revisão em cada publicação.`;
  const d=data.diagnostico;
  if(d)$("status").textContent+=` Extração: ${data.publicacoes_extraidas} publicações; ${d.paginas_com_texto}/${data.paginas} páginas com texto.${d.paginas_sem_texto.length?` Atenção: páginas ${d.paginas_sem_texto.join(", ")} sem texto extraível; OCR não está habilitado.`:""}`;
  renderClientes();$("status").textContent+=" Envios de 75 a 100 pontos são automáticos; publicações já enviadas ou descartadas não são reenviadas.";acompanharAutomaticos(dados);
 }catch(err){$("status").textContent=`Não foi possível processar ${file.name}: ${err.message}`}
 finally{analisandoPDF=false;$("modoEnvio").disabled=false;carregarHistorico();$("pdf").disabled=false;$("analisarPDF").disabled=false}
}
$("form").addEventListener("submit",e=>{e.preventDefault();analisarPDF()});
$("pdf").addEventListener("change",analisarPDF);

const compact=s=>norm(s).replace(/[^a-z0-9]/g,"");const lista=s=>String(s||"").split(/[,;\n]/).map(x=>x.trim()).filter(Boolean);
function avaliar(pub,c){const match=(pub.correspondencias||[]).find(item=>item.cliente_id===String(c.id));return match?{...match,cliente:c}:null}
function reconhecer(pub){let best=null;for(const c of clientes){const result=avaliar(pub,c);if(result&&(!best||result.score>best.score))best=result}return best}function aplicarReconhecimento(pub){pub._match=reconhecer(pub);pub._cliente=pub._match?.cliente||null;return pub}
function renderClientes(){if(dados.length)dados.forEach(aplicarReconhecimento);const q=norm($("buscaCliente").value);$("clientes").innerHTML=clientes.filter(c=>norm(c.nome+" "+c.email+" "+c.tipo).includes(q)).map(c=>`<div class="client-row"><button class="client ${c.id===clienteAtivo?'active':''}" data-id="${esc(c.id)}"><b>${esc(c.nome)}</b><small>${esc(c.tipo||'Pessoa')} · ${esc(c.email)}</small><small class="count">${dados.filter(x=>x._cliente?.id===c.id).length} ocorrência(s) no jornal</small></button><button class="edit-client" data-edit="${esc(c.id)}" title="Editar monitorado">Editar</button></div>`).join("")||'<div class="empty small">Cadastre o primeiro monitorado.</div>';$("todosClientes").classList.toggle("hidden",!clienteAtivo);renderPublicacoes()}
$("buscaCliente").oninput=renderClientes;$("novoCliente").onclick=()=>abrirCliente();$("cancelarCliente").onclick=()=>$("clienteForm").classList.add("hidden");$("todosClientes").onclick=()=>{clienteAtivo=null;selecionado=-1;renderClientes()};$("clientes").onclick=e=>{const edit=e.target.closest("[data-edit]"),b=e.target.closest("[data-id]");if(edit)abrirCliente(clientes.find(c=>c.id===edit.dataset.edit));else if(b)focarCliente(b.dataset.id)};function abrirCliente(c={}){$("clienteId").value=c.id||"";$("clienteTipo").value=c.tipo||"Pessoa";$("clienteNome").value=c.nome||"";$("clienteEmail").value=c.email||destinoPadrao;$("clienteIdentificador").value=c.identificador||"";$("clienteProcessos").value=c.processos||"";$("clienteVariantes").value=c.variantes||"";$("clienteTermos").value=c.termos||"";$("clienteForm").classList.remove("hidden")}
function focarCliente(id){clienteAtivo=id;const encontrados=dados.filter(x=>x._cliente?.id===id);renderClientes();if(encontrados.length){selecionar(encontrados[0]._id);$("status").textContent=`${encontrados.length} publicação(ões) localizada(s) para ${clientes.find(c=>c.id===id)?.nome}.`}else if(dados.length){$("status").textContent="Nenhuma ocorrência desse cliente foi localizada no jornal. Confira o nome ou acrescente OAB/variações no cadastro."}}
$("clienteForm").onsubmit=async e=>{e.preventDefault();const c={id:$("clienteId").value||String(Date.now()),tipo:$("clienteTipo").value,nome:$("clienteNome").value.trim(),email:$("clienteEmail").value.trim(),identificador:$("clienteIdentificador").value.trim(),processos:$("clienteProcessos").value.trim(),variantes:$("clienteVariantes").value.trim(),termos:$("clienteTermos").value.trim()},i=clientes.findIndex(x=>x.id===c.id);if(i<0)clientes.push(c);else clientes[i]=c;const r=await fetch("/api/clientes",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(clientes)});if(!r.ok)return alert("Não foi possível salvar o monitorado.");$("clienteForm").classList.add("hidden");dados.forEach(aplicarReconhecimento);focarCliente(c.id);if(dados.length)$("status").textContent="Cadastro salvo. As evidências exibidas pertencem à última análise; analise o PDF novamente para aplicar o cadastro atualizado."};
function faixaCor(score){return Number(score)>=75?"score-green":Number(score)>=40?"score-orange":"score-red"}
function renderPublicacoes(){const q=norm($("filtro").value),list=dados.filter(x=>(!clienteAtivo||x._cliente?.id===clienteAtivo)&&norm(Object.values(x).join(" ")).includes(q));const nome=clientes.find(c=>c.id===clienteAtivo)?.nome;$("queueTitle").textContent=nome?`${nome} (${list.length})`:`Publicações (${list.length})`;$("publicacoesLista").innerHTML=list.map(x=>`<div class="publication-row ${x.bloqueada?'is-blocked':x.envio_automatico?.status==='enviado'?'is-sent':''}"><div class="publication-controls"><span class="publication-check ${x.envio_automatico?.status==='enviado'?'confirmed':'pending'}" role="img" aria-label="${x.envio_automatico?.status==='enviado'?'Envio confirmado':'Envio ainda não confirmado'}" title="${x.envio_automatico?.status==='enviado'?'Envio confirmado':'Envio ainda não confirmado'}">✓</span><button type="button" class="reject-publication" aria-pressed="${!!x.bloqueada}" data-reject="${x._id}" aria-label="${x.bloqueada?'Desfazer marcação':'Marcar como não cliente'}" title="${x.bloqueada?'Desfazer marcação':'Marcar como não cliente'}" ${(!x.bloqueada&&(x.confianca??x._match?.score??0)>=75)||['na_fila','enviando','aguardando_outlook','enviado'].includes(x.envio_automatico?.status)?'disabled':''}>×</button></div><button data-pub="${x._id}" class="publication-item ${x._id===selecionado?'active':''}"><span class="match ${faixaCor(x._match?.score)}">${esc(rotuloEnvio(x))}${x._match?`${x._match.score}/100 · ${esc(x._cliente.nome)}`:'! Sem correspondência'}</span><small class="auto-error">${esc(x.envio_automatico?.erro||"")}</small><b>${esc(x.processo)}</b><small class="origin">${esc(x.cabecalho||'Origem não identificada')}</small><small>${esc(x.tipo)} · pág. ${esc(x.pagina||'—')}</small><p>${esc(x.partes)}</p></button></div>`).join("")||'<div class="empty small">Nenhuma publicação encontrada para este cliente.</div>'}
$("filtro").oninput=renderPublicacoes;$("publicacoesLista").onclick=e=>{const reject=e.target.closest("[data-reject]");if(reject){alternarDescarte(Number(reject.dataset.reject));return}const b=e.target.closest("[data-pub]");if(b)selecionar(Number(b.dataset.pub))};function selecionar(id){selecionado=id;const x=dados.find(p=>p._id===id);$("empty").classList.add("hidden");$("editor").classList.remove("hidden");let reasons=$("matchReasons");if(!reasons){reasons=document.createElement("div");reasons.id="matchReasons";reasons.className="match-reasons";$("editor").prepend(reasons)}const faixa=faixaCor(x._match?.score);reasons.innerHTML=x._match?`<span class="confidence ${faixa}">${x._match.score}/100 de correspondência</span><br>Por que encontrou: ${x._match.motivos.map(esc).join(" · ")}`:"Sem correspondência automática. Selecione manualmente um monitorado.";reasons.innerHTML+=`<br>Estrutura: ${esc(x.confianca_estrutural??"—")}/100 · Páginas: ${esc((x.paginas_origem||[x.pagina]).join(", "))}<br>${(x.motivos_estrutura||[]).map(esc).join(" · ")}<br><small>Pontuações heurísticas, não probabilidades.</small>${x.revisao_manual?`<br><b>Revisão: ${esc(x.revisao_manual.motivo)}</b>`:""}`;$("destCliente").innerHTML='<option value="">Selecione…</option>'+clientes.map(c=>`<option value="${esc(c.id)}">${esc(c.nome)}</option>`).join("");$("destCliente").value=x._cliente?.id||"";$("cabecalho").value=x.cabecalho||"";$("processo").value=x.processo||"";$("comarca").value=x.comarca||"";$("vara").value=x.vara||"";$("tipo").value=x.tipo||"";$("pagina").value=x.pagina||"";$("conteudo").value=x.conteudo||"";preencherCliente();$("confirmado").checked=false;$("enviar").disabled=true;$("matchBadge").textContent=x._match?`${x._match.score}/100 de correspondência`:"Requer associação manual";$("matchBadge").className="pill "+faixa;$("sendStatus").textContent=x.bloqueada?"Marcado como não cliente.":"";$("rascunho").disabled=!!x.bloqueada;renderPublicacoes()}
function preencherCliente(){const c=clientes.find(x=>x.id===$("destCliente").value),p=dados.find(x=>x._id===selecionado);$("destEmail").value=c?(c.email||destinoPadrao):"";$("assunto").value=c?`Publicação processual — ${$("processo").value||p?.processo||""}`:"";destacarCliente()}$("destCliente").onchange=()=>{preencherCliente();dados.find(p=>p._id===selecionado)._cliente=clientes.find(c=>c.id===$("destCliente").value)||null;renderPublicacoes()};$("confirmado").onchange=()=>$("enviar").disabled=!$("confirmado").checked||!!dados.find(p=>p._id===selecionado)?.bloqueada;
function montarCorpoEmail(){return[`Cabeçalho / origem`,$("cabecalho").value.trim()||"Não identificado","",`Assunto`,$("assunto").value.trim(),"",`Processo`,$("processo").value.trim()||"Não identificado","",`Comarca`,$("comarca").value.trim()||"Não identificada","",`Vara / unidade`,$("vara").value.trim()||"Não identificada","",`Tipo`,$("tipo").value.trim()||"Não identificado","",`Página`,$("pagina").value.trim()||"Não identificada","",`Conteúdo`,$("conteudo").value.trim()].join("\r\n")}
async function acompanharEnvio(id){for(let tentativa=0;tentativa<60;tentativa++){await new Promise(resolve=>setTimeout(resolve,1000));try{const r=await fetch(`/api/envios/${id}`),job=await r.json();if(["enviado","capturado_teste"].includes(job.status)){$("sendStatus").textContent=job.status==="capturado_teste"?"Capturado no teste — não enviado ao Gmail":"Saída confirmada";$("enviar").disabled=!$("confirmado").checked;return}if(job.status==="erro"){$("sendStatus").textContent="Erro: "+job.erro;$("enviar").disabled=!$("confirmado").checked;return}$("sendStatus").textContent=job.status==="aguardando_outlook"?"Aguardando saída pelo Outlook…":"Envio em andamento…"}catch{}}$("sendStatus").textContent="Envio ainda em processamento. Consulte novamente em instantes.";$("enviar").disabled=!$("confirmado").checked}
function payload(){return{revisao_id:dados.find(p=>p._id===selecionado)?.revisao_id,para:$("destEmail").value.trim(),assunto:$("assunto").value.trim(),corpo:montarCorpoEmail(),cliente_nome:clientes.find(c=>c.id===$("destCliente").value)?.nome||"Cliente",publicacao:Object.fromEntries(["processo","comarca","vara","cabecalho","tipo","pagina","conteudo"].map(k=>[k,$(k).value])),confirmado:$("confirmado").checked}}$("rascunho").onclick=async()=>{const p=payload();if(!p.para)return alert("Selecione um cliente com e-mail.");try{const r=await fetch("/api/rascunho",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)});if(!r.ok)throw new Error("Não foi possível gerar o rascunho.");download("publicacao.eml",await r.blob(),"message/rfc822");$("sendStatus").textContent="Rascunho com card baixado. Abra o arquivo no programa de e-mail."}catch(e){$("sendStatus").textContent=e.message}};$("enviar").onclick=async()=>{const registro=dados.find(p=>p._id===selecionado);if(registro?.bloqueada)return;const p=payload();if(!p.para||!p.assunto||!$("conteudo").value.trim())return alert("Preencha destinatário, assunto e conteúdo.");$("enviar").disabled=true;$("sendStatus").textContent="Colocando na fila…";const inicio=performance.now();try{const r=await fetch("/api/enviar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)}),out=await r.json();if(!r.ok)throw new Error(out.erro||"Falha ao iniciar o envio.");const segundos=((performance.now()-inicio)/1000).toFixed(1);$("sendStatus").textContent=`✓ Enfileirado em ${segundos}s`;registro.envio_automatico={status:out.status,envio_id:out.envio_id};renderPublicacoes();acompanharAutomaticos(dados);acompanharEnvio(out.envio_id)}catch(err){$("sendStatus").textContent="Erro: "+err.message;$("enviar").disabled=!$("confirmado").checked}};
$("json").onclick=()=>download("clipping.json",JSON.stringify(dados,null,2),"application/json");$("csv").onclick=()=>{const h=["processo","classe","cabecalho","orgao","comarca","unidade","secao","vara","tipo","partes","advogados","oabs","pagina"];download("clipping.csv","\ufeff"+[h.join(";"),...dados.map(x=>h.map(k=>`"${String(x[k]??"").replaceAll('"','""')}"`).join(";"))].join("\n"),"text/csv;charset=utf-8")};function download(n,c,t){const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([c],{type:t}));a.download=n;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}init();

// A camada de destaque preserva o texto editável e o conteúdo enviado por e-mail.
function destacarCliente(){
 const campo=$("conteudo"),camada=$("conteudoDestaques");
 const cliente=clientes.find(c=>c.id===$("destCliente").value);
 const texto=campo.value,indices=[];let normalizado="";
 for(let i=0;i<texto.length;){const caractere=String.fromCodePoint(texto.codePointAt(i)),n=norm(caractere);for(const letra of n){normalizado+=letra;indices.push([i,i+caractere.length])}i+=caractere.length}
 const nomes=[cliente?.nome,...lista(cliente?.variantes)].filter(Boolean);
 const intervalos=[];
 for(const nome of nomes){
  const partes=norm(nome).trim().split(/\s+/).map(p=>p.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));
  if(!partes.join(""))continue;
  const re=new RegExp(partes.join("\\s+"),"gu");
  for(const m of normalizado.matchAll(re)){
   const inicio=m.index,fim=inicio+m[0].length;
   if(/[\p{L}\p{N}]/u.test(normalizado[inicio-1]||"")||/[\p{L}\p{N}]/u.test(normalizado[fim]||""))continue;
   intervalos.push([indices[inicio][0],indices[fim-1][1]]);
  }
 }
 intervalos.sort((a,b)=>a[0]-b[0]);const unidos=[];
 for(const trecho of intervalos){const ultimo=unidos[unidos.length-1];if(ultimo&&trecho[0]<=ultimo[1])ultimo[1]=Math.max(ultimo[1],trecho[1]);else unidos.push([...trecho])}
 let html="",pos=0;for(const [inicio,fim] of unidos){html+=esc(texto.slice(pos,inicio))+"<mark>"+esc(texto.slice(inicio,fim))+"</mark>";pos=fim}
 camada.innerHTML=html+esc(texto.slice(pos))+"\n";
 camada.scrollTop=campo.scrollTop;camada.scrollLeft=campo.scrollLeft;
}
$("conteudo").addEventListener("input",destacarCliente);
$("conteudo").addEventListener("scroll",()=>{const c=$("conteudo"),d=$("conteudoDestaques");d.scrollTop=c.scrollTop;d.scrollLeft=c.scrollLeft});
new ResizeObserver(()=>{const c=$("conteudo");$("conteudoDestaques").style.width=c.clientWidth+"px";$("conteudoDestaques").style.height=c.clientHeight+"px"}).observe($("conteudo"));

function rotuloEnvio(pub){
 if(pub.bloqueada)return "✕ Não é cliente · ";
 const envio=pub.envio_automatico;
 if(!envio)return pub.revisao_manual?"Revisar · ":"";
 return ({descartada:"Não será enviada · ",aguardando_revisao:"Aguardando conferência · ",capturado_teste:"Capturado no teste · ",na_fila:"Na fila de envio · ",enviando:"Enviando · ",aguardando_outlook:"Aguardando Outlook · ",enviado:"✓ Encaminhado ao e-mail · ",erro:"Falha no envio · "})[envio.status]||"Verificando envio · ";
}
async function acompanharAutomaticos(registros){
 const ativos=()=>registros.filter(p=>["na_fila","enviando","aguardando_outlook"].includes(p.envio_automatico?.status));
 while(dados===registros&&ativos().length){
  const pendentes=ativos();
  for(let i=0;i<pendentes.length;i+=5){
   await Promise.all(pendentes.slice(i,i+5).map(async p=>{
    try{const r=await fetch(`/api/envios/${p.envio_automatico.envio_id}`),job=await r.json();
     if(r.ok)p.envio_automatico={...p.envio_automatico,...job};
     else if(r.status===404)p.envio_automatico={...p.envio_automatico,status:"erro",erro:job.erro};
    }catch{}
   }));
  }
  if(dados!==registros)return;
  renderPublicacoes();
  const auto=registros.filter(p=>p.envio_automatico),falhas=auto.filter(p=>p.envio_automatico.status==="erro").length;
  $("status").textContent=`Envios automáticos: ${auto.filter(p=>p.envio_automatico.status==="capturado_teste").length} capturado(s) no teste, ${auto.filter(p=>p.envio_automatico.status==="enviado").length} encaminhado(s), ${ativos().length} em andamento, ${falhas} com falha. ${falhas?"Consulte o erro na publicação e reanalise o PDF após corrigir a causa.":""}`;
  if(ativos().length)await new Promise(resolve=>setTimeout(resolve,2000));
 }
}

let verificandoEmail=false;
async function atualizarStatusEmail(){
 if(verificandoEmail)return;
 verificandoEmail=true;
 try{
  const r=await fetch("/api/email-status",{cache:"no-store",signal:AbortSignal.timeout(25000)});
  if(!r.ok)throw new Error("Falha ao consultar conexão");
  const h=await r.json();
  $("smtpBadge").textContent=h.email_mode==="teste"?"TESTE — caixa local, sem envio ao Gmail":h.email_ready===false?"Envio indisponível — verifique o Outlook":h.email_mode==="outlook"?"Outlook conectado · 75–100 pontos → henriquefelipe1520@gmail.com":"SMTP configurado · 75–100 pontos → henriquefelipe1520@gmail.com";
  $("smtpBadge").title=(h.email_detail||"")+" · Verificado às "+new Date().toLocaleTimeString();
 }catch{
  $("smtpBadge").textContent="Conexão de e-mail não confirmada — tentando novamente";
  $("smtpBadge").title="A consulta não foi concluída. Nova verificação automática em até 30 segundos.";
 }finally{verificandoEmail=false}
}
atualizarStatusEmail();
setInterval(atualizarStatusEmail,30000);
window.addEventListener("focus",atualizarStatusEmail);


$("baixarPublicacao").onclick=()=>download("publicacao.txt",$("cabecalho").value.trim()+"\n\n"+$("conteudo").value.trim(),"text/plain;charset=utf-8");

let historicoAtual=[];
function mostrarModo(modo){
 $("modoEnvio").value=modo;
 $("avisoModo").textContent=modo==="teste"?"TESTE — os e-mails ficam nesta caixa local. Nada será enviado ao Gmail ou ao Outlook.":"REAL — correspondências de 75 a 100 pontos são enviadas automaticamente para henriquefelipe1520@gmail.com, sem repetir envios já registrados.";
 $("avisoModo").style.color=modo==="teste"?"#9a5800":"#166534";
}
fetch("/api/modo").then(r=>r.json()).then(h=>mostrarModo(h.modo)).catch(()=>{$("avisoModo").textContent="Não foi possível consultar o modo."});
$("modoEnvio").onchange=async()=>{
 try{const r=await fetch("/api/modo",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({modo:$("modoEnvio").value})});const h=await r.json();if(!r.ok)throw Error(h.erro);mostrarModo(h.modo);atualizarStatusEmail()}catch(e){$("avisoModo").textContent=e.message}
};
async function carregarHistorico(){
 try{const r=await fetch("/api/historico",{cache:"no-store"});if(!r.ok)throw Error("Falha ao carregar histórico");historicoAtual=(await r.json()).envios;renderHistorico();$("erroHistorico").textContent=""}catch(e){$("erroHistorico").textContent=e.message}
}
function renderHistorico(){
 const busca=norm($("buscaHistorico").value);
 const rows=historicoAtual.filter(x=>(!$("filtroModo").value||x.modo===$("filtroModo").value)&&norm([x.processo,x.assunto,x.cliente,x.para].join(" ")).includes(busca));
 const labels={na_fila:"Na fila",enviando:"Enviando",enviado:"Saída confirmada",capturado_teste:"Capturado no teste",erro:"Falha",aguardando_outlook:"Aguardando Outlook"};
 $("historicoEnvios").innerHTML=rows.length?'<table style="width:100%;text-align:left;border-spacing:12px"><thead><tr><th>Modo</th><th>Publicação / assunto</th><th>Data</th><th>Situação</th><th>Ações</th></tr></thead><tbody>'+rows.map(x=>`<tr><td>${esc(x.modo)}</td><td>${esc(x.assunto||x.processo||"")}<br><small>${esc(x.para||"")}</small></td><td>${esc(new Date(x.criado_em*1000).toLocaleString())}</td><td><span class="${x.status==='enviado'?'delivery-sent':''}">${x.status==='enviado'?'✓ ':''}${esc(labels[x.status]||x.status)}</span>${x.erro?`<br><small>${esc(x.erro)}</small>`:""}</td><td><button class="secondary" data-ler="${esc(x.envio_id)}">Ver publicação</button>${x.status==="erro"&&!x.nova_tentativa?` <button data-repetir="${esc(x.envio_id)}">Tentar novamente</button>`:""}</td></tr>`).join("")+"</tbody></table>":"Nenhum envio neste modo.";
}
$("historicoEnvios").onclick=async e=>{const ler=e.target.closest("[data-ler]");if(ler){abrirPublicacao(ler.dataset.ler);return}const b=e.target.closest("[data-repetir]");if(!b)return;b.disabled=true;try{const r=await fetch("/api/repetir/"+encodeURIComponent(b.dataset.repetir),{method:"POST"});const h=await r.json();if(!r.ok)throw Error(h.erro);await carregarHistorico()}catch(e){$("erroHistorico").textContent=e.message;b.disabled=false}};
$("filtroModo").onchange=renderHistorico;$("atualizarHistorico").onclick=carregarHistorico;
carregarHistorico();setInterval(carregarHistorico,10000);

function mudarTela(){
 const publicacoes=location.hash==="#publicacoes";
 $("telaAnalise").classList.toggle("hidden",publicacoes);
 $("telaPublicacoes").classList.toggle("hidden",!publicacoes);
 for(const [id,active] of [["navAnalise",!publicacoes],["navPublicacoes",publicacoes]]){
  $(id).classList.toggle("active",active);
  if(active)$(id).setAttribute("aria-current","page");else $(id).removeAttribute("aria-current");
 }
 document.title=(publicacoes?"Publicações":"Análise e envio")+" | Clipping Jurídico";
 if(publicacoes)carregarHistorico();
}
async function abrirPublicacao(id){
 $("tituloLeitura").dataset.registro=id;
 const registro=historicoAtual.find(x=>x.envio_id===id);
 $("tituloLeitura").textContent=registro?.assunto||registro?.processo||"Publicação integral";
 $("leituraPublicacao").classList.remove("hidden");
 $("previewPublicacao").srcdoc="<p>Carregando publicação…</p>";
 try{
  const r=await fetch("/api/visualizar/"+encodeURIComponent(id));
  if(!r.ok)throw Error("Este registro antigo não possui conteúdo salvo para visualização.");
  const html=await r.text();
  if($("tituloLeitura").dataset.registro!==id)return;
  $("previewPublicacao").srcdoc=html;
  $("leituraPublicacao").scrollIntoView({behavior:"smooth",block:"start"});
 }catch(e){if($("tituloLeitura").dataset.registro===id)$("previewPublicacao").srcdoc="<p>"+esc(e.message)+"</p>"}
}
$("fecharLeitura").onclick=()=>{$("tituloLeitura").dataset.registro="";$("leituraPublicacao").classList.add("hidden");$("previewPublicacao").srcdoc=""};
$("buscaHistorico").oninput=renderHistorico;
window.addEventListener("hashchange",mudarTela);mudarTela();

function atualizarArquivoVisual(){const file=$("pdf").files[0];$("nomeArquivoVisual").textContent=file?.name||"Nenhum arquivo selecionado";$("detalheArquivoVisual").textContent=file?`${(file.size/1024/1024).toFixed(2)} MB · PDF` :"Selecione um Diário de Justiça para começar"}
$("pdf").addEventListener("change",atualizarArquivoVisual);
for(const event of ["dragenter","dragover"]){$("dropArea").addEventListener(event,e=>{e.preventDefault();if(!analisandoPDF)$("dropArea").classList.add("dragging")})}
for(const event of ["dragleave","drop"]){$("dropArea").addEventListener(event,e=>{e.preventDefault();$("dropArea").classList.remove("dragging")})}
$("dropArea").addEventListener("drop",e=>{if(analisandoPDF)return;const file=e.dataTransfer.files[0];if(!file)return;if(!file.name.toLowerCase().endsWith(".pdf")){$("status").textContent="Escolha um arquivo PDF.";return}const transfer=new DataTransfer();transfer.items.add(file);$("pdf").files=transfer.files;atualizarArquivoVisual();analisarPDF()});

async function alternarDescarte(id){
 const p=dados.find(x=>x._id===id);if(!p)return;
 try{const r=await fetch('/api/revisao',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:p.revisao_id,acao:p.bloqueada?'restaurar':'bloquear'})}),out=await r.json();if(!r.ok)throw new Error(out.erro);p.bloqueada=out.bloqueada;renderPublicacoes();if(selecionado===id){$('confirmado').checked=false;$('enviar').disabled=true;$('rascunho').disabled=p.bloqueada;$('sendStatus').textContent=p.bloqueada?'Marcado como não cliente.':'Marcação desfeita. Confira antes de enviar.'}}
 catch(e){$('status').textContent=e.message}
}
const ajuda=document.createElement('p');ajuda.className='review-help';ajuda.textContent='Pontuação: verde 75–100 · laranja 40–74 · vermelho abaixo de 40. × Não é cliente · ✓ Envio confirmado.';$('publicacoesLista').before(ajuda);

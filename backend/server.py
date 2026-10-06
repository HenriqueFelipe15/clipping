# Dependências do servidor, dos parsers e do e-mail.
from email_card import render_card
import json
import os
import re
import hashlib
import smtplib
import subprocess
import tempfile
import threading
import time
import uuid
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pymupdf as fitz
import cnj_parser
import tcepr_parser
import domsc_parser

# Configuração, arquivos locais e controle das tarefas concorrentes.
PORT = 8000
ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DATA_DIR = ROOT / "data"
CLIENTS_FILE = DATA_DIR / "clientes.json"
AUTO_SEND_FILE = DATA_DIR / "envios_automaticos.json"
AUTO_SEND_THRESHOLD = 75
DEFAULT_RECIPIENT = "henriquefelipe1520@gmail.com"
AUTO_SEND_LOCK = threading.Lock()
EMAIL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="email")
EMAIL_JOBS = {}
EMAIL_JOBS_LOCK = threading.Lock()

SETTINGS_FILE=DATA_DIR / "modo_envio.json"
DELIVERY_FILE=DATA_DIR / "historico_envios.json"
DELIVERY_LOCK=threading.RLock()
REVIEW_FILE=DATA_DIR / "revisao_publicacoes.json"
REVIEW_LOCK=threading.RLock()

# Revisão manual e bloqueio de publicações.
def load_reviews():
    return json.loads(REVIEW_FILE.read_text(encoding="utf-8")) if REVIEW_FILE.exists() else {}

def save_reviews(rows):
    DATA_DIR.mkdir(exist_ok=True)
    temporary=REVIEW_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(REVIEW_FILE)

def review_publication(key,action,payload=None):
    with REVIEW_LOCK:
        rows=load_reviews()
        row=rows.get(key)
        if not row: raise ValueError("Publicação não encontrada. Analise novamente o PDF.")
        previous=existing_auto_send(load_auto_sends().get(key))
        if previous:
            if action=="enviar": return previous
            raise ValueError("O envio já foi iniciado ou concluído e não pode ser cancelado pelo X.")
        if action in ("bloquear","restaurar"):
            row["bloqueada"]=action=="bloquear"
            save_reviews(rows)
            return {"bloqueada":row["bloqueada"]}
        if row.get("bloqueada"): raise ValueError("Publicação descartada: envio bloqueado.")
        if row["modo"]!=delivery_mode(): raise ValueError("O modo de envio mudou. Analise novamente o PDF.")
        if payload is None and not row["elegivel"]: raise ValueError("Esta publicação exige conferência individual.")
        job_id=queue_email({**(payload or row["payload"]),"_modo":row["modo"],"revisao_id":key},lambda created:record_auto_send(key,row["cliente"],row["registro"],created))
        with EMAIL_JOBS_LOCK:
            return {**EMAIL_JOBS.get(job_id,{"status":"na_fila"}),"envio_id":job_id}

# Modo de envio, histórico persistente e fila de e-mails.
def delivery_mode():
    if not SETTINGS_FILE.exists(): return "real"
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))["modo"]

def delivery_history():
    if not DELIVERY_FILE.exists(): return {}
    return json.loads(DELIVERY_FILE.read_text(encoding="utf-8"))

def write_delivery(job_id,values):
    with DELIVERY_LOCK:
        history=delivery_history()
        history[job_id]={**history.get(job_id,{}),**values}
        DATA_DIR.mkdir(exist_ok=True)
        temporary=DELIVERY_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
        temporary.replace(DELIVERY_FILE)


def run_email_job(job_id,payload):
    with EMAIL_JOBS_LOCK: EMAIL_JOBS[job_id]={"status":"enviando","atualizado_em":time.time()}
    try:
        result=({"status":"capturado_teste","mensagem":"Capturado no teste — não enviado ao Gmail."} if payload.get("_modo")=="teste" else send_email(payload)) or {"status":"enviado","mensagem":"Mensagem aceita pelo servidor SMTP; entrega depende do provedor."}
        result["atualizado_em"]=time.time()
    except Exception as exc:
        result={"status":"erro","erro":str(exc),"atualizado_em":time.time()}
    write_delivery(job_id,result)
    update_auto_send_status(job_id,result)
    with EMAIL_JOBS_LOCK: EMAIL_JOBS[job_id]=result


def recover_test_jobs():
    """Completa capturas locais interrompidas; nunca aciona SMTP/Outlook."""
    with DELIVERY_LOCK:
        for job_id,job in delivery_history().items():
            if job.get('modo')!='teste' or job.get('status') not in ('na_fila','enviando'):
                continue
            payload=job.get('payload')
            if not payload or not (payload.get('corpo') or payload.get('html')):
                write_delivery(job_id,{'status':'erro','erro':'Conteúdo indisponível para recuperar a captura de teste.'})
                continue
            run_email_job(job_id,{**payload,'_modo':'teste'})

def queue_email(payload,on_created=None):
    payload={**payload,"_modo":payload.get("_modo",delivery_mode())}
    job_id=uuid.uuid4().hex
    write_delivery(job_id,{"envio_id":job_id,"modo":payload["_modo"],"status":"na_fila","criado_em":time.time(),"para":payload.get("para"),"assunto":payload.get("assunto"),"cliente":payload.get("cliente_nome",""),"payload":payload})
    with EMAIL_JOBS_LOCK: EMAIL_JOBS[job_id]={"status":"na_fila","atualizado_em":time.time()}
    if on_created: on_created(job_id)
    if payload['_modo']=='teste':
        # A captura local não precisa de fila em segundo plano: persiste antes de responder.
        run_email_job(job_id,payload)
    else:
        EMAIL_EXECUTOR.submit(run_email_job,job_id,payload)
    return job_id

# Cadastro de monitorados e prevenção de envios duplicados.
def load_clients():
    if not CLIENTS_FILE.exists(): return []
    try: return json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return []

def save_clients(clients):
    DATA_DIR.mkdir(exist_ok=True)
    CLIENTS_FILE.write_text(json.dumps(clients, ensure_ascii=False, indent=2), encoding="utf-8")

def load_auto_sends():
    if not AUTO_SEND_FILE.exists(): return {}
    try:
        value=json.loads(AUTO_SEND_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,json.JSONDecodeError): return {}

def save_auto_sends(history):
    DATA_DIR.mkdir(exist_ok=True)
    temporary=AUTO_SEND_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(AUTO_SEND_FILE)

def record_auto_send(key,client,record,job_id):
    with AUTO_SEND_LOCK:
        history=load_auto_sends()
        history[key]={"envio_id":job_id,"cliente_id":client.get("id"),"processo":record.get("processo"),"status":"na_fila","criado_em":time.time()}
        save_auto_sends(history)

def update_auto_send_status(job_id,result):
    with AUTO_SEND_LOCK:
        history=load_auto_sends(); changed=False
        for item in history.values():
            if item.get("envio_id")==job_id:
                item.update({key:value for key,value in result.items() if key in ("status","erro","mensagem","atualizado_em","outlook_token","assunto","para","submetido_em","ultima_recuperacao","tentativas_recuperacao")})
                changed=True
        if changed: save_auto_sends(history)

# Integração SMTP/Outlook e confirmação dos envios.
def email_connection_status():
    if delivery_mode()=="teste": return {"email_mode":"teste","email_ready":True,"email_detail":"Caixa local de testes. Não envia ao Gmail."}
    if os.getenv("SMTP_HOST") and (os.getenv("SMTP_FROM") or os.getenv("SMTP_USER")):
        return {"email_mode":"smtp","email_ready":None,"email_detail":"SMTP configurado; conexão será verificada no envio."}
    if os.name!="nt": return {"email_mode":"indisponivel","email_ready":False,"email_detail":"Configure um serviço de e-mail."}
    script=r'''$ErrorActionPreference="Stop"
try {
 $app=New-Object -ComObject Outlook.Application
 $session=$app.Session
 if ($session.Accounts.Count -eq 0) { throw "Nenhuma conta configurada no Outlook." }
 if ($session.Offline) { throw "O Outlook está offline." }
 Write-Output "OUTLOOK_CONECTADO"
} catch { Write-Error $_; exit 1 }
'''
    try:
        result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        ready=result.returncode==0 and "OUTLOOK_CONECTADO" in result.stdout
        return {"email_mode":"outlook","email_ready":ready,"email_detail":"Outlook conectado." if ready else "Sem acesso ao Outlook. Inicie o sistema pelo arquivo Iniciar sistema.cmd na sua sessão do Windows."}
    except Exception:
        return {"email_mode":"outlook","email_ready":False,"email_detail":"Não foi possível verificar a conexão com o Outlook."}


def send_via_outlook(payload):
    """Envia pelo perfil já autenticado no Outlook clássico, sem abrir janela."""
    script=r'''
$ErrorActionPreference = "Stop"
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$outlook = New-Object -ComObject Outlook.Application
$session = $outlook.Session
if ($session.Accounts.Count -eq 0) { throw "Nenhuma conta de e-mail configurada no Outlook." }
if ($session.Offline) { throw "O Outlook está offline. Conecte-o antes de enviar." }
$mail = $outlook.CreateItem(0)
$mail.To = $payload.para
$mail.Subject = $payload.assunto
if ($payload.html) { $mail.HTMLBody = $payload.html } else { $mail.Body = $payload.corpo }
$property=$mail.UserProperties.Add("ClippingToken",1)
$property.Value=$payload.outlook_token
$mail.Send()
Write-Output "SUBMETIDO"
try { $session.SendAndReceive($false) } catch { }
'''
    token=uuid.uuid4().hex
    submitted=time.time()
    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    result=subprocess.run(
        ["powershell.exe","-NoProfile","-NonInteractive","-Command",script],
        input=json.dumps({**payload,"outlook_token":token},ensure_ascii=True),text=True,capture_output=True,
        timeout=45,creationflags=creationflags
    )
    if "SUBMETIDO" not in result.stdout:
        detail=normalize(result.stderr) or "O Outlook não confirmou o envio."
        if "80070520" in detail or "0x80070520" in detail:
            detail="O servidor não tem acesso à sessão do Outlook. Inicie o sistema pelo arquivo Iniciar sistema.cmd na sua sessão do Windows."
        raise RuntimeError(f"Falha no envio pelo Outlook: {detail}")

    return {"status":"aguardando_outlook","mensagem":"Mensagem submetida ao Outlook; aguardando confirmação nos Itens Enviados.","outlook_token":token,"assunto":payload["assunto"],"para":payload["para"],"submetido_em":submitted}


OUTLOOK_CHECK_LOCK=threading.Lock()
OUTLOOK_CHECK_CACHE={}

def confirm_outlook_sent(job_id,job):
    if job.get("status")!="aguardando_outlook": return job
    with OUTLOOK_CHECK_LOCK:
        cached=OUTLOOK_CHECK_CACHE.get(job_id)
        if cached and time.time()-cached[0]<15: return cached[1]
        script=r'''$ErrorActionPreference="Stop"
$payload=[Console]::In.ReadToEnd() | ConvertFrom-Json
$app=New-Object -ComObject Outlook.Application
$confirmed=$false
$items=$app.Session.GetDefaultFolder(5).Items
$items.Sort("[SentOn]",$true)
$since=[DateTimeOffset]::FromUnixTimeSeconds([long]$payload.submetido_em).LocalDateTime.AddSeconds(-2)
for($i=1;$i -le $items.Count;$i++) {
 $item=$items.Item($i)
 if($item.SentOn -lt $since) { break }
 if($payload.outlook_token) {
  $prop=$item.UserProperties.Find("ClippingToken")
  if($prop -and $prop.Value -eq $payload.outlook_token) { Write-Output "CONFIRMADO"; $confirmed=$true; break }
 } elseif($item.Subject -ceq $payload.assunto -and $item.To.Trim("'") -ieq $payload.para) {
  Write-Output "CONFIRMADO"; $confirmed=$true; break
 }
}
if (-not $confirmed -and $payload.recuperar) {
 $outbox=$app.Session.GetDefaultFolder(4).Items
 for($i=$outbox.Count;$i -ge 1;$i--) {
  $item=$outbox.Item($i)
  $same=$false
  if($payload.outlook_token) {
   $prop=$item.UserProperties.Find("ClippingToken")
   $same=($prop -and $prop.Value -eq $payload.outlook_token)
  } else {
   $same=($item.Subject -ceq $payload.assunto -and $item.To.Trim("'") -ieq $payload.para)
  }
  if($same) { $item.Send(); Write-Output "REATIVADO"; break }
 }
 $app.Session.SendAndReceive($false)
}
'''
        try:
            recover=time.time()-job.get("ultima_recuperacao",job.get("submetido_em",time.time()))>=60
            result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],input=json.dumps({**job,"recuperar":recover and job.get("tentativas_recuperacao",0)<3},ensure_ascii=True),text=True,capture_output=True,timeout=15,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if result.returncode==0 and "CONFIRMADO" in result.stdout:
                job={**job,"erro":"","status":"enviado","mensagem":"Saída confirmada nos Itens Enviados do Outlook. Recebimento depende do provedor.","atualizado_em":time.time()}
                with EMAIL_JOBS_LOCK: EMAIL_JOBS[job_id]=job
                update_auto_send_status(job_id,job)
            elif "REATIVADO" in result.stdout:
                job={**job,"ultima_recuperacao":time.time(),"tentativas_recuperacao":job.get("tentativas_recuperacao",0)+1,
                     "mensagem":"Mensagem localizada na Caixa de Saída e reativada; aguardando confirmação."}
            elif time.time()-job.get("submetido_em",time.time())>180:
                job={**job,"erro":"Saída ainda não confirmada. Verifique a Caixa de Saída e os erros de sincronização do Outlook. Nenhuma cópia adicional foi criada."}
        except (OSError,subprocess.TimeoutExpired) as exc:
            job={**job,"erro":"Não foi possível confirmar a saída no Outlook: "+str(exc)}
        with EMAIL_JOBS_LOCK: EMAIL_JOBS[job_id]=job
        update_auto_send_status(job_id,job)
        if job_id in delivery_history(): write_delivery(job_id,{k:v for k,v in job.items() if k!="payload"})
        OUTLOOK_CHECK_CACHE[job_id]=(time.time(),job)
        return job



EMAIL_MONITOR_STOP=threading.Event()


def reconcile_pending_emails():
    pending={item["envio_id"]:item for item in load_auto_sends().values()
             if item.get("envio_id") and item.get("status")=="aguardando_outlook"}
    pending.update({key:value for key,value in delivery_history().items() if value.get("status")=="aguardando_outlook"})
    with EMAIL_JOBS_LOCK:
        pending.update({key:dict(value) for key,value in EMAIL_JOBS.items() if value.get("status")=="aguardando_outlook"})
    for job_id,job in pending.items():
        if EMAIL_MONITOR_STOP.is_set(): break
        confirm_outlook_sent(job_id,job)


def monitor_email_delivery():
    while not EMAIL_MONITOR_STOP.is_set():
        try: reconcile_pending_emails()
        except Exception as exc: print("[EMAIL MONITOR]",str(exc),flush=True)
        EMAIL_MONITOR_STOP.wait(20)


def send_email(payload):
    host=os.getenv("SMTP_HOST"); sender=os.getenv("SMTP_FROM") or os.getenv("SMTP_USER")
    if not host or not sender:
        if os.name=="nt": return send_via_outlook(payload)
        raise RuntimeError("Nenhum meio de envio automático está configurado.")
    msg=EmailMessage(); msg["From"]=sender; msg["To"]=payload["para"]; msg["Subject"]=payload["assunto"]; msg.set_content(payload["corpo"])
    if payload.get("html"): msg.add_alternative(payload["html"], subtype="html")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT","587")), timeout=30) as smtp:
        if os.getenv("SMTP_TLS","1") != "0": smtp.starttls()
        if os.getenv("SMTP_USER"): smtp.login(os.getenv("SMTP_USER"),os.getenv("SMTP_PASSWORD",""))
        smtp.send_message(msg)

# Leitura do PDF recebido pelo formulário.
def parse_multipart(handler):
    content_type = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length)
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("O envio precisa ser multipart/form-data.")
    msg = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    for part in msg.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if 'name="pdf"' in disposition:
            filename = part.get_filename() or "arquivo.pdf"
            return filename, part.get_payload(decode=True)
    raise ValueError("Campo PDF não encontrado.")

# Normalização e pontuação das correspondências com clientes.
def normalize(s):
    return re.sub(r"\s+", " ", s or "").strip()

def normalize_search(s):
    """Normaliza texto para localizar clientes sem depender de caixa ou acentos."""
    value=unicodedata.normalize("NFD",str(s or ""))
    value="".join(char for char in value if unicodedata.category(char)!="Mn")
    return normalize(value).casefold()

def client_values(value):
    if isinstance(value,list): return [normalize(item) for item in value if normalize(item)]
    return [normalize(item) for item in re.split(r"[,;\n]+",str(value or "")) if normalize(item)]

def evaluate_client(record,client):
    """Usa somente conteúdo editorial; pontuação heurística, não probabilidade."""
    searchable=normalize_search(" ".join(str(record.get(key) or "") for key in ("conteudo","processo","partes","advogados","oabs")))
    if record.get('parser') == 'domsc_layout':
        searchable += ' ' + normalize_search(record.get('cabecalho', ''))
    process=re.sub(r"\D","",record.get("processo") or "")
    base=0; reasons=[]; strong=False
    def contains(value):
        value=normalize_search(value)
        return bool(value) and bool(re.search(r"(?<!\w)"+re.escape(value)+r"(?!\w)",searchable))
    def mark(points,reason):
        nonlocal base
        base=max(base,points)
        if reason not in reasons: reasons.append(reason)
    for known_process in client_values(client.get("processos")):
        known=re.sub(r"\D","",known_process)
        if len(known)==20 and known==process:
            mark(100,"Número principal de processo conhecido"); strong=True
    identifier=normalize_search(client.get("identificador"))
    digits=re.sub(r"\D","",identifier)
    if client.get("tipo")=="Advogado":
        # UF é obrigatória: o mesmo número pode existir em estados diferentes.
        oab=re.fullmatch(r"(?:oab\s*[/:-]?\s*)?([a-z]{2})\s*[/:-]?\s*([0-9.]+)|([0-9.]+)\s*/\s*([a-z]{2})",identifier)
        if oab:
            uf=oab.group(1) or oab.group(4); number=re.sub(r"\D","",oab.group(2) or oab.group(3))
            if number:
                number_pattern=r"[.\s]*".join(number)
                if re.search(rf"(?<!\w){uf}\s*[/:-]?\s*{number_pattern}(?![\w.-])|(?<![\w.]){number_pattern}\s*/\s*{uf}(?!\w)",searchable):
                    mark(95,"OAB com UF exata"); strong=True
    elif len(digits) in (11,14) and re.fullmatch(r"[\d.\s/-]+",identifier):
        pattern=r"[.\s/-]*".join(digits)
        if re.search(r"(?<!\d)"+pattern+r"(?!\d)",searchable):
            mark(100,"CPF/CNPJ exato"); strong=True
    name=normalize_search(client.get("nome"))
    if contains(name):
        interested=normalize_search(record.get("interessados", ""))
        in_parties=bool(name and re.search(r"(?<!\w)"+re.escape(name)+r"(?!\w)",interested))
        mark(75,"Nome completo no campo Interessados" if in_parties else "Nome completo exato")
    for variation in client_values(client.get("variantes")):
        if contains(variation): mark(70,f"Variação encontrada: {variation}")
    for term in client_values(client.get("termos")):
        if len(normalize_search(term))>2 and contains(term): mark(60,f"Termo encontrado: {term}")
    tokens=[token for token in name.split() if len(token)>2]
    if base<75 and len(tokens)>=2 and all(contains(token) for token in tokens): mark(50,"Nome aproximado")
    score=min(100,base+(min(15,(len(reasons)-1)*5) if len(reasons)>1 else 0))
    if not strong: score=min(score,84)
    return {"cliente":client,"score":score,"motivos":reasons,"identificador_forte":strong} if score>=40 else None

def matching_clients(record,clients):
    return [match for client in clients if (match:=evaluate_client(record,client))]

def matching_client_ids(record,clients):
    return [str(match["cliente"].get("id")) for match in matching_clients(record,clients) if match["cliente"].get("id")]

# Montagem do e-mail e regras de envio automático.
def publication_email(client,record):
    subject=f"Publicação processual — {record.get('processo') or 'processo não identificado'}"
    body="\r\n".join([
        "Cabeçalho / origem",record.get("cabecalho") or "Não identificado","",
        "Assunto",subject,"","Processo",record.get("processo") or "Não identificado","",
        "Comarca",record.get("comarca") or "Não identificada","",
        "Vara / unidade",record.get("vara") or "Não identificada","",
        "Tipo",record.get("tipo") or "Não identificado","",
        "Página",str(record.get("pagina") or "Não identificada"),"",
        "Conteúdo",record.get("conteudo") or ""
    ])
    return {"para":DEFAULT_RECIPIENT,"assunto":subject,"corpo":body,"html":render_card(client,record),"confirmado":True}

def auto_send_blockers(match,record,email):
    reasons=[]
    if not email: reasons.append("Destinatário não definido")
    if not AUTO_SEND_THRESHOLD <= match.get("score",0) <= 100:
        reasons.append("Correspondência fora da faixa de 75 a 100 pontos")
    return reasons


def should_auto_send(score,email,match=None,record=None):
    return not auto_send_blockers({**(match or {}),"score":score},record or {},email)


def existing_auto_send(previous):
    if not previous: return None
    with EMAIL_JOBS_LOCK:
        job=EMAIL_JOBS.get(previous.get("envio_id"))
    state=job or previous
    # Falhas podem ser tentadas novamente; somente envios concluídos ou ativos são deduplicados.
    if state.get("status") in ("enviado","capturado_teste","aguardando_outlook") or (job and state.get("status") in ("na_fila","enviando")):
        return {"status":state["status"],"envio_id":previous.get("envio_id"),"mensagem":state.get("mensagem","")}
    return None


def auto_send_key(client,record,mode="real"):
    raw="|".join([str(client.get("id","")),str(record.get("processo","")),str(record.get("conteudo",""))])
    return ("teste:" if mode=="teste" else "")+hashlib.sha256(raw.encode("utf-8")).hexdigest()

# Extração do PDF e separação das publicações por contexto.
def extract_pages(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return cnj_parser.extract(doc)

def find_page(text, pages, pos):
    cur=0
    for n,t in pages:
        end=cur+len(t)+1
        if cur <= pos < end: return n
        cur=end
    return None

def clean_page_text(text):
    """Remove cabeçalhos/rodapés repetidos sem apagar o conteúdo editorial."""
    kept=[]
    for line in (text or "").splitlines():
        value=normalize(line)
        if re.match(r"(?i)^Disponibilizado\s*(?:-|em)?\s*\d{2}/\d{2}/\d{4}$",value): continue
        if re.match(r"(?i)^Di.rio da Justi.a Eletr.nico\s*-\s*MT\s*-\s*Ed\.",value): continue
        if re.match(r"(?i)^(?:Caderno de Anexos\s+)?P.gina\s+\d+\s+de\s+\d+$",value): continue
        kept.append(line)
    return "\n".join(kept)

def labeled_value(block, label, next_labels):
    following="|".join(re.escape(x) for x in next_labels)
    match=re.search(rf"(?is)\b{re.escape(label)}\s*:\s*(.*?)(?=(?:{following})\s*:|$)",block)
    return normalize(match.group(1)) if match else ""

def heading_contexts(full):
    """Mapeia a hierarquia editorial ativa em cada posição do diário."""
    events=[]; position=0
    state={"orgao":"","comarca":"","unidade":"","secao":""}
    for raw in full.splitlines(True):
        value=normalize(raw)
        if value and len(value)<=140:
            if re.match(r"(?i)^(?:TRIBUNAL DE JUSTI.A|FORO EXTRAJUDICIAL|COMARCAS)$",value):
                state={"orgao":value,"comarca":"","unidade":"","secao":""}
            elif re.match(r"(?i)^Comarca de .+",value):
                state["comarca"]=value; state["unidade"]=""; state["secao"]=""
            elif re.match(r"(?i)^(?:Diretoria do F.rum|Ger.ncia .+|Divis.o .+|Departamento .+|Coordenadoria .+|N.cleo .+|Cart.rio .+|Munic.pio de .+|Varas? .+|\d+.? Vara .+)",value):
                state["unidade"]=value; state["secao"]=""
            elif re.match(r"(?i)^(?:Edital|Decis.o|Portaria|Extrato|Intima..o|Despacho|Ato|Aviso)(?:\s*/.*)?$",value):
                state["secao"]=value
            else:
                position+=len(raw); continue
            events.append((position,state.copy()))
        position+=len(raw)
    return events

def context_at(events,position):
    active={"orgao":"","comarca":"","unidade":"","secao":""}
    for event_position,state in events:
        if event_position>position: break
        active=state
    return active

def split_publications(pages):
    if domsc_parser.recognizes(pages):
        return domsc_parser.split(pages)
    if tcepr_parser.recognizes(pages):
        return tcepr_parser.split(pages)
    if cnj_parser.recognizes(pages):
        return cnj_parser.split(pages)
    cleaned_pages=[(number,clean_page_text(text)) for number,text in pages]
    full="\n".join(t for _,t in cleaned_pages)
    # Perfis conhecidos: "N. 0000000-... - classe" e o formato TJMT
    # administrativo "Processo: (código) 000-00.0000.811.0000 Classe:...".
    pattern=re.compile(
        r"(?mi)(?:^\s*N\.\s*(?P<numero_n>[0-9]{1,7}-[0-9]{2}\.[0-9]{4}\.[0-9A-Za-z]+\.[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)?)\s*-\s*(?P<classe_n>[^\n]+)"
        r"|^[ \t]*Processo\s*:\s*(?:\((?P<codigo>\d+)\)\s*)?(?P<numero_p>[0-9]{1,7}-[0-9]{2}\.[0-9]{4}\.(?:8\.11|811)\.[0-9]{4})"
        r"|^\s*(?P<ato>(?:PORTARIA|EDITAL|TERMO(?:\s+DE)?|PROVIMENTO|PEDIDO\s+DE)[^\n]{3,180}(?:N(?:\.|�|�|\s)|CIA\s|ID\s*:)[^\n]*))"
    )
    matches=list(pattern.finditer(full))
    contexts=heading_contexts(full)
    records=[]

    for i,m in enumerate(matches):
        block=full[m.start():matches[i+1].start() if i+1<len(matches) else len(full)]
        # Uma relação de processos termina quando o jornal muda de caderno/seção,
        # mesmo que não haja outro "Processo:" depois do último item.
        if m.group("numero_n") or m.group("numero_p"):
            section=re.search(r"(?mi)^\s*(?:FORO EXTRAJUDICIAL|CADERNO DE ANEXOS|TRIBUNAL DE JUSTI.A|COMARCAS)\s*$",block[120:])
            if section: block=block[:120+section.start()]
        ato=normalize(m.group("ato"))
        process=normalize(m.group("numero_n") or m.group("numero_p"))
        if not process and ato:
            identifier=re.search(r"[0-9]{1,7}-[0-9]{2}\.[0-9]{4}\.(?:8\.11|811)\.[0-9]{4}",block)
            process=identifier.group(0) if identifier else ato[:120]
        classe=normalize(m.group("classe_n") or labeled_value(block,"Classe",["Objeto","Polo Ativo","Polo Passivo","Vitima(s)","Vítima(s)","Advogado(s)"]))
        if ato: classe=ato.split(" ",1)[0].title()
        if not classe: classe="Não identificada"

        header="Não identificado"
        hierarchy=context_at(contexts,m.start())
        headings=[hierarchy[k] for k in ("orgao","comarca","unidade","secao") if hierarchy[k]]
        if headings: header=" | ".join(headings)
        else:
            hm=re.search(r"(?is)(PODER JUDICI.RIO.*?)(?=PROCESSO:)", block)
            if hm: header=normalize(hm.group(1))

        tipo="Ato administrativo" if ato else "Publicação processual"
        low=block.lower()
        if "intimação" in low or "intimem-se" in low: tipo="Intimação"
        elif "acórdão" in low: tipo="Acórdão"
        elif "decisão" in low: tipo="Decisão"
        elif "despacho" in low: tipo="Despacho"

        vara="Não consta"
        vp=[
            r"(?i)\b\d+\s*[ªaºo]?\s*Vara(?:\s+(?:da|de|do|dos|das))?\s+[A-ZÀ-Ú][^\n,.;]{0,100}",
            r"(?i)\bVara\s+(?:da|de|do|dos|das)\s+[A-ZÀ-Ú][^\n,.;]{0,100}"
        ]
        for p in vp:
            x=re.search(p,block)
            if x:
                vara=normalize(x.group(0)); break
        if vara=="Não consta" and hierarchy["unidade"]: vara=hierarchy["unidade"]

        comarca="Não consta"
        cp=[
            r"(?i)\bComarca\s+(?:de|da|do)\s+([A-ZÀ-Ú][^\n,.;]{1,80})",
            r"(?i)\b(?:de|em)\s+([A-ZÀ-Ú][A-Za-zÀ-Ú\s]{2,60})/(?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MG|MS|MT|PA|PB|PE|PI|PR|RJ|RN|RO|RR|RS|SC|SE|SP|TO)\b"
        ]
        for p in cp:
            x=re.search(p,block)
            if x:
                comarca=normalize(x.group(1)); break
        if comarca=="Não consta" and hierarchy["comarca"]:
            comarca=re.sub(r"(?i)^Comarca de\s+","",hierarchy["comarca"])

        parties=[]
        for label in ["Polo Ativo","Polo Passivo"]:
            value=labeled_value(block,label,["Polo Ativo","Polo Passivo","Vitima(s)","Vítima(s)","Advogado(s)","Objeto"])
            if value: parties.append(f"{label}: {value}")
        for key in ["A:","R:"]:
            for x in re.finditer(re.escape(key)+r"\s*([^\n]+)",block,re.I): parties.append(normalize(key+" "+x.group(1)))
        parties=list(dict.fromkeys(parties))

        lawyer_lines=[]
        labeled_lawyer=labeled_value(block,"Advogado(s)",["Processo"])
        if labeled_lawyer: lawyer_lines.append(labeled_lawyer)
        for line in block.splitlines():
            if re.search(r"Adv\(s\)",line,re.I):
                lawyer_lines.append(normalize(line))
        lawyer_lines=list(dict.fromkeys(lawyer_lines))

        oabs=re.findall(r"\b[A-Z]{2}(?:[A-Z])?\d{3,7}(?:-[A-Z])?\b",block)
        oabs=list(dict.fromkeys(oabs))

        first_page=find_page(full,cleaned_pages,m.start())
        last_page=find_page(full,cleaned_pages,m.start()+len(block.rstrip())-1)
        source_pages=list(range(first_page,last_page+1)) if first_page and last_page else []
        suspicious=[number for number,text in pages if number in source_pages and not text.strip()]
        structural_reasons=["Início reconhecido pelo padrão do diário"]
        structural_score=40
        if len(re.sub(r"\D","",process))==20:
            structural_score+=20; structural_reasons.append("Número processual com 20 dígitos")
        if classe!="Não identificada":
            structural_score+=10; structural_reasons.append("Classe ou ato identificado")
        if parties or lawyer_lines:
            structural_score+=10; structural_reasons.append("Campos de partes ou advogados identificados")
        if i+1<len(matches):
            structural_score+=10; structural_reasons.append("Limite seguinte reconhecido")
        if headings:
            structural_score+=10; structural_reasons.append("Contexto editorial identificado")
        if suspicious: structural_score=min(structural_score,60)
        records.append({
            "parser":"regras_legadas",
            "parser_version":"2.0",
            "confianca_estrutural":structural_score,
            "motivos_estrutura":structural_reasons,
            "paginas_origem":source_pages,
            "paginas_suspeitas":suspicious,
            "conteudo_original":block,
            "processo":process,
            "classe":classe,
            "cabecalho":header,
            "orgao":hierarchy["orgao"] or "Não identificado",
            "unidade":hierarchy["unidade"] or "Não identificada",
            "secao":hierarchy["secao"] or "Não identificada",
            "comarca":comarca,
            "vara":vara,
            "tipo":tipo,
            "partes":" | ".join(parties) if parties else "Não identificado",
            "advogados":" | ".join(lawyer_lines) if lawyer_lines else "Não identificado",
            "oabs":", ".join(oabs) if oabs else "Não identificado",
            "pagina":find_page(full,cleaned_pages,m.start()),
            "conteudo":normalize(block)
        })
    return records

# Rotas da API e entrega dos arquivos da interface.
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} - {fmt % args}")

    def json_response(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/modo": return self.json_response({"modo":delivery_mode()})
        if path=="/api/historico":
            recover_test_jobs()
            history=list(delivery_history().values())
            known={x["envio_id"] for x in history}
            history.extend({**x,"modo":"real"} for x in load_auto_sends().values() if x.get("envio_id") not in known)
            return self.json_response({"envios":[{k:v for k,v in x.items() if k!="payload"} for x in sorted(history,key=lambda x:x.get("criado_em",0),reverse=True)]})
        if path.startswith("/api/visualizar/"):
            job=delivery_history().get(path.rsplit("/",1)[-1])
            if not job: return self.json_response({"erro":"Conteúdo indisponível para este registro antigo."},404)
            from html import escape
            payload=job.get("payload",{})
            raw=(payload.get("html") or "<pre>"+escape(payload.get("corpo",""))+"</pre>").encode("utf-8")
            self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Security-Policy","sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:")
            self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if path=="/api/health":
            import sys
            mode="smtp" if os.getenv("SMTP_HOST") else ("outlook" if os.name=="nt" else "indisponivel")
            return self.json_response({"ok":True,"api":"clipping-juridico","python":sys.version.split()[0],"smtp":bool(os.getenv("SMTP_HOST")),"email_mode":mode,"destino_padrao":DEFAULT_RECIPIENT,"limiar_envio_automatico":AUTO_SEND_THRESHOLD})
        if path=="/api/email-status": return self.json_response(email_connection_status())
        if path=="/api/clientes": return self.json_response({"clientes":load_clients()})
        if path.startswith("/api/envios/"):
            job_id=path.rsplit("/",1)[-1]
            with EMAIL_JOBS_LOCK: job=EMAIL_JOBS.get(job_id)
            if not job:
                job=next((item for item in load_auto_sends().values() if item.get("envio_id")==job_id),None)
                if job and job.get("status") in ("na_fila","enviando"):
                    job={**job,"status":"erro","erro":"O servidor foi reiniciado antes de confirmar o envio. Reanalise o PDF para tentar novamente."}
            if not job: job=delivery_history().get(job_id)
            if not job: return self.json_response({"erro":"Envio não encontrado. Reanalise o PDF para verificar o envio."},404)
            return self.json_response({"id":job_id,**confirm_outlook_sent(job_id,job)})
        if path=="/": path="/index.html"
        fp=(FRONTEND/path.lstrip("/")).resolve()
        if not str(fp).startswith(str(FRONTEND.resolve())) or not fp.exists():
            self.send_error(404); return
        types={".html":"text/html; charset=utf-8",".css":"text/css; charset=utf-8",".js":"application/javascript; charset=utf-8"}
        data=fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",types.get(fp.suffix,"application/octet-stream"))
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path=urlparse(self.path).path
        if path=="/api/revisao":
            try:
                data=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
                if data.get("acao") not in ("bloquear","restaurar","enviar"): raise ValueError("Ação inválida.")
                return self.json_response(review_publication(data.get("id"),data["acao"]))
            except Exception as exc: return self.json_response({"erro":str(exc)},409)
        if path=="/api/modo":
            try:
                mode=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0")))).get("modo")
                if mode not in ("teste","real"): raise ValueError("Modo inválido")
                DATA_DIR.mkdir(exist_ok=True)
                SETTINGS_FILE.write_text(json.dumps({"modo":mode}),encoding="utf-8")
                return self.json_response({"modo":mode})
            except Exception as exc: return self.json_response({"erro":str(exc)},400)
        if path.startswith("/api/repetir/"):
            with DELIVERY_LOCK:
                old=delivery_history().get(path.rsplit("/",1)[-1])
                if not old or old.get("status")!="erro" or old.get("nova_tentativa"):
                    return self.json_response({"erro":"Somente falhas sem nova tentativa podem ser repetidas."},409)
                if old.get("modo")!=delivery_mode():
                    return self.json_response({"erro":"Selecione o modo correspondente antes de repetir."},409)
                if old.get("payload",{}).get("revisao_id"):
                    try: return self.json_response(review_publication(old["payload"]["revisao_id"],"enviar",old["payload"]),202)
                    except ValueError as exc: return self.json_response({"erro":str(exc)},409)
                def link_retry(new_id):
                    with AUTO_SEND_LOCK:
                        history=load_auto_sends()
                        for item in history.values():
                            if item.get("envio_id")==old["envio_id"]:
                                item.update(envio_id=new_id,status="na_fila",erro="")
                        save_auto_sends(history)
                job_id=queue_email(old["payload"],link_retry)
                write_delivery(old["envio_id"],{"nova_tentativa":job_id})
                return self.json_response({"envio_id":job_id},202)

        if path=="/api/clientes":
            try:
                clients=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"[]")
                if not isinstance(clients,list): raise ValueError("Lista de clientes inválida.")
                save_clients(clients); return self.json_response({"ok":True,"clientes":clients})
            except Exception as e: return self.json_response({"erro":str(e)},400)
        if path=="/api/rascunho":
            try:
                payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
                if load_reviews().get(payload.get("revisao_id"),{}).get("bloqueada"):
                    raise ValueError("Publicação descartada: rascunho bloqueado.")
                msg=EmailMessage()
                msg["To"]=payload.get("para",""); msg["Subject"]=payload.get("assunto","")
                msg["X-Unsent"]="1"
                msg.set_content(payload.get("corpo", ""))
                msg.add_alternative(render_card({"nome":payload.get("cliente_nome")},payload.get("publicacao") or {}),subtype="html")
                content=msg.as_bytes()
                self.send_response(200); self.send_header("Content-Type","message/rfc822")
                self.send_header("Content-Length",str(len(content))); self.end_headers(); self.wfile.write(content)
                return
            except Exception as e: return self.json_response({"erro":str(e)},400)
        if path=="/api/enviar":
            try:
                payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
                for field in ("para","assunto","corpo"):
                    if not normalize(payload.get(field)): raise ValueError(f"Campo {field} é obrigatório.")
                if payload.get("confirmado") is not True: raise ValueError("A conferência precisa ser confirmada antes do envio.")
                if isinstance(payload.get("publicacao"),dict):
                    payload["html"]=render_card({"nome":payload.get("cliente_nome")},payload["publicacao"])
                if payload.get("revisao_id"):
                    return self.json_response({"ok":True,**review_publication(payload["revisao_id"],"enviar",payload)},202)
                job_id=queue_email(payload)
                return self.json_response({"ok":True,"status":"na_fila","envio_id":job_id,"mensagem":"Envio colocado na fila."},202)
            except Exception as e: return self.json_response({"erro":str(e)},400)
        if path!="/api/analisar":
            return self.json_response({"erro":"Rota não encontrada."},404)
        try:
            mode=delivery_mode()
            filename,pdf_bytes=parse_multipart(self)
            if not pdf_bytes: raise ValueError("O PDF recebido está vazio.")
            pages=extract_pages(pdf_bytes)
            if not any(text.strip() for _,text in pages):
                raise ValueError("Este PDF não tem texto extraível. Se for digitalizado, aplique reconhecimento de texto (OCR) antes de adicionar o arquivo.")
            extracted=split_publications(pages)
            if not extracted:
                raise ValueError("Não foi possível separar as publicações neste formato de PDF. Nenhum envio foi realizado; o documento precisa de revisão.")
            clients=load_clients()
            auto_history=load_auto_sends()
            auto_queued=[]
            records=[]
            for record in extracted:
                matches=matching_clients(record,clients)
                if not matches: continue
                matches.sort(key=lambda item:item["score"],reverse=True)
                best=matches[0]; client=best["cliente"]
                record["cliente_ids"]=[str(item["cliente"].get("id")) for item in matches]
                record["cliente_id_sugerido"]=str(client.get("id",""))
                record["confianca"]=best["score"]
                record["motivos_confianca"]=best["motivos"]
                record["arquivo_origem"]=filename
                record["capturada_em"]=time.time()
                record["correspondencias"]=[{"cliente_id":str(item["cliente"].get("id","")),"score":item["score"],"motivos":item["motivos"],"identificador_forte":item.get("identificador_forte",False)} for item in matches]
                # Nomes sobrepostos sem evidência que os diferencie exigem conferência.
                best_name=normalize_search(client.get("nome"))
                record["correspondencia_ambigua"]=any(
                    best_name and normalize_search(item["cliente"].get("nome"))
                    and (best_name in normalize_search(item["cliente"].get("nome")) or normalize_search(item["cliente"].get("nome")) in best_name)
                    and item.get("identificador_forte",False)==best.get("identificador_forte",False)
                    for item in matches[1:]
                )
                email=DEFAULT_RECIPIENT
                blockers=auto_send_blockers(best,record,email)
                key=auto_send_key(client,record,mode)
                record["revisao_id"]=key
                with REVIEW_LOCK:
                    reviews=load_reviews()
                    blocked=reviews.get(key,{}).get("bloqueada",False)
                    record["bloqueada"]=blocked
                    reviews[key]={"bloqueada":blocked,"modo":mode,"elegivel":not blockers,"cliente":client,"registro":dict(record),"payload":{**publication_email(client,record),"cliente_nome":client.get("nome","")}}
                    save_reviews(reviews)
                with REVIEW_LOCK:
                    existing=existing_auto_send(load_auto_sends().get(key))
                    if existing:
                        record["envio_automatico"]=existing
                    elif load_reviews().get(key,{}).get("bloqueada"):
                        record["bloqueada"]=True
                        record["envio_automatico"]={"status":"descartada"}
                    elif should_auto_send(best["score"],email,best,record):
                        record["envio_automatico"]=review_publication(key,"enviar")
                        auto_queued.append(record["envio_automatico"]["envio_id"])
                    else:
                        record["revisao_manual"]={"motivo":" · ".join(blockers),"motivos":blockers}
                records.append(record)
            return self.json_response({
                "modo":mode,
                "arquivo":filename,
                "paginas":len(pages),
                "publicacoes":len(records),
                "publicacoes_extraidas":len(extracted),
                "diagnostico":{"parser":extracted[0].get("parser","regras_legadas"),"parser_version":extracted[0].get("parser_version","2.0"),"paginas_com_texto":sum(bool(text.strip()) for _,text in pages),"paginas_sem_texto":[number for number,text in pages if not text.strip()],"aviso":"Pontuações heurísticas; não representam probabilidade estatística. Páginas sem texto exigem revisão; OCR não está habilitado."},
                "envios_automaticos":len(auto_queued),
                "revisao_manual":sum(1 for record in records if record.get("revisao_manual")),
                "registros":records
            })
        except Exception as e:
            print("[ERRO]",repr(e))
            return self.json_response({"erro":str(e)},500)

# Inicialização do servidor e do monitor de entregas.
if __name__=="__main__":
    import sys
    print(f"Sistema de Clipping Jurídico v3")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Acesse: http://localhost:{PORT}")
    threading.Thread(target=monitor_email_delivery,daemon=True,name="email-monitor").start()
    ThreadingHTTPServer(("localhost",PORT),Handler).serve_forever()

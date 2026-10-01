SISTEMA DE CLIPPING JURÍDICO V3

Esta versão remove a dependência do módulo cgi e usa um parser multipart compatível
com Python 3.13/3.14. Também inclui tratamento de erro na API.

REQUISITOS
- Windows
- Python 3.10 ou superior
- VS Code

EXECUÇÃO
1. Abra esta pasta no VS Code.
2. Abra o terminal em backend.
3. Se houver um .venv antigo:
   deactivate
   Remove-Item -Recurse -Force .venv
4. Crie:
   python -m venv .venv
5. Ative:
   .venv\Scripts\Activate.ps1
6. Instale:
   python -m pip install -r requirements.txt
7. Rode:
   python server.py
8. Abra:
   http://localhost:8000

TESTE DA API
http://localhost:8000/api/health
Deve retornar {"ok":true,...}

Depois envie o PDF pela tela.

FLUXO
1. Cadastre os clientes e os termos de reconhecimento (nome, variantes, OAB etc.).
2. Envie o Diário. Somente publicações dos clientes cadastrados entram na captura.
3. Marque a confirmação e envie ou abra um rascunho no programa de e-mail.

FORMATOS DE JORNAL RECONHECIDOS
- Publicações iniciadas por "N." e número processual.
- Relações do TJMT iniciadas por "Processo:", com Classe, Objeto, polos e advogados.
- Atos administrativos identificados por Portaria, Edital, Termo, Provimento ou Pedido.
- Mudanças de caderno/seção, cabeçalhos, rodapés e assinaturas são usadas para limitar o conteúdo.

MONITORADOS E CONFIANÇA
- Tipos: pessoa, empresa, advogado, processo ou termo.
- Identificação por nome, variações, CPF/CNPJ, OAB, processo e palavras-chave.
- O e-mail é opcional no cadastro e obrigatório apenas para enviar a publicação.
- Cada ocorrência informa a pontuação e os motivos da correspondência.
- Faixas sugeridas: 90-100 forte; 70-89 revisar; 40-69 possível correspondência.
- O envio automático ocorre após a análise para correspondências de 75 a 100 pontos, sempre para henriquefelipe1520@gmail.com. Não exige identificador forte nem pontuação estrutural mínima, conforme configuração solicitada pelo usuário.
- O destinatário padrão de todos os clientes é henriquefelipe1520@gmail.com; novos clientes também o utilizam quando não houver outro e-mail informado.
- Nome, variações e palavras-chave sem identificador forte ficam limitados a 84/100; resultados de 75 a 84 também são enviados. As pontuações são heurísticas, não probabilidades.
- O sistema registra os envios automáticos para não reenviar a mesma publicação ao importar novamente o mesmo diário.

ENVIO AUTOMÁTICO (OPCIONAL)
Configure SMTP_HOST, SMTP_PORT, SMTP_FROM, SMTP_USER e SMTP_PASSWORD antes de
iniciar o servidor. SMTP_TLS aceita 1 (padrão) ou 0.
No Windows, quando o SMTP não estiver configurado, o sistema usa automaticamente
o perfil autenticado no Outlook clássico e envia sem abrir uma janela de rascunho.
O corpo do e-mail inclui cabeçalho/origem, assunto, processo, comarca, unidade,
tipo, página e o conteúdo integral revisado da publicação.
Os envios são colocados em uma fila local para que a solicitação responda em menos
de 5 segundos. A tela acompanha a execução e só confirma depois do envio real.

MELHORIAS DE RECONHECIMENTO — SETEMBRO/2026
- Correspondência calculada no servidor e exibida pelo navegador sem recálculo divergente.
- A busca utiliza apenas campos editoriais, sem nomes de arquivos ou motivos anteriores.
- Processo cadastrado corresponde ao número principal, normalizado para 20 dígitos.
- CPF/CNPJ aceitam pontuação; OAB exige UF e número completos nas formas suportadas.
- Menções a Processo: no meio de uma linha não iniciam uma nova publicação.
- Números isolados no conteúdo são preservados.
- Cada resultado inclui texto original do bloco, arquivo, páginas de origem, versão das regras,
  pontuação estrutural, evidências e motivos de revisão; disponíveis na exportação JSON.
- A importação informa páginas sem texto extraível. OCR não está implementado.
- Após alterar um monitorado, reanalise o PDF para atualizar as evidências.
- O parser continua baseado nos formatos já suportados; não há detecção universal de tribunais.
- Os limites estruturais são conservadores e precisam ser calibrados com amostras conferidas.

TESTES (sem envio real de e-mail)
Na pasta backend: .venv\Scripts\python.exe -m unittest discover -v

RECONHECIMENTO DO DIÁRIO DO CNJ
- Perfil identificado pela capa do Diário da Justiça do Conselho Nacional de Justiça.
- Usa coordenadas e negrito para separar títulos de publicações e referências no corpo.
- Preserva a hierarquia Secretaria Geral / Secretaria Processual / PJE / INTIMAÇÃO.
- Publicações continuam entre páginas até o próximo título ou mudança de seção.
- Preserva edição, data e página entre continuações, conforme o exemplo manual fornecido.
- Preserva assinaturas e notas; fim sem indício de encerramento reduz a pontuação estrutural, sem bloquear a política de envio por correspondência.
- Editor e e-mail exibem o cabeçalho em linhas. Baixar publicação TXT reúne cabeçalho e íntegra.
- JSON inclui publicacao_integral, trechos_origem e limites com página e coordenadas PDF.
- Validado com DJ191/2026: 5 portarias e 10 publicações processuais.
- Outros modelos mantêm as regras anteriores; este perfil não garante suporte universal.
- Reinicie o servidor e reimporte o PDF para aplicar o novo reconhecimento.
- Validação da amostra, sem e-mail: backend\.venv\Scripts\python.exe tools\validar_cnj191.py CAMINHO_PDF CAMINHO_EXEMPLO_MANUAL

RECUPERAÇÃO DE ENVIO PELO OUTLOOK
- O servidor verifica pendências a cada 20 segundos, mesmo com o navegador fechado.
- Após 60 segundos, uma mensagem ainda na Caixa de Saída pode ser reativada até 3 vezes, sem criar cópias.
- O token da mensagem identifica novos envios; pendências antigas usam assunto e destinatário.
- Pendência acima de 3 minutos sem confirmação mostra orientação para verificar o Outlook.
- O status enviado exige confirmação nos Itens Enviados; recebimento é verificado no destino.
- A mesma publicação já enviada não é reenviada ao reimportar o PDF.

MODO DE TESTE E HISTÓRICO
- Selecione Teste ou Real na tela. O modo fica salvo entre reinícios.
- Teste captura o mesmo corpo/HTML na caixa local integrada ao histórico, sem SMTP, Outlook ou Mailpit.
- Real mantém o envio ao destinatário autorizado, conforme faixa de 75 a 100 pontos.
- Cada mensagem mantém o modo em que entrou na fila; trocar o seletor não muda mensagens já enfileiradas.
- Histórico mostra modo, assunto, data, estado, erros e visualização do e-mail.
- Tentar novamente está disponível para falhas; o modo selecionado deve coincidir com o registro.
- Registros antigos podem não ter o conteúdo salvo para visualização.
- Os registros de teste não bloqueiam o envio real da mesma publicação.

ENVIO AUTOMÁTICO E DESCARTE
- A análise envia automaticamente correspondências de 75 a 100 pontos no modo selecionado, sem reenviar publicações já registradas como enviadas ou em andamento.
- Abaixo de 75 pontos, o X vermelho sinaliza que a publicação não é de um cliente. A marcação pode ser desfeita. Essas publicações não entram no envio automático.
- O descarte é salvo por publicação, cliente e modo e permanece ao reanalisar o PDF.
- O envio individual continua disponível para conferência manual. Publicações descartadas permanecem bloqueadas no envio automático e individual.
- A marca verde indica envio real confirmado. Capturas de teste e mensagens aguardando Outlook não recebem essa marca.
- O X fica indisponível para mensagens cujo envio já foi iniciado ou concluído.

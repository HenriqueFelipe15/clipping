"""Card HTML compartilhado pelos envios manual e automático."""
from datetime import datetime
from html import escape


def render_card(client, record):
    def value(key, fallback="Não informado"):
        return escape(str(record.get(key) or fallback))
    name = escape(str(client.get("nome") or "Cliente"))
    date = value("data", datetime.now().strftime("%d/%m/%Y"))
    cells = []
    for index, (label, key, icon) in enumerate([("PROCESSO", "processo", "▤"), ("COMARCA", "comarca", "⌖"), ("VARA", "vara", "⚖")]):
        border = "border-left:1px solid #e8f0f8;" if index else ""
        cells.append(f'''<td class="field" valign="top" style="{border}padding:4px 20px;width:33.33%;">
        <div style="font-size:10px;letter-spacing:1.3px;color:#73859c;margin-bottom:10px;">{label}</div>
        <table role="presentation" cellpadding="0" cellspacing="0"><tr><td valign="top"><span style="display:inline-block;background:#eff6fd;border-radius:8px;padding:7px 10px;color:#3977ba;font-size:18px;">{icon}</span></td>
        <td style="padding-left:10px;font-size:14px;font-weight:600;color:#192f4c;word-break:break-word;">{value(key)}</td></tr></table></td>''')
    header = value("cabecalho").replace("\n", "<br>")
    content = value("conteudo", "Conteúdo não informado").replace("\n", "<br>")
    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Publicação processual</title><style>@media(max-width:600px){{.field{{display:block!important;width:auto!important;border-left:0!important;padding:12px 0!important}}.outer{{padding:16px!important}}.footer-cell{{display:block!important;width:auto!important;padding:10px 0!important}}}}</style></head>
    <body style="margin:0;background:#f5f8fc;font-family:Arial,Helvetica,sans-serif;color:#192f4c;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td class="outer" style="padding:40px 24px;">
    <table role="presentation" align="center" width="100%" cellpadding="0" cellspacing="0" style="max-width:960px;background:#fff;border:1px solid #e6eef7;border-radius:16px;box-shadow:0 3px 14px #192f4c08;">
    <tr><td style="padding:28px 28px 24px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td style="width:48px;"><span style="display:inline-block;border-radius:50%;padding:10px 13px;background:#edf5fe;color:#3977ba;font-size:20px;">&#128100;&#65038;</span></td>
    <td style="padding-left:12px;"><div style="font-size:19px;font-weight:600;">{name}</div><div style="font-size:10px;letter-spacing:1.5px;color:#73859c;margin-top:6px;">CLIENTE</div></td>
    <td align="right"><span style="display:inline-block;background:#edf5fe;border-radius:20px;padding:9px 12px;color:#3977ba;font-size:10px;font-weight:600;letter-spacing:.6px;">● &nbsp; NOVA PUBLICAÇÃO</span> <span style="display:inline-block;padding:8px 0 8px 12px;font-size:12px;color:#73859c;">{date}</span></td>
    </tr></table></td></tr>
    <tr><td style="padding:0 8px 26px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{''.join(cells)}</tr></table></td></tr>
    <tr><td style="padding:0 28px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e8f0f8;"><tr>
    <td class="footer-cell" style="padding:22px 0;"><table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="font-size:25px;color:#3977ba;padding-right:14px;">&#128227;&#65038;</td><td><div style="font-size:14px;font-weight:600;">Nova publicação processual</div><div style="font-size:12px;color:#73859c;margin-top:6px;">Foi identificada uma nova publicação no processo acima.</div></td></tr></table></td>
    <td class="footer-cell" align="right" style="padding:22px 0 22px 16px;"><span style="display:inline-block;color:#73859c;font-size:12px;line-height:1.6;">Conteúdo integral abaixo ↓</span></td>
    </tr></table></td></tr></table>
    <div id="publicacao" style="max-width:904px;margin:28px auto 0;padding:24px 28px;background:#fff;border:1px solid #e6eef7;border-radius:12px;">
    <h2 style="font-size:17px;margin:0 0 14px;">Publicação integral</h2>
    <div style="font-size:12px;color:#73859c;line-height:1.8;margin-bottom:18px;">{header}<br>Tipo: {value("tipo")} · Página: {value("pagina")}</div>
    <div style="font-size:14px;line-height:1.8;overflow-wrap:anywhere;">{content}</div></div>
    </td></tr></table></body></html>'''

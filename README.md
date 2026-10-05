# Cortes YouTube (GitHub Actions)

Vídeo do YouTube → Gemini escolhe os trechos → corte 9:16 com legenda animada → upload como Short.
Roda grátis nos servidores do GitHub; o n8n dispara e recebe o resultado.

## Secrets (Settings › Secrets and variables › Actions)

| Secret | De onde vem |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey (plano gratuito) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | `python autorizar_youtube.py client_secret.json` (ver abaixo) |
| `YT_COOKIES` | cookies.txt (formato Netscape) de uma conta Google **descartável** — evita o bloqueio de download |
| `GROQ_API_KEY` | opcional, https://console.groq.com/keys — reserva grátis quando o Gemini está sobrecarregado |
| `CALLBACK_TOKEN` | qualquer senha longa; o n8n confere no header `x-token` |

Variáveis opcionais (aba *Variables*): `GEMINI_MODEL` (padrão `gemini-flash-latest`), `WHISPER_MODEL` (padrão `small`), `CALLBACK_URL`.

### OAuth do YouTube
1. Google Cloud Console → novo projeto → ative **YouTube Data API v3**.
2. Tela de consentimento OAuth → tipo *Externo* → **publique o app (Em produção)**. Em modo *Teste* o refresh token expira em 7 dias.
3. Credenciais → *ID do cliente OAuth* → tipo **App para computador** → baixe o JSON como `client_secret.json`.
4. `pip install google-auth-oauthlib && python autorizar_youtube.py client_secret.json` → entre com a conta dona do canal.

> Projetos de API não auditados só conseguem subir vídeos **privados**. Para publicar direto como público, peça a auditoria gratuita em https://support.google.com/youtube/contact/yt_api_form. Até lá, o fluxo sobe privado e você publica pelo Studio.

## Disparo

```bash
curl -X POST https://api.github.com/repos/DONO/cortes-youtube/dispatches \
  -H "Authorization: Bearer GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  -d '{"event_type":"corte","client_payload":{"video_id":"XXXXXXXXXXX","tema":"finanças","num_cortes":"2","publicar":"sim","privacidade":"private","callback_url":"https://.../webhook/cortes-retorno"}}'
```

Campos do `client_payload`: `video_id` (obrigatório), `tema`, `num_cortes` (1), `publicar` (`nao`/`sim`), `privacidade` (`private`/`unlisted`/`public`), `formato` (`blur`/`crop`), `idioma` (`pt`), `callback_url`.

O token do GitHub é um *fine-grained token* com acesso só a este repositório e permissão **Contents: read and write**.

## Teste local

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python pipeline.py --video-id jNQXAC9IVRw --trechos 0-18 --idioma en --dur-min 5
```

`--trechos` pula o Gemini; `--arquivo video.mp4` pula o download. Os cortes ficam em `saida/`.

## Limites do plano grátis
- GitHub Actions: 2.000 min/mês em repositório privado (~5–8 min por corte).
- YouTube Data API: 10.000 unidades/dia → ~6 uploads/dia (1.600 cada); cada busca do n8n gasta 100.
- Gemini Flash gratuito: limite por minuto/dia; o script tenta de novo em caso de 429.

---

# Notícia → Vídeo (`noticia.yml` + `noticia.py`)

E-mail de notícia → Gemini escreve o roteiro em cenas → **Cloudflare Workers AI (FLUX.1 schnell)** gera uma imagem por cena com contexto brasileiro → **Edge TTS** narra em pt-BR → ffmpeg monta o 9:16 com zoom lento e legenda palavra a palavra. Tudo grátis.

Secrets extras: `CF_ACCOUNT_ID` e `CF_API_TOKEN` (Cloudflare › AI › Workers AI › *Use REST API* — token com permissão **Workers AI: Read/Edit**). Reaproveita `GEMINI_API_KEY`, `GROQ_API_KEY`, `YT_*` e `CALLBACK_TOKEN`.

Variáveis opcionais: `VOZ` (`pt-BR-AntonioNeural`, `pt-BR-FranciscaNeural`, `pt-BR-ThalitaMultilingualNeural`), `VELOCIDADE` (`+10%`), `MARCA_NOTICIA` (marca d'água), `CF_MODELO`, `CALLBACK_URL_NOTICIA`.

Disparo (o n8n faz isso — fluxo pronto para importar em `n8n/noticia-video.json`):

```bash
curl -X POST https://api.github.com/repos/DONO/cortes-youtube/dispatches \
  -H "Authorization: Bearer GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  -d '{"event_type":"noticia","client_payload":{"titulo":"...","texto":"...","url":"https://...","publicar":"nao","callback_url":"https://.../webhook/noticia-retorno"}}'
```

Teste local: `python noticia.py --titulo "..." --texto-arquivo noticia.txt` (ou `--roteiro roteiro.json` para pular o LLM). Sem as chaves da Cloudflare ele usa fundo liso no lugar das imagens. O vídeo sai em `saida/noticia.mp4` e as imagens ficam nos Artifacts do run.

Limites: FLUX schnell gasta poucos neurons por imagem — os 10 mil/dia grátis dão para dezenas de imagens (~6 por vídeo). Cada vídeo leva ~3–5 min de Actions.

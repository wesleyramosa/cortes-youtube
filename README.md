# Cortes YouTube (GitHub Actions)

VÃ­deo do YouTube â†’ Gemini escolhe os trechos â†’ corte 9:16 com legenda animada â†’ upload como Short.
Roda grÃ¡tis nos servidores do GitHub; o n8n dispara e recebe o resultado.

## Secrets (Settings â€º Secrets and variables â€º Actions)

| Secret | De onde vem |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey (plano gratuito) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | `python autorizar_youtube.py client_secret.json` (ver abaixo) |
| `YT_COOKIES` | cookies.txt (formato Netscape) de uma conta Google **descartÃ¡vel** â€” evita o bloqueio de download |
| `CALLBACK_TOKEN` | qualquer senha longa; o n8n confere no header `x-token` |

VariÃ¡veis opcionais (aba *Variables*): `GEMINI_MODEL` (padrÃ£o `gemini-2.5-flash`), `WHISPER_MODEL` (padrÃ£o `small`), `CALLBACK_URL`.

### OAuth do YouTube
1. Google Cloud Console â†’ novo projeto â†’ ative **YouTube Data API v3**.
2. Tela de consentimento OAuth â†’ tipo *Externo* â†’ **publique o app (Em produÃ§Ã£o)**. Em modo *Teste* o refresh token expira em 7 dias.
3. Credenciais â†’ *ID do cliente OAuth* â†’ tipo **App para computador** â†’ baixe o JSON como `client_secret.json`.
4. `pip install google-auth-oauthlib && python autorizar_youtube.py client_secret.json` â†’ entre com a conta dona do canal.

> Projetos de API nÃ£o auditados sÃ³ conseguem subir vÃ­deos **privados**. Para publicar direto como pÃºblico, peÃ§a a auditoria gratuita em https://support.google.com/youtube/contact/yt_api_form. AtÃ© lÃ¡, o fluxo sobe privado e vocÃª publica pelo Studio.

## Disparo

```bash
curl -X POST https://api.github.com/repos/DONO/cortes-youtube/dispatches \
  -H "Authorization: Bearer GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  -d '{"event_type":"corte","client_payload":{"video_id":"XXXXXXXXXXX","tema":"finanÃ§as","num_cortes":"2","publicar":"sim","privacidade":"private","callback_url":"https://.../webhook/cortes-retorno"}}'
```

Campos do `client_payload`: `video_id` (obrigatÃ³rio), `tema`, `num_cortes` (1), `publicar` (`nao`/`sim`), `privacidade` (`private`/`unlisted`/`public`), `formato` (`blur`/`crop`), `idioma` (`pt`), `callback_url`.

O token do GitHub Ã© um *fine-grained token* com acesso sÃ³ a este repositÃ³rio e permissÃ£o **Contents: read and write**.

## Teste local

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python pipeline.py --video-id jNQXAC9IVRw --trechos 0-18 --idioma en --dur-min 5
```

`--trechos` pula o Gemini; `--arquivo video.mp4` pula o download. Os cortes ficam em `saida/`.

## Limites do plano grÃ¡tis
- GitHub Actions: 2.000 min/mÃªs em repositÃ³rio privado (~5â€“8 min por corte).
- YouTube Data API: 10.000 unidades/dia â†’ ~6 uploads/dia (1.600 cada); cada busca do n8n gasta 100.
- Gemini Flash gratuito: limite por minuto/dia; o script tenta de novo em caso de 429.

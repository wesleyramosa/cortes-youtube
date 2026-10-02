"""Rode UMA vez no seu PC para gerar o refresh token do canal de destino.

    pip install google-auth-oauthlib
    python autorizar_youtube.py client_secret.json

Abre o navegador, você entra com a conta DONA do canal, e o script imprime
os 3 valores para cadastrar como secrets no GitHub.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

arquivo = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(
    arquivo, scopes=["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
cfg = json.load(open(arquivo, encoding="utf-8"))
cfg = cfg.get("installed") or cfg.get("web")

print("\nCadastre estes secrets no GitHub (Settings > Secrets and variables > Actions):\n")
print("YT_CLIENT_ID     =", cfg["client_id"])
print("YT_CLIENT_SECRET =", cfg["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)

"""Rode UMA vez no seu PC para o GitHub Actions poder ler e gravar no seu Google Drive.

    pip install google-auth-oauthlib
    python autorizar_drive.py client_secret.json

Abre o navegador: escolha a conta dona das pastas de cortes. Se aparecer
"O Google não verificou este app", clique em Avançado > Acessar (o app é seu).
Imprime os 3 valores para cadastrar como secrets no GitHub.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

arquivo = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(
    arquivo, scopes=["https://www.googleapis.com/auth/drive"])
creds = flow.run_local_server(port=0, prompt="select_account consent", access_type="offline")

conta = build("drive", "v3", credentials=creds, cache_discovery=False).about().get(
    fields="user(emailAddress)").execute()["user"]["emailAddress"]

cfg = json.load(open(arquivo, encoding="utf-8"))
cfg = cfg.get("installed") or cfg.get("web")
print(f"\nDrive autorizado: {conta}")
print("\nCadastre estes secrets no GitHub (Settings > Secrets and variables > Actions):\n")
print("GD_CLIENT_ID     =", cfg["client_id"])
print("GD_CLIENT_SECRET =", cfg["client_secret"])
print("GD_REFRESH_TOKEN =", creds.refresh_token)

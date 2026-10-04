"""Rode UMA vez no seu PC para gerar o refresh token do canal de destino.

    pip install google-auth-oauthlib
    python autorizar_youtube.py client_secret.json

Abre o navegador: escolha a conta e, para canais de marca, o CANAL na lista.
O script confirma o nome do canal autorizado (CANAL_AUTORIZADO.txt) e imprime
os 3 valores para cadastrar como secrets no GitHub.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

arquivo = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(
    arquivo, scopes=["https://www.googleapis.com/auth/youtube.upload",
                     "https://www.googleapis.com/auth/youtube.readonly"])
# select_account força a tela de escolha, onde canais de marca aparecem separados.
creds = flow.run_local_server(port=0, prompt="select_account consent", access_type="offline")

canais = build("youtube", "v3", credentials=creds, cache_discovery=False).channels().list(
    part="snippet", mine=True).execute().get("items", [])
nomes = ", ".join(f"{c['snippet']['title']} ({c['id']})" for c in canais) or "nenhum canal"
with open("CANAL_AUTORIZADO.txt", "w", encoding="utf-8") as f:
    f.write(nomes + "\n")

cfg = json.load(open(arquivo, encoding="utf-8"))
cfg = cfg.get("installed") or cfg.get("web")
print(f"\nCanal autorizado: {nomes}")
print("\nCadastre estes secrets no GitHub (Settings > Secrets and variables > Actions):\n")
print("YT_CLIENT_ID     =", cfg["client_id"])
print("YT_CLIENT_SECRET =", cfg["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)

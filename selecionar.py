"""Escolhe, para cada canal de canais.json, o vídeo mais visto entre os últimos
uploads que ainda não foi cortado, e dispara o workflow `corte` para ele.

Os IDs já usados ficam em processados.txt (commitado pelo workflow).
"""
import json
import os
import subprocess
from pathlib import Path

CFG = json.loads(Path("canais.json").read_text(encoding="utf-8"))
FEITOS = Path("processados.txt")
feitos = set(FEITOS.read_text(encoding="utf-8").split()) if FEITOS.exists() else set()


def uploads(canal_id):
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(CFG["olhar_ultimos"]),
           f"https://www.youtube.com/channel/{canal_id}/videos"]
    if Path("cookies.txt").exists():
        cmd[1:1] = ["--cookies", "cookies.txt"]
    saida = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(saida).get("entries") or []


escolhidos = []
for canal in CFG["canais"]:
    try:
        videos = uploads(canal["id"])
    except subprocess.CalledProcessError as e:
        print(f"[{canal['nome']}] falhou ao listar: {e.stderr[-300:]}")
        continue
    candidatos = [v for v in videos
                  if v.get("id") not in feitos
                  and (v.get("duration") or 0) >= CFG["duracao_minima_s"]]
    if not candidatos:
        print(f"[{canal['nome']}] nenhum vídeo novo")
        continue
    v = max(candidatos, key=lambda x: x.get("view_count") or 0)
    print(f"[{canal['nome']}] {v['id']} — {v.get('title')} ({v.get('view_count')} views)")
    escolhidos.append((canal, v["id"]))

if os.environ.get("DRY_RUN"):
    raise SystemExit(f"DRY_RUN: {len(escolhidos)} vídeo(s) seriam disparados")

for canal, video_id in escolhidos:
    subprocess.run(["gh", "workflow", "run", "corte.yml", "--ref", os.environ.get("REF", "main"),
                    "-f", f"video_id={video_id}", "-f", f"tema={canal['tema']}",
                    "-f", f"num_cortes={CFG['cortes_por_video']}",
                    "-f", f"publicar={CFG['publicar']}", "-f", f"privacidade={CFG['privacidade']}",
                    "-f", f"formato={CFG['formato']}"], check=True)
    feitos.add(video_id)

FEITOS.write_text("\n".join(sorted(feitos)) + "\n", encoding="utf-8")
print(f"Disparados: {len(escolhidos)}")

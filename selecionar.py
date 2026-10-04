"""Agenda os próximos cortes: pega os próximos horários livres de canais.json,
escolhe vídeos dos canais (o mais visto ainda não usado, alternando canais)
e dispara o workflow `corte` com o horário de publicação de cada corte.

Estado commitado pelo workflow:
- processados.txt: vídeos já cortados (nunca repete)
- agendados.txt: horários já ocupados (rodar duas vezes não duplica)
"""
import json
import math
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CFG = json.loads(Path("canais.json").read_text(encoding="utf-8"))
FEITOS, AGENDADOS = Path("processados.txt"), Path("agendados.txt")
ler = lambda p: set(p.read_text(encoding="utf-8").split()) if p.exists() else set()
feitos, ocupados = ler(FEITOS), ler(AGENDADOS)


def proximos_horarios():
    """Próximos horários livres (hoje e amanhã), com folga para o processamento."""
    fuso = ZoneInfo(CFG.get("fuso", "America/Sao_Paulo"))
    agora = datetime.now(fuso)
    livres = []
    for dia in (agora.date(), agora.date() + timedelta(days=1)):
        for hhmm in CFG["horarios"]:
            h, m = map(int, hhmm.split(":"))
            quando = datetime(dia.year, dia.month, dia.day, h, m, tzinfo=fuso)
            if quando > agora + timedelta(minutes=45) and quando.isoformat() not in ocupados:
                livres.append(quando.isoformat())
    return livres[:len(CFG["horarios"])]


def uploads(canal_id):
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(CFG["olhar_ultimos"]),
           f"https://www.youtube.com/channel/{canal_id}/videos"]
    if Path("cookies.txt").exists():
        cmd[1:1] = ["--cookies", "cookies.txt"]
    saida = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(saida).get("entries") or []


def candidatos(canal):
    try:
        videos = uploads(canal["id"])
    except subprocess.CalledProcessError as e:
        print(f"[{canal['nome']}] falhou ao listar: {e.stderr[-300:]}")
        return []
    ok = [v for v in videos if v.get("id") not in feitos
          and (v.get("duration") or 0) >= CFG["duracao_minima_s"]]
    return sorted(ok, key=lambda v: v.get("view_count") or 0, reverse=True)


horarios = proximos_horarios()
por_video = CFG["cortes_por_video"]
precisa = math.ceil(len(horarios) / por_video)
print(f"Horários livres: {horarios}")

# Alterna os canais até juntar vídeos suficientes.
filas = {c["id"]: candidatos(c) for c in CFG["canais"]}
escolhidos, rodada = [], 0
while len(escolhidos) < precisa and any(filas.values()):
    canal = CFG["canais"][rodada % len(CFG["canais"])]
    if filas[canal["id"]]:
        v = filas[canal["id"]].pop(0)
        print(f"[{canal['nome']}] {v['id']} — {v.get('title')} ({v.get('view_count')} views)")
        escolhidos.append((canal, v["id"]))
    rodada += 1

if os.environ.get("DRY_RUN"):
    raise SystemExit(f"DRY_RUN: {len(escolhidos)} vídeo(s) para {len(horarios)} horário(s)")

for k, (canal, video_id) in enumerate(escolhidos):
    meus = horarios[k * por_video:(k + 1) * por_video]
    if not meus:
        break
    subprocess.run(["gh", "workflow", "run", "corte.yml", "--ref", os.environ.get("REF", "main"),
                    "-f", f"video_id={video_id}", "-f", f"tema={canal['tema']}",
                    "-f", f"num_cortes={len(meus)}", "-f", f"horarios={','.join(meus)}",
                    "-f", f"publicar={CFG['publicar']}", "-f", f"privacidade={CFG['privacidade']}",
                    "-f", f"formato={CFG['formato']}"], check=True)
    feitos.add(video_id)
    ocupados.update(meus)
    print(f"Disparado {video_id} para {meus}")

FEITOS.write_text("\n".join(sorted(feitos)) + "\n", encoding="utf-8")
AGENDADOS.write_text("\n".join(sorted(ocupados)) + "\n", encoding="utf-8")

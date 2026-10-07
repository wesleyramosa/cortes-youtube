"""Agenda os cortes do dia para cada perfil (canal de destino) de canais.json:
escolhe vídeos dos canais de origem (o mais visto ainda não usado, alternando
canais) e dispara o workflow `corte` com o horário de publicação de cada corte.

Estado commitado pelo workflow:
- processados.txt: vídeos já cortados (nunca repete, nem entre perfis)
- agendados.txt: horários já ocupados ("perfil|ISO"; o perfil principal sem prefixo)
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
FUSO = ZoneInfo(CFG.get("fuso", "America/Sao_Paulo"))
AGORA = datetime.now(FUSO)
DRY = bool(os.environ.get("DRY_RUN"))


def chave(perfil, iso):
    # O primeiro perfil mantém o formato antigo (só o horário) para não perder o histórico.
    return iso if perfil["perfil"] == CFG["perfis"][0]["perfil"] else f"{perfil['perfil']}|{iso}"


def horario_do_dia(hhmm):
    """Horário da programação de hoje; antes das 05h conta como madrugada seguinte."""
    h, m = map(int, hhmm.split(":"))
    dia = AGORA.date() + timedelta(days=1 if h < 5 else 0)
    return datetime(dia.year, dia.month, dia.day, h, m, tzinfo=FUSO)


def livres(perfil, horarios, folga_min=15):
    saida = []
    for hhmm in horarios:
        quando = horario_do_dia(hhmm)
        if quando > AGORA + timedelta(minutes=folga_min) and \
                chave(perfil, quando.isoformat()) not in ocupados:
            saida.append(quando.isoformat())
    return saida


def uploads(canal_id):
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(CFG["olhar_ultimos"]),
           f"https://www.youtube.com/channel/{canal_id}/videos"]
    if Path("cookies.txt").exists():
        cmd[1:1] = ["--cookies", "cookies.txt"]
    saida = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(saida).get("entries") or []


_cache = {}


def candidatos(perfil, canal):
    if canal["id"] not in _cache:
        try:
            _cache[canal["id"]] = uploads(canal["id"])
        except subprocess.CalledProcessError as e:
            print(f"[{canal['nome']}] falhou ao listar: {e.stderr[-300:]}")
            _cache[canal["id"]] = []
    ok = [v for v in _cache[canal["id"]] if v.get("id") not in feitos
          and (v.get("duration") or 0) >= perfil["duracao_minima_s"]]
    return sorted(ok, key=lambda v: v.get("view_count") or 0, reverse=True)


def disparar(perfil, canal, video_id, slots, tipo="curto"):
    print(f"[{perfil['perfil']}] disparado {tipo} {video_id} para {slots}")
    feitos.add(video_id)
    ocupados.update(chave(perfil, s) for s in slots)
    if DRY:
        return
    subprocess.run(["gh", "workflow", "run", "corte.yml", "--ref", os.environ.get("REF", "main"),
                    "-f", f"video_id={video_id}", "-f", f"tema={canal['tema']}",
                    "-f", f"num_cortes={len(slots)}", "-f", f"horarios={','.join(slots)}",
                    "-f", f"publicar={perfil['publicar']}",
                    "-f", f"privacidade={perfil['privacidade']}",
                    "-f", f"formato={perfil['formato']}", "-f", f"tipo={tipo}",
                    "-f", f"perfil={perfil['perfil']}"], check=True)


def agendar_longo(perfil):
    """Um vídeo longo por dia, alternando o canal de origem a cada dia."""
    cfg = perfil.get("longo")
    if not cfg:
        return
    slot = livres(perfil, [cfg["horario"]], folga_min=60)
    if not slot:
        return
    canais = perfil["canais"]
    for k in range(len(canais)):
        canal = canais[(AGORA.toordinal() + k) % len(canais)]
        longos = [v for v in candidatos(perfil, canal)
                  if (v.get("duration") or 0) >= cfg["duracao_minima_origem_s"]]
        if longos:
            print(f"[{perfil['perfil']}] longo: {longos[0].get('title')}")
            disparar(perfil, canal, longos[0]["id"], slot, "longo")
            return
    print(f"[{perfil['perfil']}] nenhum vídeo de origem longo disponível")


def agendar_curtos(perfil):
    horarios = livres(perfil, perfil["horarios"])
    por_video = perfil["cortes_por_video"]
    precisa = math.ceil(len(horarios) / por_video)
    print(f"[{perfil['perfil']}] horários livres: {horarios}")
    filas = {c["id"]: candidatos(perfil, c) for c in perfil["canais"]}
    escolhidos, rodada = [], 0
    while len(escolhidos) < precisa and any(filas.values()):
        canal = perfil["canais"][rodada % len(perfil["canais"])]
        if filas[canal["id"]]:
            v = filas[canal["id"]].pop(0)
            if v["id"] not in feitos:
                print(f"[{perfil['perfil']}] [{canal['nome']}] {v['id']} — {v.get('title')}")
                escolhidos.append((canal, v["id"]))
                feitos.add(v["id"])  # reserva já, para o próximo perfil não pegar o mesmo
        rodada += 1
    for k, (canal, video_id) in enumerate(escolhidos):
        meus = horarios[k * por_video:(k + 1) * por_video]
        if meus:
            disparar(perfil, canal, video_id, meus)


for perfil in CFG["perfis"]:
    agendar_longo(perfil)
    agendar_curtos(perfil)

if DRY:
    raise SystemExit("DRY_RUN: nada foi disparado nem gravado")
FEITOS.write_text("\n".join(sorted(feitos)) + "\n", encoding="utf-8")
AGENDADOS.write_text("\n".join(sorted(ocupados)) + "\n", encoding="utf-8")

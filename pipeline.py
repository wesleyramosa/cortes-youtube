"""Pipeline de cortes: baixa um vídeo do YouTube, escolhe os melhores trechos
com o Gemini, corta em 9:16 com legenda queimada e publica como Short.

Configuração por variáveis de ambiente (o workflow do GitHub Actions preenche)
ou por argumentos de linha de comando, para testar localmente.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

TRAB = Path("trabalho")
SAIDA = Path("saida")
IDIOMAS = {"pt": "português do Brasil", "en": "inglês", "es": "espanhol"}


def env(nome, padrao=""):
    return os.environ.get(nome, "").strip() or padrao


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


# ---------------------------------------------------------------- download

def baixar(video_id, cookies):
    TRAB.mkdir(exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    base = ["yt-dlp", "--no-playlist", "--no-warnings"]
    if cookies and Path(cookies).exists():
        base += ["--cookies", cookies]
    run(base + [
        "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
        "--merge-output-format", "mp4", "--write-info-json",
        "-o", str(TRAB / "video.%(ext)s"), url,
    ])
    info = json.loads((TRAB / "video.info.json").read_text(encoding="utf-8"))

    # Legendas em chamada separada: falha aqui não deve derrubar o pipeline.
    lang = escolher_legenda(info)
    if lang:
        subprocess.run([str(c) for c in base + [
            "--skip-download", "--write-subs", "--write-auto-subs",
            "--sub-langs", lang, "--sub-format", "json3",
            "-o", str(TRAB / "video.%(ext)s"), url,
        ]])
    return str(TRAB / "video.mp4"), info


def escolher_legenda(info):
    """Prefere legenda manual no idioma do vídeo; senão a automática original."""
    idioma = (info.get("language") or "").split("-")[0]
    manuais = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    for k in manuais:
        if idioma and k.split("-")[0] == idioma:
            return k
    for k in autos:
        if k.endswith("-orig"):
            return k
    if idioma and idioma in autos:
        return idioma
    return next(iter(manuais), None)


def ler_json3():
    arqs = glob.glob(str(TRAB / "video.*.json3"))
    if not arqs:
        return []
    dados = json.loads(Path(arqs[0]).read_text(encoding="utf-8"))
    segs = []
    for ev in dados.get("events", []):
        if "segs" not in ev or ev.get("aAppend"):
            continue
        txt = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not txt:
            continue
        ini = ev.get("tStartMs", 0) / 1000
        segs.append({"ini": ini, "fim": ini + ev.get("dDurationMs", 0) / 1000, "txt": txt})
    return segs


# ------------------------------------------------------------- transcrição

_modelo = None


def whisper():
    global _modelo
    if _modelo is None:
        from faster_whisper import WhisperModel
        _modelo = WhisperModel(env("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    return _modelo


def transcrever(arquivo, idioma, palavras=False):
    segs, _ = whisper().transcribe(arquivo, language=idioma or None,
                                   word_timestamps=palavras, vad_filter=True)
    segs = list(segs)
    if palavras:
        return [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]
    return [{"ini": s.start, "fim": s.end, "txt": s.text.strip()} for s in segs]


# ------------------------------------------------------- escolha dos trechos

def escolher_trechos(segs, info, tema, n, dmin, dmax, idioma):
    if not (env("GEMINI_API_KEY") or env("GROQ_API_KEY")):
        sys.exit("Defina GEMINI_API_KEY ou GROQ_API_KEY (ou use --trechos para testar sem IA).")
    transcricao = "\n".join(f"[{s['ini']:.1f}-{s['fim']:.1f}] {s['txt']}" for s in segs)[:400_000]
    prompt = f"""Você é editor de cortes virais para YouTube Shorts, Reels e TikTok.
Tema do canal: {tema or "geral"}
Vídeo original: "{info.get('title', '')}" ({info.get('channel', '')})

Abaixo está a transcrição com tempos em segundos. Escolha os {n} melhores trechos (notas de 0 a 100) que:
- sejam AUTOCONTIDOS (façam sentido para quem não viu o vídeo);
- durem entre {dmin} e {dmax} segundos;
- comecem com um gancho forte já nos primeiros 3 segundos;
- terminem numa frase completa, sem cortar a ideia;
- não se sobreponham.
Priorize: opinião forte, revelação, história com desfecho, dica prática, humor, conflito.

Responda somente JSON neste formato, ordenado pela nota (maior primeiro):
{{"cortes":[{{"inicio":0.0,"fim":0.0,"nota":0,"gancho":"primeira frase do trecho","motivo":"por que viraliza",
"chamada":"frase de impacto de 3 a 6 palavras para aparecer na tela, sem emojis",
"titulo":"título chamativo em {IDIOMAS.get(idioma, idioma)}, até 70 caracteres",
"descricao":"1 ou 2 frases em {IDIOMAS.get(idioma, idioma)}","hashtags":["sem #, até 5"]}}]}}

TRANSCRIÇÃO:
{transcricao}"""
    for provedor in (gemini, groq):
        texto = provedor(prompt)
        if texto:
            return json.loads(texto)["cortes"][:n]
    sys.exit("Nenhum provedor de IA respondeu (Gemini e Groq ocupados ou sem chave).")


def gemini(prompt):
    """Tenta o modelo configurado e, se ocupado/aposentado, os outros Flash e Flash-Lite."""
    chave = env("GEMINI_API_KEY")
    if not chave:
        return None
    modelo = env("GEMINI_MODEL", "gemini-flash-latest")
    corpo = {"contents": [{"parts": [{"text": prompt}]}],
             "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    candidatos = [modelo] + [m for m in modelos_gemini(chave) if m != modelo]
    for rodada in range(2):
        for m in list(candidatos):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
            r = requests.post(url, headers={"x-goog-api-key": chave}, json=corpo, timeout=300)
            if r.ok:
                print(f"Trechos escolhidos com {m}", flush=True)
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            print(f"Gemini {m}: {r.status_code}", flush=True)
            if r.status_code not in (429, 500, 503):
                print(r.text[:500], flush=True)
                candidatos.remove(m)
        if rodada == 0 and candidatos:
            print("Gemini ocupado; nova rodada em 30s", flush=True)
            time.sleep(30)
    return None


def modelos_gemini(chave):
    """Flash e Flash-Lite disponíveis na chave, mais novos primeiro (o Google renomeia modelos)."""
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     headers={"x-goog-api-key": chave}, params={"pageSize": 200}, timeout=60)
    if not r.ok:
        return ["gemini-flash-lite-latest"]
    nomes = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    ruins = ("image", "tts", "audio", "live", "thinking", "exp", "preview", "embedding")
    ok = [x for x in nomes if "flash" in x and not any(b in x for b in ruins)]
    flash = sorted((x for x in ok if "lite" not in x), reverse=True)[:3]
    lite = sorted((x for x in ok if "lite" in x), reverse=True)[:3]
    return flash + lite


def groq(prompt):
    """Reserva gratuita quando o Gemini está fora do ar (API compatível com OpenAI)."""
    chave = env("GROQ_API_KEY")
    if not chave:
        return None
    base = "https://api.groq.com/openai/v1"
    cab = {"Authorization": f"Bearer {chave}"}
    modelos = [env("GROQ_MODEL", "llama-3.3-70b-versatile")]
    lista = requests.get(f"{base}/models", headers=cab, timeout=60)
    if lista.ok:
        ids = [m["id"] for m in lista.json().get("data", [])]
        modelos += sorted((i for i in ids if any(k in i for k in ("70b", "120b", "maverick", "kimi"))),
                          reverse=True)
    for m in dict.fromkeys(modelos):
        r = requests.post(f"{base}/chat/completions", headers=cab, timeout=300, json={
            "model": m, "temperature": 0.4, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}]})
        if r.ok:
            print(f"Trechos escolhidos com Groq {m}", flush=True)
            return r.json()["choices"][0]["message"]["content"]
        print(f"Groq {m}: {r.status_code} {r.text[:300]}", flush=True)
    return None


def ajustar(corte, duracao, dmin, dmax):
    ini = max(0.0, float(corte["inicio"]) - 0.2)
    fim = min(duracao, float(corte["fim"]) + 0.4)
    if fim - ini > dmax:
        fim = ini + dmax
    if fim - ini < dmin:
        fim = min(duracao, ini + dmin)
    corte["inicio"], corte["fim"] = round(ini, 2), round(fim, 2)
    return corte


# ----------------------------------------------------------- legenda (ASS)

AMARELO = "&H0000D4FF&"  # ASS usa &HAABBGGRR


def ts(seg):
    cs = int(round(seg * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def limpa(p):
    return p.upper().replace("\\", "").replace("{", "(").replace("}", ")")


def gerar_ass(palavras, destino, duracao, chamada="", marca="", max_palavras=3):
    """Legenda palavra a palavra + título-gancho, marca d'água e chamada final."""
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Leg,DejaVu Sans,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,480,1
Style: Caixa,DejaVu Sans,66,&H00000000,&H00000000,{AMARELO[:-1]},&H00000000,-1,0,0,0,100,100,0,0,3,16,0,8,90,90,250,1
Style: Marca,DejaVu Sans,34,&H50FFFFFF,&H50FFFFFF,&H80000000,&H00000000,-1,0,0,0,100,100,1,0,1,2,0,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    grupos, atual = [], []
    for p in palavras:
        if atual and (len(atual) >= max_palavras or p[0] - atual[-1][1] > 0.6):
            grupos.append(atual)
            atual = []
        atual.append(p)
    if atual:
        grupos.append(atual)

    linhas = []
    for gi, g in enumerate(grupos):
        prox = grupos[gi + 1][0][0] if gi + 1 < len(grupos) else g[-1][1] + 0.5
        for i, (ini, fim, _) in enumerate(g):
            fim_ev = g[i + 1][0] if i + 1 < len(g) else min(max(fim, ini + 0.15) + 0.3, prox)
            texto = " ".join(
                (r"{\c" + AMARELO + "}" + limpa(w) + r"{\c&H00FFFFFF&}") if j == i else limpa(w)
                for j, (_, _, w) in enumerate(g))
            linhas.append(f"Dialogue: 0,{ts(ini)},{ts(fim_ev)},Leg,,0,0,0,,{texto}")

    if chamada:  # título-gancho com leve "pop" de entrada
        linhas.append(f"Dialogue: 1,{ts(0)},{ts(min(3.5, duracao))},Caixa,,0,0,0,,"
                      r"{\fscx80\fscy80\t(0,150,\fscx100\fscy100)}" + limpa(chamada))
    if marca:
        linhas.append(f"Dialogue: 1,{ts(0)},{ts(duracao)},Marca,,0,0,0,,{marca}")
    if duracao > 10:
        linhas.append(f"Dialogue: 1,{ts(duracao - 2.5)},{ts(duracao)},Caixa,,0,0,0,,"
                      r"{\fad(200,0)}SIGA PARA MAIS CORTES")
    Path(destino).write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")


# ------------------------------------------------------------ silêncios

def cortar_silencios(arquivo, palavras, destino, pausa=0.6):
    """Remove pausas longas entre palavras; devolve (arquivo, palavras remapeadas, duração)."""
    dur = duracao_de(arquivo)
    if not palavras:
        return arquivo, palavras, dur
    trechos = [[max(0.0, palavras[0][0] - 0.1), None]]
    for (_, fim_ant, _), (ini, _, _) in zip(palavras, palavras[1:]):
        if ini - fim_ant > pausa:
            trechos[-1][1] = fim_ant + 0.15
            trechos.append([ini - 0.1, None])
    trechos[-1][1] = min(dur, palavras[-1][1] + 0.4)
    novo = sum(b - a for a, b in trechos)
    if dur - novo < 0.8:  # pouco a ganhar: mantém o original
        return arquivo, palavras, dur
    print(f"Silêncios removidos: {dur - novo:.1f}s ({len(trechos)} trechos)", flush=True)
    sel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in trechos)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", arquivo,
         "-vf", f"select='{sel}',setpts=N/FRAME_RATE/TB",
         "-af", f"aselect='{sel}',asetpts=N/SR/TB",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "160k", destino])

    def remapa(x):
        acum = 0.0
        for a, b in trechos:
            if x <= b:
                return acum + max(0.0, x - a)
            acum += b - a
        return acum
    return str(destino), [(remapa(i), remapa(f), w) for i, f, w in palavras], duracao_de(str(destino))


def duracao_de(arquivo):
    saida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", arquivo], capture_output=True, text=True).stdout
    return float(saida.strip() or 0)


def zoom_por_frase(palavras, nivel=0.12, max_frase=4.0):
    """Expressão de zoom: alterna 'punch-in' a cada frase (troca seca, estilo cortes)."""
    frases, ini, ant = [], None, None
    for a, b, w in palavras:
        if ini is None:
            ini = a
        elif (a - ant[1] > 0.35 or ant[2].endswith((".", "?", "!")) or a - ini > max_frase):
            frases.append((ini, a))
            ini = a
        ant = (a, b, w)
    if ini is not None:
        frases.append((ini, ant[1] + 0.5))
    pares = [f"between(it,{a:.2f},{b:.2f})" for k, (a, b) in enumerate(frases) if k % 2 == 1]
    return f"1+{nivel}*({'+'.join(pares)})" if pares else "1"

# ----------------------------------------------------- enquadramento 9:16

def centros_dos_rostos(arquivo, passo=0.5):
    """Centro horizontal (0–1) do maior rosto a cada `passo` segundos; None sem rosto."""
    import cv2
    frontal = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    perfil = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    cap = cv2.VideoCapture(arquivo)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    largura = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    altura = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    a_cada = max(1, round(fps * passo))
    pontos, i = [], 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % a_cada == 0:
            _, quadro = cap.retrieve()
            esc = 640 / quadro.shape[1]
            cinza = cv2.cvtColor(cv2.resize(quadro, None, fx=esc, fy=esc), cv2.COLOR_BGR2GRAY)
            minimo = (int(cinza.shape[0] * 0.08),) * 2
            rostos = list(frontal.detectMultiScale(cinza, 1.1, 6, minSize=minimo))
            if not rostos:
                rostos = list(perfil.detectMultiScale(cinza, 1.1, 6, minSize=minimo))
            if rostos:
                x, _, w, _ = max(rostos, key=lambda r: r[2] * r[3])
                pontos.append((i / fps, (x + w / 2) / cinza.shape[1]))
            else:
                pontos.append((i / fps, None))
        i += 1
    cap.release()
    return pontos, largura, altura

CHEIO = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[f]"


def enquadrar(arquivo, formato):
    """Grafo ffmpeg que termina em [f] com o vídeo já em 1080x1920."""
    if formato == "crop":
        return CHEIO
    if formato == "blur":  # vídeo inteiro no meio, fundo desfocado
        return ("[0:v]split[a][b];"
                "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:2[bg];"
                "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[f]")
    return filtro_segue_rosto(arquivo)


def filtro_segue_rosto(arquivo):
    """Recorte 9:16 em tela cheia que acompanha o rosto, sem tremer (zona morta + transição)."""
    pontos, largura, altura = centros_dos_rostos(arquivo)
    if not largura or largura / altura <= 9 / 16 + 0.01:
        return CHEIO  # já é vertical
    achados = [c for _, c in pontos if c is not None]
    print(f"Rosto encontrado em {len(achados)}/{len(pontos)} amostras", flush=True)
    if not achados:
        return CHEIO  # sem rosto: centro

    # Preenche buracos com o último rosto visto e suaviza com mediana de 5 amostras.
    ultimo, cheios = achados[0], []
    for t, c in pontos:
        ultimo = c if c is not None else ultimo
        cheios.append((t, ultimo))
    suaves = []
    for k, (t, _) in enumerate(cheios):
        janela = sorted(c for _, c in cheios[max(0, k - 2):k + 3])
        suaves.append((t, janela[len(janela) // 2]))

    cw = int(altura * 9 / 16) // 2 * 2
    para_x = lambda c: max(0, min(largura - cw, round(c * largura - cw / 2)))
    # Só move o quadro quando o rosto sai da zona morta (10% da largura).
    alvo = suaves[0][1]
    chaves = [(0.0, para_x(alvo))]
    for t, c in suaves[1:]:
        if abs(c - alvo) > 0.10:
            chaves.append((t, para_x(alvo)))
            chaves.append((t + 0.4, para_x(c)))
            alvo = c
    expr = str(chaves[-1][1])
    for (t0, x0), (t1, x1) in reversed(list(zip(chaves, chaves[1:]))):
        trecho = str(x0) if x0 == x1 else f"{x0}+({x1 - x0})*(t-{t0:.2f})/{t1 - t0:.2f}"
        expr = f"if(lt(t,{t1:.2f}),{trecho},{expr})"
    print(f"Enquadramento: {len(chaves)} posições", flush=True)
    return f"[0:v]crop=w={cw}:h={int(altura) // 2 * 2}:x='{expr}':y=0,scale=1080:1920[f]"


# ------------------------------------------------------------------ render

def renderizar(video, corte, idioma, formato, nome):
    bruto = TRAB / f"{nome}_bruto.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{corte['inicio']:.2f}", "-i", video,
         "-t", f"{corte['fim'] - corte['inicio']:.2f}", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-c:a", "aac", "-b:a", "160k", bruto])

    palavras = transcrever(str(bruto), idioma, palavras=True)
    fonte, palavras, dur = cortar_silencios(str(bruto), palavras, TRAB / f"{nome}_seco.mp4")

    ass = TRAB / f"{nome}.ass"
    gerar_ass(palavras, ass, dur, chamada=corte.get("chamada", ""), marca=env("MARCA_DAGUA"))
    filtro = (f"{enquadrar(fonte, formato)};"
              f"[f]fps=30,zoompan=z='{zoom_por_frase(palavras)}'"
              ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
              "eq=contrast=1.06:saturation=1.15,unsharp=5:5:0.5,"
              f"ass={ass.as_posix()}[t];"
              "color=c=0xFFD400:s=1080x10:r=30[barra];"
              f"[t][barra]overlay=x='-w+w*t/{max(dur, 1):.2f}':y=H-h:shortest=1[v]")
    final = SAIDA / f"{nome}.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", fonte, "-filter_complex", filtro,
         "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", final])
    return final


# ----------------------------------------------------------------- publicar

def publicar(arquivo, titulo, descricao, tags, privacidade, idioma, publicar_em=""):
    """Sobe o vídeo; com `publicar_em` (ISO 8601 futuro) o YouTube publica sozinho na hora."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(None, refresh_token=env("YT_REFRESH_TOKEN"),
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=env("YT_CLIENT_ID"), client_secret=env("YT_CLIENT_SECRET"),
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    corpo = {
        "snippet": {"title": titulo[:100], "description": descricao[:5000], "tags": tags[:15],
                    "categoryId": "22", "defaultLanguage": idioma},
        "status": {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False},
    }
    if publicar_em:
        from datetime import datetime, timezone
        quando = datetime.fromisoformat(publicar_em)
        if quando > datetime.now(timezone.utc):
            corpo["status"].update(privacyStatus="private", publishAt=quando.isoformat())
            print(f"Agendado para {quando.isoformat()}", flush=True)
        else:
            print(f"Horário {publicar_em} já passou; publicando agora", flush=True)
    req = yt.videos().insert(part="snippet,status", body=corpo,
                             media_body=MediaFileUpload(str(arquivo), mimetype="video/mp4",
                                                        chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def montar_textos(corte, info, video_id):
    titulo = corte.get("titulo") or info.get("title", "")
    if len(titulo) <= 90:
        titulo += " #shorts"
    tags = [h.lstrip("#").replace(" ", "") for h in corte.get("hashtags", []) if h]
    licenca = info.get("license") or ""
    descricao = (f"{corte.get('descricao', '')}\n\n"
                 + " ".join(f"#{t}" for t in tags)
                 + f"\n\nTrecho de: {info.get('title', '')} — {info.get('channel', '')}\n"
                 f"https://youtu.be/{video_id}"
                 + (f"\nLicença: {licenca}" if licenca else ""))
    return titulo, descricao, tags


# --------------------------------------------------------------------- main

def avisar(url, dados):
    if not url:
        return
    try:
        requests.post(url, json=dados, timeout=30,
                      headers={"x-token": env("CALLBACK_TOKEN")}).raise_for_status()
    except Exception as e:  # o aviso não deve derrubar o pipeline
        print(f"Falha ao avisar callback: {e}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", default=env("VIDEO_ID"))
    ap.add_argument("--arquivo", default="", help="vídeo local (pula o download)")
    ap.add_argument("--tema", default=env("TEMA"))
    ap.add_argument("--num-cortes", type=int, default=int(env("NUM_CORTES", "1")))
    ap.add_argument("--dur-min", type=int, default=int(env("DUR_MIN", "20")))
    ap.add_argument("--dur-max", type=int, default=int(env("DUR_MAX", "58")))
    ap.add_argument("--idioma", default=env("IDIOMA", "pt"))
    ap.add_argument("--formato", default=env("FORMATO", "auto"), choices=["auto", "blur", "crop"])
    ap.add_argument("--publicar", default=env("PUBLICAR", "nao"))
    ap.add_argument("--privacidade", default=env("PRIVACIDADE", "private"))
    ap.add_argument("--horarios", default=env("HORARIOS"),
                    help="horários ISO separados por vírgula, um por corte (publicação agendada)")
    ap.add_argument("--trechos", default="", help="ex.: 120-165,300-340 (pula o Gemini)")
    ap.add_argument("--cookies", default=env("COOKIES_FILE", "cookies.txt"))
    a = ap.parse_args()

    SAIDA.mkdir(exist_ok=True)
    TRAB.mkdir(exist_ok=True)
    if a.arquivo:
        video, info = a.arquivo, {"title": Path(a.arquivo).stem}
    else:
        video, info = baixar(a.video_id, a.cookies)
    duracao = float(info.get("duration") or 1e9)

    if a.trechos:
        cortes = [{"inicio": float(x.split("-")[0]), "fim": float(x.split("-")[1]), "chamada": env("CHAMADA")}
                  for x in a.trechos.split(",")]
    else:
        segs = ler_json3()
        print(f"Legenda do YouTube: {len(segs)} segmentos", flush=True)
        if not segs:
            print("Sem legenda — transcrevendo o vídeo inteiro com Whisper", flush=True)
            segs = transcrever(video, a.idioma)
        cortes = escolher_trechos(segs, info, a.tema, a.num_cortes, a.dur_min, a.dur_max, a.idioma)

    resultado = {"status": "ok", "video_id": a.video_id, "tema": a.tema,
                 "video_titulo": info.get("title"), "canal": info.get("channel"),
                 "run_url": env("RUN_URL"), "cortes": []}
    for i, corte in enumerate(cortes, 1):
        corte = ajustar(corte, duracao, a.dur_min, a.dur_max)
        arquivo = renderizar(video, corte, a.idioma, a.formato, f"corte_{i}")
        titulo, descricao, tags = montar_textos(corte, info, a.video_id)
        corte.update({"arquivo": arquivo.name, "titulo_final": titulo, "descricao_final": descricao})
        if a.publicar == "sim":
            horarios = [h.strip() for h in a.horarios.split(",") if h.strip()]
            quando = horarios[i - 1] if i <= len(horarios) else ""
            corte["publicar_em"] = quando
            corte["youtube_id"] = publicar(arquivo, titulo, descricao, tags, a.privacidade,
                                           a.idioma, quando)
            corte["youtube_url"] = f"https://youtube.com/shorts/{corte['youtube_id']}"
            print(f"Publicado: {corte['youtube_url']}", flush=True)
        else:
            print(f"Publicação desligada (publicar={a.publicar}); corte só salvo em Artifacts",
                  flush=True)
        resultado["cortes"].append(corte)

    (SAIDA / "resultado.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    avisar(env("CALLBACK_URL"), resultado)


if __name__ == "__main__":
    main()

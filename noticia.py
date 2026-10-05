"""Notícia → vídeo curto 9:16.

O Gemini (ou o Groq, de reserva) escreve o roteiro dividido em cenas, a
Cloudflare Workers AI gera uma imagem por cena, o Edge TTS narra em pt-BR e o
ffmpeg monta tudo com zoom lento (Ken Burns) e legenda palavra a palavra.
Reaproveita as funções do pipeline de cortes (LLM, legenda, upload, callback).
"""
import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import edge_tts
import requests

from pipeline import avisar, duracao_de, env, gemini, gerar_ass, groq, publicar, run

TRAB = Path("trabalho/noticia")
SAIDA = Path("saida")
FPS = 30

# Vai no fim de todo prompt de imagem: é o que tira a cara de banco de imagem americano.
ESTILO = ("photorealistic, natural light, shot on smartphone, Brazilian people and places, "
          "Brazilian Portuguese context, vertical composition with the subject centered, "
          "no text, no letters, no logos, no watermark")


# ----------------------------------------------------------------- roteiro

def escrever_roteiro(titulo, texto, n_cenas):
    prompt = f"""Você é roteirista de um canal de notícias em vídeo curto (Shorts/Reels/TikTok) para o público brasileiro.
Transforme a notícia abaixo em um roteiro narrado de 35 a 55 segundos, dividido em exatamente {n_cenas} cenas.

Regras do roteiro:
- Português do Brasil, linguagem simples e direta, frases curtas, tom de quem conta a notícia para um amigo.
- A primeira cena é um gancho forte que faz a pessoa parar de rolar (sem clickbait mentiroso).
- Fiel à notícia: não invente números, nomes, datas nem declarações que não estejam no texto.
- A última cena fecha com uma pergunta para o público comentar.
- Cada "fala" tem de 12 a 25 palavras. Escreva números por extenso quando forem curtos.

Regras do prompt de imagem (campo "imagem", em INGLÊS):
- Descreva uma foto realista que ilustre a cena: quem aparece, onde, o que está fazendo, enquadramento.
- Sempre ambiente e pessoas brasileiras (ruas, casas, comércio, transporte, rostos e roupas do Brasil).
- Nunca peça texto, placas legíveis, logotipos, marcas ou rostos de pessoas reais/famosas.

Responda só com JSON neste formato:
{{"titulo": "título do vídeo, até 80 caracteres",
  "chamada": "gancho de até 6 palavras para a tela inicial",
  "descricao": "2 ou 3 frases resumindo a notícia",
  "hashtags": ["5 hashtags sem #"],
  "cenas": [{{"fala": "texto narrado", "imagem": "prompt da imagem em inglês"}}]}}

TÍTULO DA NOTÍCIA: {titulo}

TEXTO DA NOTÍCIA:
{texto[:12000]}"""
    for llm in (gemini, groq):
        resposta = llm(prompt)
        if not resposta:
            continue
        try:
            roteiro = json.loads(resposta.strip().removeprefix("```json").removesuffix("```"))
        except json.JSONDecodeError as e:
            print(f"JSON inválido do LLM: {e}", flush=True)
            continue
        if roteiro.get("cenas"):
            return roteiro
    raise SystemExit("Nenhum LLM devolveu um roteiro válido")


# ----------------------------------------------------------------- imagens

def gerar_imagem(prompt, destino):
    """FLUX.1 schnell na Cloudflare Workers AI (plano gratuito: ~10 mil neurons/dia)."""
    conta, chave = env("CF_ACCOUNT_ID"), env("CF_API_TOKEN")
    if not (conta and chave):
        print("Sem CF_ACCOUNT_ID/CF_API_TOKEN — usando fundo liso", flush=True)
        return False
    modelo = env("CF_MODELO", "@cf/black-forest-labs/flux-1-schnell")
    corpo = {"prompt": f"{prompt}. {ESTILO}"[:2000]}
    if "flux" in modelo:
        corpo["steps"] = 8  # máximo do schnell; a saída é sempre 1024x1024
    else:  # SDXL Lightning e afins aceitam tamanho vertical
        corpo.update(width=768, height=1344)
    url = f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/run/{modelo}"
    for tentativa in range(3):
        r = requests.post(url, headers={"Authorization": f"Bearer {chave}"}, json=corpo, timeout=180)
        if r.ok:
            if r.headers.get("content-type", "").startswith("image/"):
                destino.write_bytes(r.content)
            else:
                destino.write_bytes(base64.b64decode(r.json()["result"]["image"]))
            return True
        print(f"Cloudflare {r.status_code}: {r.text[:300]}", flush=True)
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(10 * (tentativa + 1))
    return False


def fundo_liso(destino):
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x1d2b3a:s=1080x1920",
         "-frames:v", "1", destino])


# -------------------------------------------------------------------- voz

async def _narrar(texto, voz, velocidade, mp3):
    com = edge_tts.Communicate(texto, voz, rate=velocidade, boundary="WordBoundary")
    palavras = []
    with open(mp3, "wb") as f:
        async for pedaco in com.stream():
            if pedaco["type"] == "audio":
                f.write(pedaco["data"])
            elif pedaco["type"] == "WordBoundary":  # tempos em unidades de 100 ns
                ini = pedaco["offset"] / 1e7
                palavras.append((ini, ini + pedaco["duration"] / 1e7, pedaco["text"]))
    return palavras


def narrar(texto, voz, velocidade, mp3):
    for tentativa in range(3):
        try:
            return asyncio.run(_narrar(texto, voz, velocidade, mp3))
        except Exception as e:  # o serviço do Edge às vezes recusa uma conexão
            print(f"Edge TTS falhou ({e}); tentando de novo", flush=True)
            time.sleep(5 * (tentativa + 1))
    raise SystemExit("Edge TTS indisponível")


# ------------------------------------------------------------------ vídeo

def animar(imagem, duracao, i, destino):
    """Zoom lento alternando aproximar, afastar e deslizar, para a imagem parada não cansar."""
    n = int(duracao * FPS) + 1
    movimentos = [
        ("1+0.12*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),          # aproxima
        ("1.12-0.12*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),       # afasta
        ("1.12", "(iw-iw/zoom)*on/{n}", "(ih-ih/zoom)/2"),               # desliza p/ direita
        ("1.12", "(iw-iw/zoom)*(1-on/{n})", "(ih-ih/zoom)/2"),           # desliza p/ esquerda
    ]
    z, x, y = (e.format(n=n) for e in movimentos[i % len(movimentos)])
    # Amplia antes do zoompan: em resolução maior o movimento não "treme".
    filtro = (f"scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
              f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s=1080x1920:fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", imagem, "-vf", filtro, "-frames:v", n,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", destino])


def concatenar(arquivos, destino, extra=()):
    lista = destino.with_suffix(".txt")
    lista.write_text("".join(f"file '{Path(a).resolve().as_posix()}'\n" for a in arquivos),
                     encoding="utf-8")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lista,
         *extra, destino])


def montar(roteiro, a):
    cenas = roteiro["cenas"]
    clipes, audios, palavras, inicio = [], [], [], 0.0
    imagem_anterior = None
    for i, cena in enumerate(cenas):
        print(f"Cena {i + 1}/{len(cenas)}: {cena['fala']}", flush=True)
        mp3, wav = TRAB / f"voz_{i}.mp3", TRAB / f"voz_{i}.wav"
        tempos = narrar(cena["fala"], a.voz, a.velocidade, mp3)
        pausa = 0.8 if i == len(cenas) - 1 else 0.25
        dur = duracao_de(str(mp3)) + pausa
        # Áudio da cena com o silêncio no fim, para cada cena ter a duração exata do clipe.
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-af", "apad", "-t", f"{dur:.3f}",
             "-ar", "44100", "-ac", "2", wav])
        palavras += [(inicio + ini, inicio + fim, w) for ini, fim, w in tempos]

        img = TRAB / f"cena_{i}.png"
        if not gerar_imagem(cena.get("imagem", cena["fala"]), img):
            if imagem_anterior:
                img = imagem_anterior
            else:
                fundo_liso(img)
        imagem_anterior = img
        clipe = TRAB / f"cena_{i}.mp4"
        animar(img, dur, i, clipe)
        clipes.append(clipe)
        audios.append(wav)
        inicio += dur

    video, audio = TRAB / "imagens.mp4", TRAB / "narracao.wav"
    concatenar(clipes, video, ["-c", "copy"])
    concatenar(audios, audio)
    legenda = TRAB / "legenda.ass"
    gerar_ass(palavras, legenda, inicio, chamada=roteiro.get("chamada", ""),
              marca=env("MARCA_NOTICIA"), final="SIGA PARA MAIS NOTÍCIAS")
    final = SAIDA / "noticia.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", audio,
         "-vf", f"ass={legenda.as_posix()}", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
         "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", final])
    return final, inicio


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--titulo", default=env("NOTICIA_TITULO"))
    ap.add_argument("--texto", default=env("NOTICIA_TEXTO"))
    ap.add_argument("--texto-arquivo", default="", help="lê o texto da notícia de um arquivo")
    ap.add_argument("--url", default=env("NOTICIA_URL"), help="link da fonte (vai na descrição)")
    ap.add_argument("--roteiro", default="", help="JSON de roteiro pronto (pula o LLM)")
    ap.add_argument("--cenas", type=int, default=int(env("NUM_CENAS", "6")))
    ap.add_argument("--voz", default=env("VOZ", "pt-BR-AntonioNeural"))
    ap.add_argument("--velocidade", default=env("VELOCIDADE", "+10%"))
    ap.add_argument("--publicar", default=env("PUBLICAR", "nao"))
    ap.add_argument("--privacidade", default=env("PRIVACIDADE", "private"))
    ap.add_argument("--publicar-em", default=env("PUBLICAR_EM"))
    a = ap.parse_args()

    TRAB.mkdir(parents=True, exist_ok=True)
    SAIDA.mkdir(exist_ok=True)
    if a.texto_arquivo:
        a.texto = Path(a.texto_arquivo).read_text(encoding="utf-8")

    if a.roteiro:
        roteiro = json.loads(Path(a.roteiro).read_text(encoding="utf-8"))
    else:
        if not (a.titulo or a.texto):
            raise SystemExit("Informe o título e/ou o texto da notícia")
        roteiro = escrever_roteiro(a.titulo, a.texto, a.cenas)
    (TRAB / "roteiro.json").write_text(json.dumps(roteiro, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    arquivo, duracao = montar(roteiro, a)
    tags = [h.lstrip("#").replace(" ", "") for h in roteiro.get("hashtags", []) if h]
    titulo = roteiro.get("titulo") or a.titulo
    if len(titulo) <= 90:
        titulo += " #shorts"
    descricao = (roteiro.get("descricao", "") + "\n\n" + " ".join(f"#{t}" for t in tags)
                 + (f"\n\nFonte: {a.url}" if a.url else ""))

    resultado = {"status": "ok", "noticia_titulo": a.titulo, "noticia_url": a.url,
                 "titulo": titulo, "descricao": descricao, "hashtags": tags,
                 "duracao": round(duracao, 1), "arquivo": arquivo.name, "roteiro": roteiro,
                 "run_url": env("RUN_URL")}
    if a.publicar == "sim":
        resultado["youtube_id"] = publicar(arquivo, titulo, descricao, tags, a.privacidade, "pt",
                                           a.publicar_em)
        resultado["youtube_url"] = f"https://youtube.com/shorts/{resultado['youtube_id']}"
        print(f"Publicado: {resultado['youtube_url']}", flush=True)
    else:
        print("Publicação desligada; vídeo só salvo em Artifacts", flush=True)

    (SAIDA / "noticia.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(json.dumps({k: v for k, v in resultado.items() if k != "roteiro"},
                     ensure_ascii=False, indent=2))
    avisar(env("CALLBACK_URL"), resultado)


if __name__ == "__main__":
    main()

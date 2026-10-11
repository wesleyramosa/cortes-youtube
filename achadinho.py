"""Achadinho → vídeo curto 9:16 de produto (Reels/Shorts), sem custo.

O Gemini (ou o Groq, de reserva) escreve o roteiro em cenas a partir dos dados
da oferta, o Edge TTS narra em pt-BR e o ffmpeg monta o vídeo com a FOTO REAL do
produto (fundo claro, zoom lento, preço em destaque e legenda palavra a palavra).
Se houver cota no Nano Banana (Gemini imagem), algumas cenas usam a foto do
produto num cenário de uso — sem alterar o produto. Se não houver, segue só com
a foto original. Reaproveita as funções de noticia.py e pipeline.py.
"""
import argparse
import base64
import json
import time
from pathlib import Path

import requests

from noticia import animar, concatenar, narrar
from pipeline import avisar, duracao_de, env, gemini, gerar_ass, groq, run

TRAB = Path("trabalho/achadinho")
SAIDA = Path("saida")
LARANJA = "&H002D4DEE&"  # #EE4D2D em BGR (ASS)


# ----------------------------------------------------------------- roteiro

def escrever_roteiro(p, n_cenas):
    prompt = f"""Você é roteirista de vídeos curtos de "achadinhos" (Reels/Shorts/TikTok) para o público brasileiro.
Escreva um roteiro narrado de 20 a 30 segundos sobre o produto abaixo, dividido em exatamente {n_cenas} cenas.

PRODUTO: {p['nome']}
PREÇO: {p['preco']}
DESCONTO: {p.get('desconto') or 0}%
NOTA: {p.get('nota') or '-'}
VENDIDOS: {p.get('vendidos') or '-'}

Regras:
- Português do Brasil, natural e animado, sem gírias forçadas. Frases curtas.
- Cena 1: gancho forte que faz parar de rolar (sem mentira nem exagero).
- Use SÓ informações que estão acima ou que são óbvias pelo nome do produto. Não invente
  material, medidas, garantia, brinde, frete grátis nem "menor preço do Brasil".
- Cite o preço uma vez, escrito do jeito que se fala (ex.: "trinta e nove e noventa").
- Última cena: chamada para ação terminando com "o link está na bio".
- Cada "fala" tem de 8 a 18 palavras.
- Campo "imagem" (em INGLÊS): um cenário realista de uso para colocar ESTE produto
  (ex.: "on a bright modern kitchen counter, morning light"). Nunca descreva o produto
  diferente do que ele é, nunca peça texto, logos ou rostos.

Responda só com JSON neste formato:
{{"chamada": "gancho de até 5 palavras para a tela inicial",
  "cenas": [{{"fala": "texto narrado", "imagem": "cenário em inglês"}}],
  "legenda_instagram": "legenda com emojis e 3 a 5 hashtags",
  "legenda_facebook": "legenda curta com emojis",
  "titulo_youtube": "título até 70 caracteres"}}"""
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


AVISO = "Preço consultado no dia da publicação, pode mudar."


def fechar_legendas(roteiro, link):
    """Avisos de publicidade e preço sempre presentes, independente do que o LLM escreveu."""
    ig = roteiro.get("legenda_instagram", "").strip()
    fb = roteiro.get("legenda_facebook", "").strip()
    roteiro["legenda_instagram"] = f"{ig}\n\n{AVISO} Link na bio 🔗 #publi"
    roteiro["legenda_facebook"] = f"{fb}\n\n👉 {link}\n\n{AVISO} Contém link de afiliado. #publi"
    return roteiro


# ----------------------------------------------------------------- imagens

def baixar_foto(url, destino):
    for tentativa in range(3):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            destino.write_bytes(r.content)
            return
        except Exception as e:
            print(f"Falha ao baixar foto ({e})", flush=True)
            time.sleep(5 * (tentativa + 1))
    raise SystemExit("Não consegui baixar a foto do produto")


def nano_banana(foto, cenario, destino):
    """Coloca o produto num cenário de uso. Devolve False se não houver cota/chave."""
    chave = env("GEMINI_API_KEY")
    if not chave or env("USAR_NANO_BANANA", "sim") != "sim":
        return False
    modelo = env("NANO_MODEL", "gemini-3.1-flash-image")
    prompt = (f"Place this exact product {cenario}. Keep the product IDENTICAL to the photo: same "
              "shape, colors, proportions, logo and details — do not redesign it. Photorealistic "
              "lifestyle photo, bright natural light, vertical 9:16, no text, no watermark, "
              "no human faces.")
    corpo = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(foto.read_bytes()).decode()}},
        {"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    try:
        r = requests.post(url, params={"key": chave}, json=corpo, timeout=180)
        if not r.ok:
            print(f"Nano Banana {r.status_code}: {r.text[:200]}", flush=True)
            return False
        for parte in r.json()["candidates"][0]["content"]["parts"]:
            dados = parte.get("inlineData") or parte.get("inline_data")
            if dados:
                destino.write_bytes(base64.b64decode(dados["data"]))
                return True
    except Exception as e:
        print(f"Nano Banana falhou ({e})", flush=True)
    return False


def quadro_produto(foto, destino):
    """Foto original sobre fundo claro (a própria foto desfocada e clareada) — visual limpo."""
    filtro = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
              "boxblur=40:2,drawbox=x=0:y=0:w=iw:h=ih:color=white@0.72:t=fill[fundo];"
              "[0:v]scale=940:1100:force_original_aspect_ratio=decrease[prod];"
              "[fundo][prod]overlay=(W-w)/2:(H-h)/2-120")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", foto, "-filter_complex", filtro,
         "-frames:v", "1", destino])


def quadro_cenario(imagem, destino):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", imagem, "-vf",
         "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
         "-frames:v", "1", destino])


# ------------------------------------------------------------------ vídeo

def legenda_com_preco(palavras, destino, duracao, roteiro, preco):
    gerar_ass(palavras, destino, duracao, chamada=roteiro.get("chamada", ""),
              marca=env("MARCA_ACHADINHO"), final="LINK NA BIO")
    texto = Path(destino).read_text(encoding="utf-8")
    estilo = (f"Style: Preco,DejaVu Sans,74,&H00FFFFFF,&H00FFFFFF,{LARANJA},&H00000000,"
              "-1,0,0,0,100,100,0,0,3,18,0,8,90,90,120,1")
    texto = texto.replace("\n[Events]", f"\n{estilo}\n\n[Events]", 1)
    # O preço aparece depois do gancho e fica até o fim.
    ini = min(3.5, duracao / 3)
    texto += (f"Dialogue: 2,{_ts(ini)},{_ts(duracao)},Preco,,0,0,0,,"
              r"{\fad(250,0)}" + f"POR {preco}\n")
    Path(destino).write_text(texto, encoding="utf-8")


def _duracao(arquivo):
    try:
        return duracao_de(str(arquivo))
    except ValueError:  # ffprobe devolve "N/A" quando não consegue medir
        return 0.0


def _ts(seg):
    cs = int(round(seg * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def montar(roteiro, produto, foto, a):
    cenas = roteiro["cenas"]
    clipes, audios, palavras, inicio = [], [], [], 0.0
    base = TRAB / "quadro_produto.png"
    quadro_produto(foto, base)
    for i, cena in enumerate(cenas):
        print(f"Cena {i + 1}/{len(cenas)}: {cena['fala']}", flush=True)
        mp3, wav = TRAB / f"voz_{i}.mp3", TRAB / f"voz_{i}.wav"
        tempos = narrar(cena["fala"], a.voz, a.velocidade, mp3)
        pausa = 1.2 if i == len(cenas) - 1 else 0.2
        # O mp3 do Edge não traz duração confiável no cabeçalho: decodifica para wav (medida
        # exata) e tira o silêncio que sobra no fim, para o ritmo ficar ágil.
        bruto = TRAB / f"voz_{i}_bruto.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-af",
             "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse",
             "-ar", "44100", "-ac", "2", bruto])
        fala = _duracao(bruto) or _duracao(mp3)
        if tempos:  # nunca menor que a última palavra narrada
            fala = max(fala, tempos[-1][1] + 0.05)
        dur = fala + pausa
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", bruto, "-af", "apad", "-t", f"{dur:.3f}",
             "-ar", "44100", "-ac", "2", wav])
        palavras += [(inicio + ini, inicio + fim, w) for ini, fim, w in tempos]

        # Primeira e última cena: sempre a foto real. Meio: cenário do Nano Banana, se der.
        quadro = base
        if 0 < i < len(cenas) - 1:
            gerada = TRAB / f"nano_{i}.png"
            if nano_banana(foto, cena.get("imagem", "on a clean bright table"), gerada):
                quadro = TRAB / f"cena_{i}.png"
                quadro_cenario(gerada, quadro)
        clipe = TRAB / f"cena_{i}.mp4"
        animar(quadro, dur, i, clipe)
        clipes.append(clipe)
        audios.append(wav)
        inicio += dur

    video, audio = TRAB / "imagens.mp4", TRAB / "narracao.wav"
    concatenar(clipes, video, ["-c", "copy"])
    concatenar(audios, audio)
    legenda = TRAB / "legenda.ass"
    legenda_com_preco(palavras, legenda, inicio, roteiro, produto["preco"])
    final = SAIDA / "achadinho.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", audio,
         "-vf", f"ass={legenda.as_posix()}", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", final])
    return final, inicio


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--produto", default=env("PRODUTO"),
                    help='JSON: {"id","nome","preco","imagem","link","desconto","nota","vendidos"}')
    ap.add_argument("--roteiro", default="", help="JSON de roteiro pronto (pula o LLM)")
    ap.add_argument("--cenas", type=int, default=int(env("NUM_CENAS", "4")))
    ap.add_argument("--voz", default=env("VOZ_ACHADINHO", "pt-BR-FranciscaNeural"))
    ap.add_argument("--velocidade", default=env("VELOCIDADE", "+10%"))
    a = ap.parse_args()

    TRAB.mkdir(parents=True, exist_ok=True)
    SAIDA.mkdir(exist_ok=True)
    produto = json.loads(a.produto)
    for campo in ("nome", "preco", "imagem", "link"):
        if not produto.get(campo):
            raise SystemExit(f"Produto sem o campo '{campo}'")

    foto = TRAB / "foto.jpg"
    baixar_foto(produto["imagem"], foto)
    if a.roteiro:
        roteiro = json.loads(Path(a.roteiro).read_text(encoding="utf-8"))
    else:
        roteiro = escrever_roteiro(produto, a.cenas)
    roteiro = fechar_legendas(roteiro, produto["link"])
    (TRAB / "roteiro.json").write_text(json.dumps(roteiro, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    arquivo, duracao = montar(roteiro, produto, foto, a)
    resultado = {"status": "ok", "produto": produto, "duracao": round(duracao, 1),
                 "arquivo": arquivo.name, "chamada": roteiro.get("chamada", ""),
                 "narracao": " ".join(c["fala"] for c in roteiro["cenas"]),
                 "legenda_instagram": roteiro["legenda_instagram"],
                 "legenda_facebook": roteiro["legenda_facebook"],
                 "titulo_youtube": roteiro.get("titulo_youtube", produto["nome"])[:90],
                 "run_url": env("RUN_URL")}
    if env("PUBLICAR_YT") == "sim":  # sobe privado até a auditoria da API do YouTube sair
        from pipeline import publicar
        titulo = resultado["titulo_youtube"][:85] + " #shorts"
        descricao = (roteiro.get("legenda_facebook", "").replace(produto["link"], "")
                     + f"\n\nLink: {produto['link']}")
        try:
            vid = publicar(arquivo, titulo, descricao, ["achadinhos", "shopee", "ofertas"],
                           env("PRIVACIDADE", "private"), "pt")
            resultado["youtube_url"] = f"https://youtube.com/shorts/{vid}"
        except Exception as e:  # YouTube não pode derrubar o Instagram/Facebook
            print(f"Falha no YouTube: {e}", flush=True)
            resultado["youtube_erro"] = str(e)[:300]
    (SAIDA / "achadinho.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    if env("AVISAR_NO_SCRIPT") == "sim":  # no Actions quem avisa é o passo seguinte, já com a URL
        avisar(env("CALLBACK_URL"), resultado)


if __name__ == "__main__":
    main()

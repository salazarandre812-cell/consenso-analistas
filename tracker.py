#!/usr/bin/env python3
"""
Tracker de consenso unanime de analistas.

Percorre um universo de accoes, le a distribuicao de recomendacoes de
analistas na Finnhub e guarda as que estao a 100% em compra, com um
minimo de cobertura para o numero fazer sentido.

Uso pessoal. Dados via Finnhub (plano gratuito).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- config

API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()

# Numero minimo de analistas para a percentagem ser interpretavel.
# Com 2 analistas, "100% compra" nao significa nada. Nao baixes muito isto.
MIN_ANALISTAS = 10

# Quantas posicoes mostrar.
TOP_N = 10

# Segundos entre chamadas. O plano gratuito da Finnhub da ~60/min.
INTERVALO = 1.1

# Durante quantos dias um alerta de quebra de consenso fica na pagina.
# Se so abrires isto uma vez por semana, sobe para 14 ou 21.
DIAS_ALERTA = 14

BASE = Path(__file__).parent
FICHEIRO_DADOS = BASE / "data" / "latest.json"
FICHEIRO_HISTORICO = BASE / "data" / "history.jsonl"
FICHEIRO_PAGINA = BASE / "docs" / "index.html"
FICHEIRO_UNIVERSO = BASE / "universe.txt"

URL_SP500 = (
    "https://raw.githubusercontent.com/datasets/"
    "s-and-p-500-companies/main/data/constituents.csv"
)

# Listas oficiais de todos os tickers cotados na Nasdaq e na NYSE (+ outras
# bolsas cobertas pelo ficheiro "otherlisted"). Usadas como universo
# principal; o S&P 500 acima passa a ser apenas o primeiro nivel de reserva
# se estas duas nao responderem.
URL_NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
URL_OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# Rede de seguranca se o CSV do universo estiver inacessivel.
UNIVERSO_FALLBACK = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA",
    "AMZN": "Amazon", "GOOGL": "Alphabet", "META": "Meta Platforms",
    "AVGO": "Broadcom", "TSLA": "Tesla", "JPM": "JPMorgan Chase",
    "V": "Visa", "MA": "Mastercard", "UNH": "UnitedHealth",
    "XOM": "Exxon Mobil", "COST": "Costco", "HD": "Home Depot",
    "PG": "Procter & Gamble", "JNJ": "Johnson & Johnson",
    "NFLX": "Netflix", "AMD": "AMD", "CRM": "Salesforce",
}


# ------------------------------------------------------------------ http

def http_json(url, tentativas=4):
    """GET com backoff. Devolve None se falhar de vez."""
    for tentativa in range(tentativas):
        try:
            pedido = urllib.request.Request(
                url, headers={"User-Agent": "consensus-tracker/1.0"}
            )
            with urllib.request.urlopen(pedido, timeout=25) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            if erro.code == 429:          # rate limit
                espera = 5 * (tentativa + 1)
                print(f"  rate limit, a esperar {espera}s", file=sys.stderr)
                time.sleep(espera)
                continue
            if erro.code in (401, 403):
                print("Chave da API recusada. Verifica FINNHUB_API_KEY.",
                      file=sys.stderr)
                sys.exit(1)
            return None
        except Exception:
            time.sleep(2 * (tentativa + 1))
    return None


def http_texto(url):
    try:
        pedido = urllib.request.Request(
            url, headers={"User-Agent": "consensus-tracker/1.0"}
        )
        with urllib.request.urlopen(pedido, timeout=25) as resposta:
            return resposta.read().decode("utf-8")
    except Exception:
        return None


# -------------------------------------------------------------- universo

def _parse_symbol_directory(texto, coluna_symbol):
    """Faz parsing de um ficheiro pipe-delimited da Nasdaq Trader.

    Exclui ETFs e "test issues" — o que sobra sao acoes normais, que e o
    que interessa para leituras de recomendacoes de analistas.
    """
    universo = {}
    linhas = texto.splitlines()
    if not linhas:
        return universo

    cabecalho = linhas[0].split("|")
    idx = {nome: i for i, nome in enumerate(cabecalho)}
    if coluna_symbol not in idx or "Security Name" not in idx:
        return universo

    for linha in linhas[1:]:
        if not linha or linha.startswith("File Creation Time"):
            continue
        campos = linha.split("|")
        if len(campos) != len(cabecalho):
            continue

        symbol = campos[idx[coluna_symbol]].strip()
        etf = campos[idx.get("ETF", -1)].strip() if "ETF" in idx else ""
        teste = (campos[idx.get("Test Issue", -1)].strip()
                 if "Test Issue" in idx else "")
        if not symbol or etf == "Y" or teste == "Y":
            continue

        nome = campos[idx["Security Name"]].strip()
        universo[symbol.replace(".", "-").upper()] = nome or symbol

    return universo


def carregar_universo_mercado_completo():
    """Todos os tickers da Nasdaq + NYSE (e bolsas afins), via Nasdaq Trader.

    Sao dois ficheiros porque a Nasdaq Trader separa por operadora de
    listagem: um para a propria Nasdaq, outro para tudo o resto (NYSE,
    NYSE American, NYSE Arca, Cboe BZX, ...).
    """
    universo = {}

    texto_nasdaq = http_texto(URL_NASDAQ_LISTED)
    if texto_nasdaq:
        universo.update(_parse_symbol_directory(texto_nasdaq, "Symbol"))

    texto_outras = http_texto(URL_OTHER_LISTED)
    if texto_outras:
        universo.update(_parse_symbol_directory(texto_outras, "ACT Symbol"))

    return universo


def carregar_universo():
    """Devolve {ticker: nome}. universe.txt local tem prioridade.

    Reserva em dois niveis: se a lista completa do mercado (Nasdaq + NYSE)
    nao responder, cai para o S&P 500; se nem isso responder, usa a lista
    fixa de emergencia.
    """
    if FICHEIRO_UNIVERSO.exists():
        universo = {}
        for linha in FICHEIRO_UNIVERSO.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            if "," in linha:
                ticker, nome = linha.split(",", 1)
                universo[ticker.strip().upper()] = nome.strip()
            else:
                universo[linha.upper()] = linha.upper()
        if universo:
            print(f"Universo: {len(universo)} tickers (universe.txt)")
            return universo

    universo = carregar_universo_mercado_completo()
    if universo:
        print(f"Universo: {len(universo)} tickers (Nasdaq + NYSE)")
        return universo

    csv_bruto = http_texto(URL_SP500)
    if csv_bruto:
        import csv
        import io
        universo = {}
        leitor = csv.DictReader(io.StringIO(csv_bruto))
        for linha in leitor:
            ticker = (linha.get("Symbol") or linha.get("symbol") or "").strip()
            nome = (linha.get("Security") or linha.get("Name")
                    or linha.get("security") or ticker).strip()
            if ticker:
                universo[ticker.replace(".", "-").upper()] = nome
        if universo:
            print(f"Universo: {len(universo)} tickers (S&P 500, reserva)")
            return universo

    print("Nao consegui obter nenhuma lista de mercado. A usar a reserva fixa.",
          file=sys.stderr)
    return dict(UNIVERSO_FALLBACK)


# --------------------------------------------------------------- recolha

def ler_recomendacoes(ticker):
    """Distribuicao de ratings mais recente para um ticker."""
    url = (f"https://finnhub.io/api/v1/stock/recommendation"
           f"?symbol={ticker}&token={API_KEY}")
    dados = http_json(url)
    if not dados or not isinstance(dados, list):
        return None

    # A Finnhub devolve um registo por mes, do mais recente para o mais antigo.
    registo = max(dados, key=lambda r: r.get("period", ""))

    compra_forte = int(registo.get("strongBuy", 0) or 0)
    compra = int(registo.get("buy", 0) or 0)
    manter = int(registo.get("hold", 0) or 0)
    venda = int(registo.get("sell", 0) or 0)
    venda_forte = int(registo.get("strongSell", 0) or 0)
    total = compra_forte + compra + manter + venda + venda_forte

    if total == 0:
        return None

    return {
        "compra_forte": compra_forte,
        "compra": compra,
        "manter": manter,
        "venda": venda,
        "venda_forte": venda_forte,
        "total": total,
        "pct_compra": (compra_forte + compra) / total,
        "periodo": registo.get("period", ""),
    }


def recolher(universo):
    """Le o universo inteiro e devolve {ticker: leitura}.

    Guardamos tudo, nao so o que qualifica: para saber se uma accao
    antes unanime desceu, e preciso ter a leitura de agora.
    """
    leituras = {}
    falhas = 0
    tickers = sorted(universo)

    for indice, ticker in enumerate(tickers, 1):
        if indice % 50 == 0 or indice == 1:
            print(f"  {indice}/{len(tickers)}...")

        rec = ler_recomendacoes(ticker)
        if rec is None:
            falhas += 1
        else:
            rec["ticker"] = ticker
            rec["nome"] = universo[ticker]
            leituras[ticker] = rec

        time.sleep(INTERVALO)

    return leituras, falhas


def qualifica(rec):
    return rec["total"] >= MIN_ANALISTAS and rec["pct_compra"] >= 1.0


def comparar_vigilancia(vigilancia_anterior, leituras, hoje):
    """Compara quem estava unanime com a leitura de agora.

    Um ticker sem resposta da API mantem-se em vigilancia sem gerar
    alerta: uma falha de rede nao e uma mudanca de sentimento.
    """
    alertas = []

    for ticker, antes in vigilancia_anterior.items():
        agora = leituras.get(ticker)
        if agora is None:
            continue
        if qualifica(agora):
            continue

        discordantes = agora["manter"] + agora["venda"] + agora["venda_forte"]

        if agora["pct_compra"] < 1.0:
            motivo = "consenso"
        else:
            # Continua unanime, mas ja nao ha analistas que cheguem
            # para o numero ser interpretavel.
            motivo = "cobertura"

        alertas.append({
            "data": hoje,
            "ticker": ticker,
            "nome": agora["nome"],
            "motivo": motivo,
            "pct_agora": round(agora["pct_compra"] * 100, 1),
            "total_antes": antes.get("total"),
            "total_agora": agora["total"],
            "discordantes": discordantes,
            "manter": agora["manter"],
            "venda": agora["venda"] + agora["venda_forte"],
            "unanime_desde": antes.get("desde"),
        })

    alertas.sort(key=lambda a: (a["motivo"] != "consenso", a["pct_agora"]))
    return alertas


def construir_vigilancia(qualificadas, vigilancia_anterior, leituras, hoje):
    """Todas as accoes unanimes de agora, com a data desde quando o sao.

    Um ticker que estava em vigilancia e nao teve leitura nesta corrida
    fica retido: se caisse fora, uma falha de rede desarmava o alerta e a
    quebra seguinte passava despercebida.
    """
    vigilancia = {}
    for r in qualificadas:
        anterior = vigilancia_anterior.get(r["ticker"], {})
        vigilancia[r["ticker"]] = {
            "nome": r["nome"],
            "total": r["total"],
            "desde": anterior.get("desde", hoje),
        }

    for ticker, antes in vigilancia_anterior.items():
        if ticker not in vigilancia and ticker not in leituras:
            vigilancia[ticker] = antes

    return vigilancia


# ----------------------------------------------------------------- html

PAGINA = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Consenso unanime &middot; {data_curta}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --tinta:      #0d1219;
    --painel:     #151d28;
    --linha:      #232f3f;
    --texto:      #e2e8f0;
    --apagado:    #75859c;
    --marca:      #d9a441;
    --entrada:    #5fb3bd;
    --saida:      #a8657a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 2.5rem 1.25rem 5rem;
    background: var(--tinta);
    color: var(--texto);
    font-family: "IBM Plex Sans", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .folha {{ max-width: 780px; margin: 0 auto; }}

  header {{ border-bottom: 1px solid var(--linha); padding-bottom: 1.5rem; }}
  .sobrescrito {{
    font-family: "IBM Plex Mono", monospace;
    font-size: .7rem; letter-spacing: .16em; text-transform: uppercase;
    color: var(--marca); margin: 0 0 .7rem;
  }}
  h1 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: clamp(1.7rem, 5vw, 2.4rem);
    line-height: 1.1; letter-spacing: -.02em; margin: 0 0 .8rem;
  }}
  .subtitulo {{
    color: var(--apagado); font-size: .92rem; line-height: 1.55;
    margin: 0; max-width: 52ch;
  }}
  .meta {{
    font-family: "IBM Plex Mono", monospace; font-size: .74rem;
    color: var(--apagado); margin-top: 1.2rem;
    display: flex; flex-wrap: wrap; gap: 1.4rem;
  }}
  .meta b {{ color: var(--texto); font-weight: 500; }}

  /* Alertas de mudanca de sentimento. Fica antes da lista porque uma
     quebra e mais informativa do que a lista continuar igual. */
  .alertas {{
    margin: 2rem 0 0; border: 1px solid #4a2f39; border-left-width: 3px;
    border-radius: 4px; background: var(--painel); padding: 1.25rem 1.4rem;
  }}
  .alertas h2 {{
    font-family: "IBM Plex Mono", monospace; font-weight: 600;
    font-size: .72rem; letter-spacing: .14em; text-transform: uppercase;
    color: var(--saida); margin: 0 0 1.1rem;
  }}
  .alerta {{ padding: .8rem 0; border-top: 1px solid var(--linha); }}
  .alerta:first-of-type {{ padding-top: 0; border-top: 0; }}
  .alerta-topo {{
    display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap;
  }}
  .alerta-ticker {{
    font-family: "Space Grotesk", sans-serif; font-weight: 700;
    font-size: 1.02rem;
  }}
  .alerta-empresa {{ color: var(--apagado); font-size: .8rem; }}
  .queda {{
    font-family: "IBM Plex Mono", monospace; font-size: .82rem;
    font-weight: 600; color: var(--saida); margin-left: auto;
    white-space: nowrap;
  }}
  .queda s {{ color: var(--apagado); font-weight: 400; text-decoration: none; }}
  .alerta-nota {{
    color: var(--apagado); font-size: .82rem; line-height: 1.55;
    margin: .4rem 0 0;
  }}
  .alerta-nota b {{ color: var(--texto); font-weight: 500; }}
  .selo {{
    font-family: "IBM Plex Mono", monospace; font-size: .66rem;
    letter-spacing: .1em; text-transform: uppercase;
    padding: .15rem .45rem; border: 1px solid var(--linha);
    border-radius: 2px; color: var(--apagado);
  }}

  .movimentos {{ display: flex; flex-wrap: wrap; gap: .5rem; margin: 1.75rem 0 0; }}
  .etiqueta {{
    font-family: "IBM Plex Mono", monospace; font-size: .74rem;
    padding: .3rem .6rem; border: 1px solid var(--linha); border-radius: 3px;
  }}
  .etiqueta.entrou {{ color: var(--entrada); border-color: #2a4750; }}
  .etiqueta.saiu   {{ color: var(--saida);   border-color: #4a2f39; }}

  ol {{ list-style: none; padding: 0; margin: 2rem 0 0; }}
  li {{
    display: grid;
    grid-template-columns: 1fr auto;
    gap: .3rem 1.5rem;
    padding: 1.05rem 0;
    border-bottom: 1px solid var(--linha);
  }}
  .ticker {{
    font-family: "Space Grotesk", sans-serif; font-weight: 700;
    font-size: 1.12rem; letter-spacing: -.01em;
  }}
  .empresa {{ color: var(--apagado); font-size: .84rem; }}
  .contagem {{
    font-family: "IBM Plex Mono", monospace; font-size: .95rem;
    font-weight: 600; text-align: right; white-space: nowrap;
  }}
  .contagem span {{ color: var(--apagado); font-weight: 400; font-size: .74rem; }}

  /* A barra de cobertura: um tracinho por analista. O sinal de 20
     analistas nao vale o mesmo que o de 10, e isso tem de se ver. */
  .cobertura {{
    grid-column: 1 / -1; display: flex; gap: 2px; margin-top: .55rem;
  }}
  .cobertura i {{
    display: block; width: 7px; height: 13px;
    background: var(--marca); opacity: .85; border-radius: 1px;
  }}

  .vazio {{
    margin: 2.5rem 0; padding: 1.6rem; border: 1px dashed var(--linha);
    border-radius: 4px; color: var(--apagado); font-size: .92rem;
    line-height: 1.6;
  }}

  footer {{
    margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--linha);
    color: var(--apagado); font-size: .78rem; line-height: 1.7;
  }}
  footer p {{ margin: 0 0 .7rem; max-width: 62ch; }}
  footer a {{ color: var(--apagado); }}
</style>
</head>
<body>
<div class="folha">

  <header>
    <p class="sobrescrito">Consenso unanime de analistas</p>
    <h1>{n_encontradas} accoes sem uma unica recomendacao de venda ou manutencao</h1>
    <p class="subtitulo">De {n_universo} accoes analisadas, estas sao as que
    reunem cobertura de pelo menos {min_analistas} analistas com a totalidade
    a atribuir rating de compra.</p>
    <div class="meta">
      <span>Atualizado <b>{data_longa}</b></span>
      <span>Periodo dos ratings <b>{periodo}</b></span>
      <span>Sem resposta <b>{falhas}</b></span>
    </div>
  </header>

  {alertas}

  {movimentos}

  {lista}

  <footer>
    <p>Ordenado pelo numero de analistas que cobrem cada accao, nao por
    preferencia. A barra dourada mostra um tracinho por analista.</p>
    <p>As recomendacoes do sell-side tendem historicamente para o lado
    positivo &mdash; ratings de venda sao uma pequena fraccao do total. Um
    consenso unanime diz mais sobre o sentimento dos analistas do que sobre
    o comportamento futuro do preco.</p>
    <p>Dados de <a href="https://finnhub.io">Finnhub</a>. Ferramenta pessoal,
    sem fins comerciais. Nao e recomendacao de investimento.</p>
  </footer>

</div>
</body>
</html>
"""


def escapar(texto):
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def montar_lista(resultados):
    if not resultados:
        return ('<div class="vazio">Nenhuma accao do universo cumpre os '
                'criterios nesta verificacao. Com um piso de cobertura '
                'exigente, isto acontece com regularidade &mdash; e o '
                'resultado esperado, nao uma falha.</div>')

    linhas = []
    for r in resultados:
        tracos = "".join("<i></i>" for _ in range(r["total"]))
        linhas.append(f"""    <li>
      <div>
        <div class="ticker">{escapar(r['ticker'])}</div>
        <div class="empresa">{escapar(r['nome'])}</div>
      </div>
      <div class="contagem">{r['total']}<br><span>analistas</span></div>
      <div class="cobertura">{tracos}</div>
    </li>""")
    return "<ol>\n" + "\n".join(linhas) + "\n  </ol>"


def data_pt(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m")
    except Exception:
        return iso or "&mdash;"


def montar_alertas(alertas):
    if not alertas:
        return ""

    blocos = []
    for a in alertas:
        if a["motivo"] == "consenso":
            partes = []
            if a["manter"]:
                partes.append(f"{a['manter']} passaram a manter")
            if a["venda"]:
                partes.append(f"{a['venda']} a vender")
            mudanca = " e ".join(partes) if partes else "mudaram de rating"
            nota = (f"De {a['total_agora']} analistas, <b>{mudanca}</b>. "
                    f"Unanime desde {data_pt(a['unanime_desde'])}.")
            selo = ""
            queda = (f'<s>100%</s> &rarr; {a["pct_agora"]:.0f}%')
        else:
            nota = (f"Continua sem discordantes, mas a cobertura desceu de "
                    f"<b>{a['total_antes']} para {a['total_agora']} "
                    f"analistas</b> &mdash; abaixo do piso, deixa de ser "
                    f"um numero interpretavel.")
            selo = '<span class="selo">cobertura</span>'
            queda = f'<s>{a["total_antes"]}</s> &rarr; {a["total_agora"]}'

        blocos.append(f"""    <div class="alerta">
      <div class="alerta-topo">
        <span class="alerta-ticker">{escapar(a['ticker'])}</span>
        <span class="alerta-empresa">{escapar(a['nome'])}</span>
        {selo}
        <span class="queda">{queda}</span>
      </div>
      <p class="alerta-nota">{nota}</p>
    </div>""")

    titulo = ("Mudanca de sentimento &middot; ultimos "
              f"{DIAS_ALERTA} dias")
    return (f'<section class="alertas">\n    <h2>{titulo}</h2>\n'
            + "\n".join(blocos) + "\n  </section>")


def montar_movimentos(entraram):
    """So entradas novas. As saidas ou sao uma quebra de consenso (e
    aparecem nos alertas, com o motivo) ou sao apenas queda no ranking
    sem mudanca nenhuma de sentimento — ruido que nao vale sinalizar."""
    if not entraram:
        return ""
    etiquetas = [f'<span class="etiqueta entrou">+ {escapar(t)}</span>'
                 for t in sorted(entraram)]
    return '<div class="movimentos">' + "".join(etiquetas) + "</div>"


def escrever_pagina(resultados, n_universo, falhas, entraram, alertas):
    agora = datetime.now(timezone.utc)
    periodo = resultados[0]["periodo"] if resultados else "&mdash;"

    html = PAGINA.format(
        data_curta=agora.strftime("%d/%m/%Y"),
        data_longa=agora.strftime("%d/%m/%Y %H:%M UTC"),
        n_encontradas=len(resultados),
        n_universo=n_universo,
        min_analistas=MIN_ANALISTAS,
        periodo=periodo,
        falhas=falhas,
        alertas=montar_alertas(alertas),
        movimentos=montar_movimentos(entraram),
        lista=montar_lista(resultados),
    )
    FICHEIRO_PAGINA.parent.mkdir(parents=True, exist_ok=True)
    FICHEIRO_PAGINA.write_text(html, encoding="utf-8")


# ----------------------------------------------------------------- main

def main():
    if not API_KEY:
        print("Falta a variavel FINNHUB_API_KEY.", file=sys.stderr)
        print("Obtem uma chave gratuita em https://finnhub.io/register",
              file=sys.stderr)
        sys.exit(1)

    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    limite = (datetime.now(timezone.utc) - timedelta(days=DIAS_ALERTA)
              ).strftime("%Y-%m-%d")

    anteriores = set()
    vigilancia_anterior = {}
    alertas_antigos = []
    if FICHEIRO_DADOS.exists():
        try:
            antigo = json.loads(FICHEIRO_DADOS.read_text(encoding="utf-8"))
            anteriores = {r["ticker"] for r in antigo.get("resultados", [])}
            vigilancia_anterior = antigo.get("vigilancia", {})
            alertas_antigos = antigo.get("alertas", [])
        except Exception:
            pass

    universo = carregar_universo()
    print(f"A recolher ratings (~{len(universo) * INTERVALO / 60:.0f} min)...")

    leituras, falhas = recolher(universo)

    qualificadas = [r for r in leituras.values() if qualifica(r)]
    qualificadas.sort(key=lambda r: (-r["total"], r["ticker"]))
    resultados = qualificadas[:TOP_N]

    novos_alertas = comparar_vigilancia(vigilancia_anterior, leituras, hoje)
    vigilancia = construir_vigilancia(
        qualificadas, vigilancia_anterior, leituras, hoje)

    # Os alertas ficam visiveis DIAS_ALERTA dias: se so abrires a pagina
    # de semana a semana, uma quebra de terca-feira nao pode desaparecer
    # na quarta. Um ticker que reentre em vigilancia limpa o seu alerta.
    recuperados = {a["ticker"] for a in alertas_antigos} & set(vigilancia)
    alertas = novos_alertas + [
        a for a in alertas_antigos
        if a["data"] >= limite
        and a["ticker"] not in {n["ticker"] for n in novos_alertas}
        and a["ticker"] not in recuperados
    ]

    atuais = {r["ticker"] for r in resultados}
    entraram = sorted(atuais - anteriores) if anteriores else []

    instantaneo = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "universo": len(universo),
        "min_analistas": MIN_ANALISTAS,
        "sem_resposta": falhas,
        "total_qualificadas": len(qualificadas),
        "entraram": entraram,
        "alertas": alertas,
        "vigilancia": vigilancia,
        "resultados": resultados,
    }

    FICHEIRO_DADOS.parent.mkdir(parents=True, exist_ok=True)
    FICHEIRO_DADOS.write_text(
        json.dumps(instantaneo, ensure_ascii=False, indent=2), encoding="utf-8")

    with FICHEIRO_HISTORICO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(instantaneo, ensure_ascii=False) + "\n")

    escrever_pagina(resultados, len(universo), falhas, entraram, alertas)

    print(f"\n{len(qualificadas)} accoes qualificadas, "
          f"{len(resultados)} na lista.")
    if entraram:
        print(f"Entraram: {', '.join(entraram)}")
    for a in novos_alertas:
        if a["motivo"] == "consenso":
            print(f"  ALERTA {a['ticker']}: 100% -> {a['pct_agora']:.0f}% "
                  f"({a['discordantes']}/{a['total_agora']} discordantes)")
        else:
            print(f"  ALERTA {a['ticker']}: cobertura "
                  f"{a['total_antes']} -> {a['total_agora']} analistas")
    for r in resultados:
        print(f"  {r['ticker']:6} {r['total']:3} analistas  {r['nome']}")


if __name__ == "__main__":
    main()

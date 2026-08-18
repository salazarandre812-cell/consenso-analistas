# Tracker de consenso unânime

Uma lista das ações da Nasdaq + NYSE onde 100% dos analistas que as cobrem
têm rating de compra — com um piso mínimo de cobertura para o número
significar alguma coisa.

Corre sozinho no GitHub Actions. Sem servidor, sem custos (dentro dos
minutos grátis — ver nota sobre frequência mais abaixo).

---

## Instalação (~10 minutos)

**1. Chave da Finnhub**

Regista-te em <https://finnhub.io/register>. O plano gratuito dá ~60 chamadas
por minuto e não pede cartão. Copia a chave.

**2. Repositório**

Cria um repositório novo no GitHub — **privado** é o mais sensato, já que os
termos do plano gratuito da Finnhub são para uso pessoal não-comercial. Faz
upload destes ficheiros para a raiz.

**3. Guardar a chave**

No repositório: `Settings` → `Secrets and variables` → `Actions` →
`New repository secret`.

- Name: `FINNHUB_API_KEY`
- Secret: a tua chave

**4. Primeira execução**

Separador `Actions` → `Consenso de analistas` → `Run workflow`. Com o
universo alargado a toda a Nasdaq + NYSE (milhares de tickers), a corrida
demora cerca de 2 horas. A partir daí corre sozinho uma vez por semana, à
segunda-feira às 07:00 UTC.

**Porque só uma vez por semana:** a 1.1s por chamada à Finnhub, cobrir o
mercado inteiro (em vez de só o S&P 500) faz a corrida passar de ~10 minutos
para ~2 horas. Cinco corridas de 2h por semana ultrapassaria os 2.000
minutos/mês grátis de GitHub Actions em repositórios privados — por isso o
`cron` está em modo semanal. Se preferires mais frequência, o botão
`Run workflow` continua disponível a qualquer momento para correres à mão.

**5. Ver o resultado**

Duas opções:

- Abrir `docs/index.html` diretamente no GitHub (ou fazer download).
- Ativar o GitHub Pages: `Settings` → `Pages` → source `main`, pasta `/docs`.
  Ficas com um URL fixo que podes pôr nos favoritos do telemóvel.
  (Em repositório privado, o Pages exige plano pago — em repositório público,
  é grátis mas fica visível para toda a gente.)

---

## Correr localmente

```bash
set FINNHUB_API_KEY=a_tua_chave     # Windows cmd
python tracker.py
```

Não precisa de dependências — só a biblioteca padrão do Python.

Para agendar no Windows sem GitHub: Agendador de Tarefas → tarefa diária →
ação `python C:\caminho\tracker.py`. Só corre com o PC ligado, que é a razão
para preferir o GitHub Actions.

---

## Configuração

No topo do `tracker.py`:

| Variável | Por omissão | O que faz |
|---|---|---|
| `MIN_ANALISTAS` | `10` | Piso de cobertura. **Não baixes muito.** Com 2 analistas, "100% compra" é ruído: tipicamente são os bancos que fizeram o IPO. É este número que separa um sinal de um artefacto estatístico. |
| `TOP_N` | `10` | Quantas posições mostrar. |
| `INTERVALO` | `1.1` | Segundos entre chamadas. Abaixo de 1.0 apanhas rate limit. |

**Universo próprio:** cria um `universe.txt` na raiz, uma linha por ação:

```
AAPL,Apple
ASML,ASML Holding
# linhas com cardinal são ignoradas
```

Se o ficheiro existir, substitui a lista de mercado completo. Útil se
quiseres seguir só a tua watchlist — e muito mais rápido (podes inclusive
voltar ao `cron` diário sem preocupação de custos, já que uma watchlist
pequena corre em segundos).

---

## Alertas de mudança de sentimento

Quando uma ação que estava a 100% deixa de estar, aparece um aviso no topo da
página. Há três formas de sair da lista e só duas contam como aviso:

| Situação | Aparece? | Como |
|---|---|---|
| Analistas mudaram para manter ou vender | Sim | `100% → 77%`, com quantos mudaram e para quê |
| Continua unânime mas a cobertura caiu abaixo do piso | Sim, com selo `cobertura` | `11 → 7 analistas` |
| Continua unânime e com cobertura, só foi ultrapassada no ranking | Não | Nada mudou no sentimento — sinalizar isto seria ruído |

Cada alerta diz também desde quando a ação era unânime. Uma quebra ao fim de
seis meses não é a mesma coisa que uma quebra ao fim de duas semanas.

Os alertas ficam visíveis `DIAS_ALERTA` dias (14 por omissão), para que uma
quebra à terça não desapareça na quarta se só abrires a página ao fim de
semana. Se a ação recuperar o consenso, o alerta é limpo automaticamente.

**Sem falsos positivos por falha de rede:** se a API não responder para um
ticker, ele fica retido em vigilância e nenhum aviso é gerado. Uma falha de
rede não é uma mudança de sentimento — e, mais importante, não desarma o
alerta para a corrida seguinte.

---

## O que sai

- `docs/index.html` — a página, com as entradas e saídas desde a última corrida
- `data/latest.json` — o instantâneo atual
- `data/history.jsonl` — uma linha por execução, acumula desde o primeiro dia

O `history.jsonl` é a parte que ganha valor com o tempo. Ao fim de uns meses
tens uma série de como o consenso se moveu, que é bastante mais interessante
do que a fotografia de um dia.

---

## Ressalvas

O ranking é por **número de analistas**, não por preferência. Mais gente a
dizer o mesmo é um sinal mais robusto do que menos gente a dizer o mesmo.

As recomendações do sell-side enviesam historicamente para o lado positivo —
ratings de venda são uma fração pequena do total, por razões de relacionamento
comercial entre os bancos e as empresas que cobrem. Unanimidade em compra é
menos rara do que a intuição sugere, e a evidência sobre o seu poder preditivo
é mista.

Haverá dias em que a lista sai vazia. Com um piso de cobertura exigente isso é
o resultado esperado, não uma avaria.

Ferramenta pessoal. Não é recomendação de investimento, e os dados da Finnhub
no plano gratuito não podem ser redistribuídos comercialmente.

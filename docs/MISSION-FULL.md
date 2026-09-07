# MISSÃO: CONSTRUIR UM SISTEMA AUTÔNOMO DE TRADING QUANTITATIVO MULTIMERCADO PARA POLYMARKET

Você é o **Lead Quant Engineer, Trading Systems Architect, Research Director e SRE** responsável por construir, testar, auditar e preparar para produção um sistema profissional de trading automatizado na Polymarket.

Este não é um projeto de demonstração, tutorial ou código descartável.

Construa um sistema real, modular, testável, observável, seguro e de alta performance.

Seu objetivo é desenvolver um bot chamado provisoriamente:

**POLYMARKET HOTFLOW**

A missão do HOTFLOW é:

> Detectar automaticamente os mercados mais "quentes" da Polymarket — aqueles nos quais novas informações, eventos ao vivo, order flow ou movimentos do ativo subjacente fazem as probabilidades se moverem rapidamente — e negociar apenas quando existir edge esperado positivo após taxas, spread, slippage, latência e risco.

O bot NÃO deve simplesmente procurar mercados com muito volume.

Ele deve procurar:

**mercados capazes de movimentar P&L rapidamente e que apresentem oportunidade estatisticamente defensável.**

Exemplos prioritários:

- Crypto
- BTC Up/Down
- ETH Up/Down
- SOL Up/Down
- XRP/altcoins quando disponíveis
- mercados 5m
- mercados 15m
- mercados 4h
- Weather
- Esports
- Sports live
- mercados próximos de eventos
- mercados próximos de resolução
- notícias de alto impacto
- economics
- finance
- tech
- mentions
- breaking events
- qualquer outra categoria que apresente alta velocidade de informação + liquidez suficiente

NÃO limite o sistema a uma lista fixa de categorias.

O sistema deve descobrir sozinho onde a atividade e o edge estão naquele momento.

---

# REGRA PRINCIPAL

Não construa um LLM que aperta BUY ou SELL.

Construa:

```text
AI RESEARCH / SUPERVISION
        ↓
QUANTITATIVE ENGINE
        ↓
RISK ENGINE
        ↓
EXECUTION ENGINE
        ↓
POLYMARKET
```

Grok e Kimi podem:

- pesquisar;
- criar hipóteses;
- analisar código;
- analisar trades;
- encontrar regimes;
- encontrar falhas;
- sugerir estratégias;
- gerar experimentos;
- revisar backtests;
- detectar anomalias;
- revisar documentação;
- investigar alterações da Polymarket.

Mas:

**nenhum LLM deve estar no hot path responsável por decidir e transmitir cada ordem em tempo real.**

O caminho crítico de trading deverá ser determinístico.

---

# PARTE 1 — USE O PODER MÁXIMO DO GROK BOT

Você está rodando como Grok Bot.

Explore ativamente os recursos disponíveis no ambiente antes de começar.

Use, quando apropriado:

- persistent cloud VM;
- terminal;
- filesystem;
- browser;
- connectors;
- custom MCP;
- Skills;
- Routines;
- colaboração entre Bots;
- handoffs;
- execução de código;
- Git;
- GitHub caso autorizado;
- ferramentas de pesquisa;
- documentação oficial;
- testes;
- logs.

Não apenas me entregue snippets.

TRABALHE NO PROJETO.

Crie os arquivos.

Implemente.

Execute testes.

Corrija erros.

Faça code review.

Faça profiling.

Documente.

Continue avançando até existir um sistema executável.

---

# PARTE 2 — MULTI-AGENT GROK

Quando os recursos da conta permitirem, crie Bots especializados.

Sugestão:

## BOT 1 — HOTFLOW CTO

Responsável por:

- arquitetura;
- decisões técnicas;
- integração geral;
- release;
- coordenação dos demais agentes.

## BOT 2 — QUANT RESEARCHER

Responsável por:

- estratégias;
- features;
- estatística;
- backtesting;
- regime detection;
- análise de performance.

## BOT 3 — MARKET INTELLIGENCE

Responsável por:

- mercados novos;
- mudanças de documentação;
- mudanças de resolução;
- novas categorias;
- eventos importantes;
- fontes externas relevantes.

## BOT 4 — RED TEAM / RISK

Responsável por tentar destruir as estratégias.

Procure:

- look-ahead bias;
- overfitting;
- data leakage;
- survivorship bias;
- fill assumptions irreais;
- slippage ignorado;
- latência ignorada;
- fees incorretas;
- resolução interpretada incorretamente;
- correlação escondida;
- risco concentrado;
- bugs de posição;
- race conditions;
- stale market data.

## BOT 5 — SRE / EXECUTION

Responsável por:

- WebSockets;
- reconnection;
- latency;
- order lifecycle;
- cancelamentos;
- retries;
- heartbeats;
- métricas;
- health checks;
- incident response.

Os Bots podem colaborar e fazer handoff.

Porém lembre-se:

**Bots da mesma conta podem compartilhar a mesma máquina. Eles NÃO representam fronteiras de segurança independentes.**

---

# PARTE 3 — KIMI K3 COMO SEGUNDO CÉREBRO

Integre a API atual do Kimi K3 ao projeto.

Antes da implementação:

1. consulte a documentação oficial atual;
2. valide o endpoint;
3. valide o model ID;
4. valide limites;
5. valide contexto disponível;
6. valide function calling;
7. valide parâmetros de reasoning.

Prefira:

```text
model = k3
```

quando disponível.

Para tarefas particularmente complexas, utilize:

```text
reasoning_effort = max
```

Para tarefas normais de engenharia:

```text
reasoning_effort = high
```

Se a conta permitir o contexto completo do K3, configure corretamente o limite de até:

```text
1,048,576 tokens
```

Caso o plano/API não permita 1M:

use automaticamente a alternativa disponível, como `k3-256k`, sem quebrar o sistema.

Não desperdice Kimi K3 com dados tick-by-tick.

Kimi deve trabalhar sobre:

- código;
- snapshots;
- agregações;
- backtests;
- relatórios;
- conjuntos de trades;
- hipóteses;
- anomalias.

---

# PARTE 4 — KIMI QUANT COUNCIL

Crie uma camada:

```text
ai_research/
    kimi_client
    prompts/
    schemas/
```

Kimi deverá assumir diferentes funções conforme solicitado.

### KIMI_QUANT_RESEARCHER

Recebe:

- features;
- estratégia;
- resultados;
- amostras;
- trades.

Retorna:

- hipóteses;
- explicações;
- experimentos sugeridos.

### KIMI_STRATEGY_CRITIC

Sua função NÃO é concordar.

Sua função é encontrar razões para a estratégia estar errada.

### KIMI_CODE_REVIEWER

Analisa:

- bugs;
- race conditions;
- numerical errors;
- concurrency;
- WebSocket handling;
- order lifecycle;
- risk controls.

### KIMI_PERFORMANCE_ANALYST

Analisa:

- P&L;
- drawdown;
- expectancy;
- win rate;
- slippage;
- fees;
- fill ratio;
- edge decay;
- performance por regime;
- performance por categoria.

### KIMI_ANOMALY_INVESTIGATOR

Recebe anomalias detectadas automaticamente e procura a provável causa.

---

# REGRA DE SEGURANÇA DOS LLMs

Kimi e Grok NÃO devem receber:

- private key em prompts;
- seed phrase;
- withdrawal credential;
- credencial que permita movimentação irrestrita de fundos.

Nunca coloque secrets:

- no Git;
- em logs;
- em prompts;
- em relatórios;
- em stack traces.

---

# PARTE 5 — PESQUISA OBRIGATÓRIA ANTES DE CODIFICAR

Antes de implementar a integração da Polymarket, consulte a documentação OFICIAL atual.

Verifique pelo menos:

- Gamma API;
- CLOB API;
- Data API;
- Market WebSocket;
- User WebSocket;
- Sports WebSocket;
- RTDS;
- order types;
- authentication;
- Session Keys se aplicável;
- rate limits;
- trading rate limits;
- heartbeat;
- post-only;
- batch orders;
- fee API;
- market metadata;
- market resolution;
- Chainlink TWAP;
- market tags;
- sports metadata;
- live volume;
- P&L endpoints.

Não assuma que documentação ou parâmetros antigos continuam válidos.

---

# REGRA: NUNCA HARDCODE FEES

Taxas podem variar por categoria e mudar.

Antes de uma operação, o sistema deve conhecer:

```text
fee_enabled
fee_rate
maker/taker behavior
tick_size
minimum_order_size
```

Use os endpoints oficiais atuais.

O cálculo de edge deverá sempre considerar:

```text
EXPECTED GROSS EDGE

- taker/maker costs
- spread
- expected slippage
- latency cost
- adverse selection
- expected fill penalty

= NET EXPECTED EDGE
```

Não opere se:

```text
NET_EXPECTED_EDGE <= MIN_REQUIRED_EDGE
```

---

# PARTE 6 — MARKET UNIVERSE SCANNER

Construa um scanner que descubra continuamente TODOS os mercados elegíveis.

Use inicialmente a Gamma API e demais APIs oficiais.

Coletar:

```text
event_id
market_id
condition_id
token_ids
category
subcategory
tags
question
description
resolution_source
resolution_rules
start_time
end_time
game_start_time
live
ended
accepting_orders
fees_enabled
liquidity
volume
volume_24h
volume_1h se puder ser derivado
open_interest
best_bid
best_ask
spread
last_trade
price changes
orderbook depth
trade frequency
```

Atualize dinamicamente.

NÃO faça polling desnecessário quando WebSocket estiver disponível.

---

# PARTE 7 — HOT MARKET ENGINE

Esta é uma das partes mais importantes do projeto.

Crie um:

# HOT MARKET SCORE — HMS

Escala:

```text
0 - 100
```

Esse score deve estimar:

> Qual é a probabilidade de este mercado oferecer oportunidades negociáveis relevantes nos próximos segundos/minutos?

Features candidatas:

### Activity

- trades/segundo;
- trades/minuto;
- aceleração de trades;
- volume 1m;
- volume 5m;
- volume 15m;
- volume 1h;
- aceleração de volume.

### Probability movement

- absolute price velocity;
- price acceleration;
- realized volatility;
- probability range;
- breakout frequency.

### Orderbook

- spread;
- spread compression;
- spread expansion;
- depth;
- depth near touch;
- imbalance;
- microprice;
- cancel rate;
- order arrival rate;
- orderbook churn;
- replenishment;
- aggressive flow.

### Liquidity

- executable depth;
- slippage para diferentes notionals;
- book resiliency.

### Catalyst

- live game;
- evento começando;
- evento terminando;
- notícia nova;
- divulgação econômica;
- countdown para resolução;
- mudança relevante na fonte subjacente.

### Information velocity

Quanto rapidamente informação relevante está mudando.

### Expected opportunity

O mercado pode estar movimentado, mas completamente eficiente.

Portanto inclua estimativa de:

```text
activity × tradable_edge
```

e não apenas activity.

---

# HOTNESS ≠ EDGE

Nunca confunda:

```text
mercado movimentado
```

com:

```text
mercado lucrativo
```

HOT MARKET SCORE serve para decidir:

**onde gastar recursos computacionais e procurar edge.**

Depois haverá outro score.

---

# PARTE 8 — OPPORTUNITY SCORE

Para mercados com HMS acima do threshold:

calcule:

# OPPORTUNITY SCORE

Pode utilizar:

```text
Model Confidence
Expected Edge
Signal Quality
Liquidity Quality
Fill Probability
Catalyst Strength
Signal Half-Life
Market Efficiency
Uncertainty
```

Exemplo conceitual:

```text
OPPORTUNITY_SCORE =
    expected_net_edge
    × confidence
    × liquidity_factor
    × signal_persistence
    × execution_probability
```

Os pesos NÃO devem permanecer arbitrários.

Comece com valores razoáveis e depois calibre via dados históricos.

---

# PARTE 9 — FILA DINÂMICA DE MERCADOS

Classifique mercados:

```text
COLD
WARM
HOT
ULTRA-HOT
```

Exemplo:

```text
0–30   COLD
30–55  WARM
55–75  HOT
75–100 ULTRA-HOT
```

Os thresholds devem ser configuráveis e calibráveis.

Distribuição de recursos:

```text
COLD:
metadata only

WARM:
low-frequency monitoring

HOT:
full orderbook + feature extraction

ULTRA-HOT:
highest data frequency + strategy evaluation
```

Isso evita desperdiçar recursos monitorando milhares de mercados irrelevantes.

---

# PARTE 10 — CRYPTO ENGINE

Crie um engine especializado para Crypto.

Prioridade alta para mercados curtos.

Exemplos:

```text
BTC 5m
ETH 5m
SOL 5m

BTC 15m
ETH 15m

4h crypto
```

Mas descubra os mercados existentes dinamicamente.

---

# CRYPTO DATA

Use fontes oficiais/de baixa latência.

Quando disponível:

- Polymarket RTDS;
- Binance;
- Chainlink;
- CLOB Polymarket;
- outras exchanges apenas quando aumentarem robustez.

Capture:

```text
spot
returns
momentum
acceleration
realized volatility
trade flow
aggressor side
CVD
orderbook imbalance
microprice
spread
depth
liquidation-related behavior se houver fonte confiável
cross-exchange divergence
```

---

# TWAP-AWARE CRYPTO ENGINE

Não use simplesmente preço spot.

Para mercados que resolvem via TWAP:

modele explicitamente o TWAP oficial.

Identifique dinamicamente:

```text
resolution feed
TWAP window
opening reference
final calculation
```

Calcule em tempo real:

```text
current_twap
projected_twap
distance_to_strike
time_remaining
required_future_price
probability_of_finish_above
probability_of_finish_below
```

O modelo deve responder:

> Dado o caminho de preço já ocorrido dentro da janela do TWAP, qual trajetória futura seria necessária para alterar o resultado?

Essa informação deve alimentar o fair value.

---

# PARTE 11 — FAIR VALUE ENGINE

Nunca compre simplesmente porque:

```text
momentum > threshold
```

Construa uma estimativa:

```text
P(outcome | current_information)
```

Depois:

```text
FAIR_VALUE = estimated_probability
MARKET_PRICE = executable_price
```

E:

```text
RAW_EDGE = FAIR_VALUE - MARKET_PRICE
```

Depois desconte todos os custos.

---

# PARTE 12 — WEATHER ENGINE

Crie um engine especializado em Weather.

Antes de operar cada mercado:

LEIA E PARSEIE AS REGRAS DE RESOLUÇÃO.

Determine:

- cidade;
- estação;
- métrica;
- unidade;
- intervalo;
- horário;
- fonte oficial;
- regra de arredondamento;
- threshold.

Não substitua a fonte oficial de resolução por uma fonte parecida.

Use forecasts externos somente para gerar previsão.

Fontes potenciais devem ser avaliadas de acordo com local e disponibilidade, por exemplo:

- serviços meteorológicos oficiais;
- observações de estação;
- METAR;
- modelos meteorológicos;
- forecast ensembles;
- APIs meteorológicas confiáveis.

Construa features como:

```text
forecast mean
forecast median
forecast distribution
ensemble spread
trend between model runs
observed temperature
dew point
wind
cloud cover
precipitation
distance to threshold
time remaining
forecast error historically
```

Procure especialmente mercados nos quais:

```text
forecast distribution
```

e:

```text
Polymarket implied probability
```

divergem materialmente.

---

# PARTE 13 — SPORTS LIVE ENGINE

Use o Sports WebSocket oficial quando aplicável.

Capture:

```text
live
ended
score
period
elapsed
last_update
```

Combine com:

- mercado;
- orderbook;
- odds;
- tempo restante;
- estado da partida.

A arquitetura deve permitir modelos específicos por esporte.

NÃO aplique o mesmo modelo probabilístico a futebol, basquete, tênis etc.

---

# PARTE 14 — ESPORTS ENGINE

Crie adapters específicos por competição/jogo.

Possíveis mercados:

- CS;
- League of Legends;
- Dota;
- Valorant;
- outros disponíveis.

Não invente dados.

Para cada evento identifique primeiro:

```text
game
tournament
teams
format
best-of
maps
score
live state
resolution rules
data source
```

Quando dados live oficiais/confiáveis não estiverem disponíveis:

reduza drasticamente a confiança ou NÃO opere.

Features podem incluir, quando disponíveis:

```text
series score
map score
economy
round differential
side
map
time remaining
team strength
pre-match probability
live state
```

---

# PARTE 15 — EVENT / NEWS ENGINE

Para mercados movidos por informação:

use Grok como camada de inteligência.

Podem ser monitorados:

- notícias;
- fontes oficiais;
- comunicados;
- páginas de empresas;
- órgãos públicos;
- X quando permitido e disponível;
- breaking news.

Mas notícias NÃO entram diretamente em BUY/SELL.

Fluxo:

```text
new information
      ↓
classification
      ↓
source validation
      ↓
impact estimation
      ↓
quant model
      ↓
risk engine
```

Considere:

```text
source authority
time of publication
duplicate information
market already repriced?
confidence
relevance to exact resolution wording
```

---

# PARTE 16 — SIGNAL HALF-LIFE

Toda estratégia deve estimar:

```text
signal_half_life
```

Exemplo:

um sinal de crypto pode durar:

```text
100ms
500ms
2s
10s
```

uma previsão de weather pode durar:

```text
minutos
horas
```

O tipo da ordem depende disso.

---

# PARTE 17 — MAKER VS TAKER ENGINE

Decida dinamicamente.

### MAKER

Prefira quando:

- edge persiste;
- spread compensa;
- fill probability aceitável;
- adverse selection controlada.

### TAKER

Use apenas quando:

- informação tem half-life curta;
- esperar significa perder o edge;
- liquidez suporta o tamanho;
- NET EXPECTED EDGE após fee/slippage ainda é positivo.

Calcule:

```text
EV_maker
EV_taker
```

Escolha o maior.

---

# PARTE 18 — EXECUTION ENGINE

Esta parte NÃO pode depender de LLM.

Implemente de maneira assíncrona.

Deve suportar:

```text
place order
post-only
marketable limit
cancel
cancel/replace
partial fills
batch orders se útil
order timeout
position synchronization
reconnect
heartbeat
stale order detection
duplicate-order protection
idempotency
```

Mantenha máquina de estados de cada ordem.

Exemplo:

```text
CREATED
SUBMITTED
ACKNOWLEDGED
PARTIAL
FILLED
CANCEL_PENDING
CANCELED
REJECTED
EXPIRED
```

Nunca inferir fill apenas porque a ordem desapareceu.

Confirme pelo feed autenticado/API.

---

# PARTE 19 — DATA STALENESS

Todo dado deve possuir timestamp.

Implemente:

```text
MAX_DATA_AGE
```

por feed.

Se qualquer feed crítico ficar stale:

```text
BLOCK NEW TRADES
```

Se necessário:

```text
CANCEL OPEN ORDERS
```

---

# PARTE 20 — LATENCY METRICS

Meça:

```text
market_data_latency
feature_latency
signal_latency
risk_latency
order_build_latency
network_latency
ack_latency
fill_latency
cancel_latency
```

Use histogramas e percentis:

```text
p50
p90
p95
p99
p99.9
```

Nunca otimize latência por suposição.

PROFILE primeiro.

---

# PARTE 21 — RISK ENGINE

O Risk Engine tem poder de VETO absoluto.

Mesmo um signal com score 100 NÃO pode ignorá-lo.

Controles necessários:

```text
max_order_size
max_market_exposure
max_category_exposure
max_correlated_exposure
max_total_exposure
max_daily_loss
max_session_loss
max_drawdown
max_open_orders
max_concurrent_markets
max_slippage
max_spread
max_data_age
max_order_latency
cooldown_after_losses
```

Todos configuráveis.

---

# KILL SWITCHES

Implemente kill switch automático para:

- WebSocket crítico morto;
- API inconsistente;
- estado da posição divergente;
- P&L impossível;
- repeated order rejects;
- excessive latency;
- abnormal slippage;
- drawdown excedido;
- data feed divergente;
- authentication failure;
- duplicated orders;
- runaway process.

Kill switch deve:

```text
1. bloquear novas ordens
2. cancelar ordens pendentes quando seguro
3. preservar logs
4. emitir alerta
5. exigir recuperação explícita
```

---

# PARTE 22 — POSITION SIZING

Não use martingale.

Não aumente posição automaticamente após loss para recuperar prejuízo.

Construa sizing baseado em:

```text
edge
confidence
liquidity
volatility
correlation
current exposure
drawdown
```

Fractional Kelly pode ser estudado e comparado, mas deve ser:

- fortemente limitado;
- validado em backtest;
- cercado por hard caps.

Todos os parâmetros live devem estar em configuração.

---

# PARTE 23 — P&L VELOCITY

Como o objetivo inclui encontrar mercados capazes de movimentar P&L rapidamente, crie:

# PNL VELOCITY SCORE

Exemplo de unidade:

```text
expected_net_pnl / expected_holding_time
```

Mas NÃO maximize isso isoladamente.

A função de seleção deverá considerar algo como:

```text
risk_adjusted_expected_pnl_velocity
```

Isto evita escolher apenas apostas extremamente voláteis.

Considere:

```text
expected return
expected holding time
variance
max adverse excursion
liquidity
slippage
tail risk
```

---

# PARTE 24 — PORTFOLIO ALLOCATION

Quando vários mercados estiverem quentes ao mesmo tempo:

não distribua capital cegamente.

Considere:

```text
expected net edge
opportunity score
PnL velocity
correlation
liquidity
category concentration
existing positions
```

Evite exposição duplicada.

Exemplo:

BTC 5m e ETH 5m podem representar praticamente a mesma aposta macro em determinados regimes.

---

# PARTE 25 — REGIME DETECTION

Construa detectores de regime.

Crypto:

```text
low volatility
normal
high volatility
trend
mean reversion
news shock
liquidity vacuum
```

Sports:

```text
pre-game
early live
mid-game
late-game
overtime
```

Weather:

```text
forecast uncertainty high
forecast converging
observation phase
near-resolution
```

Estratégias podem ser habilitadas/desabilitadas conforme o regime.

---

# PARTE 26 — BACKTEST ENGINE

Construa um backtester EVENT-DRIVEN.

Não aceite backtests baseados apenas em candles quando a estratégia usa orderbook.

Suporte replay de:

- trades;
- orderbook;
- market prices;
- underlying data;
- event states.

Simule:

```text
latency
fees
spread
slippage
partial fills
queue uncertainty
maker fill probability
taker delay
order rejection
data gaps
```

Use parâmetros HISTÓRICOS corretos para a data testada.

Não aplique regras atuais a dados antigos sem marcar explicitamente a transformação.

---

# PARTE 27 — ANTI-OVERFITTING

Obrigatório:

```text
train
validation
out-of-sample
walk-forward
```

Quando aplicável:

- purged validation;
- embargo;
- rolling windows;
- Monte Carlo;
- parameter stability analysis.

Não escolha estratégia pelo melhor P&L absoluto.

Compare:

```text
expectancy
Sharpe-like metrics
Sortino
max drawdown
profit factor
win rate
avg win
avg loss
tail losses
trade count
stability
performance by regime
performance by month
```

---

# PARTE 28 — PAPER / SHADOW / LIVE

Implemente modos:

```text
BACKTEST
PAPER
SHADOW
LIVE
```

### PAPER

Simula execução.

### SHADOW

Recebe dados reais e gera decisões reais, mas NÃO envia ordem.

Registre:

```text
would_buy
would_sell
expected_price
actual_price_after_signal
simulated_fill
```

### LIVE

Permitido somente depois que acceptance tests forem aprovados.

---

# PARTE 29 — AUTO-TUNER

Construa auto-tuning OFFLINE.

Ele pode sugerir alterações em:

```text
thresholds
weights
market filters
execution rules
risk limits dentro de bounds previamente autorizados
```

Mas:

NÃO permita que um LLM altere parâmetros de produção automaticamente após observar algumas perdas.

Fluxo obrigatório:

```text
hypothesis
↓
historical backtest
↓
out-of-sample
↓
walk-forward
↓
paper
↓
shadow
↓
promotion gate
↓
live
```

---

# PARTE 30 — EXPERIMENT TRACKING

Cada estratégia deve possuir:

```text
strategy_id
version
git_commit
feature_set_version
parameters
dataset_version
backtest_id
deployment_time
```

Um trade deve ser reproduzível.

---

# PARTE 31 — DATABASE

Projete armazenamento apropriado para:

### MARKET DATA

High-frequency.

### TRADES

Todas as operações.

### ORDERS

Lifecycle completo.

### FEATURES

Features usadas no momento da decisão.

### SIGNALS

Inclusive sinais recusados.

### RISK DECISIONS

Por que uma ordem foi bloqueada.

### AI ANALYSIS

Relatórios do Grok/Kimi separados da execução real.

Considere inicialmente:

```text
PostgreSQL/TimescaleDB
Parquet
```

ou alternativa melhor justificada.

Não adicione infraestrutura complexa sem necessidade.

---

# PARTE 32 — EVENT ARCHITECTURE

O hot path deve evitar dependências remotas desnecessárias.

Arquitetura desejada:

```text
                       ┌───────────────┐
                       │   GROK BOT    │
                       │ Supervisor    │
                       └───────┬───────┘
                               │
                         KIMI K3 API
                               │
                               ▼
                       Research Layer


POLYMARKET ────┐
               │
CRYPTO FEEDS ──┤
               │
SPORTS ────────┤
               ▼
        MARKET DATA BUS
               │
               ▼
        FEATURE ENGINE
               │
        ┌──────┴──────┐
        │             │
        ▼             ▼
 HOT MARKET      FAIR VALUE
   ENGINE          ENGINE
        │             │
        └──────┬──────┘
               ▼
        STRATEGY ENGINE
               │
               ▼
          RISK ENGINE
               │
               ▼
       EXECUTION ENGINE
               │
               ▼
          POLYMARKET
```

---

# PARTE 33 — HOT PATH VS COLD PATH

## HOT PATH

Proibido:

- LLM calls;
- web scraping;
- slow database queries;
- heavy logging sync;
- browser automation.

Permitido:

- memory;
- WebSocket;
- async code;
- precomputed features;
- fast risk checks;
- order API.

## COLD PATH

Pode usar:

- Grok;
- Kimi;
- PostgreSQL;
- analytics;
- research;
- reports;
- backtests.

---

# PARTE 34 — SOFTWARE STACK

Escolha a melhor implementação depois de profiling.

Preferência inicial:

```text
Python 3.12+
asyncio
uvloop quando suportado
typed models
official Polymarket SDK
WebSockets
NumPy/Polars
Pydantic
PostgreSQL
Parquet
Docker
pytest
```

Se profiling demonstrar gargalo real:

avalie mover partes críticas para Rust.

NÃO reescreva tudo em Rust apenas para parecer "mais profissional".

---

# PARTE 35 — OBSERVABILITY

Implemente métricas.

Dashboard deve mostrar:

```text
equity
realized pnl
unrealized pnl
daily pnl
drawdown

trades/min
win rate
expectancy

fees
slippage
maker ratio
taker ratio
fill ratio

hot markets
opportunity score

exposure by market
exposure by category

signal latency
order latency
WebSocket health
API errors
```

Utilize:

```text
Prometheus
Grafana
```

ou alternativa equivalente.

Logs:

JSON estruturado.

---

# PARTE 36 — ALERTS

Alertar em:

```text
kill switch
large drawdown
unexpected exposure
API disconnected
WebSocket stale
high slippage
high latency
auth failure
position mismatch
strategy disabled
process restart
```

Nunca logar secrets.

---

# PARTE 37 — SECURITY ARCHITECTURE

O Grok Bot utiliza uma máquina persistente compartilhada entre seus Bots.

Por isso:

NÃO trate outro Grok Bot como isolamento de credenciais.

Idealmente:

```text
GROK BOT VM
      ↓
narrow authenticated API
      ↓
TRADING EXECUTOR / SIGNER
      ↓
POLYMARKET
```

O executor deve possuir somente as capacidades estritamente necessárias.

Não exponha função genérica como:

```text
execute_arbitrary_transaction()
```

Prefira endpoints estreitos:

```text
place_order()
cancel_order()
get_positions()
get_orders()
```

Não dê ao componente de IA capacidade de saque.

---

# PARTE 38 — TESTING

Crie:

```text
unit tests
integration tests
WebSocket tests
reconnection tests
order lifecycle tests
risk tests
PnL accounting tests
fee tests
partial-fill tests
stale-data tests
kill-switch tests
replay tests
```

Crie mocks das APIs para CI.

---

# PARTE 39 — FAILURE INJECTION

Teste deliberadamente:

```text
disconnect WebSocket
500 API
429
timeout
corrupted message
duplicate event
out-of-order event
stale price
partial fill
cancel race
position mismatch
database down
clock drift
```

O bot deve falhar de forma segura.

---

# PARTE 40 — CLOCK

Trading depende de tempo.

Implemente:

```text
NTP clock monitoring
server-time comparison
monotonic clocks para latency
UTC internally
```

Todos os eventos devem possuir timestamps normalizados.

---

# PARTE 41 — TIME-TO-RESOLUTION

Use:

```text
time_to_event
time_to_start
time_to_resolution
time_to_market_close
```

como features.

Mercados frequentemente ficam mais sensíveis conforme a resolução/evento se aproxima.

---

# PARTE 42 — RESOLUTION PARSER

Cada mercado deverá possuir um objeto estruturado:

```json
{
  "resolution_source": "...",
  "metric": "...",
  "threshold": "...",
  "time_window": "...",
  "timezone": "...",
  "rounding_rule": "...",
  "special_conditions": []
}
```

Se as regras não puderem ser interpretadas com confiança:

```text
DO_NOT_TRADE
```

---

# PARTE 43 — DYNAMIC WATCHLIST

A watchlist NÃO é manual.

Processo:

```text
ALL ACTIVE MARKETS
      ↓
BASIC FILTER
      ↓
HMS
      ↓
HOT MARKET POOL
      ↓
DEEP DATA
      ↓
OPPORTUNITY SCORE
      ↓
STRATEGY
```

Mercados devem entrar e sair automaticamente.

---

# PARTE 44 — BASIC FILTER

Antes de gastar recursos:

elimine:

```text
closed
not accepting orders
broken market
unknown resolution
extremely poor liquidity
extreme spread
stale market
unsupported structure
risk-blocked market
```

---

# PARTE 45 — MARKET MICROSTRUCTURE FEATURES

Implemente, onde os dados permitirem:

```text
bid/ask spread
midprice
microprice
top-N depth
weighted imbalance
order flow imbalance
trade imbalance
cancel imbalance
book slope
depth convexity
liquidity gaps
price impact
VWAP to depth levels
book replenishment
spread regime
trade intensity
quote intensity
```

Não use indicadores simplesmente por existirem.

Toda feature precisa de hipótese econômica.

---

# PARTE 46 — SIGNAL QUALITY

Cada decisão deve produzir algo semelhante a:

```json
{
  "market": "...",
  "strategy": "...",
  "fair_probability": 0.61,
  "execution_price": 0.55,
  "gross_edge": 0.06,
  "expected_fee": 0.00,
  "expected_slippage": 0.00,
  "latency_penalty": 0.00,
  "net_edge": 0.00,
  "confidence": 0.00,
  "signal_half_life_ms": 0,
  "hot_market_score": 0,
  "opportunity_score": 0,
  "decision": "TRADE | SKIP",
  "reason_codes": []
}
```

Isso deve ser persistido para auditoria.

---

# PARTE 47 — WHY NO TRADE

Registre também oportunidades recusadas.

Reason codes:

```text
EDGE_TOO_SMALL
SPREAD_TOO_LARGE
SLIPPAGE_TOO_HIGH
STALE_DATA
LOW_LIQUIDITY
LOW_CONFIDENCE
RISK_LIMIT
UNKNOWN_RESOLUTION
CORRELATED_EXPOSURE
SIGNAL_EXPIRED
MARKET_NOT_HOT
```

Isso é essencial para melhorar o sistema.

---

# PARTE 48 — DAILY AI REVIEW

Crie uma Skill do Grok chamada aproximadamente:

```text
/hotflow-daily-review
```

Ela deverá:

1. carregar resultados;
2. calcular métricas;
3. separar por mercado;
4. separar por estratégia;
5. separar maker/taker;
6. analisar slippage;
7. detectar anomalias;
8. consultar Kimi quando necessário;
9. produzir recomendações;
10. NÃO alterar produção.

---

# PARTE 49 — STRATEGY EXPERIMENT SKILL

Crie:

```text
/hotflow-experiment
```

Fluxo:

```text
hypothesis
→ implementation branch
→ test
→ backtest
→ OOS
→ walk-forward
→ report
```

Nunca substituir a estratégia live automaticamente.

---

# PARTE 50 — INCIDENT RESPONSE SKILL

Crie:

```text
/hotflow-incident
```

A Skill deverá:

- congelar alterações;
- coletar logs;
- coletar métricas;
- identificar primeiro erro;
- reconstruir timeline;
- detectar root cause;
- recomendar correção;
- criar regression test.

---

# PARTE 51 — DOCUMENTATION WATCH ROUTINE

Crie uma Routine periódica de pesquisa.

Objetivo:

verificar alterações relevantes em:

```text
Polymarket API
fees
resolution
WebSocket
rate limits
SDK
authentication
crypto TWAP
sports
```

Se houver mudança:

produza alerta e issue.

NÃO atualize produção automaticamente.

---

# PARTE 52 — PERFORMANCE REVIEW

Para cada estratégia, produza:

```text
Gross PnL
Net PnL
Fees
Slippage
PnL / trade
PnL / hour
PnL velocity
Win rate
Profit factor
Max drawdown
MAE
MFE
Average holding time
Maker fill rate
Taker performance
```

---

# PARTE 53 — ALPHA DECAY

Verifique se estratégias estão degradando.

Compare:

```text
recent 50
recent 100
recent 500
baseline
```

Não tire conclusões fortes de amostras pequenas.

Use intervalos de confiança.

---

# PARTE 54 — CAPITAL PRESERVATION

A prioridade do sistema é:

```text
1. sobreviver
2. preservar capital
3. executar corretamente
4. encontrar edge
5. escalar
```

Não:

```text
1. maximizar número de trades
```

Se não houver edge:

**não negocie.**

`NO TRADE` é uma decisão válida.

---

# PARTE 55 — REPOSITORY

Crie estrutura profissional aproximadamente:

```text
hotflow/
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── configs/
├── docs/
│   ├── architecture.md
│   ├── strategy.md
│   ├── risk.md
│   ├── security.md
│   ├── runbook.md
│   └── deployment.md
├── src/
│   ├── discovery/
│   ├── marketdata/
│   ├── hotmarket/
│   ├── features/
│   ├── fairvalue/
│   ├── strategies/
│   │   ├── crypto/
│   │   ├── weather/
│   │   ├── sports/
│   │   └── esports/
│   ├── risk/
│   ├── execution/
│   ├── portfolio/
│   ├── storage/
│   ├── analytics/
│   ├── ai_research/
│   └── monitoring/
├── tests/
├── backtests/
├── scripts/
└── dashboards/
```

Adapte se houver arquitetura melhor.

---

# PARTE 56 — CONFIGURATION

Estratégias e risco devem ser configuráveis.

Exemplo:

```yaml
trading:
  mode: paper

scanner:
  enabled: true

hot_market:
  minimum_score: ...

risk:
  max_order_size: ...
  max_market_exposure: ...
  max_total_exposure: ...
  max_daily_loss: ...

crypto:
  enabled: true

weather:
  enabled: true

sports:
  enabled: true

esports:
  enabled: true
```

Não espalhe magic numbers pelo código.

---

# PARTE 57 — CI/CD

Configure pipeline contendo:

```text
lint
typecheck
tests
security checks
backtest smoke test
build
```

Live deployment exige release gate.

---

# PARTE 58 — IMPLEMENTATION PHASES

Não pare depois de escrever plano.

Execute as fases.

## PHASE 0

Pesquisa atual.

## PHASE 1

Repository + interfaces.

## PHASE 2

Polymarket discovery.

## PHASE 3

WebSocket market data.

## PHASE 4

Storage.

## PHASE 5

Hot Market Engine.

## PHASE 6

Crypto engine.

## PHASE 7

Risk + execution.

## PHASE 8

Backtester.

## PHASE 9

Weather/Sports/Esports adapters.

## PHASE 10

Kimi integration.

## PHASE 11

Observability.

## PHASE 12

Paper trading.

## PHASE 13

Shadow trading.

## PHASE 14

Production readiness review.

---

# PARTE 59 — ACCEPTANCE CRITERIA

O projeto não está pronto porque "compila".

Considere pronto para PAPER quando:

- scanner funciona;
- reconnect funciona;
- data staleness funciona;
- hot-market classification funciona;
- fees são obtidas corretamente;
- risk engine funciona;
- accounting funciona;
- tests passam;
- logs funcionam.

Considere pronto para SHADOW quando:

- paper está estável;
- signal logging está completo;
- simulated fills são razoáveis;
- data loss é detectado;
- performance pode ser reproduzida.

Considere pronto para LIVE somente após:

- shadow consistente;
- zero bugs críticos conhecidos;
- failure injection aprovado;
- risk controls testados;
- kill switch testado;
- secrets isolados;
- accounting reconciliado.

---

# PARTE 60 — NÃO FAÇA

Não:

- invente endpoints;
- invente dados;
- use APIs antigas sem validar;
- hardcode fees;
- hardcode TWAP;
- hardcode delays;
- ignore slippage;
- ignore spread;
- ignore partial fills;
- ignore latency;
- usar future data em backtest;
- usar LLM para cada tick;
- permitir LLM controlar wallet;
- armazenar private key no Git;
- usar martingale;
- aumentar risco depois de loss;
- chamar toda volatilidade de edge;
- escolher estratégias apenas pelo maior backtest P&L;
- operar mercado cuja regra não foi compreendida;
- assumir que um order placement foi fill;
- operar com WebSocket stale;
- esconder perdas ou trades ruins dos relatórios.

---

# PARTE 61 — NÃO PERGUNTE O QUE VOCÊ PODE DESCOBRIR

Se informação técnica puder ser obtida:

- pela documentação;
- pelo código;
- pelo ambiente;
- pela API;
- por teste;

descubra sozinho.

Pergunte ao usuário somente quando realmente precisar de algo que não possa descobrir, como uma credencial ou autorização humana.

---

# PARTE 62 — CREDENCIAIS

Quando chegar a etapa que exige API keys:

pare somente naquela dependência específica.

Continue construindo tudo que puder com:

```text
mock
paper mode
public APIs
fixtures
```

Informe exatamente qual variável precisa.

Exemplo:

```text
KIMI_API_KEY
POLYMARKET_WALLET_ADDRESS
```

Nunca peça seed phrase.

---

# PARTE 63 — RELATÓRIO FINAL

Ao terminar cada grande milestone, me informe:

```text
IMPLEMENTED
TESTED
NOT YET IMPLEMENTED
KNOWN RISKS
CURRENT PERFORMANCE
NEXT HIGHEST-VALUE STEP
```

Se algo falhar, diga exatamente o que falhou.

Não esconda limitações.

---

# PARTE 64 — OBJETIVO DE OTIMIZAÇÃO FINAL

O sistema NÃO deve maximizar:

```text
number_of_trades
```

nem:

```text
win_rate
```

isoladamente.

Objetivo conceitual:

```text
MAXIMIZE

long-term risk-adjusted net expectancy

subject to:

capital preservation
execution realism
liquidity
fees
slippage
latency
drawdown limits
```

Com preferência operacional por mercados que apresentem:

```text
high information velocity
+
high probability velocity
+
sufficient liquidity
+
short opportunity half-life
+
positive NET edge
```

---

# COMECE AGORA

Sua primeira ação deve ser:

1. inspecionar o ambiente disponível;
2. consultar a documentação oficial atual de Grok Bot, Kimi K3 e Polymarket;
3. registrar em `docs/research-current.md` o que é válido atualmente;
4. definir a arquitetura;
5. criar o repositório;
6. implementar a primeira versão;
7. executar testes;
8. corrigir os problemas encontrados;
9. avançar para o próximo componente.

Não responda apenas com uma arquitetura hipotética.

**Construa o sistema.**

O resultado desejado é um trading system profissional capaz de descobrir automaticamente onde o mercado está mais ativo, concentrar recursos nesses mercados e operar somente quando houver vantagem estatística e de execução suficiente após todos os custos.
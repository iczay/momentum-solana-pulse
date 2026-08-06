# Solana Pulse

**An automatically updating report on the state of the Solana ecosystem.**

Live dashboard: enable GitHub Pages on this repo (Settings → Pages → deploy from `main`, root) and it serves at `https://iczay.github.io/momentum-solana-pulse/`.

Built for the Superteam Canada bounty *"Develop Solana Ecosystem Auto-Updating Report & Interactive Dashboard."*

---

## What it does

`collect.py` gathers a full snapshot of Solana's network health and economics, writes it to `data.json`, and appends a row to `history.jsonl` so trends accumulate over time. A GitHub Actions workflow runs it **every hour** and commits the result, so the report is never stale and needs no server, no database, and no babysitting.

`index.html` is a static dashboard that reads `data.json`. No build step, no framework, no npm install. Open the file and it works.

## Design principles

Three rules drove every decision here:

1. **Every number is fetched, never asserted.** There are no hardcoded figures in this report. If a metric is on the dashboard, `collect.py` pulled it from a named source this hour, and `data.json` records which source.
2. **A dead upstream degrades one tile, not the whole report.** Every fetch is wrapped in `safe()`. If CoinGecko rate-limits or DeFiLlama has a bad minute, that metric becomes `—`, the failure is written into `data.json`'s `errors` array, and the dashboard shows a banner naming exactly what failed. Silent gaps are worse than reported ones — a dashboard that hides its own failures is a dashboard that lies.
3. **Zero dependencies.** Python standard library only. Nothing to `pip install`, nothing to audit, no supply chain, no lockfile drift. It will still run in five years.

## Metrics collected

**Network performance** (Solana RPC)
- Live TPS, 1-hour average TPS, 1-hour peak TPS
- Non-vote TPS — real user activity, separated from consensus traffic
- Average slot time against the 400 ms target
- Epoch number and progress, absolute slot, block height
- Cluster health (`getHealth`)

**Validators and decentralisation** (Solana RPC)
- Active vs. delinquent validator count, and delinquency as a share of the set
- **Nakamoto coefficient** — how many validators would have to collude to halt the chain, computed by walking the sorted stake distribution to the 33% threshold. This is the single most honest decentralisation number available, and it is derived here rather than quoted.
- Top-10 stake concentration, total active stake (in SOL and USD)
- Average commission across the active set
- Top 10 validators by stake, with individual share and commission

**Economics** (DeFiLlama, CoinGecko)
- SOL price, market cap, 24h change and volume
- DeFi TVL with 7-day and 30-day change
- Stablecoin supply on Solana with 30-day change
- DEX volume (24h and 7d) and network fees / Real Economic Value (24h and 7d)
- Derived: annualised fees, and a fees-to-market-cap ratio — a price-to-fees multiple for the network

**Supply** (Solana RPC)
- Total and circulating SOL, circulating percentage

## Sample output

From a real run (epoch 1012, 2026-08-06):

| Metric | Value |
|---|---|
| TPS (1h avg) | 4,087 |
| Non-vote TPS | 3,673 |
| Avg slot time | 0.421 s |
| Active validators | 693 |
| Delinquent | 7 (1.00%) |
| Nakamoto coefficient | 18 |
| Top-10 stake share | 24.35% |
| DeFi TVL | $4.75B (−7.53% 30d) |
| Stablecoin supply | $3.16B (+24.38% 30d) |
| DEX volume 24h | $1.64B |
| Network fees 24h | $7.78M |
| Circulating supply | 581.3M SOL (92.03%) |

Note the story those last numbers tell together: TVL is down 7.5% over 30 days while stablecoin supply is up 24.4%. Capital is arriving on the chain but sitting in stables rather than entering DeFi positions — a risk-off posture inside a growing deposit base, which a TVL figure alone would misread as decline.

## Running it

```bash
git clone https://github.com/iczay/momentum-solana-pulse
cd momentum-solana-pulse
python3 collect.py        # writes data.json + appends history.jsonl
python3 -m http.server 8000
# open http://localhost:8000
```

Point it at your own RPC if the public endpoint rate-limits you:

```bash
SOLANA_RPC=https://your-endpoint.example/ python3 collect.py
```

## Automation

`.github/workflows/update.yml` runs hourly on a cron schedule (and on demand via *Run workflow*). It executes the collector and commits `data.json` and `history.jsonl` only when something changed, so the history stays clean. Refresh interval is one line in the workflow.

Because `history.jsonl` is append-only and committed, the repo accumulates a real time series of Solana's health, one row per hour — usable directly for charting without any external storage.

## Data sources

| Domain | Source |
|---|---|
| On-chain | Solana JSON-RPC (`api.mainnet-beta.solana.com`, configurable) |
| TVL, stablecoins, DEX volume, fees | [DeFiLlama](https://defillama.com/chain/Solana) |
| Price and market cap | [CoinGecko](https://www.coingecko.com/en/coins/solana) |

## Roadmap

- Sparklines rendered from `history.jsonl` once it has accumulated depth
- Dune Analytics integration for tokenised-equity volume and daily active addresses
- Tracking of upcoming protocol upgrades (Alpenglow, SIMD-525)
- Delinquency alerting when a validator drops out of the active set

## License

MIT.

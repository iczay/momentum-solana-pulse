#!/usr/bin/env python3
"""solana-pulse: collect a full snapshot of Solana network + economic health.

Pure standard library. No API keys. Writes data.json (current) and appends to
history.jsonl so the dashboard can draw trends. Every metric records its source
so the report is auditable rather than asserted.
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
UA  = {"User-Agent": "solana-pulse/1.0 (+https://github.com/iczay/momentum-solana-pulse)",
       "Accept": "application/json"}
HERE = os.path.dirname(os.path.abspath(__file__))

def http(url, timeout=30):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))

def rpc(method, params=None, timeout=30):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or []}).encode()
    req = urllib.request.Request(RPC, data=body,
                                 headers={"Content-Type": "application/json", **UA})
    return json.load(urllib.request.urlopen(req, timeout=timeout)).get("result")

ERRORS = []

def safe(label, fn, default=None):
    """Never let one dead upstream kill the whole report."""
    try:
        return fn()
    except Exception as e:
        print(f"  ! {label}: {type(e).__name__}: {e}", file=sys.stderr)
        ERRORS.append({"metric": label, "error": f"{type(e).__name__}: {e}"})
        return default

def collect():
    snap = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": {}}

    # ---------- network performance (Solana RPC) ----------
    ep = safe("getEpochInfo", lambda: rpc("getEpochInfo"), {})
    if ep:
        snap["epoch"] = {
            "epoch": ep["epoch"],
            "slot_index": ep["slotIndex"],
            "slots_in_epoch": ep["slotsInEpoch"],
            "progress_pct": round(100 * ep["slotIndex"] / ep["slotsInEpoch"], 2),
            "absolute_slot": ep["absoluteSlot"],
            "block_height": ep.get("blockHeight"),
        }

    perf = safe("getRecentPerformanceSamples",
                lambda: rpc("getRecentPerformanceSamples", [60]), [])
    if perf:
        tps = [s["numTransactions"] / s["samplePeriodSecs"] for s in perf]
        non_vote = [s.get("numNonVoteTransactions", 0) / s["samplePeriodSecs"] for s in perf]
        slot_time = [s["samplePeriodSecs"] / s["numSlots"] for s in perf if s["numSlots"]]
        snap["performance"] = {
            "tps_latest": round(tps[0], 1),
            "tps_avg_1h": round(sum(tps) / len(tps), 1),
            "tps_peak_1h": round(max(tps), 1),
            "non_vote_tps_latest": round(non_vote[0], 1),
            "avg_slot_time_s": round(sum(slot_time) / len(slot_time), 3) if slot_time else None,
            "samples": len(perf),
        }

    health = safe("getHealth", lambda: rpc("getHealth"))
    snap["health"] = "ok" if health == "ok" else str(health)

    # ---------- validators & stake decentralisation ----------
    va = safe("getVoteAccounts", lambda: rpc("getVoteAccounts"), {})
    if va:
        cur, delin = va.get("current", []), va.get("delinquent", [])
        stakes = sorted((v["activatedStake"] for v in cur), reverse=True)
        total = sum(stakes) or 1
        # Nakamoto coefficient: how many validators to reach 33% of stake
        run, nakamoto = 0, 0
        for s in stakes:
            run += s; nakamoto += 1
            if run > total * 0.33:
                break
        top = sorted(cur, key=lambda v: -v["activatedStake"])[:10]
        snap["validators"] = {
            "active": len(cur),
            "delinquent": len(delin),
            "delinquent_pct": round(100 * len(delin) / (len(cur) + len(delin)), 2) if cur else None,
            "total_active_stake_sol": round(total / 1e9),
            "nakamoto_coefficient": nakamoto,
            "top10_stake_pct": round(100 * sum(stakes[:10]) / total, 2),
            "avg_commission_pct": round(sum(v.get("commission", 0) for v in cur) / len(cur), 2) if cur else None,
            "top_validators": [{"vote_account": v["votePubkey"],
                                "stake_sol": round(v["activatedStake"] / 1e9),
                                "stake_pct": round(100 * v["activatedStake"] / total, 3),
                                "commission_pct": v.get("commission")} for v in top],
        }

    sup = safe("getSupply", lambda: rpc("getSupply",
               [{"excludeNonCirculatingAccountsList": True}]).get("value"), {})
    if sup:
        snap["supply"] = {
            "total_sol": round(sup["total"] / 1e9),
            "circulating_sol": round(sup["circulating"] / 1e9),
            "circulating_pct": round(100 * sup["circulating"] / sup["total"], 2),
        }
    snap["sources"]["onchain"] = RPC

    # ---------- economics (DeFiLlama, CoinGecko) ----------
    def tvl():
        d = http("https://api.llama.fi/v2/historicalChainTvl/Solana")
        cur = d[-1]["tvl"]
        wk  = d[-8]["tvl"] if len(d) > 8 else None
        mo  = d[-31]["tvl"] if len(d) > 31 else None
        return {"tvl_usd": cur,
                "change_7d_pct":  round(100 * (cur - wk) / wk, 2) if wk else None,
                "change_30d_pct": round(100 * (cur - mo) / mo, 2) if mo else None}
    snap["defi"] = safe("defillama_tvl", tvl, {})

    def stables():
        d = http("https://stablecoins.llama.fi/stablecoincharts/Solana?stablecoin=1")
        cur = d[-1]["totalCirculatingUSD"]["peggedUSD"]
        mo  = d[-31]["totalCirculatingUSD"]["peggedUSD"] if len(d) > 31 else None
        return {"stablecoin_supply_usd": cur,
                "change_30d_pct": round(100 * (cur - mo) / mo, 2) if mo else None}
    snap["stablecoins"] = safe("defillama_stables", stables, {})

    def dex():
        d = http("https://api.llama.fi/overview/dexs/solana"
                 "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true")
        return {"volume_24h_usd": d.get("total24h"), "volume_7d_usd": d.get("total7d"),
                "change_1d_pct": d.get("change_1d")}
    snap["dex"] = safe("defillama_dex", dex, {})

    def fees():
        d = http("https://api.llama.fi/overview/fees/solana"
                 "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true")
        return {"fees_24h_usd": d.get("total24h"), "fees_7d_usd": d.get("total7d"),
                "change_1d_pct": d.get("change_1d")}
    snap["fees"] = safe("defillama_fees", fees, {})

    def price():
        d = http("https://api.coingecko.com/api/v3/simple/price?ids=solana"
                 "&vs_currencies=usd&include_market_cap=true&include_24hr_change=true"
                 "&include_24hr_vol=true")["solana"]
        return {"price_usd": d["usd"], "market_cap_usd": d.get("usd_market_cap"),
                "change_24h_pct": round(d.get("usd_24h_change", 0), 2),
                "volume_24h_usd": d.get("usd_24h_vol")}
    snap["market"] = safe("coingecko_price", price, {})

    snap["sources"].update({
        "defi": "https://defillama.com/chain/Solana",
        "market": "https://www.coingecko.com/en/coins/solana",
    })

    # ---------- derived: network price-to-fees ----------
    px = (snap.get("market") or {}).get("price_usd")
    f24 = (snap.get("fees") or {}).get("fees_24h_usd")
    if px and f24:
        mcap = (snap.get("market") or {}).get("market_cap_usd")
        snap["derived"] = {"annualised_fees_usd": round(f24 * 365),
                           "fees_to_mcap_ratio": round(f24 * 365 / mcap, 5) if mcap else None}

    snap["errors"] = ERRORS
    snap["ok"] = len(ERRORS) == 0
    return snap

def main():
    print("collecting solana-pulse snapshot ...")
    snap = collect()
    with open(os.path.join(HERE, "data.json"), "w") as f:
        json.dump(snap, f, indent=2)
    with open(os.path.join(HERE, "history.jsonl"), "a") as f:
        f.write(json.dumps({
            "t": snap["generated_at"],
            "tps": (snap.get("performance") or {}).get("tps_avg_1h"),
            "price": (snap.get("market") or {}).get("price_usd"),
            "tvl": (snap.get("defi") or {}).get("tvl_usd"),
            "stables": (snap.get("stablecoins") or {}).get("stablecoin_supply_usd"),
            "dex_vol": (snap.get("dex") or {}).get("volume_24h_usd"),
            "validators": (snap.get("validators") or {}).get("active"),
            "delinquent": (snap.get("validators") or {}).get("delinquent"),
            "nakamoto": (snap.get("validators") or {}).get("nakamoto_coefficient"),
        }) + "\n")
    print(f"wrote data.json ({len(ERRORS)} upstream errors)")
    return 0

if __name__ == "__main__":
    sys.exit(main())

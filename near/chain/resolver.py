"""The stake resolver's numbers (F76, F80): one stake batch's net results and pot change, integers only.

Per staked account, from the batch's sealed lives (INFERRED where prd §4.3/§4.4 leave it open):
  * a life draws at most the per-life stake (0.01 NEAR, F76), and only from stake parts (each lock and
    top-up, with the block time it landed, from `market.batch_stakes`) that landed at least 30 s before the
    life's earliest possible start. Lives draw in lock order, so a top-up made after a life's
    result was public can never reach that life;
  * a life with at least 1 KO pays its draw * (1 + base score - AI score) (`quote.payout`'s formula, on
    the room's basis-point spread); a 0-KO life pays nothing and its draw goes to the pot;
  * stake no life drew returns whole (net 0): a stake is never lost for a life it did not cover;
  * gains are paid from the pot (what came in this batch plus what was there); if they exceed it, every
    gain is scaled down in proportion (floor), so the pot never goes below zero;
  * what is left in the pot is recycled to the accounts whose lives scored at least 1 KO, in proportion
    to what those lives paid out (floor); the rounding residue stays in the pot.
`market.resolve` checks only that it conserves: every open stake one result, no net below -stake, and
stakes plus pot sum to zero. `check()` asserts the same before anything is sent.
"""

from near.house import quote

MICRO, RPS_MAX = quote.MICRO, quote.RPS_MAX


def bins_from_spread(spread_bps: dict) -> tuple:
    """The room's spread ({one, two, three, four_plus} in bps, never on 0) as five bins over 0..4+."""
    return (0, spread_bps["one"], spread_bps["two"], spread_bps["three"], spread_bps["four_plus"])


def life_payout(share: int, bins: tuple, kos: int, base_bps) -> int:
    if kos <= 0:
        return 0
    ai = quote.rps_numerator(bins, kos) * MICRO // RPS_MAX
    base = quote.rps_numerator(tuple(base_bps), kos) * MICRO // RPS_MAX
    return share * (MICRO + base - ai) // MICRO


PER_LIFE = 10 ** 22        # 0.01 NEAR a life (F76)
SKEW_NS = 30 * 10 ** 9     # a part counts for a life only if it landed 30 s before the life's earliest start


def cover(parts, t):
    """The stake that certainly existed at time t (ns): every part (lock or top-up) that landed by then."""
    if t is None:
        return 0
    return sum(int(p["amount"]) for p in parts if int(p["at"]) <= t - SKEW_NS)


def compute(open_stakes: dict, lives: list, pot_before: int, base_bps, parts=None) -> dict:
    """open_stakes: {account: yocto}; lives: [{account, life_id, kos, bins or None, locked_after_ns}].

    parts: {account: [{amount, at}]}, each lock and top-up with the block time it landed (`batch_stakes`).
    """
    parts = parts or {}
    base_net, weight, detail = {}, {}, []
    for account in sorted(open_stakes):
        amount = int(open_stakes[account])
        mine = sorted((l for l in lives if l["account"] == account and l["bins"] is not None),
                      key=lambda l: (l.get("locked_after_ns") or 0, l["life_id"]))
        drawn = returned = 0
        any_ko = False
        for life in mine:
            room = min(amount, cover(parts.get(account, []), life.get("locked_after_ns"))) - drawn
            draw = max(0, min(PER_LIFE, room))
            if draw == 0:
                detail.append({"account_id": account, "life_id": life["life_id"], "draw": "0",
                               "why": "no stake known before this life began"})
                continue
            p = life_payout(draw, life["bins"], life["kos"], base_bps)
            drawn += draw
            returned += p
            any_ko |= life["kos"] >= 1
            detail.append({"account_id": account, "life_id": life["life_id"], "draw": str(draw), "kos": life["kos"],
                           "paid": str(p)})
        base_net[account] = returned - drawn          # undrawn stake comes back whole
        weight[account] = returned if any_ko else 0
        detail.append({"account_id": account, "stake": str(amount), "drawn": str(drawn), "returned": str(returned)})
    losses = sum(-n for n in base_net.values() if n < 0)
    gains = sum(n for n in base_net.values() if n > 0)
    available = pot_before + losses
    net = dict(base_net)
    if gains > available:
        for a in net:
            if net[a] > 0:
                net[a] = net[a] * available // gains
    left = available - sum(n for n in net.values() if n > 0)
    total_w = sum(weight.values())
    if total_w > 0 and left > 0:
        for a in sorted(net):
            net[a] += left * weight[a] // total_w
    pot_delta = -sum(net.values())
    results = [{"account_id": a, "net": str(net[a])} for a in sorted(net)]
    out = {"results": results, "pot_delta": str(pot_delta), "pot_after": str(pot_before + pot_delta), "detail": detail}
    check(open_stakes, out, pot_before)
    return out


def check(open_stakes: dict, out: dict, pot_before: int) -> None:
    """The conservation `market.resolve` enforces, asserted locally first."""
    accounts = [r["account_id"] for r in out["results"]]
    if sorted(accounts) != sorted(open_stakes) or len(set(accounts)) != len(accounts):
        raise ValueError("every open stake needs exactly one result")
    for r in out["results"]:
        if int(r["net"]) < -int(open_stakes[r["account_id"]]):
            raise ValueError("a stake cannot lose more than itself")
    if sum(int(r["net"]) for r in out["results"]) + int(out["pot_delta"]) != 0:
        raise ValueError("stakes and pot must sum to zero")
    if pot_before + int(out["pot_delta"]) < 0:
        raise ValueError("the pot cannot go below zero")


def next_base_rate(actuals: list) -> list:
    """The next published spread: the trailing base rate over every life so far, else the lab number."""
    bins = quote.base_rate_bps(actuals) if actuals else None
    return list(bins or quote.PUBLISHED_BASE_BPS)

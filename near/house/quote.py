"""Prediction math: the ranked probability score, the payout and the calibration readout.

Game code, standard library only, integers only (no float anywhere in a score or a payout).
A prediction is a spread of four whole percents over 1, 2, 3 and 4+ KOs for the coming life, plus
the AI's chance of 0 KOs. It can never bet 0: the four numbers sum to 100 and carry no zero bin.
The life's real KO count scores it over five ordered outcomes (0, 1, 2, 3, 4+) by the ranked
probability score, normalised to 0..1 and held here as micro-units (1,000,000 = 1.0).
"""

from collections import defaultdict

SCALE = 10_000                     # basis points
MICRO = 1_000_000                  # one whole score, in micro-units
RPS_MAX = 4 * SCALE * SCALE        # four cumulative steps, each at most (10,000 bps)^2
MIN_LIVES = 10                     # a readout needs at least this many lives
# The sweep's lab number for default kits (prd 4.4), used until real lives exist.
PUBLISHED_BASE_BPS = (4010, 3470, 1570, 640, 310)


def check_spread(spread_pct, zero_pct):
    """None when valid, else the reason. Floats, bools, negatives and a bet on 0 are refused."""
    if not isinstance(spread_pct, (list, tuple)) or len(spread_pct) != 4:
        return "spread needs four numbers over 1, 2, 3 and 4+ KOs"
    if any(type(x) is not int or x < 0 for x in spread_pct):
        return "spread numbers are whole percents of at least 0"
    if sum(spread_pct) != 100:
        return "spread sums to 100"
    if type(zero_pct) is not int or not 0 <= zero_pct <= 100:
        return "zero_pct is a whole percent from 0 to 100"
    return None


def five_bins(spread_pct):
    """The AI's spread as five basis-point bins: nothing on 0, so it can never bet 0."""
    return (0,) + tuple(x * (SCALE // 100) for x in spread_pct)


def _bin(actual):
    if type(actual) is not int or actual < 0:
        raise ValueError("actual KOs are a whole number of at least 0")
    return min(actual, 4)


def rps_numerator(bins_bps, actual):
    """Sum over the four cumulative steps of (forecast - outcome)^2, in bps^2."""
    if len(bins_bps) != 5 or sum(bins_bps) != SCALE or any(type(x) is not int or x < 0 for x in bins_bps):
        raise ValueError("five non-negative bins totalling 10000 bps")
    hit, cumulative, total = _bin(actual), 0, 0
    for i in range(4):
        cumulative += bins_bps[i]
        total += (cumulative - (SCALE if hit <= i else 0)) ** 2
    return total


def score(spread_pct, actual, zero_pct=0):
    """The AI's ranked probability score in micro-units: 0 is perfect, 1,000,000 is worst."""
    reason = check_spread(spread_pct, zero_pct)
    if reason:
        raise ValueError(reason)
    return rps_numerator(five_bins(spread_pct), actual) * MICRO // RPS_MAX


def base_score(base_bps, actual):
    """The same score for a published base-rate spread, which keeps its real share on 0."""
    return rps_numerator(tuple(base_bps), actual) * MICRO // RPS_MAX


def payout(stake_yocto, spread_pct, actual, base_bps=PUBLISHED_BASE_BPS):
    """stake * (1 + base score - AI score) on a life with at least 1 KO; a 0-KO life pays nothing.

    The whole stake of a 0-KO life goes to the pot, however the life ended (prd 4.4).
    """
    if type(stake_yocto) is not int or stake_yocto < 0:
        raise ValueError("stake is yoctoNEAR, a whole number of at least 0")
    if _bin(actual) == 0:
        return 0
    delta = base_score(base_bps, actual) - score(spread_pct, actual)
    return stake_yocto * (MICRO + delta) // MICRO


def base_rate_bps(actuals):
    """Five bins of basis points from observed KO counts, rounding residue to the largest bin."""
    counts = [0] * 5
    for a in actuals:
        counts[_bin(a)] += 1
    if not actuals:
        return None
    bins = [n * SCALE // len(actuals) for n in counts]
    bins[max(range(5), key=lambda i: (counts[i], -i))] += SCALE - sum(bins)
    return tuple(bins)


def calibration(rows, min_lives=MIN_LIVES, published=PUBLISHED_BASE_BPS):
    """Per persona: skill against its own trailing base rate, and a reliability table.

    rows are log lines with persona, spread_pct, zero_pct, actual, in the order they were written (the log's own
    order). Order is never read from the life key: a key such as "<run>/<who>:life:10" sorts as text before ":life:2",
    and a run prefix sorts by its seed, not by time.
    A life's base rate is the persona's own lives before it (the published spread when none).
    Skill is (base - ai) / base over the same lives, in milli-units; always repeating the
    persona's own base rate scores 0. Under min_lives the skill is None, never a guess.
    """
    by_persona = defaultdict(list)
    for row in rows:
        by_persona[row["persona"]].append(row)
    result = {}
    for persona in sorted(by_persona):
        lives = by_persona[persona]                    # write order, as given
        ai_total = base_total = 0
        priors, zero_buckets = [], defaultdict(lambda: [0, 0, 0])
        spread_sum, spread_hits, scored = [0] * 4, [0] * 4, 0
        for row in lives:
            actual = row["actual"]
            own = base_rate_bps(priors) or tuple(published)
            ai_total += rps_numerator(five_bins(row["spread_pct"]), actual)
            base_total += rps_numerator(own, actual)
            priors.append(actual)
            bucket = zero_buckets[min(row["zero_pct"] // 10, 9)]
            bucket[0] += 1
            bucket[1] += row["zero_pct"]
            bucket[2] += _bin(actual) == 0
            if _bin(actual) >= 1:
                scored += 1
                for i in range(4):
                    spread_sum[i] += row["spread_pct"][i]
                    spread_hits[i] += _bin(actual) == i + 1
        skill = None
        if len(lives) >= min_lives and base_total:
            skill = (base_total - ai_total) * 1000 // base_total
        result[persona] = {
            "lives": len(lives), "skill_milli": skill,
            "reliability_zero": {str(b * 10): {"lives": n, "mean_predicted_pct_milli": p * 1000 // n,
                                               "observed_zero_pct_milli": z * 100_000 // n}
                                 for b, (n, p, z) in sorted(zero_buckets.items())},
            "reliability_spread": {"scored_lives": scored,
                                   "mean_predicted_pct_milli": [s * 1000 // scored for s in spread_sum] if scored else None,
                                   "observed_pct_milli": [h * 100_000 // scored for h in spread_hits] if scored else None},
        }
    return result

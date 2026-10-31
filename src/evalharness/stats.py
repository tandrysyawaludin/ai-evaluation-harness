"""Statistics for evaluation: evals are experiments.

Wilson intervals, seeded bootstrap CIs, McNemar's paired test, and a
sample-size estimator — all standard library.
"""
import math
import random


def wilson_interval(successes, n, z=1.96):
    """Wilson score interval for a proportion. Returns (low, high)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def bootstrap_ci(values, statistic=None, n_boot=2000, seed=123, alpha=0.05):
    """Percentile bootstrap CI for the mean (or a given statistic) of values."""
    if not values:
        return (0.0, 0.0)
    statistic = statistic or (lambda xs: sum(xs) / len(xs))
    rng = random.Random(seed)
    n = len(values)
    stats = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        stats.append(statistic(sample))
    stats.sort()
    lo = stats[int((alpha / 2) * n_boot)]
    hi = stats[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return (lo, hi)


def bootstrap_diff_ci(a_correct, b_correct, n_boot=2000, seed=123):
    """Bootstrap CI for (accuracy_b - accuracy_a) on paired 0/1 outcomes."""
    diffs = [b - a for a, b in zip(a_correct, b_correct)]
    return bootstrap_ci(diffs, n_boot=n_boot, seed=seed)


def mcnemar(a_correct, b_correct):
    """McNemar's test for paired binary outcomes.

    b = items A got wrong and B got right; c = items A got right and B
    got wrong. Uses the chi-square statistic with continuity correction
    and, for small discordant counts, an exact two-sided binomial p-value.
    Returns dict with b, c, statistic, p_value.
    """
    b = sum(1 for a, bb in zip(a_correct, b_correct) if not a and bb)
    c = sum(1 for a, bb in zip(a_correct, b_correct) if a and not bb)
    discordant = b + c
    if discordant == 0:
        return {"b": b, "c": c, "statistic": 0.0, "p_value": 1.0}
    if discordant < 25:
        # Exact: under H0, b ~ Binomial(discordant, 0.5)
        k = min(b, c)
        tail = sum(math.comb(discordant, i) for i in range(k + 1)) / (2 ** discordant)
        p = min(1.0, 2 * tail)
        stat = (abs(b - c) - 1) ** 2 / discordant
        return {"b": b, "c": c, "statistic": stat, "p_value": p}
    stat = (abs(b - c) - 1) ** 2 / discordant
    # chi-square with 1 df survival function via erfc
    p = math.erfc(math.sqrt(stat / 2))
    return {"b": b, "c": c, "statistic": stat, "p_value": p}


def sample_size_for_difference(p1, delta, alpha=0.05, power=0.8):
    """Approx. per-group n to detect p1 -> p1+delta (two proportions).

    Normal approximation; z values for common alpha/power are tabled
    to keep this dependency-free and transparent.
    """
    z_alpha = {0.05: 1.96, 0.01: 2.576}.get(alpha, 1.96)
    z_beta = {0.8: 0.842, 0.9: 1.282}.get(power, 0.842)
    p2 = p1 + delta
    if not (0 < p1 < 1 and 0 < p2 < 1):
        raise ValueError("proportions must be inside (0, 1)")
    num = (z_alpha + z_beta) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil(num / (delta ** 2))

"""
Tuning the ranking from the user's own choices (v1.32).

The extension shows two listings at a time and the user picks the one
they'd rather live in. Each listing carries its per-criterion expected
satisfaction (`ScoredListing.sat`, 0-1, unknowns at their measured odds)
and its chance a must-have fails, so a pick is a comparison the ranking
can be checked against:

    rank value R = (sum_i w_i * s_i / sum_i w_i) * (1 - fail risk)

which is exactly what `scoring.rank` orders by. The weights w are the
criteria's points (1-10 on the setup page).

The fit is a Bradley-Terry (logistic) model on R: the chance the user
picks A over B is sigmoid(k * (R_A - R_B)). It finds the weights (and the
sharpness k) that make the user's picks most likely, with a pull back
toward the weights the user set (`STRENGTH`), so a handful of picks can
nudge the weights but not throw them away. Weights stay positive (they
are exp(theta)); the result is put back on the 1-10 scale.

What it reports, so nobody has to take it on faith:
- agreement before: how often the current weights rank the picked one higher;
- agreement after: the same with the new weights, on the same picks
  (optimistic: the weights were fit to them);
- agreement held out: each pick predicted by weights fit without it
  (leave-one-out), the honest number.

New weights are suggested only when the held-out agreement beats the
current weights' and the new points don't do worse on the picks;
otherwise the answer is that the current weights already fit.

Only criteria that count in the match are tuned; must-haves still hide
what fails them, whatever their weight. v1.40: a must-have is also locked
here: its weight takes part in the fit but is never changed or suggested
("a must-have is the thing I'm not willing to change"). No numpy: the data is tens of
picks and a dozen weights.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from .scoring import PreferenceSet

STRENGTH = 0.6  # the pull toward the user's own weights (per weight, on log scale)
STEPS = 400
RATE = 0.15
MIN_PICKS = 8  # fewer than this: report, but don't suggest anything
MAX_PICKS = 120  # the most recent picks the fit uses
LOO_MAX = 30  # up to this many picks: leave-one-out; more: k-fold
FOLDS = 5


class CalibrationError(ValueError):
    pass


def _sig(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _value(w: list[float], s: list[float], fail: float) -> float:
    total = sum(w)
    return (sum(a * b for a, b in zip(w, s)) / total if total > 0 else 0.0) * (1.0 - fail)


def _pairs(raw: Any, names: list[str]) -> list[tuple[list[float], float, list[float], float, float]]:
    """(s_a, fail_a, s_b, fail_b, y): y = 1 if A was picked, 0 if B. "Can't decide" and unreadable picks
    are left out. v1.41: "Neither" says both rank below what the user does pick: each side becomes a
    comparison with the latest listing picked before it (or after, if none was yet), which wins."""
    if not isinstance(raw, list):
        raise CalibrationError("pairs: a list of {a, b, pick}")
    out = []
    winners: list[tuple[list[float], float]] = []  # the picked side of each pick, in order
    neither: list[tuple[int, list[tuple[list[float], float]]]] = []  # (winners seen so far, both sides)
    for p in raw:
        if not isinstance(p, dict) or p.get("pick") not in ("a", "b", "neither"):
            continue
        sides = []
        for k in ("a", "b"):
            x = p.get(k)
            sat = x.get("sat") if isinstance(x, dict) else None
            if not isinstance(sat, dict):
                break
            vec = []
            for n in names:
                v = sat.get(n)
                vec.append(min(1.0, max(0.0, float(v))) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0.5)
            f = x.get("fail")
            fail = min(1.0, max(0.0, float(f))) if isinstance(f, (int, float)) and not isinstance(f, bool) and math.isfinite(f) else 0.0
            sides.append((vec, fail))
        if len(sides) != 2:
            continue
        if p["pick"] == "neither":
            neither.append((len(winners), sides))
            continue
        out.append((sides[0][0], sides[0][1], sides[1][0], sides[1][1], 1.0 if p["pick"] == "a" else 0.0))
        winners.append(sides[0] if p["pick"] == "a" else sides[1])
    for seen, sides in neither:
        if not winners:
            break  # nothing picked yet to rank them below
        w = winners[seen - 1] if seen else winners[0]
        for s, f in sides:
            out.append((w[0], w[1], s, f, 1.0))
    return out


def _agreement(w: list[float], pairs: list[tuple[list[float], float, list[float], float, float]]) -> Optional[float]:
    if not pairs:
        return None
    hit = 0.0
    for sa, fa, sb, fb, y in pairs:
        d = _value(w, sa, fa) - _value(w, sb, fb)
        hit += 0.5 if abs(d) < 1e-9 else float((d > 0) == (y == 1.0))
    return hit / len(pairs)


def _fit(w0: list[float], pairs: list[tuple[list[float], float, list[float], float, float]],
         locked: tuple[bool, ...] = ()) -> list[float]:
    """Weights that make the picks most likely, pulled toward w0. Gradient descent on theta = log w (and log k).
    locked: weights that stay exactly as set (must-haves)."""
    theta0 = [math.log(max(x, 0.25)) for x in w0]
    theta = theta0[:]
    kappa = math.log(8.0)  # how sharply a difference in R decides a pick
    m = [0.0] * (len(theta) + 1)
    v = [0.0] * (len(theta) + 1)
    for step in range(1, STEPS + 1):
        w = [math.exp(t) for t in theta]
        k = math.exp(kappa)
        total = sum(w)
        g = [STRENGTH * 2 * (t - t0) for t, t0 in zip(theta, theta0)] + [0.02 * kappa]
        for sa, fa, sb, fb, y in pairs:
            ua = sum(a * b for a, b in zip(w, sa)) / total
            ub = sum(a * b for a, b in zip(w, sb)) / total
            d = ua * (1 - fa) - ub * (1 - fb)
            p = _sig(k * d)
            err = p - y  # dLoss/dz for the logistic loss
            for j, wj in enumerate(w):
                dd = ((1 - fa) * (sa[j] - ua) - (1 - fb) * (sb[j] - ub)) / total
                g[j] += err * k * dd * wj  # chain rule through w = exp(theta)
            g[-1] += err * k * d
        # Adam steps: the scale of the gradient varies a lot between criteria
        params = theta + [kappa]
        for i in range(len(theta)):
            if i < len(locked) and locked[i]:
                g[i] = 0.0
        for i, gi in enumerate(g):
            m[i] = 0.9 * m[i] + 0.1 * gi
            v[i] = 0.999 * v[i] + 0.001 * gi * gi
            mh = m[i] / (1 - 0.9 ** step)
            vh = v[i] / (1 - 0.999 ** step)
            params[i] -= RATE * mh / (math.sqrt(vh) + 1e-8)
        theta, kappa = params[:-1], max(-3.0, min(6.0, params[-1]))
    return [math.exp(t) for t in theta]


def _to_points(w: list[float], w0: list[float]) -> list[int]:
    """Back on the setup page's scale: the same total as before, each 1-10."""
    total0, total = sum(w0), sum(w)
    return [max(1, min(10, round(x * total0 / total))) for x in w]


def tune(prefs: PreferenceSet, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise CalibrationError("{pairs}")
    tuned = [p for p in prefs.preferences if p.weighted]
    if not tuned:
        raise CalibrationError("nothing counts in the match yet: give a criterion some importance first")
    names = [p.name for p in tuned]
    w0 = [float(p.points) for p in tuned]
    pairs = _pairs(body.get("pairs"), names)[-MAX_PICKS:]  # the most recent: tastes move
    out: dict[str, Any] = {"picks": len(pairs), "min_picks": MIN_PICKS, "before": _agreement(w0, pairs)}
    if len(pairs) < MIN_PICKS:
        out.update(enough=False, suggest=False, criteria=[{"name": p.name, "label": p.label, "before": p.points, "after": p.points,
                                                           "locked": p.dealbreaker} for p in tuned])
        return out
    locked = tuple(p.dealbreaker for p in tuned)
    w = _fit(w0, pairs, locked)
    points = [p.points if lock else x for p, lock, x in zip(tuned, locked, _to_points(w, w0))]
    # held out: each pick predicted by weights fit without it. Leave-one-out up to LOO_MAX picks;
    # past that, FOLDS-fold (v1.34: 200 picks one at a time was minutes of work, holding up the helper)
    folds = len(pairs) if len(pairs) <= LOO_MAX else FOLDS
    held = 0.0
    for f in range(folds):
        test = pairs[f::folds]
        rest = [p for i, p in enumerate(pairs) if i % folds != f]
        held += (_agreement(_fit(w0, rest, locked), test) or 0.0) * len(test)
    after = _agreement([float(x) for x in points], pairs)
    held_out = held / len(pairs)
    out.update(
        enough=True,
        after=after,
        held_out=held_out,
        # only worth changing if weights it hadn't seen predict the picks better than what's set now
        suggest=held_out > (out["before"] or 0.0) + 1e-9 and after >= (out["before"] or 0.0) and points != [p.points for p in tuned],
        criteria=[{"name": p.name, "label": p.label, "before": p.points, "after": a, "locked": p.dealbreaker} for p, a in zip(tuned, points)],
    )
    return out

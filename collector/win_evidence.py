"""Fail-closed, read-only evidence audit. Does not authorize betting."""
from datetime import datetime, timezone
from math import isfinite


def fresh(stamp, captured, max_age=180):
    try:
        a = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        b = datetime.fromisoformat(captured.replace("Z", "+00:00"))
        if a.tzinfo is None or b.tzinfo is None:
            return False
        age = (b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds()
        return -30 <= age <= max_age
    except (AttributeError, TypeError, ValueError):
        return False


def assess_win_evidence(odds_audit, official_starts, starts_captured_utc,
                        win_pool, captured_utc, max_age_seconds=180):
    """Validate evidence only, not the V3 probability, EV or stake gates.

    A WIN pool must explicitly declare market WIN and scope SINGLE_MARKET.
    Combined turnover cannot substitute for a separate WIN pool.
    """
    quotes = odds_audit if isinstance(odds_audit, dict) else {}
    times = quotes.get("market_last_updated")
    odds_ok = (
        quotes.get("status") == "STRUCTURE_VALID_UNVERIFIED"
        and not quotes.get("errors")
        and isinstance(quotes.get("snapshot"), dict)
        and quotes["snapshot"].get("market") == "WIN"
        and bool(quotes["snapshot"].get("runners"))
        and isinstance(times, list) and bool(times)
        and all(fresh(t, captured_utc, max_age_seconds) for t in times)
    )
    starts_ok = (
        isinstance(official_starts, list) and bool(official_starts)
        and fresh(starts_captured_utc, captured_utc, max_age_seconds)
        and all(isinstance(h, dict)
                and type(h.get("startNumber")) is int and h["startNumber"] > 0
                and isinstance(h.get("horseName"), str) and bool(h["horseName"].strip())
                and type(h.get("isScratched")) is bool for h in official_starts)
    )
    if starts_ok:
        numbers = [h["startNumber"] for h in official_starts]
        starts_ok = len(numbers) == len(set(numbers))
    p = win_pool if isinstance(win_pool, dict) else {}
    amount = p.get("turnover")
    pool_ok = (
        p.get("market") == "WIN" and p.get("scope") == "SINGLE_MARKET"
        and type(amount) in (int, float) and isfinite(amount) and amount >= 0
        and isinstance(p.get("currency"), str) and bool(p["currency"].strip())
        and isinstance(p.get("source"), str) and bool(p["source"].strip())
        and fresh(p.get("captured_utc"), captured_utc, max_age_seconds)
    )
    errors = []
    if not odds_ok:
        errors.append("WIN_ODDS_NOT_VALIDATED")
    if not starts_ok:
        errors.append("OFFICIAL_SCRATCHES_NOT_FRESH_OR_COMPLETE")
    if not pool_ok:
        errors.append("SEPARATE_WIN_POOL_NOT_VERIFIED")
    return {
        "schema": "prewatch_win_evidence_v1",
        "status": "EVIDENCE_COMPLETE_UNVERIFIED_FOR_BET" if not errors else "BLOCKED",
        "odds": "STRUCTURE_VALID_UNVERIFIED" if odds_ok else "BLOCKED",
        "scratches": "FRESH_OFFICIAL_SNAPSHOT" if starts_ok else "BLOCKED",
        "win_pool": "SEPARATE_POOL_OBSERVED" if pool_ok else "BLOCKED",
        "errors": errors,
        "bet_authorized": False,
    }

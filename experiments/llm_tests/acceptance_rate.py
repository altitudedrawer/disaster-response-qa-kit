"""Compute acceptance rates from YOUR filled-in review sheet. Never edit numbers by hand.

    python experiments/llm_tests/acceptance_rate.py                       # default sheet
    python experiments/llm_tests/acceptance_rate.py my_sheet.csv --json   # machine-readable

Definitions (decided BEFORE running the experiment, so they can't be bent to fit results):
  accepted : kept exactly as generated; it ran green unmodified AND tests something real
  edited   : kept after changes (wrong expected value fixed, import fixed, assertion tightened...)
  rejected : thrown away
  acceptance_rate = accepted / total          usable_rate = (accepted + edited) / total
The 95% interval is a Wilson score interval: with a few dozen tests the uncertainty is large,
and the interval makes that visible.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_SHEET = Path(__file__).resolve().parent / "review_sheet.csv"
REQUIRED = ["test_id", "module", "target_function", "model", "prompt_version",
            "decision", "reason_category", "ran_green_unmodified", "notes"]
DECISIONS = ("accepted", "edited", "rejected")
REASONS = {
    "ok": "nothing wrong (use for accepted)",
    "wrong_expected_value": "asserted the wrong answer",
    "hallucinated_api": "used a function/parameter/field that doesn't exist",
    "tests_implementation_detail": "checks internals the docstring doesn't promise",
    "duplicate": "same as another generated or existing test",
    "trivial": "passes but checks nothing meaningful",
    "nondeterministic": "flaky: time, randomness, ordering",
    "needs_network_or_io": "breaks the offline rule",
    "style_only": "only naming/formatting changed (edited)",
    "other": "explain in notes",
}


class SheetError(Exception):
    pass


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise SheetError(f"missing columns: {missing}")
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in reader]
    rows = [r for r in rows if any(r.values())]          # ignore blank lines
    problems, seen = [], set()
    for i, r in enumerate(rows, start=2):                # line 1 is the header
        r["decision"] = r["decision"].lower()
        r["ran_green_unmodified"] = r["ran_green_unmodified"].lower()
        if not r["test_id"]:
            problems.append(f"line {i}: empty test_id")
        elif r["test_id"] in seen:
            problems.append(f"line {i}: duplicate test_id {r['test_id']!r}")
        seen.add(r["test_id"])
        if not r["decision"]:
            problems.append(f"line {i}: {r['test_id']}: not reviewed yet (decision is blank)")
        elif r["decision"] not in DECISIONS:
            problems.append(f"line {i}: decision must be one of {DECISIONS}, got {r['decision']!r}")
        if r["decision"] and r["reason_category"] not in REASONS:
            problems.append(f"line {i}: reason_category {r['reason_category']!r} not in {sorted(REASONS)}")
        if r["ran_green_unmodified"] not in ("yes", "no"):
            problems.append(f"line {i}: ran_green_unmodified must be yes/no")
        if r["decision"] == "accepted" and r["ran_green_unmodified"] == "no":
            problems.append(f"line {i}: 'accepted' requires ran_green_unmodified=yes (else it's 'edited')")
        if r["reason_category"] == "other" and not r["notes"]:
            problems.append(f"line {i}: reason_category 'other' needs notes")
    if problems:
        raise SheetError("review sheet has problems:\n  " + "\n  ".join(problems))
    return rows


def summarize(rows: list[dict]) -> dict:
    def block(rs):
        c = Counter(r["decision"] for r in rs)
        n = len(rs)
        lo, hi = wilson(c["accepted"], n)
        return {
            "total": n, "accepted": c["accepted"], "edited": c["edited"], "rejected": c["rejected"],
            "acceptance_rate": c["accepted"] / n if n else None,
            "acceptance_ci95": [lo, hi],
            "usable_rate": (c["accepted"] + c["edited"]) / n if n else None,
            "ran_green_unmodified": sum(r["ran_green_unmodified"] == "yes" for r in rs),
        }
    out = {"overall": block(rows)}
    for key in ("model", "prompt_version", "module", "target_function"):
        groups = defaultdict(list)
        for r in rows:
            groups[r[key] or "(blank)"].append(r)
        out[f"by_{key}"] = {g: block(rs) for g, rs in sorted(groups.items())}
    out["reasons_edited"] = dict(Counter(r["reason_category"] for r in rows if r["decision"] == "edited").most_common())
    out["reasons_rejected"] = dict(Counter(r["reason_category"] for r in rows if r["decision"] == "rejected").most_common())
    return out


def render(s: dict) -> str:
    def line(name, b):
        lo, hi = b["acceptance_ci95"]
        return (f"{name:<28} n={b['total']:<4} acc={b['accepted']:<3} edit={b['edited']:<3} rej={b['rejected']:<3} "
                f"acceptance={b['acceptance_rate']:.1%} (95% CI {lo:.1%}-{hi:.1%})  usable={b['usable_rate']:.1%}")
    out = [line("OVERALL", s["overall"])]
    for key in ("model", "prompt_version", "module", "target_function"):
        out.append(f"\n-- by {key}")
        out += [line("  " + g, b) for g, b in s[f"by_{key}"].items()]
    out.append(f"\n-- why edited:   {s['reasons_edited'] or '-'}")
    out.append(f"-- why rejected: {s['reasons_rejected'] or '-'}")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Acceptance rate of LLM-generated tests from the review sheet")
    p.add_argument("sheet", nargs="?", default=str(DEFAULT_SHEET))
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        rows = load(Path(a.sheet))
    except SheetError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not rows:
        print("Review sheet has no rows yet. Run the experiment and fill it in first (see README.md).")
        return 1
    s = summarize(rows)
    print(json.dumps(s, indent=2) if a.json else render(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())

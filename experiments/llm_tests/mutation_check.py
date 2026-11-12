"""Mutation check: which tests catch which deliberately-injected bugs?

"Passes on correct code" is a weak bar for a test; "fails on broken code" is the real one.
For each mutant below, this copies src/ to a temp dir, injects ONE bug, runs the given test
files against it, and records which tests fail (= "kill" the mutant).

    python experiments/llm_tests/mutation_check.py experiments/llm_tests/generated/*_v1.py
    python experiments/llm_tests/mutation_check.py tests/                    # our own suite, for comparison

Writes a per-test CSV (default experiments/llm_tests/mutation_results.csv) and prints a
per-mutant table. These are measured facts to INFORM your review; decisions stay yours.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# id, file under src/pipeline, description, exact original text, replacement.
# Phase 1 used the first 7 ad hoc; M08-M13 were added 2026-11-12 so every module the LLM
# tested has mutants. Each `old` must occur exactly once (checked by tests/test_llm_experiment.py).
MUTANTS = [
    ("M01", "geo.py", "no antimeridian split",
     "if ring.bounds[0] >= -180 and ring.bounds[2] <= 180:", "if True:"),
    ("M02", "join.py", "no exact geodesic distance filter",
     'hits = cand[cand["distance_km"] <= radius_km]', "hits = cand"),
    ("M03", "join.py", "inscribed (unpadded) pre-filter polygon",
     "prefilter_radius_m(radius_m))", "radius_m)"),
    ("M04", "clean.py", "duplicates keep the OLDEST update",
     'sort_values("updated", ascending=False', 'sort_values("updated", ascending=True'),
    ("M05", "clean.py", "min magnitude becomes exclusive",
     'low = df["mag"] < min_mag', 'low = df["mag"] <= min_mag'),
    ("M06", "join.py", "inner join drops events with 0 cities",
     'on="id", how="left"', 'on="id", how="inner"'),
    ("M07", "geo.py", "spherical instead of WGS84 ellipsoid",
     'Geod(ellps="WGS84")', 'Geod(ellps="sphere")'),
    ("M08", "clean.py", "non-earthquake events (landslides) kept",
     "df = df[~not_eq]", "df = df"),
    ("M09", "geo.py", "pole check removed",
     "if float(geodesic_distance_m(lon, lat, lon, pole_lat)) <= radius_m:", "if False:"),
    ("M10", "geo.py", "radius 0 accepted",
     "if radius_m <= 0:", "if radius_m < 0:"),
    ("M11", "join.py", "city order farthest-first (wrong nearest_city)",
     '.sort_values(["id", "distance_km"], kind="stable")',
     '.sort_values(["id", "distance_km"], ascending=[True, False], kind="stable")'),
    ("M12", "publish.py", "list/dict property values not rejected",
     "nested = [k for k, v in props.items() if isinstance(v, (list, dict))]", "nested = []"),
    ("M13", "publish.py", "out-of-range lon/lat not rejected",
     "or not (-180 <= x <= 180 and -90 <= y <= 90):", "or False:"),
]


def sheet_id(classname: str, name: str) -> str:
    """JUnit case -> the review sheet's test_id: '<file>.py::<test>' or '<file>.py::<Class>::<test>'.
    Parametrized cases ('test_x[a]', 'test_x[b]') collapse into one id, like one sheet row."""
    parts = classname.split(".")
    base = name.split("[")[0]
    if parts and parts[-1].startswith("Test") and len(parts) > 1:
        return f"{parts[-2]}.py::{parts[-1]}::{base}"
    return f"{parts[-1]}.py::{base}"


def failing_tests(src_dir: Path, targets: list[str]) -> tuple[set[str], set[str], set[str]]:
    """Run pytest on targets with `pipeline` imported from src_dir. Returns (all, failed, skipped) ids."""
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "r.xml"
        subprocess.run([sys.executable, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider",
                        "-o", f"pythonpath={src_dir}", f"--junitxml={xml}"],
                       cwd=ROOT, capture_output=True, text=True)
        allt, failed, skipped = set(), set(), set()
        if not xml.exists():
            return allt, failed, skipped
        for case in ET.parse(xml).iter("testcase"):
            tid = sheet_id(case.get("classname", ""), case.get("name", ""))
            allt.add(tid)
            if any(c.tag in ("failure", "error") for c in case):
                failed.add(tid)
            elif any(c.tag == "skipped" for c in case):
                skipped.add(tid)
        return allt, failed, skipped


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Which tests kill which injected bugs")
    p.add_argument("targets", nargs="+", help="test files or directories")
    p.add_argument("--out", default=str(ROOT / "experiments/llm_tests/mutation_results.csv"))
    a = p.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        clean_src = Path(tmp) / "clean" / "src"
        shutil.copytree(ROOT / "src", clean_src)
        baseline_all, baseline_failed, baseline_skipped = failing_tests(clean_src, a.targets)
        if not baseline_all:
            print("ERROR: no tests collected", file=sys.stderr)
            return 2
        # a test that fails (or is skipped) on correct code can't meaningfully "kill" anything
        usable = baseline_all - baseline_failed - baseline_skipped
        kills: dict[str, list[str]] = {t: [] for t in sorted(baseline_all)}
        print(f"baseline: {len(baseline_all)} tests; {len(baseline_failed)} fail and {len(baseline_skipped)} "
              "are skipped on the UNMUTATED code (both excluded from kill counts)\n")
        print(f"{'mutant':<6} {'module':<11} {'killed by':>9}  description")
        for mid, fname, desc, old, new in MUTANTS:
            src = Path(tmp) / mid / "src"
            shutil.copytree(ROOT / "src", src)
            f = src / "pipeline" / fname
            text = f.read_text()
            if text.count(old) != 1:
                print(f"ERROR: {mid}: pattern found {text.count(old)}x in {fname}", file=sys.stderr)
                return 2
            f.write_text(text.replace(old, new))
            _, failed, _ = failing_tests(src, a.targets)
            killers = sorted(failed & usable)
            for t in killers:
                kills[t].append(mid)
            print(f"{mid:<6} {fname[:-3]:<11} {len(killers):>9}  {desc}")

    survived = [m[0] for m in MUTANTS if not any(m[0] in v for v in kills.values())]
    print(f"\nmutants killed by at least one test: {len(MUTANTS) - len(survived)}/{len(MUTANTS)}"
          + (f"; survived: {', '.join(survived)}" if survived else ""))
    print(f"tests that killed no mutant: {sum(1 for t in usable if not kills[t])}/{len(usable)}")
    out = Path(a.out)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["test_id", "status_on_correct_code", "mutants_killed", "kill_count"])
        for t, ms in kills.items():
            status = "fail" if t in baseline_failed else "skipped" if t in baseline_skipped else "pass"
            w.writerow([t, status, ";".join(ms), len(ms)])
    print(f"per-test results -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

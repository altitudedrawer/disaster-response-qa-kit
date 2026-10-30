"""Run one generated test file and APPEND one row per test to the review sheet.

Fills only measured facts: test_id, module, target_function (from the test name),
model, prompt_version, ran_green_unmodified (from pytest's JUnit report).
`decision` and `reason_category` are left BLANK on purpose: those are your judgement.
acceptance_rate.py refuses to compute anything until every row is reviewed.

    python experiments/llm_tests/prefill_sheet.py experiments/llm_tests/generated/gpt_clean_v1.py \
        --model "<exact model name>" --module pipeline.clean
"""
import argparse
import ast
import csv
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from acceptance_rate import REQUIRED  # noqa: E402

TARGETS = {  # module -> public functions the prompts cover
    "pipeline.clean": ["clean_events", "CleanResult"],
    "pipeline.geo": ["geodesic_buffer", "geodesic_distance_m"],
    "pipeline.join": ["cities_near_events"],
    "pipeline.publish": ["validate_geojson", "PublishError"],
}


def test_names(path: Path) -> list[str]:
    """All test functions in the file (incl. inside Test* classes), even if it fails to import."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            names += [f"{node.name}::{n.name}" for n in node.body
                      if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]
    return names


def passed_tests(path: Path) -> set[str]:
    """Names (without parametrize ids) whose every case passed, according to pytest."""
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "r.xml"
        proc = subprocess.run([sys.executable, "-m", "pytest", str(path), "-q", "-p", "no:cacheprovider",
                               f"--junitxml={xml}"], cwd=ROOT, capture_output=True, text=True)
        print(proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-500:])
        if not xml.exists():
            return set()
        status: dict[str, bool] = {}
        for case in ET.parse(xml).iter("testcase"):
            cls = case.get("classname", "").split(".")[-1]
            base = case.get("name", "").split("[")[0]
            key = f"{cls}::{base}" if cls.startswith("Test") else base
            ok = not any(child.tag in ("failure", "error", "skipped") for child in case)
            status[key] = status.get(key, True) and ok
        return {k for k, ok in status.items() if ok}


def guess_target(test_name: str, module: str) -> str:
    fn = test_name.split("::")[-1].removeprefix("test_")
    matches = [t for t in TARGETS.get(module, []) if fn.startswith(t)]
    return max(matches, key=len) if matches else ""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Prefill review_sheet.csv from one generated test file")
    p.add_argument("generated_file")
    p.add_argument("--model", required=True, help="exact model name as shown in the LLM app")
    p.add_argument("--module", required=True, choices=sorted(TARGETS))
    p.add_argument("--prompt-version", default="v1")
    p.add_argument("--sheet", default=str(HERE / "review_sheet.csv"))
    a = p.parse_args(argv)

    path = Path(a.generated_file).resolve()
    names = test_names(path)
    if not names:
        print(f"no test functions found in {path}", file=sys.stderr)
        return 2
    sheet = Path(a.sheet)
    with open(sheet, newline="", encoding="utf-8") as f:
        existing = {r["test_id"] for r in csv.DictReader(f)}
    green = passed_tests(path)
    rows = []
    for n in names:
        tid = f"{path.name}::{n}"
        if tid in existing:
            print(f"skip (already in sheet): {tid}")
            continue
        rows.append({"test_id": tid, "module": a.module, "target_function": guess_target(n, a.module),
                     "model": a.model, "prompt_version": a.prompt_version, "decision": "",
                     "reason_category": "", "ran_green_unmodified": "yes" if n in green else "no",
                     "notes": ""})
    with open(sheet, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=REQUIRED).writerows(rows)
    print(f"added {len(rows)} rows ({sum(r['ran_green_unmodified'] == 'yes' for r in rows)} ran green) "
          f"to {sheet.name}; now fill in decision + reason_category for each")
    return 0


if __name__ == "__main__":
    sys.exit(main())

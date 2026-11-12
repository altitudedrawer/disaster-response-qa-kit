"""Walk through the review sheet one test at a time and record YOUR decision for each.

    python experiments/llm_tests/review.py                    # every row still blank, in order
    python experiments/llm_tests/review.py --module pipeline.geo
    python experiments/llm_tests/review.py --redo "dsv41flash_geo_v1.py::test_geodesic_buffer_custom_n_vertices"

For each test it shows: the test's code, the docstring the LLM was given for the target function,
whether it ran green unmodified, and which injected bugs (mutation_check.py) it catches. You type
the decision, reason and notes; the row is saved immediately, so you can quit (q) and resume.
It applies the same rules as acceptance_rate.py, so mistakes are caught on the spot.
This tool never decides anything: it only records what you type.
"""
from __future__ import annotations

import argparse
import ast
import csv
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from acceptance_rate import DECISIONS, REASONS, REQUIRED  # noqa: E402

try:
    from mutation_check import MUTANTS  # noqa: E402
    MUTANT_DESC = {m[0]: m[2] for m in MUTANTS}
except Exception:  # noqa: BLE001 -- descriptions are a nicety, not required
    MUTANT_DESC = {}

REASON_KEYS = list(REASONS)
SHORT = {"a": "accepted", "e": "edited", "r": "rejected"}


# ---------- pure helpers (unit-tested) ----------

def get_test_source(generated_dir: Path, test_id: str) -> str:
    """Source of one test (function, or Class::method) from its generated file."""
    fname, *rest = test_id.split("::")
    path = generated_dir / fname
    if not path.exists():
        return f"(file not found: {path})"
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"(file doesn't parse: {e})"
    nodes = tree.body
    for part in rest[:-1]:                      # descend into classes
        cls = next((n for n in nodes if isinstance(n, ast.ClassDef) and n.name == part), None)
        if cls is None:
            return f"(class {part} not found)"
        nodes = cls.body
    fn = next((n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == rest[-1]), None)
    return ast.get_source_segment(src, fn) if fn else f"(test {rest[-1]} not found in {fname})"


def helpers_used(generated_dir: Path, test_id: str) -> dict[str, str]:
    """Module-level helper functions/fixtures in the same file that this test refers to by name."""
    fname = test_id.split("::")[0]
    path = generated_dir / fname
    if not path.exists():
        return {}
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    body = get_test_source(generated_dir, test_id)
    used = {}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("test") and n.name in body:
            used[n.name] = ast.get_source_segment(src, n)
    return used


def docstring_for(prompts_dir: Path, module: str, prompt_version: str, target: str) -> str:
    """The signature + docstring the LLM was shown for `target`, taken from the frozen prompt."""
    path = prompts_dir / f"{module.split('.')[-1]}_{prompt_version}.txt"
    if not path.exists() or not target:
        return "(prompt not found)"
    text = path.read_text(encoding="utf-8")
    try:
        code = text.split("```python", 1)[1].split("```", 1)[0]
        tree = ast.parse(code)
    except (IndexError, SyntaxError):
        return "(couldn't read the prompt's code block)"
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == target:
            return ast.get_source_segment(code, n)
    return f"({target} not in {path.name})"


def load_mutations(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["test_id"]: [m for m in r["mutants_killed"].split(";") if m] for r in csv.DictReader(f)}


def check_row(row: dict) -> list[str]:
    """The same per-row rules acceptance_rate.py enforces."""
    d, reason, notes = row["decision"], row["reason_category"], row["notes"].strip()
    problems = []
    if d not in DECISIONS:
        problems.append(f"decision must be one of {DECISIONS}")
    if reason not in REASONS:
        problems.append(f"reason must be one of {REASON_KEYS}")
    if d == "accepted" and row["ran_green_unmodified"] == "no" and reason != "found_real_bug":
        problems.append("this test did NOT run green unmodified, so it can't be 'accepted' "
                        "(use 'edited', or reason found_real_bug if it failed only because our code was wrong)")
    if reason == "found_real_bug" and d != "accepted":
        problems.append("found_real_bug means the test is kept unmodified -> decision must be 'accepted'")
    if reason in ("found_real_bug", "other") and not notes:
        problems.append(f"reason {reason!r} needs a note")
    return problems


def save(sheet: Path, rows: list[dict]) -> None:
    """Write atomically: a crash mid-write can't leave a half-written sheet."""
    fd, tmp = tempfile.mkstemp(dir=sheet.parent, prefix=".review_", suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REQUIRED, lineterminator="\n")
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in REQUIRED} for r in rows)
    os.replace(tmp, sheet)


# ---------- interactive loop ----------

def main(argv=None, ask=input, out=sys.stdout) -> int:
    p = argparse.ArgumentParser(description="Record your review decisions, one test at a time")
    p.add_argument("--sheet", default=str(HERE / "review_sheet.csv"))
    p.add_argument("--generated-dir", default=str(HERE / "generated"))
    p.add_argument("--prompts-dir", default=str(HERE / "prompts"))
    p.add_argument("--mutations", default=str(HERE / "mutation_results.csv"))
    p.add_argument("--module", help="only rows for this module, e.g. pipeline.geo")
    p.add_argument("--redo", help="re-review one test_id even if already decided")
    a = p.parse_args(argv)

    def say(*parts):
        print(*parts, file=out)

    sheet = Path(a.sheet)
    with open(sheet, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in REQUIRED:
            r.setdefault(k, "")
    kills = load_mutations(Path(a.mutations))
    gen, prompts = Path(a.generated_dir), Path(a.prompts_dir)

    if a.redo:
        todo = [r for r in rows if r["test_id"] == a.redo]
        if not todo:
            say(f"no row with test_id {a.redo!r}")
            return 2
    else:
        todo = [r for r in rows if not r["decision"].strip()
                and (not a.module or r["module"] == a.module)]
    done_before = sum(1 for r in rows if r["decision"].strip())
    say(f"{len(rows)} rows: {done_before} already decided, {len(todo)} to review now. "
        "Answers are saved after every test; 'q' quits, 's' skips.\n")

    for i, r in enumerate(todo, 1):
        say("=" * 78)
        say(f"[{i}/{len(todo)}] {r['test_id']}")
        say(f"target: {r['module']}.{r['target_function']}   ran green unmodified: {r['ran_green_unmodified'].upper()}")
        ks = kills.get(r["test_id"])
        if ks is None:
            say("injected bugs caught: (no mutation data)")
        elif ks:
            say("injected bugs caught: " + "; ".join(f"{m} {MUTANT_DESC.get(m, '')}".strip() for m in ks))
        else:
            say("injected bugs caught: NONE of the 13 (look hard: trivial? duplicate? or checks something no mutant touches?)")
        say("\n--- what the LLM was given ---")
        say(docstring_for(prompts, r["module"], r["prompt_version"], r["target_function"]))
        say("\n--- the test ---")
        say(get_test_source(gen, r["test_id"]))
        helpers = helpers_used(gen, r["test_id"])
        if helpers:
            say(f"\n(uses helpers: {', '.join(helpers)}; type 'h' to show them)")
        if r["decision"]:
            say(f"\ncurrent: {r['decision']} / {r['reason_category']} / {r['notes']}")

        while True:
            ans = ask("\ndecision [a]ccepted [e]dited [r]ejected | [s]kip [h]elpers [q]uit: ").strip().lower()
            if ans == "q":   # every answer was already saved when given; nothing to write here
                say(f"stopped. {sum(1 for x in rows if x['decision'].strip())}/{len(rows)} decided.")
                return 0
            if ans == "s":
                break
            if ans == "h":
                for name, code in helpers.items():
                    say(f"\n--- helper {name} ---\n{code}")
                continue
            if ans not in SHORT:
                say("type a, e, r, s, h or q")
                continue
            decision = SHORT[ans]
            say("reasons: " + "  ".join(f"{n}={k}" for n, k in enumerate(REASON_KEYS, 1)))
            default = "ok" if decision == "accepted" and r["ran_green_unmodified"] == "yes" else ""
            pick = ask(f"reason number{f' [Enter = {default}]' if default else ''}: ").strip()
            if not pick and default:
                reason = default
            elif pick.isdigit() and 1 <= int(pick) <= len(REASON_KEYS):
                reason = REASON_KEYS[int(pick) - 1]
            else:
                say("not a valid reason number; let's redo this test")
                continue
            notes = ask("notes (optional; required for 'other' / 'found_real_bug'): ").strip()
            candidate = {**r, "decision": decision, "reason_category": reason, "notes": notes}
            problems = check_row(candidate)
            if problems:
                for prob in problems:
                    say(f"  ! {prob}")
                say("  -> not saved; answer this test again")
                continue
            r.update(decision=decision, reason_category=reason, notes=notes)
            save(sheet, rows)
            say(f"  saved: {decision} / {reason}" + (f" / {notes}" if notes else ""))
            break

    left = sum(1 for x in rows if not x["decision"].strip())
    say("\n" + ("All rows decided. Next: python experiments/llm_tests/acceptance_rate.py"
                if not left else f"{left} rows still blank; run review.py again to continue."))
    return 0


if __name__ == "__main__":
    sys.exit(main())

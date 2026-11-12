"""Tests for experiments/llm_tests/review.py (the interactive review helper).

All sheets, generated files and prompts here are synthetic temp files; the real
review sheet is never touched.
"""
import csv
import importlib.util
import io
from pathlib import Path

import pytest

EXP = Path(__file__).resolve().parents[1] / "experiments" / "llm_tests"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, EXP / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ar = load_module("acceptance_rate")

rv = load_module("review")

GEN_FILE = '''
def _helper(x):
    return x + 1


def test_clean_events_ok():
    """checks something"""
    assert _helper(1) == 2


class TestThing:
    def test_inside(self):
        assert True
'''
PROMPT = 'intro\n```python\ndef clean_events(df, min_mag=5.0) -> CleanResult:\n    """Doc for clean_events."""\n    ...\n```\nrules'


@pytest.fixture
def review_env(tmp_path):
    gen = tmp_path / "generated"; gen.mkdir()
    (gen / "m_clean_v1.py").write_text(GEN_FILE)
    prompts = tmp_path / "prompts"; prompts.mkdir()
    (prompts / "clean_v1.txt").write_text(PROMPT)
    muts = tmp_path / "mut.csv"
    muts.write_text("test_id,status_on_correct_code,mutants_killed,kill_count\n"
                    "m_clean_v1.py::test_clean_events_ok,pass,M04;M05,2\n")
    sheet = tmp_path / "sheet.csv"
    base = {"module": "pipeline.clean", "target_function": "clean_events", "model": "m",
            "prompt_version": "v1", "decision": "", "reason_category": "", "notes": ""}
    with open(sheet, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ar.REQUIRED); w.writeheader()
        w.writerow({**base, "test_id": "m_clean_v1.py::test_clean_events_ok", "ran_green_unmodified": "yes"})
        w.writerow({**base, "test_id": "m_clean_v1.py::TestThing::test_inside", "ran_green_unmodified": "no"})
    args = ["--sheet", str(sheet), "--generated-dir", str(gen), "--prompts-dir", str(prompts), "--mutations", str(muts)]
    return sheet, args, gen, prompts


def run_review(args, answers):
    it = iter(answers)
    out = io.StringIO()
    code = rv.main(args, ask=lambda _prompt: next(it), out=out)
    return code, out.getvalue()


def rows_of(sheet):
    return list(csv.DictReader(open(sheet)))


def test_review_shows_context_and_saves_decisions(review_env):
    sheet, args, *_ = review_env
    # row 1: accepted, Enter = default reason 'ok', no notes.
    # row 2 (not green): try 'accepted' -> refused; then edited + style_only + a note with a comma.
    style = str(list(ar.REASONS).index("style_only") + 1)
    ok = str(list(ar.REASONS).index("ok") + 1)
    code, out = run_review(args, ["a", "", "",
                                  "a", ok, "",          # refused: not green, so 'accepted'+'ok' breaks the rules
                                  "e", style, "renamed, reformatted"])
    assert code == 0
    assert "Doc for clean_events." in out and "assert _helper(1) == 2" in out
    assert "M04 duplicates keep the OLDEST update" in out
    assert "can't be 'accepted'" in out
    r1, r2 = rows_of(sheet)
    assert (r1["decision"], r1["reason_category"], r1["notes"]) == ("accepted", "ok", "")
    assert (r2["decision"], r2["reason_category"], r2["notes"]) == ("edited", "style_only", "renamed, reformatted")
    assert len(ar.load(sheet)) == 2                         # acceptance_rate.py accepts the result


def test_review_quit_saves_progress_and_resumes(review_env):
    sheet, args, *_ = review_env
    run_review(args, ["a", "", "", "q"])
    assert [r["decision"] for r in rows_of(sheet)] == ["accepted", ""]
    code, out = run_review(args, ["s"])                     # resume: only the blank row is shown
    assert "1 already decided, 1 to review" in out and "TestThing::test_inside" in out
    assert rows_of(sheet)[1]["decision"] == ""              # skipped -> still blank


def test_review_found_real_bug_needs_note(review_env):
    sheet, args, *_ = review_env
    frb = str(list(ar.REASONS).index("found_real_bug") + 1)
    run_review(args, ["s", "a", frb, "", "a", frb, "code fixed"])
    assert rows_of(sheet)[1]["reason_category"] == "found_real_bug"


def test_review_helpers_and_lookups(review_env):
    _, _, gen, prompts = review_env
    assert "class" not in rv.get_test_source(gen, "m_clean_v1.py::TestThing::test_inside")
    assert "_helper" in rv.helpers_used(gen, "m_clean_v1.py::test_clean_events_ok")
    assert "Doc for clean_events." in rv.docstring_for(prompts, "pipeline.clean", "v1", "clean_events")
    assert "not found" in rv.get_test_source(gen, "missing_v1.py::test_x")


def test_review_redo_changes_one_row(review_env):
    sheet, args, *_ = review_env
    run_review(args, ["a", "", "", "q"])
    rej = str(list(ar.REASONS).index("trivial") + 1)
    run_review(args + ["--redo", "m_clean_v1.py::test_clean_events_ok"], ["r", rej, ""])
    assert rows_of(sheet)[0]["decision"] == "rejected"


def test_review_quit_without_answers_leaves_file_untouched(review_env):
    sheet, args, *_ = review_env
    before = sheet.read_bytes()
    run_review(args, ["q"])
    assert sheet.read_bytes() == before


def test_review_writes_unix_line_endings(review_env):
    sheet, args, *_ = review_env
    run_review(args, ["a", "", "", "q"])
    assert b"\r\n" not in sheet.read_bytes()

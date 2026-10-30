"""Tests for the experiment TOOLING (acceptance_rate.py, extract_signatures.py).

The CSV rows here are synthetic fixtures for checking the arithmetic. They are NOT
experiment results; the real review sheet ships empty.
"""
import csv
import importlib.util
from pathlib import Path

import pytest

EXP = Path(__file__).resolve().parents[1] / "experiments" / "llm_tests"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, EXP / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ar = load_module("acceptance_rate")
es = load_module("extract_signatures")


def sheet(tmp_path, rows):
    p = tmp_path / "sheet.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ar.REQUIRED)
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({"test_id": f"t{i}", "module": "pipeline.clean", "target_function": "clean_events",
                        "model": "m", "prompt_version": "v1", "reason_category": "ok",
                        "ran_green_unmodified": "yes", "notes": "", **r})
    return p


def test_shipped_review_sheet_is_empty():
    """Honesty guard: results are filled in by the human, never pre-populated."""
    assert ar.load(EXP / "review_sheet.csv") == []


def test_rates_on_known_counts(tmp_path):
    rows = [{"decision": "accepted"}, {"decision": "accepted"},
            {"decision": "edited", "reason_category": "wrong_expected_value", "ran_green_unmodified": "no"},
            {"decision": "rejected", "reason_category": "hallucinated_api", "ran_green_unmodified": "no"}]
    s = ar.summarize(ar.load(sheet(tmp_path, rows)))["overall"]
    assert (s["total"], s["accepted"], s["edited"], s["rejected"]) == (4, 2, 1, 1)
    assert s["acceptance_rate"] == 0.5 and s["usable_rate"] == 0.75


def test_wilson_interval_known_values():
    lo, hi = ar.wilson(2, 4)                  # p = 0.5, n = 4 -> about [0.150, 0.850]
    assert lo == pytest.approx(0.150, abs=0.001) and hi == pytest.approx(0.850, abs=0.001)
    assert ar.wilson(0, 10)[0] == 0.0 and ar.wilson(10, 10)[1] == 1.0
    assert ar.wilson(0, 0) == (0.0, 0.0)


def test_group_breakdown_and_reasons(tmp_path):
    rows = [{"decision": "accepted", "model": "A"},
            {"decision": "rejected", "model": "B", "reason_category": "trivial", "ran_green_unmodified": "yes"}]
    s = ar.summarize(ar.load(sheet(tmp_path, rows)))
    assert s["by_model"]["A"]["acceptance_rate"] == 1.0 and s["by_model"]["B"]["acceptance_rate"] == 0.0
    assert s["reasons_rejected"] == {"trivial": 1}


@pytest.mark.parametrize("bad,msg", [
    ({"decision": "maybe"}, "decision must be"),
    ({"decision": "accepted", "reason_category": "vibes"}, "reason_category"),
    ({"decision": "accepted", "ran_green_unmodified": "no"}, "requires ran_green_unmodified=yes"),
    ({"decision": "rejected", "reason_category": "other"}, "needs notes"),
    ({"decision": "accepted", "ran_green_unmodified": "sometimes"}, "yes/no"),
])
def test_invalid_rows_rejected(tmp_path, bad, msg):
    with pytest.raises(ar.SheetError, match=msg):
        ar.load(sheet(tmp_path, [bad]))


def test_duplicate_test_ids_rejected(tmp_path):
    p = sheet(tmp_path, [{"decision": "accepted"}])
    p.write_text(p.read_text() + p.read_text().splitlines()[1] + "\n")
    with pytest.raises(ar.SheetError, match="duplicate test_id"):
        ar.load(p)


def test_cli_exit_codes(tmp_path, capsys):
    assert ar.main([str(EXP / "review_sheet.csv")]) == 1                 # empty -> no number
    assert ar.main([str(sheet(tmp_path, [{"decision": "accepted"}]))]) == 0
    assert "acceptance=100.0%" in capsys.readouterr().out
    assert ar.main([str(sheet(tmp_path, [{"decision": "nope"}]))]) == 2


def test_extract_shows_signatures_docstrings_and_fields_not_bodies():
    src = Path(__file__).resolve().parents[1] / "src" / "pipeline" / "clean.py"
    text = es.extract(src)
    assert "def clean_events(df: pd.DataFrame" in text and "null_magnitude" in text
    assert "events: gpd.GeoDataFrame" in text           # dataclass fields are shown
    assert "drop_duplicates" not in text                # implementation is hidden
    assert "_empty_events" not in text                  # private helpers are hidden


def test_extract_hides_function_bodies_even_annotated_locals():
    """Regression: annotated local variables inside a function leaked into the prompt."""
    src = Path(__file__).resolve().parents[1] / "src" / "pipeline" / "publish.py"
    text = es.extract(src, {"validate_geojson", "PublishError"})
    assert "problems: list[str]" not in text
    assert "class PublishError(Exception):" in text      # base class shown -> LLM knows it's an exception


pf = load_module("prefill_sheet")

FAKE_GENERATED = '''
import pytest

def test_clean_events_passes():
    assert 1 + 1 == 2

def test_clean_events_fails():
    assert 1 + 1 == 3

@pytest.mark.parametrize("x", [1, 2])
def test_clean_events_param_one_bad(x):
    assert x == 1

class TestCleanResult:
    def test_cleanresult_ok(self):
        assert True
'''


def empty_sheet(tmp_path):
    p = tmp_path / "sheet.csv"
    p.write_text(",".join(ar.REQUIRED) + "\n")
    return p


def test_prefill_records_measured_facts_and_leaves_judgement_blank(tmp_path):
    gen = tmp_path / "fake_clean_v1.py"
    gen.write_text(FAKE_GENERATED)
    sheet = empty_sheet(tmp_path)
    assert pf.main([str(gen), "--model", "fake-model", "--module", "pipeline.clean", "--sheet", str(sheet)]) == 0
    rows = {r["test_id"].split("::", 1)[1]: r for r in csv.DictReader(open(sheet))}
    assert {k: r["ran_green_unmodified"] for k, r in rows.items()} == {
        "test_clean_events_passes": "yes", "test_clean_events_fails": "no",
        "test_clean_events_param_one_bad": "no",            # one failing case => not green
        "TestCleanResult::test_cleanresult_ok": "yes"}
    assert rows["test_clean_events_passes"]["target_function"] == "clean_events"
    assert all(r["decision"] == "" and r["reason_category"] == "" for r in rows.values())
    with pytest.raises(ar.SheetError, match="not reviewed yet"):   # can't compute until reviewed
        ar.load(sheet)
    # running again doesn't duplicate rows
    pf.main([str(gen), "--model", "fake-model", "--module", "pipeline.clean", "--sheet", str(sheet)])
    assert len(list(csv.DictReader(open(sheet)))) == 4


def test_prefill_handles_file_that_cannot_import(tmp_path):
    """e.g. the LLM imported a function that doesn't exist: every test counts as not green."""
    gen = tmp_path / "fake_bad_import_v1.py"
    gen.write_text("from pipeline.clean import no_such_function\n\ndef test_a():\n    assert True\n")
    sheet = empty_sheet(tmp_path)
    pf.main([str(gen), "--model", "m", "--module", "pipeline.clean", "--sheet", str(sheet)])
    (row,) = csv.DictReader(open(sheet))
    assert row["ran_green_unmodified"] == "no"

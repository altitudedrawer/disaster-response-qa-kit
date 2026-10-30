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

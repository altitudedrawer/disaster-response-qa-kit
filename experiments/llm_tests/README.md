# Experiment: how useful are LLM-generated unit tests?

**Question:** given only a function's signature and docstring, how many of an LLM's pytest
cases can I keep as-is, keep after editing, or must throw away, and why?

**Status: NOT RUN YET.** Every number in this folder must come from `acceptance_rate.py`
run on a review sheet you filled in yourself. Nothing here is pre-filled.

## Files

| File | Purpose |
|---|---|
| `prompt_template.md` | The prompt (version `v1`). Change it → bump the version and record it |
| `extract_signatures.py` | Fills the template with a module's public signatures + docstrings (no function bodies) |
| `prompts/` | The 4 ready-to-paste prompts (`clean_v1.txt`, `geo_v1.txt`, `join_v1.txt`, `publish_v1.txt`) |
| `prefill_sheet.py` | Runs a generated file and appends one row per test (measured facts only; your decision columns stay blank) |
| `generated/` | Raw LLM output, saved **unmodified** (this is your evidence trail) |
| `review_sheet.csv` | One row per generated test, filled in by you |
| `review.py` | Interactive review: shows each test, the docstring the LLM saw and the bugs it catches; records your decision and enforces the rules as you go |
| `mutation_check.py`, `mutation_results.csv` | Which tests catch which of 13 injected bugs (measured facts to inform the review) |
| `acceptance_rate.py` | Computes rates, a 95% interval and reason breakdowns from the sheet |

## Protocol (decide the rules before you look at any output)

1. **Targets** (suggested, 4 functions with different difficulty):
   `pipeline.clean` (`clean_events`), `pipeline.geo` (`geodesic_buffer`),
   `pipeline.join` (`cities_near_events`), `pipeline.publish` (`validate_geojson`).
2. **Prompts** are already in `prompts/` (regenerate with `extract_signatures.py` if the code changes).
   On a Mac, `pbcopy < experiments/llm_tests/prompts/clean_v1.txt` copies one to the clipboard.
3. **Generate:** paste the prompt into a fresh chat. Record the exact model name and the date.
   **One shot, no follow-up corrections.** If you coach it, you're measuring yourself, not the model.
4. **Save raw output** as `generated/<model>_<module>_v1.py`, untouched.
5. **Run it as generated** (these files are outside `tests/`, so CI doesn't run them):
   ```bash
   python -m pytest experiments/llm_tests/generated/<file>.py -v -p no:cacheprovider
   ```
   Then record the measured facts automatically:
   ```bash
   python experiments/llm_tests/prefill_sheet.py experiments/llm_tests/generated/<file>.py \
       --model "<exact model name>" --module pipeline.clean
   ```
6. **Review each test**, one row per test in `review_sheet.csv`. Easiest: `python experiments/llm_tests/review.py`
   (saves after every answer; `q` to stop, run again to resume; `--redo <test_id>` to change one).
   - `accepted`: unmodified, passes, and checks something the docstring promises
   - `edited`: worth keeping but needed a change. Pick the main reason (`wrong_expected_value`, `style_only`, ...)
   - `rejected`: not worth keeping. Pick why (`hallucinated_api`, `trivial`, `duplicate`, ...)
   - The full list of reason categories is in `acceptance_rate.py`. `other` requires a note.
   - Watch for the important failure mode: a test that **passes but asserts the wrong thing**
     (e.g. matches what the code does rather than what the docstring says). Mark it `rejected` or
     `edited` with `wrong_expected_value`, even though it's green.
7. **Compute:**
   ```bash
   python experiments/llm_tests/acceptance_rate.py
   ```
   Paste the output below as-is, with model and date. Copy the tests you keep (edited version)
   into `tests/`, so CI runs them from then on.

Optional stronger signal, now automated (`mutation_check.py`, 13 documented mutants M01–M13):
```bash
python experiments/llm_tests/mutation_check.py experiments/llm_tests/generated/*_v1.py   # -> mutation_results.csv
python experiments/llm_tests/mutation_check.py tests/ --out output/mutation_ours.csv        # our suite, for comparison
```
`mutation_results.csv` has one row per review-sheet `test_id` (same format) with the mutants each
test kills. Killing no mutant is NOT proof a test is useless (it may check behaviour none of the 13
mutants touch), but it's a strong hint to look hard at questions 3 and 4 of the review.

Original idea (Phase 1): re-run the mutation check (break the code on purpose,
e.g. remove the antimeridian split) and record whether the LLM's tests catch each mutant.
"Passes on correct code" is a weak bar; "fails on broken code" is the real one.

## Known threats to validity
- **Self-grading:** you run the LLM and judge its output. The fixed definitions above, written
  before seeing results, reduce but don't remove this bias.
- **Small n:** ~40–60 tests gives wide intervals. That's why the 95% CI is reported.
- **One prompt, one shot:** results describe this prompt (`v1`) and this model on this date, not
  "LLMs" in general.
- **Docstrings were improved before the experiment** (2026-10-29/30, before any LLM output was
  seen): `CleanResult` got a docstring; the inputs of `clean_events` and `cities_near_events`,
  the defaults of `geodesic_buffer`, and the exact checks of `validate_geojson` were documented,
  because the extractor showed an LLM would otherwise have to guess. The extractor also stopped
  leaking annotated local variables from function bodies. This is noted so nobody mistakes it for tuning after the fact.

## Protocol amendments

**v1.1, 2026-10-30, made AFTER seeing the generated tests' pass/fail results** (not the review
decisions, which hadn't started). Prompts were not changed.

- New reason `found_real_bug`: a test that failed *only because the code under test was wrong*
  may be recorded as `accepted` even though `ran_green_unmodified=no`, if the test is kept
  unmodified, the code is fixed, and the notes say what was fixed. Why: v1 had no way to credit
  the most valuable outcome of test generation, finding a real defect.
- What triggered it (both now fixed in `src/`, each with a regression test in `tests/`):
  1. `geodesic_distance_m` promised "scalars or arrays" but raised `GeodError` for one point vs.
     many (`test_geodesic_distance_m_broadcasts_scalar_against_array`).
  2. `nearest_km` was "rounded to 0.01" with numpy's fast rounding, giving 12.34 for 12.345
     (correct: 12.35) (`test_cities_near_events_nearest_city_and_km`).
- Reporting rule: `acceptance_rate.py` prints the `found_real_bug` count and the acceptance
  rate under the original v1 rules next to the v1.1 rate, so both are always visible.

## Results

TODO: filled in by Zongze after running the protocol (model, date, `acceptance_rate.py` output, 2–3 sentences of takeaways).

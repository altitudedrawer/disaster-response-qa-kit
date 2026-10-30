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
| `generated/` | Raw LLM output, saved **unmodified** (this is your evidence trail) |
| `review_sheet.csv` | One row per generated test, filled in by you |
| `acceptance_rate.py` | Computes rates, a 95% interval and reason breakdowns from the sheet |

## Protocol (decide the rules before you look at any output)

1. **Targets** (suggested, 4 functions with different difficulty):
   `pipeline.clean` (`clean_events`), `pipeline.geo` (`geodesic_buffer`),
   `pipeline.join` (`cities_near_events`), `pipeline.publish` (`validate_geojson`).
2. **Make the prompt:**
   ```bash
   python experiments/llm_tests/extract_signatures.py src/pipeline/clean.py --functions CleanResult clean_events > /tmp/prompt_clean.txt
   ```
3. **Generate:** paste the prompt into a fresh chat. Record the exact model name and the date.
   **One shot, no follow-up corrections.** If you coach it, you're measuring yourself, not the model.
4. **Save raw output** as `generated/<model>_<module>_v1.py`, untouched.
5. **Run it as generated** (these files are outside `tests/`, so CI doesn't run them):
   ```bash
   python -m pytest experiments/llm_tests/generated/<file>.py -v -p no:cacheprovider
   ```
   Note which tests pass without any change → `ran_green_unmodified`.
6. **Review each test**, one row per test in `review_sheet.csv`:
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

Optional stronger signal: re-run the Phase 1 mutation check (break the code on purpose,
e.g. remove the antimeridian split) and record whether the LLM's tests catch each mutant.
"Passes on correct code" is a weak bar; "fails on broken code" is the real one.

## Known threats to validity
- **Self-grading:** you run the LLM and judge its output. The fixed definitions above, written
  before seeing results, reduce but don't remove this bias.
- **Small n:** ~40–60 tests gives wide intervals. That's why the 95% CI is reported.
- **One prompt, one shot:** results describe this prompt (`v1`) and this model on this date, not
  "LLMs" in general.
- **Docstrings were improved before the experiment** (`CleanResult` got a docstring and the
  input columns of `clean_events` were documented, after the extractor showed an LLM would
  otherwise have to guess). This is noted so nobody mistakes it for tuning after the fact.

## Results

TODO: filled in by Zongze after running the protocol (model, date, `acceptance_rate.py` output, 2–3 sentences of takeaways).

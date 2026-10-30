<!-- prompt_version: v1 -- if you change this template, bump the version and record it in the review sheet -->
You are a senior Python test engineer. Write pytest unit tests for the module `{module_name}`.

You are given ONLY the public signatures and docstrings below, not the implementations.
Test the behaviour the docstrings promise. If a docstring is ambiguous, write the test you
think is most reasonable and add a comment starting with `# ASSUMPTION:` explaining it.

```python
{signatures}
```

Rules:
1. Output a single Python file, with no prose before or after it.
2. Import from `{module_name}` exactly as named above. Do not invent functions, parameters or
   return fields that are not shown.
3. Tests must be deterministic and offline: no network, no real files outside pytest's `tmp_path`,
   no current-time dependence, no randomness without a fixed seed.
4. Prefer small hand-built inputs whose correct answer you can justify. For geographic distances,
   build points with `pyproj.Geod(ellps="WGS84").fwd(...)` so the distance is known by construction.
5. Cover: normal cases, boundaries (inclusive/exclusive limits), empty input, invalid input,
   and any edge case a docstring mentions explicitly.
6. Name every test `test_<function>_<behaviour>`. Put a one-line docstring in each test saying
   what it checks.
7. Aim for 8–15 tests. Quality over quantity: no duplicate tests that differ only in a constant.

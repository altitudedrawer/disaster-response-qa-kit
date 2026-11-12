# Workflow: build order, and why

## Order of development

| # | Phase | Why in this order |
|---|---|---|
| 0 | **Environment check** | Know what can actually run (Python version, Docker, network) before promising anything; anything that can't run gets labelled UNTESTED with instructions. |
| 1 | **Core pipeline + offline tests** | Correctness first, on small committed fixtures: tests run in under a second with no internet, so every later phase builds on a green, deterministic suite. Mutation-tested so a green suite actually means something. |
| 2 | **Real data** | Only after the logic is trusted. Real data's job is to surface *data* problems (a landslide, duplicate names, bad coordinates), not logic bugs. Verified against a brute-force oracle. |
| 3 | **ArcGIS publish + contract tests** | Integration with an external service comes after the local output is right; `--dry-run` and auto-skipping contract tests keep the suite runnable without an account or credentials. |
| 4 | **DevOps** | Package and automate something that already works: Docker → CI → Jenkins → Ansible. Each tool was run for real; running them found 3 bugs no local test could. |
| 5 | **LLM test-generation experiment** | Needs a stable, well-tested codebase as a reference, and a protocol frozen in git *before* any output is seen. |
| 6 | **Docs** | Written last so every number in them comes from a run that already happened. |

## Actual commit history

Real history, never rewritten (no backdating, rebasing or squashing). Early commits are
coarse, often one per phase, because the commit-per-unit convention below was adopted later
(2026-11-12).

| Commit | Date (−07/−08:00) | Message |
|---|---|---|
| `4bf667d` | 2026-10-20 20:47 | Initial commit |
| `b40a920` | 2026-10-20 21:09 | Core pipeline with geodesic buffers, offline fixtures, 63 tests |
| `cda4405` | 2026-10-29 15:36 | Real USGS/Natural Earth run: landslide filter, city labels, oracle check, gitignore |
| `a31bdd1` | 2026-10-29 16:32 | ArcGIS publish + contract tests; untrack generated files |
| `8826824` | 2026-10-29 17:08 | Add Docker, GitHub Actions CI, Jenkins pipeline, and Ansible playbook |
| `6085765` | 2026-10-29 17:12 | README: CI badge, mark GitHub Actions as verified |
| `0841db3` | 2026-10-29 17:35 | Add LLM test-generation experiment kit |
| `f1cb91d` | 2026-10-30 11:36 | Freeze LLM experiment v1: prompts, prefill helper, docstring fixes |
| `a645ee4` | 2026-11-12 12:23 | Record DeepSeek-generated tests; fix 2 bugs they found |

Regenerate this table with: `git log --reverse --format='%h | %ad | %s' --date=format:'%Y-%m-%d %H:%M'`

## Commit convention (from 2026-11-12 on)

One commit per meaningful unit of work, using [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <what changed, imperative, ≤ 72 chars>

<optional body: why, and anything a reviewer should know>
```

| Type | Use for | Example |
|---|---|---|
| `feat` | new behaviour | `feat(join): add nearest_city and nearest_km columns` |
| `fix` | bug fix (with its regression test) | `fix(geo): broadcast scalar vs array in geodesic_distance_m` |
| `test` | tests only | `test(geo): add antimeridian buffer case` |
| `docs` | documentation only | `docs: add DEVLOG` |
| `ci` | CI/CD config | `ci: run pytest on Python 3.13` |
| `build` | Docker, dependencies | `build(docker): run as non-root user` |
| `chore` | data snapshots, housekeeping | `chore(experiment): record mutation check results` |

Rules: keep data/results commits separate from code commits (so evidence is easy to audit);
commit a fix together with its regression test; never commit `.env`, `data/` or `output/`.

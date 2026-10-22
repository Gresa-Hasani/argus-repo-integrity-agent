# Public NP-hard problem test cohort

These public projects were selected on 14 October 2026 for integration tests. They are not student submissions and receive no academic grades.

| Repository | Problem | Useful test coverage |
| --- | --- | --- |
| [shah314/graphcoloring](https://github.com/shah314/graphcoloring) | Graph coloring | DIMACS inputs, heuristic and backtracking implementations, claimed benchmark results |
| [Docheinstein/itc2007-cct](https://github.com/Docheinstein/itc2007-cct) | Curriculum-based timetabling | ITC2007 datasets, saved solutions, several search methods |
| [githubjonas/social-golfer](https://github.com/githubjonas/social-golfer) | Social golfer variant | Repeated-meeting/socialisation objective; not automatically equivalent to strict maximum-weeks SGP |
| [ADDALemos/MPPTimetables](https://github.com/ADDALemos/MPPTimetables) | Timetabling and minimal perturbation | MaxSAT approach, ITC datasets, reference output files |

## Reproduction

Install the local evaluator: `.venv/bin/python -m pip install -e '.[dev,analytics]'`.

Clone the public manifest URLs into `test-cohort/repos/<owner>--<repo>` without recursive submodules. Then run `.venv/bin/python scripts/test_public_cohort.py`. Refresh charts without rerunning evaluations with `.venv/bin/python scripts/test_public_cohort.py --plots-only`.

The runner records evaluated commits, runs deterministic ARGUS evaluations with model and GitHub API disabled, and compares every pair for directional code containment, symmetric README token similarity and README heading similarity. Failed acquisitions remain unavailable. README structure alone cannot create a flag. The runner never executes code from these repositories.

## Results

All four links acquired successfully. Six pairs were compared; directional token-shingle code containment ranged from 0.0006 to 0.0480 (0.06% to 4.8%). None crossed the 70% threshold. All evaluations were INCOMPLETE_EVALUATION because model reasoning was disabled; zero material findings were detected by this limited pass. This is not a clean integrity verdict.

Generated reports and charts are under `output/` (ignored by Git). `cross-validation.json` contains raw pairwise measurements, evaluated commits and statuses. `code-containment.png` and `.svg` plot real measured overlap. `synthetic-grades.json` and both grade charts are explicitly synthetic test fixtures; no scores or flagged statuses are assigned to the selected projects. The fixtures verify excluding flagged rows by default and generating a second view including them, with common bins and axes. There is no grade normalization to force a bell curve.

Benchmark claims in READMEs are not independently validated solution results or automatically current frontier values. Exact instance/objective matching and independent solution validation are required before using `argus.benchmarks.assess`. In particular, maximizing socialisation with repeated meetings cannot be scored against a strict no-repeated-pairs maximum-weeks reference.

## Independent saved-solution check

`scripts/validate_itc_saved.py` checks the seven saved schedules in Docheinstein/itc2007-cct against their included ITC2007 UD2 instances. It checks lecture counts, course/teacher/curriculum/room collisions, period ranges and unavailable periods, and recomputes room-capacity, working-day, compactness and room-stability penalties. All seven schedules pass these feasibility checks, with costs 5, 36, 66, 37, 305, 40 and 14. These match the repository's claimed values. Each is a feasible upper bound for its minimization instance, not a proof of optimality. Run `.venv/bin/python scripts/validate_itc_saved.py` to reproduce `output/validated-timetables.json`.

[OptHub UD2 comp01](https://opthub.uniud.it/problems/timetabling/edutt/ctt/cb-ctt-ud2/instances/comp01) currently displays published solutions of cost 5, while its instance header is marked not validated. Do not treat that header or a README's competition-winner column as proof of a current global frontier. The [University of Udine research solver](https://github.com/iolab-uniud/cb-ctt) links this registry and provides a competition-calibrated benchmark protocol. These are useful reference sources for a later controlled solver run.

# Cohort grading and cross-validation specification

Status: batch acquisition, pairwise similarity, overlap flags, measured-statistics charts, verified-grade population helpers, and objective-comparison helpers are implemented. Assignment grading and extra-credit automation still require a rubric and independently validated benchmark results.

## Inputs

A cohort of repository URLs, assignment requirements and point weights, explicit extra-credit criteria and cap, and benchmark instances with objective direction, feasibility constraints, bounds and execution limits. Associate each grade with the evaluated commit and evidence. Missing evidence yields an unverified item, not an invented score.

## Extra credit

Award extra points only for evidenced work beyond the required baseline that meets the extra-credit rubric. README claims alone do not establish completion. Report base points, extra points and total separately, applying the configured cap. Do not count required features twice.

## Cross-validation

Acquire and record the status of every supplied repository URL. Compare every distinct pair for code overlap, README text overlap and README heading/section structure. Report a symmetric pairwise matrix where the metric is symmetric and both directions for directional containment. Preserve failed or inaccessible links as unavailable, rather than as zero similarity.

Shared README formatting is an advisory signal. Common course templates and headings must not establish an integrity flag on their own. Compare substantive claims against implementation evidence and distinguish shared templates from overlapping project-specific content.

## NP-hard benchmark evaluation

Select adapters using the actual assignment problem and benchmark instance. Validate feasibility independently before using an objective value. Record theoretical/relaxation lower and upper bounds, observed objective, time limit and whether optimality was proved. Distinguish timeout from infeasibility.

For minimization, a verified feasible solution supplies an upper bound; a lower bound is necessary to measure distance from optimality. For maximization, a verified feasible solution supplies a lower bound and an independent upper bound supports a gap. Do not grade different objective directions with one unqualified upper-bound formula, or infer optimality from a heuristic result.

The public test cohort includes graph coloring, social golfer and timetabling. These examples do not establish an assignment rubric or independently verified solver scores. Match exact instances and objectives before grading.

## Analytic grade distributions

The primary distribution excludes all flagged repositories. If any are flagged, also produce a second distribution including them, using identical bin edges and axes. Clearly mark the sample size, flagged count, mean, median, standard deviation and excluded/unverified count for each population. Incomplete or evaluator-error cases without verified grades must not be treated as zero or as cleared repositories.

Plot the actual grade histogram and individual observations. Overlay a fitted normal curve only when there are at least two observations and positive variance; label it as a descriptive fit, not a claim of normality. Empty cohorts and zero-variance grades require explicit handling. Keep raw grades intact rather than rescaling them to fit a bell curve. Export the chart and the tabular scores used to generate it.

## Integration

ARGUS currently evaluates integrity, not academic requirements or solver correctness. Add cohort grading as a separate layer consuming integrity reports and rubric/benchmark evidence. Preserve the integrity pipeline's completion statuses. Running student solver code requires an isolated benchmark runner; the existing static collectors must retain their no-repository-code-execution behavior.

## Researched reference policy and implemented comparison (14 October 2026)

`src/argus/benchmarks.py` now implements objective comparison with default 10% tolerance. It requires matching problem, instance SHA-256 and objective definition, finite nonnegative objectives, and caller-supplied independent feasibility-validation evidence. It does not execute or validate solvers, award grades, or change integrity flags. Runtime and hardware allowance are separate. The API is not yet connected to the UI or grading pipeline.

- Minimization accepts objective <= 1.10 times the reference.
- Maximization accepts objective >= 0.90 times the reference.
- No rounding increases tolerance for integer objectives. A five-color reference accepts five, not six.
- A zero reference receives no invented additive tolerance.
- Improving a proven optimum triggers a reference conflict for review. Improving a merely best-known result is labeled an improvement, not proof of optimality.
- Invalid or unverified feasibility never receives tolerance-based acceptance.

### Sources and local problem matching

Social golfer: [CSPLib results](https://www.csplib.org/Problems/prob010/results/) link a 10-week solution. The [2026 combinatorial-design research paper](https://www.mdpi.com/2073-8994/18/2/269) discusses the maximal ten-round case for 32 players in groups of four. For eight groups of four, each player meets three new players per week, so weeks <= floor(31/3) = 10. The implemented general counting bound is floor((groups * group_size - 1)/(group_size - 1)). A validated nine-week result is within 10% of ten. A bound alone does not prove attainability for arbitrary parameter combinations.

Graph coloring: [CMU DIMACS instances](https://mat.tepper.cmu.edu/COLOR/instances.html) provide named graphs and some optimal color counts; entries marked unknown are not certified optima or automatically current frontier results. Use the exact graph digest and independently validate every edge. The local k5.txt contains all ten edges on five vertices, so its clique lower bound and feasible upper bound both equal five. For arbitrary graphs, a verified clique provides a lower bound and a verified coloring an upper bound. Research dated instance-specific best-known results before using them as frontier references.

Timetabling: [ITC official problem instances](https://www.eeecs.qub.ac.uk/itc2007/curriculmcourse/course_curriculm_index_files/instances.htm) and [competition benchmarking guidance](https://www.eeecs.qub.ac.uk/itc2007/index_files/gettingstarted.htm) support exact instance matching, separate feasibility validation and machine-specific compute budgets. The local timetabling solver generates its own instances and uses its own weighted objective, so an ITC score is not interchangeable. Run a trusted reference solver on the identical custom instance and weights, or add a matching competition adapter. Infeasible schedules do not qualify even if their combined weighted cost is low.

Queens: the local visualizer finds a solution to unconstrained N-Queens. This must not be confused with NP-complete N-Queens Completion. [Gent, Jefferson and Nightingale's research](https://pure.york.ac.uk/portal/en/publications/complexity-of-n-queens-completion/) proves hardness for completion and explains the distinction. A feasibility-only problem receives a validated solution check, not an invented optimization gap.

The user requested 10% easing for compute differences. The comparison currently implements objective-quality easing. Hardware-normalized runtime evaluation remains separate: a generic 10% runtime increase does not compensate for arbitrary machine differences.

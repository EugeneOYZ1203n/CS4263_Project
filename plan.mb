# Plan: TSP-with-constraints Benchmarking Engine

## Context
Compare LLM solvers vs classical solver on constrained TSP (deadline + precedence). Engine only does: (1) generate problems + precompute reference, (2) run each given solver on problems, (3) evaluate and emit one HTML report. Engine does not contain the classical or LLM solvers; they are plugged in. Repo is empty (only a stale `__pycache__/solution.cpython-314.pyc`). Target Python 3.14, stdlib only, avoid 3.14-only features so it ports.

Deliverable after approval: save this plan as `plan.mb` in the project root (user request), then build.

## Decisions made
- Constraints: deadline `(1,(node,value))` (cumulative distance from start <= value) and precedence `(2,(a,b))`. No time windows.
- Start node always 0. Graph complete, symmetric, Euclidean random points.
- Infeasible instances included (some %). Correct answer is `None`.
- Reference c*: brute force for N<=8, branch & bound for larger N. Beyond B&B reach c*=null: grade feasibility only plus gap vs best-known across solvers.
- Solver API: Python callable only: `solver(problem, seed)`. Solver self-enforces timeout; engine measures wall time.
- Return protocol: `list[int]` = tour; `None` w/o metadata = claims infeasible; `None` + metadata with `error` key = failure (`"timeout"`, `"malformed"`, other = malformed). Optional metadata: tokens_in, tokens_out, reasoning_tokens, cost, model, settings, raw_text.
- k repeats per (solver, instance), seed passed in.
- Fixed metric set (cherry-picked by user from list below).
- Report: single self-contained HTML, inline SVG/JS, tables + charts only, no CDN.
- Outcome labels in order: Malformed, Timeout, Invalid, Valid suboptimal, Optimal; plus Correct None / Wrong None for infeasible instances.
- Sweeps: N, constraint count/density, constraint tightness, infeasible fraction, adversarial families.

## Architecture
```
benchmark/
  problem.py   # Problem dataclass: num_nodes, matrix, deadlines, precedences, seed, meta
  generate.py  # generators + sweeps + adversarial families
  reference.py # brute_force (N<=8), branch_and_bound; c*, optimal tour, feasible flag
  validate.py  # check_tour -> (valid, violations); tour_cost
  runner.py    # run(solvers, problems, k, seeds) -> RunRecords; timing, exception capture
  evaluate.py  # RunRecord -> label, gap; aggregation per solver / N / constraint level
  metrics.py   # fixed metric functions
  report.py    # one HTML file
  io.py        # JSON save/load of instances and results
  cli.py       # gen | run | report
tests/
```
Pipeline: `gen` -> instances.json (with c*) -> `run` -> results.json -> `report` -> report.html. Stages decoupled via JSON.

## Build order
1. Problem + JSON schema + validate.py (violations: missing/duplicate node, hallucinated ID, wrong start/end, deadline, precedence, wrong None).
2. reference.py: brute force, then B&B with pruning; cross-check on N<=8.
3. generate.py: Euclidean points, integer-rounded edges (open: confirm). Deadlines = optimal arrival time x slack factor (tightness). Acyclic precedences for feasible instances. Infeasible: cyclic precedence, deadline below shortest start edge, or search-proven. Adversarial: greedy trap, tight-deadline trap, precedence detour.
4. runner.py: protocol interpretation, wall-clock, exception -> Malformed, elapsed > limit -> Timeout.
5. evaluate.py + metrics.py.
6. report.py: summary table per solver, outcome distribution, metric-vs-N / constraint density / tightness curves, per-instance drilldown, run-config section.
7. Tests: validator, generator determinism, B&B == brute force, runner protocol cases, report with dummy solvers.
8. Sanity solvers: oracle, random permutation, nearest neighbour, always-None.

## Candidate metrics (~50) — cherry-pick
**Correctness:** parse rate; malformed rate; validity rate; exact-optimal rate; valid-suboptimal rate; invalid rate; mean gap; median gap; max gap; P90 gap; gap vs best-known (no c*); constraint satisfaction fraction; hallucinated-ID rate.
**Robustness:** success vs N; largest N with validity>=90%; largest N with optimal>=50%; validity vs constraint count; vs deadline tightness; vs precedence density; adversarial-set optimal rate; adversarial vs random gap delta; gap slope per node; timeout rate vs N; violation-type distribution; deadline- vs precedence-violation rate.
**Safeguard:** infeasible detection rate; false-infeasible rate; hallucinated tour on infeasible; infeasibility precision; recall; F1; error-reported vs silent-failure rate; silent invalid rate; confidence calibration (if supplied).
**Efficiency:** mean/median/P95 wall time; time vs N growth; timeout rate; mean input/output/reasoning tokens; mean cost; cost per valid; cost per optimal; time per valid.
**Reproducibility:** outcome agreement across k; tour identity rate; std of cost; std of gap; pass@k; flip rate across seeds; std of wall time.

## Open questions
- Integer-rounded Euclidean OK?
- B&B max N, N grid for graded vs ungraded sets.
- Defaults: k, time limit, infeasible fraction, slack grid.
- Self-enforced timeout means a hung solver hangs engine; add optional hard kill later?
- Tightness definition: slack over arrival time in constrained-optimal tour (recommended).
- Final metric selection.

## Verification
- pytest passes (validator, B&B vs brute force, determinism, runner protocol).
- Smoke: gen small set -> run oracle/random/NN/always-None -> report. Oracle 100% optimal; random ~0% valid on constrained N>=8; always-None perfect only on infeasible.
- report.html opens offline with tables/charts and run config.

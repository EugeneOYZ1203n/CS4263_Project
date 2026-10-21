# Plan: TSP-with-constraints Benchmarking Engine

## Context
Compare LLM solvers with a classical solver on constrained TSP (deadline + precedence). The engine is a few scripts: generate test cases with reference answers, run solver classes, evaluate the results into stats and an HTML report, and view tours in a Tkinter GUI. The solvers are plugged in through `benchmark_config.py`. It uses Python 3.14 and the stdlib only (Tkinter included), and avoids 3.14-only features.

## Problem definition (matches TSPLIB / Waterloo national optima)
- Node coordinates are **floats**. Edge weight follows TSPLIB EUC_2D: `nint(sqrt(dx²+dy²))`, so it is an **integer**. Tour costs and deadlines are therefore integers too. This is exactly how the published national optima are computed, so they stay valid references. Small instances use float coordinates in [0, 1000) under the same rule.
- Complete, symmetric graph. Closed tour starting and ending at node 0. Solvers return `[0, ..., 0]` (length N+1).
- Deadline `(v, D)`: cumulative distance from departure at 0 to the first arrival at v must be ≤ D.
- Precedence `(a, b)`: a is visited before b.
- Infeasible instance: the correct answer is `None`.

## Files & layout
```
benchmark_config.py     # SOLVERS = [SolverClass, ...] + run settings (k, time_limit, testcases dir)
generate_testcases.py   # script 1 (+ generation config constants / CLI flags)
run_solvers.py          # script 2
evaluate.py             # script 3
view_generated.py       # script 4: Tkinter viewer
tsp_common.py           # .tsp/.json IO, dist, validator, Held-Karp reference, Solver base class
solvers/                # sanity solvers: oracle, random, nearest_neighbour, always_none
data/national/          # committed .tsp + sidecar .json (+ published optimal tour if available)
README.md
tests/
testcases/              # output of script 1
  unconstrained_small/  deadline_constrained_small/  precedence_constrained_small/
  all_constrained_small/  unconstrained_large/
  infeasible_unreachable_deadline/  infeasible_precedence_cycle/
  infeasible_precedence_deadline_chain/  infeasible_deadline_pair_clash/
outputs/
  <YYYYmmdd_HHMMSS>_<SolverName>/
    testcases/<category>/<name>.json   # same stem as the .tsp: k runs (tour|None, metadata, wall time, label, violations)
    benchmark_dump.json                # evaluation statistics
    report.html
  compare_<timestamp>.html             # optional multi-solver comparison
```
Each instance is a standard TSPLIB `.tsp` (NAME, TYPE: TSP, DIMENSION, EDGE_WEIGHT_TYPE: EUC_2D, NODE_COORD_SECTION, 1-indexed in the file and 0-indexed internally) plus a sidecar `.json` with the same stem: name, category, n, seed, deadlines `[[v,D]]`, precedences `[[a,b]]`, s, feasible, optimal_cost, optimal_tour, infeasible_class, generation params.

## Solver API
```python
class Solver:                       # in tsp_common.py
    name = "MySolver"
    def solve(self, problem, seed) -> tuple[list[int] | None, dict]: ...
```
- `problem` carries coords, `dist(i,j)`, an optional full matrix for small N, deadlines and precedences. The solver enforces its own timeout. The engine measures wall time and does no hard kill (a known risk).
- Return protocol: a `list[int]` is a tour. `None` with no `error` key means "claims infeasible". `None` with `error="timeout"` gives Timeout. Any other `error`, or an exception, gives Malformed.
- Metadata (tokens, cost, model, settings, raw_text) is stored per run but not reported.
- `benchmark_config.py`: `SOLVERS = [...]`, `K = 3`, `TIME_LIMIT = 300`, `TESTCASES_DIR`, optional category filter.

## Reference solver
- Small (N 5–10): Held-Karp DP over (visited set, last node) holding the minimum cost. This is exact under deadlines because earlier arrival always dominates. Prune transitions that break a deadline or a precedence. This gives c*, an optimal tour, and an exact feasible flag. Cross-checked against brute force.
- National: published optima (wi29 = 27603, dj38 = 6656, qa194 = 9352, uy734 = 79114, zi929 = 95345, lu980 = 11340). Re-check these against the Waterloo pages when downloading. Store the published optimal tour if one can be downloaded, so the viewer can draw it. If not, only the cost is stored and the "optimal tour" toggle is disabled for that case.

## Constraint generation (feasible)
1. Pick a node subset (or all nodes) and shuffle it into a witness order starting at 0.
2. Compute all-pairs shortest paths `sp` with Floyd–Warshall, since nint rounding can break the triangle inequality.
3. Deadlines: sample n nodes, take lb = cumulative `sp` along the witness order, and set `D = ceil(lb × s)` with s ∈ {1.0, 1.2, 1.5}.
4. Precedences: sample m pairs and orient each according to the witness order.
5. The witness guarantees feasibility. There is no binding check.

## Infeasible constructions (provable; DP double-checks)
Inject one of these into a feasible all-constrained instance:
- **Unreachable deadline:** `D(v) < sp(0,v)`.
- **Precedence cycle:** a→b→…→a.
- **Precedence+deadline chain:** a1<…<ak with `D(ak) < sp(0,a1)+Σ sp(ai,ai+1)`.
- **Deadline pair clash:** each deadline is ≥ its node's `sp(0,·)`, but both are below `min(sp(0,u)+sp(u,v), sp(0,v)+sp(v,u))`.

## Sweeps / generation config
- Small sets use N 5–10:
  - unconstrained_small: N only.
  - deadline_constrained_small: n ∈ {1,2,4} × s.
  - precedence_constrained_small: m ∈ {2,4,8}, capped by N.
  - all_constrained_small: n × m × s.
- unconstrained_large: wi29, dj38, qa194, uy734, zi929, lu980, copied from data/national/. Japan was dropped.
- Infeasible folders: about 20% of instance volume across the 4 classes, N 5–10.
- Config knobs (constants at the top of the file, overridable from the CLI): master seed, N range, seeds per cell, n/m/s grids, infeasible fraction, coordinate range, output dir. Output is deterministic from the master seed.

## Outcome labels
Malformed, Timeout, Invalid, Valid suboptimal, Optimal. On infeasible instances: Correct None and Wrong None. A tour returned there is a hallucinated tour. Violations recorded: missing node, duplicate node, hallucinated ID, wrong start/end, deadline, precedence, wrong None.

## Metrics (in benchmark_dump.json)
- **Correctness:** outcome-label rates; gap mean/median/P90/max (valid tours, vs c* or the published optimum); constraint-satisfaction fraction; violation-type breakdown.
- **Safeguard:** infeasibility precision/recall/F1 (infeasible is the positive class); hallucinated-tour rate; detection rate per infeasible class.
- **Robustness:** validity, optimal rate and gap vs N, vs n/m, and vs s; largest N with validity ≥ 90%.
- **Reproducibility (k=3):** outcome agreement across k; pass@k (valid and optimal); std of gap.
- Everything is broken down per category. Wall time is recorded but not a metric.

## Scripts
- `run_solvers.py`: for each class in `SOLVERS`, creates `outputs/<ts>_<name>/` and runs every test case k times with seeds. It writes per-case JSON with the label and violations already computed via tsp_common, so the viewer works without evaluate.
- `evaluate.py <folder> [<folder> ...]`: reads the per-case JSON plus the test-case sidecars, then writes `benchmark_dump.json` and a self-contained `report.html` (inline SVG, no CDN) to each folder. With several folders it also writes `outputs/compare_<ts>.html` from their dumps.
- `view_generated.py <outputs folder>`: Tkinter window.
  - Left sidebar: `ttk.Treeview` of test cases grouped by category, each showing its label.
  - Canvas: nodes scaled to fit. Node 0 is highlighted. Deadline nodes are marked with D. Precedence arcs are optional.
  - The solver tour is drawn as a polyline, with a run selector (k) for repeated runs.
  - A **"Show optimal tour"** checkbox overlays the reference tour in a second colour.
  - Info panel: cost, c*, gap, label, violations. For None answers it shows the claim and whether it is correct.

## README.md
Covers setup, the instance format (.tsp + sidecar), generation (command, folder layout, every config knob, infeasible classes), writing a Solver class (interface, return protocol, metadata keys, timeout responsibility, a minimal example), registering it in benchmark_config.py and running run_solvers.py, evaluating (evaluate.py, output folder layout, benchmark_dump.json fields, metrics, report and compare), and the viewer.

## Build order
1. tsp_common: IO, dist, validator, Held-Karp + brute-force check, Solver base.
2. Download the national cases into data/national/ and write their sidecars.
3. generate_testcases.py.
4. Sanity solvers and benchmark_config.py.
5. run_solvers.py.
6. evaluate.py (dump, report, compare).
7. view_generated.py.
8. README.md.
9. Tests.

## Verification
- pytest: validator cases; DP == brute force on N ≤ 8; generation determinism; DP feasible=False for every infeasible-class case; a valid witness for every feasible case; national optimal tours (where stored) score exactly their published cost; runner protocol cases.
- Smoke: generate → run sanity solvers → evaluate. Oracle is 100% optimal with perfect F1. Always-None is perfect only on infeasible cases. Random is about 0% valid on constrained cases. NN gets a gap > 0 on national cases.
- report.html opens offline, and view_generated.py opens an output folder, lists categories and toggles the optimal overlay.

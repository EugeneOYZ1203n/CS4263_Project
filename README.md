# Constrained TSP Benchmark

A benchmarking engine for comparing solvers (LLM-based and classical) on the travelling salesman problem with **deadline** and **precedence** constraints. It generates test cases with exact reference answers, runs plugged-in solver classes, grades every answer, and produces statistics, an HTML report and a Tkinter viewer.

Pure Python standard library (Tkinter included). Developed on Python 3.12, targets 3.14.

```bash
python generate_testcases.py                      # 1. build testcases/
python run_solvers.py                             # 2. run every solver in benchmark_config.py
python evaluate.py outputs/<ts>_<Solver> [...]    # 3. stats + report.html (+ comparison page)
python view_generated.py outputs/<ts>_<Solver>    # 4. browse tours interactively
python -m unittest discover tests                 # tests
```

| File | Role |
|---|---|
| `tsp_common.py` | TSPLIB IO, distances, `Problem`, `Solver` base class, tour validation and grading, Held-Karp reference solver |
| `generate_testcases.py` | Script 1: test case generation |
| `benchmark_config.py` | Which solvers to run, and run settings |
| `run_solvers.py` | Script 2: runs solvers and writes per-case results |
| `evaluate.py` | Script 3: `benchmark_dump.json`, `report.html`, comparison page |
| `view_generated.py` | Script 4: Tkinter viewer |
| `solvers/baselines.py` | Sanity solvers: `Oracle`, `NearestNeighbour`, `Random`, `AlwaysNone` |
| `data/national/` | Waterloo National TSP instances with their published optima |

---

## The problem

- Nodes have **float coordinates**. The distance between two nodes is the Euclidean distance **rounded to the nearest integer** (TSPLIB `EUC_2D`). Edge weights, tour costs and deadlines are therefore integers. This is the rule the published national optima use.
- The graph is complete and symmetric.
- A tour starts and ends at node **0**, visits every other node exactly once, and is written as `[0, v1, ..., v_{n-1}, 0]`.
- **Deadline** `(v, D)`: the cumulative distance travelled from node 0 until the first arrival at `v` must be `≤ D`.
- **Precedence** `(a, b)`: `a` must be visited before `b`.
- An **infeasible** instance has no tour satisfying all constraints. The correct answer is `None`.

## Test case format

Each test case is two files with the same stem:

- `<name>.tsp`: a standard TSPLIB file (`TYPE : TSP`, `EDGE_WEIGHT_TYPE : EUC_2D`, `NODE_COORD_SECTION`). Node ids are 1-indexed in the file and 0-indexed everywhere else. Concorde, LKH and other TSPLIB tools can read it.
- `<name>.json`: the sidecar, holding the constraints and the reference answer:

| Key | Meaning |
|---|---|
| `name`, `category`, `n`, `seed` | identity; `seed` regenerates this case |
| `deadlines` | `[[v, D], ...]` (0-indexed) |
| `precedences` | `[[a, b], ...]`, a before b |
| `params` | generation parameters (`n_deadlines`, `n_precedences`, `slack`, ...) |
| `feasible` | whether any valid tour exists |
| `optimal_cost`, `optimal_tour` | exact optimum (Held-Karp). National cases have only the published cost. |
| `reference_source` | `held_karp` or `published optimum (Waterloo National TSP)` |
| `infeasible_class`, `infeasibility_proof` | for infeasible cases: which construction was used, and why it's impossible |
| `witness_tour` | the tour used to build the constraints (proves feasibility) |

---

## 1. Generating test cases

```bash
python generate_testcases.py [--out testcases] [--seed 4263] [--n-min 5] [--n-max 10]
       [--seeds-per-cell 1] [--deadlines 1 2 4] [--precedences 2 4 8] [--slacks 1.0 1.2 1.5]
       [--infeasible-fraction 0.2] [--coord-max 1000]
```

Each flag overrides the matching constant at the top of `generate_testcases.py`. Output is deterministic for a given configuration. The category folders inside `--out` are deleted and regenerated each time.

### Folders

| Folder | Contents (default config) |
|---|---|
| `unconstrained_small` | N = 5..10, no constraints |
| `deadline_constrained_small` | N × deadlines {1,2,4} × slack {1.0,1.2,1.5} |
| `precedence_constrained_small` | N × precedences {2,4,8} |
| `all_constrained_small` | N × deadlines × precedences × slack |
| `unconstrained_large` | National TSPs: wi29 (Western Sahara), dj38 (Djibouti), qa194 (Qatar), uy734 (Uruguay), zi929 (Zimbabwe), lu980 (Luxembourg) |
| `infeasible_unreachable_deadline` | see below |
| `infeasible_precedence_cycle` | |
| `infeasible_precedence_deadline_chain` | |
| `infeasible_deadline_pair_clash` | |

The default config produces 310 cases: 246 feasible and 64 infeasible.

### Config knobs

| Constant / flag | Default | Effect |
|---|---|---|
| `MASTER_SEED` / `--seed` | 4263 | seeds every case; each case's own seed is derived from it |
| `N_MIN`, `N_MAX` | 5, 10 | node counts for the small sets (max 13 for the Held-Karp reference) |
| `SEEDS_PER_CELL` | 1 | instances per sweep cell; raise it for tighter statistics |
| `DEADLINE_COUNTS` | 1 2 4 | deadlines per instance (capped at N−1) |
| `PRECEDENCE_COUNTS` | 2 4 8 | precedences per instance (capped by the number of node pairs) |
| `SLACKS` | 1.0 1.2 1.5 | deadline tightness (1.0 = the witness arrives exactly on time) |
| `INFEASIBLE_FRACTION` | 0.2 | infeasible cases as a share of all cases, split evenly across the 4 classes |
| `COORD_MAX` | 1000 | coordinates are uniform in `[0, COORD_MAX)`, rounded to 4 decimals |
| `NATIONAL` | 6 instances | national instances copied into `unconstrained_large` |

### How feasible constraints are built

1. Pick a random subset S of nodes (just large enough for the requested constraints, sometimes more) and shuffle it. The **witness tour** is `0 → S in that order → the remaining nodes → 0`.
2. **Deadlines**: sample nodes from S. Each node's deadline is `ceil(arrival time along the witness × s)`.
3. **Precedences**: sample node pairs from S and orient each pair the way the witness visits them.

The witness satisfies every constraint, so the instance is feasible by construction. Held-Karp then computes the true optimum `c*`, which is often cheaper than the witness.

### Infeasible classes

Each class starts from a feasible all-constrained instance and injects a contradiction. The contradiction is provable from shortest-path lower bounds `sp` (Floyd-Warshall; rounding means a direct edge isn't always the shortest path). Held-Karp double-checks that every one is infeasible.

| Class | Construction | What a solver must notice |
|---|---|---|
| unreachable deadline | `D(v) < sp(0, v)` | one deadline is impossible on its own |
| precedence cycle | `a → b (→ c) → a` | the precedences contradict each other |
| precedence + deadline chain | precedences `a1 < a2 < … < ak` and `D(ak) < sp(0,a1) + Σ sp(ai, ai+1)` | each constraint is fine alone; the chain forces a detour that misses the deadline |
| deadline pair clash | deadlines on u and v, each `≥ sp(0, ·)`, but both `< min(sp(0,u)+sp(u,v), sp(0,v)+sp(v,u))` | whichever of u, v is visited second arrives too late |

---

## 2. Writing a solver

Subclass `tsp_common.Solver` and implement `solve(problem, seed)`:

```python
import tsp_common as tc

class MyLLMSolver(tc.Solver):
    name = "MyLLM-v1"                       # used in output folder names and reports

    def __init__(self, model="some-model"):
        self.model = model

    def solve(self, problem: tc.Problem, seed: int):
        prompt = problem.to_text()          # ready-made description (coords, matrix, constraints)
        try:
            text, usage = call_my_llm(prompt, seed=seed, timeout=problem.time_limit)
        except TimeoutError:
            return None, {"error": "timeout"}
        tour = parse_tour(text)             # your parsing
        if tour == "INFEASIBLE":
            return None, {"model": self.model, "raw_text": text}             # claims infeasible
        if tour is None:
            return None, {"error": "could not parse answer", "raw_text": text}
        return tour, {"model": self.model, "tokens_in": usage.input, "tokens_out": usage.output,
                      "raw_text": text}
```

### What the solver receives: `Problem`

| Attribute | Description |
|---|---|
| `name`, `category` | case identity |
| `n` | number of nodes |
| `coords` | `[(x, y), ...]` floats, index = node id |
| `dist(i, j)` | integer `EUC_2D` distance |
| `matrix` | full integer distance matrix (built lazily; about 1M entries for lu980) |
| `deadlines` | `{node: D}` |
| `precedences` | `[(a, b), ...]` |
| `start` | always `0` |
| `time_limit` | seconds allowed per call (from the config) |
| `to_text(include_matrix=True)` | plain-text problem statement for prompts |
| `tour_cost(tour)` | cost of a node sequence |

The `Problem` never contains the reference answer.

### Return protocol

Return `(answer, metadata)`. A bare `answer` is also accepted.

| Return | Meaning | Graded as |
|---|---|---|
| `[0, ..., 0]` list of ints | a tour | Optimal / Valid suboptimal / Invalid |
| `None`, metadata without `error` | "this instance is infeasible" | Correct None / Wrong None |
| `None`, `metadata["error"] == "timeout"` | gave up on time | Timeout |
| `None`, any other `metadata["error"]` | failure (e.g. unparseable LLM output) | Malformed |
| anything else (not a list of ints) or an exception | | Malformed |

Optional metadata keys are stored with every run and shown in the viewer: `tokens_in`, `tokens_out`, `reasoning_tokens`, `cost`, `model`, `settings`, `raw_text`. Add any other JSON-serialisable keys you like.

**Timeouts**: the solver must enforce `problem.time_limit` itself. The engine measures wall time and labels any call longer than the limit Timeout, even if it returned a tour. It does not kill a hung solver.

**Seeds**: repeat `j` of every case gets `seed = BASE_SEED + j`. Use the seed for sampling or temperature so runs are reproducible.

## 3. Running solvers

Register solvers in `benchmark_config.py`:

```python
from solvers import OracleSolver, NearestNeighbourSolver
from my_solvers import MyLLMSolver

SOLVERS = [OracleSolver, NearestNeighbourSolver, MyLLMSolver(model="some-model")]  # classes or instances
K = 3                    # repeats per case
BASE_SEED = 0
TIME_LIMIT = 300         # seconds per call
TESTCASES_DIR = "testcases"
OUTPUT_DIR = "outputs"
CATEGORIES = None        # or a list of category folder names
```

```bash
python run_solvers.py [--solvers MyLLM-v1] [--categories unconstrained_small all_constrained_small]
                      [--k 3] [--time-limit 300] [--testcases testcases] [--out outputs]
```

Each solver gets its own folder:

```
outputs/<YYYYmmdd_HHMMSS>_<SolverName>/
  run_config.json                    # solver, k, seeds, time limit, timestamps, total wall time
  testcases/<category>/<name>.json   # same stem as the .tsp
```

Each per-case JSON contains `testcase` (path to the .tsp), `reference` (n, feasible, optimal_cost, infeasible_class, constraint counts, slack) and `runs`. Each run has `seed`, `answer`, `metadata`, `wall_time`, `label`, `error`, `violations`, `cost`, `gap`, `constraint_satisfaction` and `hallucinated_tour`.

## 4. Evaluating

```bash
python evaluate.py outputs/20261021_133748_MyLLM-v1
python evaluate.py outputs/*_Oracle outputs/*_MyLLM-v1      # plus outputs/compare_<ts>.html
```

This adds `benchmark_dump.json` and `report.html` to each folder. Both are self-contained and work offline. With two or more folders it also writes a comparison page.

### Outcome labels

| Label | When |
|---|---|
| Optimal | valid tour with cost = c* (or the published optimum) |
| Valid suboptimal | valid tour, cost > c* |
| Invalid | tour breaks a rule: missing/duplicate node, hallucinated id, wrong start/end, deadline, precedence. On an infeasible case any tour is Invalid (a *hallucinated tour*). |
| Correct None / Wrong None | `None` on an infeasible / feasible case |
| Timeout | `error="timeout"`, or wall time > limit |
| Malformed | other `error`, non-list answer, or exception |

### Metrics in `benchmark_dump.json`

These are computed for `overall` and for each entry in `per_category`:

- **Correctness**: `outcomes` / `outcome_rates`; `validity_rate` and `optimal_rate` (over runs on feasible cases); `gap` = (cost − c*) / c* over valid tours (`mean`, `median`, `p90`, `max`); `constraint_satisfaction.mean` (fraction of deadline + precedence constraints met by returned tours); `violations` (runs affected and total occurrences per violation type).
- **Safeguard** (`safeguard`): "infeasible" is the positive class, and a `None` answer is a positive prediction. Reports `tp/fp/fn/tn`, `precision`, `recall`, `f1` (0 if the solver never correctly claims infeasible), `false_infeasible_rate`, `hallucinated_tour_rate`, and `per_class` detection rates for the four infeasible classes.
- **Reproducibility** (`reproducibility`): `outcome_agreement` (share of cases whose k labels are identical); `pass_at_1_*` / `pass_at_k_*` for valid and optimal. Success means a valid (or optimal) tour on feasible cases and Correct None on infeasible ones; pass@k counts a case if any of its k runs succeeds. `mean_gap_std` is the mean per-case standard deviation of the gap.

`robustness` holds the scaling curves:

| Key | What it is |
|---|---|
| `by_n` | validity / optimal / mean gap per node count, including the national sizes |
| `by_deadlines` | `unconstrained_small` + `deadline_constrained_small` |
| `by_precedences` | `unconstrained_small` + `precedence_constrained_small` |
| `by_slack` | deadline and all-constrained sets |
| `by_total_constraints` | small sets |
| `infeasible_detection_by_n` | infeasible-case detection rate per node count |
| `largest_n_validity_90` | the largest N such that validity is ≥ 90% at every N up to it |

`cases` lists every case with its labels, costs and gaps.

Wall time is recorded per run, but it isn't reported as a metric.

### The report

The report contains:
- headline numbers;
- outcome distribution per category;
- a correctness table;
- robustness charts (vs N, deadlines, precedences, slack, total constraints, and gap vs N);
- the safeguard confusion matrix and per-class detection;
- violation breakdown;
- reproducibility;
- a searchable per-instance drilldown;
- the run configuration.

Hovering over a chart mark shows its value.

## 5. Viewer

```bash
python view_generated.py outputs/20261021_133748_MyLLM-v1     # or no argument to pick a folder
```

- **Sidebar**: cases grouped by category, each with its per-run labels (Opt / Sub / Inv / None✓ / None✗ / T/O / Mal) and a per-category count of correct runs.
- **Canvas**:
  - the solver's tour, with direction arrows for small N;
  - node 0 as a red square;
  - deadline nodes ringed in orange, or red if the solver arrives late or never;
  - precedence arcs as dashed arrows.

  Hover over a node to see its coordinates, deadline and the solver's arrival time.
- **Run** selector switches between the k repeats.
- **Show optimal tour** overlays the reference tour. It's disabled for infeasible cases and for national cases, whose published optimal tours aren't downloadable, so only their cost is known.
- **Info panel** shows the reference (c* or the infeasibility proof), the run's label, cost, gap, constraint satisfaction, tour, violations, error and metadata.

## Baseline sanity check

With the default test cases:

| Solver | Validity | Optimal | Infeasibility F1 | Notes |
|---|---|---|---|---|
| Oracle (Held-Karp) | 97.6% | 97.6% | 1.00 | optimal on every small case; Malformed on national cases (N > 12) |
| NearestNeighbour | 60.2% | 24.8% | 0.40 | only detects precedence cycles |
| Random | 14.0% | 0.8% | 0.00 | |
| AlwaysNone | 0% | 0% | 0.34 | perfect only on infeasible cases |

## Tests

```bash
python -m unittest discover tests
```

The suite covers:
- the distance rule and TSPLIB round-trip;
- every validator violation type and every grading protocol case;
- Held-Karp vs brute force on random constrained instances;
- generator determinism and reference consistency (feasible cases match c* and have valid witnesses; infeasible ones are infeasible under Held-Karp);
- every infeasibility proof;
- an end-to-end run → evaluate pipeline, including a crashing solver.

# Constrained TSP Benchmark

A benchmarking engine for comparing solvers (LLM-based and classical) on the travelling salesman problem with **deadline** and **precedence** constraints. It generates test cases with exact reference answers, runs plugged-in solver classes, grades every answer, and produces statistics, an HTML report and an interactive viewer.

**Contents**

1. [Requirements and setup](#requirements-and-setup)
2. [Quick start](#quick-start)
3. [The problem](#the-problem)
4. [Generating test cases](#1-generating-test-cases)
5. [Writing a solver](#2-writing-a-solver)
6. [Running solvers](#3-running-solvers)
7. [Evaluating results](#4-evaluating-results)
8. [The viewer](#5-the-viewer)
9. [File formats](#file-formats)
10. [Common workflows](#common-workflows)
11. [Troubleshooting](#troubleshooting)
12. [Tests](#tests)
13. [Project layout](#project-layout)

---

## Requirements and setup

- **Python 3.10 or newer** (developed on 3.12, targets 3.14).
- **Standard library only**, so there's nothing to `pip install`. `requirements.txt` documents this and lists pytest as an optional extra, so `pip install -r requirements.txt` is a harmless no-op.
- **Tkinter** is needed only for the viewer (`view_generated.py`). It ships with the python.org installers on Windows and macOS. On Debian/Ubuntu run `sudo apt install python3-tk`.
- Run every script **from the repository root**. The scripts import each other and use relative paths such as `testcases/` and `outputs/`.

```bash
git clone https://github.com/EugeneOYZ1203n/CS4263_Project.git
cd CS4263_Project
python -m unittest discover tests      # optional: check the install (about 10 s)
```

## Quick start

```bash
python generate_testcases.py                      # 1. build testcases/
python run_solvers.py                             # 2. run every solver listed in benchmark_config.py
python evaluate.py outputs/<ts>_<Solver> [...]    # 3. statistics + report.html (+ comparison page)
python view_generated.py outputs/<ts>_<Solver>    # 4. browse the tours interactively
```

Abridged output with the default configuration and the four baseline solvers:

```text
$ python generate_testcases.py
unconstrained_small                         6
deadline_constrained_small                 54
precedence_constrained_small               18
all_constrained_small                     162
unconstrained_large                         6
infeasible_unreachable_deadline            16
infeasible_precedence_cycle                16
infeasible_precedence_deadline_chain       16
infeasible_deadline_pair_clash             16
total                                     310  -> testcases/

$ python run_solvers.py
Oracle: 310 cases x k=3 -> outputs/20261021_133748_Oracle
  [   1/310] all_constrained_small/ac_N05_d1_p2_s100_000: Optimal, Optimal, Optimal
  ...
Oracle done: Malformed=18, Optimal=720, Correct None=192
  next: python evaluate.py outputs/20261021_133748_Oracle
NearestNeighbour: 310 cases x k=3 -> outputs/20261021_133748_NearestNeighbour
...

$ python evaluate.py outputs/20261021_133748_*
AlwaysNone: validity 0.0%, optimal 0.0%, F1 0.34 -> outputs/20261021_133748_AlwaysNone/report.html
NearestNeighbour: validity 60.2%, optimal 24.8%, F1 0.40 -> outputs/20261021_133748_NearestNeighbour/report.html
Oracle: validity 97.6%, optimal 97.6%, F1 1.00 -> outputs/20261021_133748_Oracle/report.html
Random: validity 14.0%, optimal 0.8%, F1 0.00 -> outputs/20261021_133748_Random/report.html
comparison -> outputs/compare_20261021_134244.html
```

Open any `report.html` or `compare_*.html` in a browser by double-clicking it. Both work offline.

---

## The problem

- Nodes have **float coordinates**. The distance between two nodes is the Euclidean distance **rounded to the nearest integer**, which is the TSPLIB `EUC_2D` rule: `int(sqrt(dx² + dy²) + 0.5)`. Edge weights, tour costs and deadlines are therefore integers, and the published optima of the national instances stay exact.
- The graph is complete and symmetric.
- A tour starts and ends at node **0**, visits every other node exactly once, and is written as `[0, v1, ..., v_{n-1}, 0]` (length N + 1).
- **Deadline** `(v, D)`: the cumulative distance travelled from node 0 until the **first arrival** at `v` must be `≤ D`.
- **Precedence** `(a, b)`: `a` must be visited before `b`.
- An **infeasible** instance has no tour that satisfies every constraint. The correct answer is `None`.

---

## 1. Generating test cases

```bash
python generate_testcases.py [flags]
```

| Flag | Default | Meaning |
|---|---|---|
| `--out DIR` | `testcases` | output directory |
| `--seed INT` | `4263` | master seed; each case's own seed is derived from it |
| `--n-min INT` | `5` | smallest node count of the small sets |
| `--n-max INT` | `10` | largest node count of the small sets (at most 13, the limit of the exact Held-Karp reference) |
| `--seeds-per-cell INT` | `1` | instances per sweep cell; raise it for tighter statistics |
| `--deadlines INT...` | `1 2 4` | deadline counts to sweep (capped at N−1) |
| `--precedences INT...` | `2 4 8` | precedence counts to sweep (capped by the number of node pairs) |
| `--slacks FLOAT...` | `1.0 1.2 1.5` | deadline tightness; 1.0 means the witness tour arrives exactly on time |
| `--infeasible-fraction FLOAT` | `0.2` | infeasible cases as a share of **all** cases, split evenly across the 4 classes |
| `--coord-max FLOAT` | `1000` | coordinates are uniform in `[0, coord-max)`, rounded to 4 decimals |

The defaults also live as constants at the top of `generate_testcases.py`: `MASTER_SEED`, `N_MIN`, `N_MAX`, `SEEDS_PER_CELL`, `DEADLINE_COUNTS`, `PRECEDENCE_COUNTS`, `SLACKS`, `INFEASIBLE_FRACTION`, `COORD_MAX`, `NATIONAL`. Edit them to change the defaults permanently.

**Behaviour**
- Output is **deterministic**: the same flags always produce byte-identical files.
- Each run **deletes and regenerates** the nine category folders inside `--out`. Other files in `--out` are left alone.
- Every feasible small case is solved exactly when generated, and every infeasible case is confirmed infeasible. Generation takes about a second with the defaults.

### Category folders

| Folder | Contents (default config) | Count |
|---|---|---|
| `unconstrained_small` | N = 5..10, no constraints | 6 |
| `deadline_constrained_small` | N × deadlines {1,2,4} × slack {1.0,1.2,1.5} | 54 |
| `precedence_constrained_small` | N × precedences {2,4,8} | 18 |
| `all_constrained_small` | N × deadlines × precedences × slack | 162 |
| `unconstrained_large` | National TSPs: wi29 (Western Sahara), dj38 (Djibouti), qa194 (Qatar), uy734 (Uruguay), zi929 (Zimbabwe), lu980 (Luxembourg) | 6 |
| `infeasible_unreachable_deadline` | N = 5..10, see below | 16 |
| `infeasible_precedence_cycle` | | 16 |
| `infeasible_precedence_deadline_chain` | | 16 |
| `infeasible_deadline_pair_clash` | | 16 |

**Case names** encode their parameters:
- `dl_N07_d2_p0_s120_031`: deadline set, N = 7, 2 deadlines, 0 precedences, slack 1.20, index 31.
- Prefixes: `uc`, `dl`, `pc`, `ac` for the feasible sets; `inf_ud`, `inf_cy`, `inf_ch`, `inf_pr` for the infeasible classes.

The national instances come from the [Waterloo National TSP collection](https://www.math.uwaterloo.ca/tsp/world/countries.html) and are stored in `data/national/` with their published optimal lengths (27603, 6656, 9352, 79114, 95345, 11340).

### How feasible constraints are built

1. Pick a random subset S of nodes (just large enough for the requested constraints, sometimes more) and shuffle it. The **witness tour** is `0 → S in that order → the remaining nodes → 0`.
2. **Deadlines**: sample nodes from S. Each node's deadline is `ceil(arrival time along the witness × slack)`.
3. **Precedences**: sample node pairs from S and orient each pair the way the witness visits them.

The witness satisfies every constraint, so the instance is feasible by construction. The exact Held-Karp solver then computes the true optimum `c*`, which is often cheaper than the witness.

### Infeasible classes

Each class starts from a feasible all-constrained instance and injects a contradiction. The contradiction is provable from shortest-path lower bounds `sp` (computed with Floyd-Warshall, because rounding means a direct edge isn't always the shortest path). The exact solver double-checks that every one is infeasible. The sidecar's `infeasibility_proof` states the reason.

| Class | Construction | What a solver must notice |
|---|---|---|
| unreachable deadline | `D(v) < sp(0, v)` | one deadline is impossible on its own |
| precedence cycle | `a → b (→ c) → a` | the precedences contradict each other |
| precedence + deadline chain | precedences `a1 < a2 < … < ak` and `D(ak) < sp(0,a1) + Σ sp(ai, ai+1)` | each constraint is fine alone; the forced detour misses the deadline |
| deadline pair clash | deadlines on u and v, each `≥ sp(0, ·)`, but both `< min(sp(0,u)+sp(u,v), sp(0,v)+sp(v,u))` | whichever of u, v is visited second arrives too late |

---

## 2. Writing a solver

A solver is a subclass of `tsp_common.Solver` with a `name` and a `solve(problem, seed)` method.

### Minimal working example

Save this as `solvers/earliest_deadline.py`:

```python
import tsp_common as tc


class EarliestDeadlineSolver(tc.Solver):
    """Among nodes whose predecessors are visited, take the earliest deadline, then the nearest."""
    name = "EarliestDeadline"

    def solve(self, problem, seed):
        preds = {}
        for a, b in problem.precedences:
            preds.setdefault(b, set()).add(a)
        tour, todo = [0], set(range(1, problem.n))
        while todo:
            ready = [v for v in todo if preds.get(v, set()) <= set(tour)]
            if not ready:
                return None, {"note": "stuck: precedence cycle"}   # claim: infeasible
            last = tour[-1]
            nxt = min(ready, key=lambda v: (problem.deadlines.get(v, float("inf")), problem.dist(last, v)))
            tour.append(nxt)
            todo.remove(nxt)
        return tour + [0], {}
```

Register it in `benchmark_config.py`, then run only that solver:

```python
from solvers.earliest_deadline import EarliestDeadlineSolver
SOLVERS = [EarliestDeadlineSolver]
```

```bash
python run_solvers.py --solvers EarliestDeadline
```

On the default test cases this heuristic reaches about 92% validity, 22% optimal and an infeasibility F1 of 0.40.

### What the solver receives: `Problem`

| Attribute / method | Description |
|---|---|
| `name`, `category` | case identity |
| `n` | number of nodes |
| `coords` | `[(x, y), ...]` floats; index = node id |
| `dist(i, j)` | integer `EUC_2D` distance |
| `matrix` | full integer distance matrix, built on first access (about 1M entries for lu980) |
| `deadlines` | `{node: D}` |
| `precedences` | `[(a, b), ...]`, a before b |
| `start` | always `0` |
| `time_limit` | seconds allowed for this call (from the config) |
| `to_text(include_matrix=True)` | plain-text problem statement, ready to use as a prompt body |
| `tour_cost(tour)` | cost of a node sequence |

The `Problem` never contains the reference answer.

### Return protocol

`solve` returns `(answer, metadata)`. A bare `answer` is also accepted.

| Return | Meaning | Graded as |
|---|---|---|
| `[0, ..., 0]`, a list of ints | a tour | Optimal / Valid suboptimal / Invalid |
| `None`, metadata **without** `error` | "this instance is infeasible" | Correct None / Wrong None |
| `None`, `metadata["error"] == "timeout"` | gave up because of time | Timeout |
| `None`, any other `metadata["error"]` | failure (e.g. unparseable LLM output) | Malformed |
| anything that isn't a list of ints, or an exception | | Malformed |

**Metadata** is stored with every run and shown in the viewer.
- Recommended keys: `model`, `settings`, `tokens_in`, `tokens_out`, `reasoning_tokens`, `cost`, `raw_text`.
- Any other key is fine too; values that aren't JSON-serialisable are stored as their `repr`.

**Timeouts**:
- The solver must enforce `problem.time_limit` itself.
- The engine measures wall time and labels any call that runs longer than the limit as Timeout, even if it returned a tour.
- The engine **cannot interrupt** a hung solver.

**Seeds**: repeat `j` of every case gets `seed = BASE_SEED + j`. Use the seed for sampling or temperature so repeats are reproducible and comparable.

### LLM solver skeleton

```python
import json
import re

import tsp_common as tc

PROMPT = """Solve this constrained travelling salesman problem.
{problem}
Reply with the tour as a JSON list, e.g. [0, 3, 1, 2, 0], or the single word INFEASIBLE."""


def parse_answer(text):
    """Return a tour, the string "infeasible", or None if unparseable."""
    if re.search(r"\bINFEASIBLE\b", text, re.IGNORECASE):
        return "infeasible"
    m = re.search(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", text)
    return json.loads(m.group()) if m else None


class MyLLMSolver(tc.Solver):
    def __init__(self, model="your-model-id", temperature=0.0):
        self.model, self.temperature = model, temperature
        self.name = f"LLM-{model}"                     # unique per configuration

    def solve(self, problem, seed):
        prompt = PROMPT.format(problem=problem.to_text(include_matrix=problem.n <= 40))
        meta = {"model": self.model, "settings": {"temperature": self.temperature}}
        try:
            # Pass the time limit to your client so the request itself is cancelled.
            reply = call_your_llm(prompt, model=self.model, seed=seed,
                                  temperature=self.temperature, timeout=problem.time_limit)
        except TimeoutError:
            return None, {**meta, "error": "timeout"}
        meta.update(raw_text=reply.text, tokens_in=reply.input_tokens, tokens_out=reply.output_tokens)
        parsed = parse_answer(reply.text)
        if parsed == "infeasible":
            return None, meta                          # a claim, graded Correct/Wrong None
        if parsed is None:
            return None, {**meta, "error": "unparseable answer"}   # graded Malformed
        return parsed, meta
```

`call_your_llm` stands for your API client. If the client has no timeout option, wrap the call in `concurrent.futures.ThreadPoolExecutor().submit(...).result(timeout=...)`. Note that the background thread keeps running after the timeout fires.

### Solver checklist

- [ ] `name` is unique across `SOLVERS` (it names the output folder and labels the reports).
- [ ] A tour starts and ends with `0` and contains plain `int`s.
- [ ] "Infeasible" is signalled with `None` and **no** `error` key; failures always set `error`.
- [ ] `problem.time_limit` is respected.
- [ ] Exceptions are fine: they are caught, stored with a traceback, and graded Malformed.

---

## 3. Running solvers

### `benchmark_config.py`

```python
from solvers import AlwaysNoneSolver, NearestNeighbourSolver, OracleSolver, RandomSolver

SOLVERS = [OracleSolver, NearestNeighbourSolver, RandomSolver, AlwaysNoneSolver]
K = 3                       # repeats per (solver, test case)
BASE_SEED = 0               # repeat j gets seed BASE_SEED + j
TIME_LIMIT = 300            # seconds per call
TESTCASES_DIR = "testcases"
OUTPUT_DIR = "outputs"
CATEGORIES = None           # None = all folders, or e.g. ["unconstrained_small", "all_constrained_small"]
```

`SOLVERS` entries can be **classes**, which are instantiated with no arguments, or **instances**, for solvers that need constructor arguments such as `MyLLMSolver(model="...")`.

### Command line

```bash
python run_solvers.py [flags]
```

| Flag | Default (from config) | Meaning |
|---|---|---|
| `--solvers NAME...` | all in `SOLVERS` | run only solvers whose `name` matches |
| `--categories CAT...` | `CATEGORIES` | run only these category folders |
| `--k INT` | `K` | repeats per case |
| `--time-limit SECONDS` | `TIME_LIMIT` | limit passed to solvers and used for Timeout labels |
| `--testcases DIR` | `TESTCASES_DIR` | where the test cases are |
| `--out DIR` | `OUTPUT_DIR` | where output folders are created |

Flags override the config for that run only. `BASE_SEED` can only be set in the config.

### Output

Each solver gets its own folder. All solvers from one invocation share the timestamp.

```
outputs/<YYYYmmdd_HHMMSS>_<SolverName>/
  run_config.json                    # solver, k, seeds, time limit, timestamps, total wall time
  testcases/<category>/<name>.json   # same stem as the .tsp; k graded runs
```

The runner prints one line per case with the k labels, then a label summary and the matching `evaluate.py` command.

---

## 4. Evaluating results

```bash
python evaluate.py FOLDER [FOLDER ...] [--compare-out PATH]
```

| Argument | Meaning |
|---|---|
| `FOLDER...` | one or more `outputs/<ts>_<Solver>` folders |
| `--compare-out PATH` | where to write the comparison page (default: `compare_<timestamp>.html` next to the first folder, i.e. in `outputs/`) |

- For **each folder**, this writes `benchmark_dump.json` and `report.html` into it. It reads only the folder, so you can re-run it at any time without re-running solvers.
- With **two or more folders**, it also writes the comparison page.

### Outcome labels

| Label | When |
|---|---|
| Optimal | valid tour with cost = c* (or the published optimum) |
| Valid suboptimal | valid tour, cost > c* |
| Invalid | the tour breaks a rule. On an infeasible case every tour is Invalid (a *hallucinated tour*). |
| Correct None | `None` on an infeasible case |
| Wrong None | `None` on a feasible case |
| Timeout | `error="timeout"`, or wall time > limit |
| Malformed | other `error`, a non-list answer, or an exception |

Violation types recorded for Invalid and Wrong None runs:
- structural: `missing_node`, `duplicate_node`, `hallucinated_id`, `wrong_start_end`;
- constraints: `deadline`, `precedence`;
- `wrong_none`.

### Metrics

These appear in `benchmark_dump.json` for `overall` and for each category in `per_category`.

**Correctness**
- `outcomes`, `outcome_rates`: label counts and shares over all runs.
- `validity_rate`, `optimal_rate`: share of runs on **feasible** cases that are valid / optimal.
- `gap`: `(cost − c*) / c*` over valid tours, with `mean`, `median`, `p90` and `max`.
- `constraint_satisfaction.mean`: mean fraction of deadline + precedence constraints met by returned tours (partial credit for invalid ones).
- `violations`: for each type, the runs affected, total occurrences and share of runs.

**Safeguard** (`safeguard`): "infeasible" is the positive class, and any `None` answer is a positive prediction.
- `tp`, `fp`, `fn`, `tn`, `precision`, `recall`, `f1`. F1 is 0 when the solver never correctly claims infeasible.
- `false_infeasible_rate`: `None` on feasible runs.
- `hallucinated_tour_rate`: tours returned on infeasible runs.
- `per_class`: detection rate per infeasible class.

**Reproducibility** (`reproducibility`)
- `outcome_agreement`: share of cases whose k labels are all identical.
- `pass_at_1_valid`, `pass_at_k_valid`, `pass_at_1_optimal`, `pass_at_k_optimal`. A run *succeeds* with a valid (or optimal) tour on a feasible case, or Correct None on an infeasible one. pass@k counts a case if any of its k runs succeeds.
- `mean_gap_std`: mean per-case standard deviation of the gap.

**Robustness** (`robustness`), each a list of `{x, cases, runs, validity, optimal, mean_gap}`:

| Key | Grouping |
|---|---|
| `by_n` | node count, including the national sizes |
| `by_deadlines` | `unconstrained_small` + `deadline_constrained_small` |
| `by_precedences` | `unconstrained_small` + `precedence_constrained_small` |
| `by_slack` | deadline and all-constrained sets |
| `by_total_constraints` | the four small sets |
| `infeasible_detection_by_n` | infeasible cases, `{x, runs, detection}` |
| `largest_n_validity_90` | largest N such that validity ≥ 90% at **every** N up to it |

Wall time is recorded per run (in the per-case JSON and the viewer), but it isn't reported as a metric.

### The report (`report.html`)

1. **Headline numbers**: validity, optimal rate, median gap, infeasibility F1, pass@k optimal, outcome agreement.
2. **Outcome distribution**: one 100% stacked bar per category (and overall). Hover over a segment for its count.
3. **Correctness by category**: validity, optimal rate, gap statistics, constraint satisfaction.
4. **Robustness**: validity and optimal rate vs N, deadlines, precedences, slack and total constraints; mean gap vs N; the per-N table.
5. **Safeguard**: confusion matrix, precision / recall / F1, false-infeasible and hallucinated-tour rates, detection per class.
6. **Violations**: share of runs with each violation type.
7. **Reproducibility**: agreement, pass@1 / pass@k, gap spread.
8. **Per-instance drilldown**: one collapsible table per category with each case's reference, run labels, costs, gaps and first issue. The search box filters by case name.
9. **Run configuration**.

Every chart has a matching table. Light and dark mode follow your system setting.

### The comparison page (`compare_<ts>.html`)

- A summary table with one row per solver.
- Outcome bars per solver.
- Validity and optimal rate vs N, validity vs slack and vs total constraints, with one line per solver.
- Detection rate per infeasible class.
- Optimal rate per category.

---

## 5. The viewer

```bash
python view_generated.py [FOLDER]
```

`FOLDER` is an `outputs/<ts>_<Solver>` folder. If you omit it, a folder picker opens in `outputs/`. The viewer reads the test case files through the path stored in each result, so keep `testcases/` in place.

**Sidebar**
- Categories (with case counts and how many runs were correct), each expandable into its cases.
- Each case shows its k run labels and is coloured by its best run.
- Abbreviations: `Opt` Optimal, `Sub` Valid suboptimal, `Inv` Invalid, `None✓` Correct None, `None✗` Wrong None, `T/O` Timeout, `Mal` Malformed.

**Toolbar**

| Control | Effect |
|---|---|
| Run | choose which of the k repeats to show |
| Show optimal tour | overlay the reference tour. Disabled for infeasible cases ("no tour exists") and national cases (only the published cost is known). |
| Precedence arcs | show or hide dashed grey arrows `a → b` |
| Node labels | show node ids and `D=` deadline values (cases with N ≤ 40) |

**Canvas**

| Mark | Meaning |
|---|---|
| blue line with arrows | the solver's tour and its direction (arrows for N ≤ 40) |
| green line | the optimal tour (dashed for small N) |
| red square | node 0, the start |
| orange ring | a deadline node met by the tour |
| thick red ring | a deadline node the tour reaches late or never |
| grey dashed arrow | a precedence constraint |
| text at the top | shown when the run returned no tour: the None claim, or the error |

Hover over a node to see its coordinates, deadline and the solver's arrival time in the status bar. The window can be resized and redraws to fit.

**Info panel**
- **Case**: name, category, N, constraint counts, slack.
- **Reference**: c* and its source, or the infeasibility class and proof.
- **Selected run**: label, seed, wall time, cost, gap, constraint satisfaction, error, raw answer if malformed, the tour, the violation list and the metadata (`raw_text` and tracebacks omitted).

---

## File formats

### Test case: `<name>.tsp`

A standard TSPLIB file. Node ids are 1-based in the file and 0-based everywhere else.

```text
NAME : dl_N05_d1_p0_s100_000
COMMENT : deadline_constrained_small (constrained TSP benchmark)
TYPE : TSP
DIMENSION : 5
EDGE_WEIGHT_TYPE : EUC_2D
NODE_COORD_SECTION
1 209.3016 722.0483
2 590.3673 756.2693
...
EOF
```

### Test case sidecar: `<name>.json`

```json
{
  "name": "dl_N05_d1_p0_s100_000", "category": "deadline_constrained_small",
  "n": 5, "seed": 3048448314,
  "deadlines": [[2, 224]], "precedences": [],
  "params": {"n_deadlines": 1, "n_precedences": 0, "slack": 1.0},
  "feasible": true, "optimal_cost": 2025, "optimal_tour": [0, 2, 4, 3, 1, 0],
  "reference_source": "held_karp",
  "infeasible_class": null, "infeasibility_proof": null,
  "witness_tour": [0, 2, 3, 4, 1, 0]
}
```

For infeasible cases, `feasible` is `false`, `optimal_cost`, `optimal_tour` and `witness_tour` are `null`, and `infeasibility_proof` explains the contradiction:

```json
{"nodes": [3, 4], "deadline": [535, 613], "lower_bound": 826,
 "reason": "whichever of 3,4 is second arrives >= 826 > deadlines 535,613"}
```

National sidecars have `reference_source: "published optimum (Waterloo National TSP)"` and `optimal_tour: null`.

### Run result: `outputs/<ts>_<Solver>/testcases/<category>/<name>.json`

```json
{
  "name": "dl_N05_d1_p0_s100_000", "category": "deadline_constrained_small",
  "testcase": "testcases/deadline_constrained_small/dl_N05_d1_p0_s100_000.tsp",
  "reference": {"n": 5, "feasible": true, "optimal_cost": 2025, "infeasible_class": null,
                "n_deadlines": 1, "n_precedences": 0, "slack": 1.0},
  "runs": [
    {"repeat": 0, "seed": 0, "wall_time": 2.19e-05,
     "answer": [0, 2, 4, 1, 3, 0], "metadata": {},
     "label": "Valid suboptimal", "error": null, "violations": [],
     "cost": 2296, "gap": 0.1338, "constraint_satisfaction": 1.0, "hallucinated_tour": false}
  ]
}
```

- `violations` entries look like `{"type": "deadline", "detail": "node 1 arrival 2782 > deadline 2035"}`.
- Malformed answers are stored as `answer: null` plus `answer_raw` (their `repr`).
- Exceptions put a `traceback` in `metadata`.

### `run_config.json`

```json
{"solver": "NearestNeighbour", "solver_class": "NearestNeighbourSolver",
 "started": "2026-10-21T13:37:48", "finished": "2026-10-21T13:37:51",
 "k": 3, "base_seed": 0, "time_limit": 300, "testcases_dir": "testcases",
 "n_cases": 310, "total_wall_time": 2.198}
```

### `benchmark_dump.json`

```text
solver, run_config, evaluated
overall        -> n_cases, n_runs, n_feasible_runs, n_infeasible_runs, outcomes, outcome_rates,
                  validity_rate, optimal_rate, gap, constraint_satisfaction, violations,
                  safeguard, reproducibility
per_category   -> {category: same structure as overall}
robustness     -> by_n, by_deadlines, by_precedences, by_slack, by_total_constraints,
                  infeasible_detection_by_n, largest_n_validity_90
cases          -> [{name, category, n, feasible, optimal_cost, infeasible_class,
                    n_deadlines, n_precedences, slack, labels, costs, gaps}, ...]
```

Rates are fractions in [0, 1], or `null` when there's nothing to measure.

---

## Common workflows

**Quick smoke test on one category**
```bash
python run_solvers.py --solvers EarliestDeadline --categories unconstrained_small --k 1
```

**Tighter statistics** (3 instances per sweep cell, about 910 cases)
```bash
python generate_testcases.py --seeds-per-cell 3
```

**Harder or easier small instances**
```bash
python generate_testcases.py --n-min 8 --n-max 12 --slacks 1.0 1.1   # up to N = 13 is supported
```

**Keep several test sets side by side**
```bash
python generate_testcases.py --out testcases_hard --n-min 9 --n-max 12
python run_solvers.py --testcases testcases_hard
```

**Re-evaluate without re-running solvers** (e.g. after updating `evaluate.py`)
```bash
python evaluate.py outputs/20261021_133748_MyLLM
```

**Compare solvers from different runs**
```bash
python evaluate.py outputs/*_Oracle outputs/*_LLM-* --compare-out outputs/oracle_vs_llm.html
```

**Reproducibility**: a test set is fully determined by its generator flags, including `--seed`, and a run by `benchmark_config.py`. Record both alongside your results. `run_config.json` already stores the run settings.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `no test cases under testcases/` | Run `python generate_testcases.py` first, or point `--testcases` at the right folder. |
| `no solvers selected` | `--solvers` must match each solver's `name` attribute exactly (case-sensitive), not the class name. |
| A run never finishes | A solver is hanging. The engine can't interrupt it, so make the solver enforce `problem.time_limit`. |
| Oracle shows Malformed on `unconstrained_large` | Expected: the exact solver refuses N > 12 and reports an error. |
| "Show optimal tour" is greyed out | Infeasible cases have no tour; national cases have only a published cost. |
| Viewer: `Test case file not found` | The result points at a `.tsp` that was moved or regenerated elsewhere. Keep `testcases/` (or the `--testcases` folder used for the run) in place. |
| Viewer looks blurry or tiny on a scaled Windows display | It is DPI-aware by default. If it still looks wrong, check Windows display scaling settings for `python.exe`. |
| `testcases/`, `outputs/` or `data/national/` not found | Default paths are relative to the current directory. Run the scripts from the repository root. |

---

## Tests

```bash
python -m unittest discover tests      # pytest also works if installed
```

The suite covers:
- the distance rule and TSPLIB round-trip, and parsing of every national file;
- every validator violation type and every grading protocol case;
- the exact solver vs brute force on random constrained instances;
- generator determinism and reference consistency (feasible cases match c* and have valid witnesses; infeasible ones are infeasible);
- every infeasibility proof;
- an end-to-end run → evaluate pipeline, including a crashing solver.

### Baseline sanity check

These are the results with the default test cases and the shipped baseline solvers.

| Solver | Validity | Optimal | Infeasibility F1 | Notes |
|---|---|---|---|---|
| Oracle (exact Held-Karp) | 97.6% | 97.6% | 1.00 | optimal on every small case; Malformed on national cases (N > 12) |
| NearestNeighbour | 60.2% | 24.8% | 0.40 | ignores deadlines; only detects precedence cycles |
| Random | 14.0% | 0.8% | 0.00 | never claims infeasible |
| AlwaysNone | 0% | 0% | 0.34 | perfect only on infeasible cases |

---

## Project layout

```
benchmark_config.py     solvers to run + run settings
generate_testcases.py   script 1: test case generation
run_solvers.py          script 2: run solvers, grade, write per-case results
evaluate.py             script 3: benchmark_dump.json, report.html, comparison page
view_generated.py       script 4: Tkinter viewer
tsp_common.py           shared core: TSPLIB IO, Problem, Solver, validation, grading, exact solver
solvers/                baseline solvers (Oracle, NearestNeighbour, Random, AlwaysNone)
data/national/          Waterloo national instances (.tsp) + sidecars with published optima
tests/                  unittest suite
plan.md                 design notes
requirements.txt        no third-party dependencies (stdlib only); pytest optional
testcases/              generated (git-ignored)
outputs/                solver results and reports (git-ignored)
```

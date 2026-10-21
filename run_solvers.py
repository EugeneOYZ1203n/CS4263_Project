"""Script 2: run every solver in benchmark_config.SOLVERS on every test case.

    python run_solvers.py [--solvers Oracle Random] [--categories unconstrained_small] [--k 3]

For each solver, writes outputs/<YYYYmmdd_HHMMSS>_<SolverName>/:
    run_config.json
    testcases/<category>/<case name>.json   (k graded runs; same stem as the .tsp)
Then run evaluate.py on that folder.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

import benchmark_config as config
import tsp_common as tc

ROOT = Path(__file__).resolve().parent


def jsonable(obj):
    return json.loads(json.dumps(obj, default=repr))


def rel(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def run_once(solver: tc.Solver, problem: tc.Problem, ref: dict, seed: int, time_limit: float) -> dict:
    """Call the solver once, time it, and grade the answer."""
    t0 = time.perf_counter()
    try:
        answer, meta = tc.normalize_result(solver.solve(problem, seed))
        exc = None
    except Exception as e:  # solver bugs are a Malformed outcome, not an engine crash
        answer, meta, exc = None, {}, e
    elapsed = time.perf_counter() - t0
    record = {"seed": seed, "wall_time": elapsed}
    if exc is not None:
        record.update({"answer": None, "metadata": {"traceback": traceback.format_exc()},
                       "label": tc.MALFORMED, "error": f"exception: {type(exc).__name__}: {exc}",
                       "violations": [], "cost": None, "gap": None,
                       "constraint_satisfaction": None, "hallucinated_tour": False})
        return record
    meta = dict(meta) if isinstance(meta, dict) else {"metadata": meta}
    graded = tc.grade(problem, ref, answer, meta, elapsed, time_limit)
    if answer is None or tc.is_well_formed(answer):
        record["answer"] = None if answer is None else list(answer)
    else:
        record["answer"] = None
        record["answer_raw"] = repr(answer)[:2000]
    record["metadata"] = jsonable(meta)
    record.update(graded)
    return record


def reference_summary(ref: dict) -> dict:
    params = ref.get("params") or {}
    return {
        "n": ref.get("n"),
        "feasible": ref.get("feasible", True),
        "optimal_cost": ref.get("optimal_cost"),
        "infeasible_class": ref.get("infeasible_class"),
        "n_deadlines": len(ref.get("deadlines", [])),
        "n_precedences": len(ref.get("precedences", [])),
        "slack": params.get("slack"),
    }


def instantiate(entry) -> tc.Solver:
    return entry() if isinstance(entry, type) else entry


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "Solver"


def run_solver(solver: tc.Solver, cases: list[Path], out_dir: Path, k: int, base_seed: int,
               time_limit: float, testcases_dir: str, verbose: bool = True) -> Counter:
    out_dir.mkdir(parents=True)
    (out_dir / "run_config.json").write_text(json.dumps({
        "solver": solver.name, "solver_class": type(solver).__qualname__,
        "started": datetime.now().isoformat(timespec="seconds"),
        "k": k, "base_seed": base_seed, "time_limit": time_limit,
        "testcases_dir": testcases_dir, "n_cases": len(cases),
    }, indent=2))
    labels: Counter = Counter()
    t_start = time.perf_counter()
    for i, tsp in enumerate(cases, 1):
        problem, ref = tc.load_case(tsp, time_limit=time_limit)
        runs = []
        for j in range(k):
            rec = run_once(solver, problem, ref, base_seed + j, time_limit)
            rec["repeat"] = j
            runs.append(rec)
            labels[rec["label"]] += 1
        case_dir = out_dir / "testcases" / problem.category
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / f"{tsp.stem}.json").write_text(json.dumps({
            "name": problem.name, "category": problem.category, "testcase": rel(tsp),
            "reference": reference_summary(ref), "runs": runs,
        }, indent=1))
        if verbose:
            print(f"  [{i:4d}/{len(cases)}] {problem.category}/{problem.name}: "
                  + ", ".join(r["label"] for r in runs), flush=True)
    cfg = json.loads((out_dir / "run_config.json").read_text())
    cfg["finished"] = datetime.now().isoformat(timespec="seconds")
    cfg["total_wall_time"] = time.perf_counter() - t_start
    (out_dir / "run_config.json").write_text(json.dumps(cfg, indent=2))
    return labels


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solvers", nargs="+", help="only run solvers with these names")
    ap.add_argument("--categories", nargs="+", default=config.CATEGORIES)
    ap.add_argument("--k", type=int, default=config.K)
    ap.add_argument("--time-limit", type=float, default=config.TIME_LIMIT)
    ap.add_argument("--testcases", default=config.TESTCASES_DIR)
    ap.add_argument("--out", default=config.OUTPUT_DIR)
    args = ap.parse_args(argv)

    solvers = [instantiate(e) for e in config.SOLVERS]
    if args.solvers:
        solvers = [s for s in solvers if s.name in args.solvers]
    if not solvers:
        ap.error("no solvers selected (check benchmark_config.SOLVERS / --solvers)")
    cases = list(tc.iter_cases(args.testcases, args.categories))
    if not cases:
        ap.error(f"no test cases under {args.testcases}/ (run generate_testcases.py first)")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    used: set[str] = set()
    for solver in solvers:
        name = safe_name(solver.name)
        while name in used or (Path(args.out) / f"{stamp}_{name}").exists():
            name += "_"
        used.add(name)
        out_dir = Path(args.out) / f"{stamp}_{name}"
        print(f"{solver.name}: {len(cases)} cases x k={args.k} -> {out_dir}")
        labels = run_solver(solver, cases, out_dir, args.k, config.BASE_SEED, args.time_limit, args.testcases)
        print(f"{solver.name} done: " + ", ".join(f"{l}={labels[l]}" for l in tc.LABELS if labels[l]))
        print(f"  next: python evaluate.py {out_dir.as_posix()}")


if __name__ == "__main__":
    main()

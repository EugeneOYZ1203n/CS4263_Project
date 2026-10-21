"""Shared core for the constrained-TSP benchmark.

Instance format, distances, tour validation/grading, the exact reference solver
and the Solver base class all live here so every script agrees on them.

Conventions (match TSPLIB EUC_2D and the published national optima):
  * coordinates are floats, edge weight = nint(euclidean distance) -> int
  * nodes are 0-indexed internally (1-indexed in .tsp files), start node is 0
  * a tour is [0, v1, ..., v_{n-1}, 0] (closed, explicit return)
  * deadline (v, D): cumulative distance from 0 to the first arrival at v <= D
  * precedence (a, b): a is visited before b
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

# Outcome labels, worst to best for feasible instances.
MALFORMED = "Malformed"
TIMEOUT = "Timeout"
INVALID = "Invalid"
VALID_SUBOPTIMAL = "Valid suboptimal"
OPTIMAL = "Optimal"
# Labels for a None answer.
CORRECT_NONE = "Correct None"
WRONG_NONE = "Wrong None"

LABELS = [MALFORMED, TIMEOUT, INVALID, VALID_SUBOPTIMAL, OPTIMAL, CORRECT_NONE, WRONG_NONE]
VALID_LABELS = {VALID_SUBOPTIMAL, OPTIMAL}

# Violation types reported by check_tour / grade.
V_MISSING = "missing_node"
V_DUPLICATE = "duplicate_node"
V_HALLUCINATED = "hallucinated_id"
V_START_END = "wrong_start_end"
V_DEADLINE = "deadline"
V_PRECEDENCE = "precedence"
V_WRONG_NONE = "wrong_none"
VIOLATION_TYPES = [V_MISSING, V_DUPLICATE, V_HALLUCINATED, V_START_END,
                   V_DEADLINE, V_PRECEDENCE, V_WRONG_NONE]


def euc_2d(a: tuple[float, float], b: tuple[float, float]) -> int:
    """TSPLIB EUC_2D distance: nint(sqrt(dx^2 + dy^2))."""
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return int(math.sqrt(dx * dx + dy * dy) + 0.5)


@dataclass
class Problem:
    """What a solver sees. Holds no reference answer."""
    name: str
    coords: list[tuple[float, float]]
    deadlines: dict[int, int] = field(default_factory=dict)
    precedences: list[tuple[int, int]] = field(default_factory=list)
    category: str = ""
    time_limit: float | None = None
    start: int = 0

    @property
    def n(self) -> int:
        return len(self.coords)

    def dist(self, i: int, j: int) -> int:
        return euc_2d(self.coords[i], self.coords[j])

    @cached_property
    def matrix(self) -> list[list[int]]:
        """Full distance matrix. O(n^2) memory; fine for every shipped instance."""
        c = self.coords
        return [[euc_2d(c[i], c[j]) for j in range(len(c))] for i in range(len(c))]

    def tour_cost(self, tour: list[int]) -> int:
        return sum(self.dist(tour[i], tour[i + 1]) for i in range(len(tour) - 1))

    def to_text(self, include_matrix: bool = True) -> str:
        """Plain-text description, handy as the body of an LLM prompt."""
        lines = [f"Nodes: 0..{self.n - 1}. Start and end at node {self.start}.",
                 "Distance between two nodes = Euclidean distance rounded to the nearest integer."]
        lines.append("Coordinates:")
        lines += [f"  {i}: ({x:.4f}, {y:.4f})" for i, (x, y) in enumerate(self.coords)]
        if include_matrix:
            lines.append("Distance matrix (row i, column j):")
            lines += ["  " + " ".join(str(v) for v in row) for row in self.matrix]
        if self.deadlines:
            lines.append("Deadlines (cumulative distance from start at first arrival must be <= D):")
            lines += [f"  node {v}: D = {d}" for v, d in sorted(self.deadlines.items())]
        if self.precedences:
            lines.append("Precedences (a must be visited before b):")
            lines += [f"  {a} before {b}" for a, b in self.precedences]
        lines.append(f"Answer: a tour [0, ..., 0] visiting every node exactly once, "
                     f"or None if no tour satisfies all constraints.")
        return "\n".join(lines)


class Solver:
    """Base class for plugged-in solvers. See README.md.

    solve() returns (tour, metadata):
      tour      list[int] like [0, ..., 0], or None to claim the instance is infeasible
      metadata  dict; with tour=None, an "error" key marks a failure instead of a claim
                ("timeout" -> Timeout, anything else -> Malformed). Optional keys:
                tokens_in, tokens_out, reasoning_tokens, cost, model, settings, raw_text.
    The solver must respect problem.time_limit itself.
    """
    name: str = "Solver"

    def solve(self, problem: Problem, seed: int) -> tuple[list[int] | None, dict]:
        raise NotImplementedError


# ---------------------------------------------------------------- IO

def read_tsp(path: str | Path) -> tuple[str, list[tuple[float, float]]]:
    """Read a TSPLIB EUC_2D file. Returns (name, 0-indexed coords)."""
    name = Path(path).stem
    coords: dict[int, tuple[float, float]] = {}
    in_coords = False
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "EOF":
            break
        if in_coords:
            parts = line.split()
            if len(parts) >= 3 and parts[0].lstrip("-").isdigit():
                coords[int(parts[0])] = (float(parts[1]), float(parts[2]))
                continue
            in_coords = False
        if line.startswith("NODE_COORD_SECTION"):
            in_coords = True
        elif ":" in line:
            key, val = (s.strip() for s in line.split(":", 1))
            if key == "NAME":
                name = val
            elif key == "EDGE_WEIGHT_TYPE" and val != "EUC_2D":
                raise ValueError(f"{path}: only EUC_2D supported, got {val}")
    ids = sorted(coords)
    if ids != list(range(1, len(ids) + 1)):
        raise ValueError(f"{path}: node ids must be 1..n")
    return name, [coords[i] for i in ids]


def write_tsp(path: str | Path, name: str, coords: list[tuple[float, float]], comment: str = "") -> None:
    lines = [f"NAME : {name}"]
    if comment:
        lines.append(f"COMMENT : {comment}")
    lines += ["TYPE : TSP", f"DIMENSION : {len(coords)}", "EDGE_WEIGHT_TYPE : EUC_2D", "NODE_COORD_SECTION"]
    lines += [f"{i + 1} {x:.4f} {y:.4f}" for i, (x, y) in enumerate(coords)]
    lines.append("EOF")
    Path(path).write_text("\n".join(lines) + "\n")


def sidecar_path(tsp_path: str | Path) -> Path:
    return Path(tsp_path).with_suffix(".json")


def load_case(tsp_path: str | Path, time_limit: float | None = None) -> tuple[Problem, dict]:
    """Load a .tsp + sidecar .json. Returns (Problem for the solver, sidecar reference dict)."""
    name, coords = read_tsp(tsp_path)
    side = json.loads(sidecar_path(tsp_path).read_text())
    problem = Problem(
        name=side.get("name", name),
        coords=coords,
        deadlines={int(v): int(d) for v, d in side.get("deadlines", [])},
        precedences=[(int(a), int(b)) for a, b in side.get("precedences", [])],
        category=side.get("category", ""),
        time_limit=time_limit,
    )
    return problem, side


def write_case(directory: str | Path, coords: list[tuple[float, float]], sidecar: dict, comment: str = "") -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tsp = directory / f"{sidecar['name']}.tsp"
    write_tsp(tsp, sidecar["name"], coords, comment)
    sidecar_path(tsp).write_text(json.dumps(sidecar, indent=2))
    return tsp


def iter_cases(testcases_dir: str | Path, categories: list[str] | None = None):
    """Yield .tsp paths under testcases_dir/<category>/, sorted."""
    root = Path(testcases_dir)
    for cat_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if categories and cat_dir.name not in categories:
            continue
        yield from sorted(cat_dir.glob("*.tsp"))


# ---------------------------------------------------------------- validation / grading

def is_well_formed(answer) -> bool:
    return isinstance(answer, (list, tuple)) and all(
        isinstance(v, int) and not isinstance(v, bool) for v in answer)


def check_tour(problem: Problem, tour: list[int]) -> dict:
    """Validate a well-formed tour.

    Returns {valid, violations: [{type, detail}], cost, constraint_satisfaction}.
    cost is None if the tour contains hallucinated ids. constraint_satisfaction is the
    fraction of deadline+precedence constraints satisfied (None if there are none).
    """
    n = problem.n
    violations: list[dict] = []

    bad_ids = sorted({v for v in tour if not 0 <= v < n})
    for v in bad_ids:
        violations.append({"type": V_HALLUCINATED, "detail": f"node {v} does not exist"})
    seq = [v for v in tour if 0 <= v < n]

    if len(tour) < 2 or tour[0] != 0 or tour[-1] != 0:
        violations.append({"type": V_START_END, "detail": "tour must start and end at node 0"})

    counts = [0] * n
    for v in tour[1:-1]:
        if 0 <= v < n:
            counts[v] += 1
    if counts[0]:
        violations.append({"type": V_DUPLICATE, "detail": f"node 0 appears {counts[0]} extra time(s)"})
    for v in range(1, n):
        if counts[v] == 0:
            violations.append({"type": V_MISSING, "detail": f"node {v} not visited"})
        elif counts[v] > 1:
            violations.append({"type": V_DUPLICATE, "detail": f"node {v} visited {counts[v]} times"})

    # First-visit arrival times along the (id-filtered) sequence.
    arrival: dict[int, int] = {}
    position: dict[int, int] = {}
    t = 0
    for i, v in enumerate(seq):
        if i > 0:
            t += problem.dist(seq[i - 1], v)
        if v not in position:
            position[v] = i
            arrival[v] = t

    satisfied = 0
    for v, d in sorted(problem.deadlines.items()):
        if v in arrival and arrival[v] <= d:
            satisfied += 1
        else:
            got = arrival.get(v)
            violations.append({"type": V_DEADLINE,
                               "detail": f"node {v} arrival {got if got is not None else 'never'} > deadline {d}"})
    for a, b in problem.precedences:
        if a in position and b in position and position[a] < position[b]:
            satisfied += 1
        else:
            violations.append({"type": V_PRECEDENCE, "detail": f"{a} must be visited before {b}"})

    total = len(problem.deadlines) + len(problem.precedences)
    return {
        "valid": not violations,
        "violations": violations,
        "cost": None if bad_ids else problem.tour_cost(seq),
        "constraint_satisfaction": satisfied / total if total else None,
    }


def normalize_result(result) -> tuple[object, dict]:
    """Accept `(answer, metadata)` or a bare answer from a solver."""
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[0], result[1]
    return result, {}


def grade(problem: Problem, ref: dict, answer, metadata: dict, elapsed: float | None = None,
          time_limit: float | None = None) -> dict:
    """Turn one solver answer into {label, violations, cost, gap, constraint_satisfaction, error}."""
    out = {"label": None, "violations": [], "cost": None, "gap": None,
           "constraint_satisfaction": None, "error": None, "hallucinated_tour": False}
    feasible = ref.get("feasible", True)
    opt = ref.get("optimal_cost")
    error = metadata.get("error") if answer is None else None
    out["error"] = error

    if time_limit is not None and elapsed is not None and elapsed > time_limit:
        out["label"] = TIMEOUT
        out["error"] = out["error"] or f"elapsed {elapsed:.1f}s > limit {time_limit}s"
        return out
    if error is not None:
        out["label"] = TIMEOUT if str(error).lower() == "timeout" else MALFORMED
        return out
    if answer is None:
        if feasible:
            out["label"] = WRONG_NONE
            out["violations"] = [{"type": V_WRONG_NONE, "detail": "claimed infeasible, but a tour exists"}]
        else:
            out["label"] = CORRECT_NONE
        return out
    if not is_well_formed(answer):
        out["label"] = MALFORMED
        out["error"] = "answer is not a list of ints"
        return out

    check = check_tour(problem, list(answer))
    out["violations"] = check["violations"]
    out["cost"] = check["cost"]
    out["constraint_satisfaction"] = check["constraint_satisfaction"]
    if not feasible:
        out["hallucinated_tour"] = True
        if check["valid"]:
            raise AssertionError(f"{problem.name}: valid tour on an instance marked infeasible")
        out["label"] = INVALID
    elif not check["valid"]:
        out["label"] = INVALID
    elif opt is None:
        out["label"] = VALID_SUBOPTIMAL
    else:
        out["gap"] = (check["cost"] - opt) / opt if opt else 0.0
        out["label"] = OPTIMAL if check["cost"] <= opt else VALID_SUBOPTIMAL
    return out


# ---------------------------------------------------------------- reference solvers

def shortest_paths(matrix: list[list[int]]) -> list[list[int]]:
    """Floyd-Warshall. nint rounding can break the triangle inequality, so sp <= direct edge."""
    n = len(matrix)
    sp = [row[:] for row in matrix]
    for k in range(n):
        spk = sp[k]
        for i in range(n):
            spi = sp[i]
            ik = spi[k]
            for j in range(n):
                if ik + spk[j] < spi[j]:
                    spi[j] = ik + spk[j]
    return sp


def held_karp(problem: Problem) -> tuple[int | None, list[int] | None]:
    """Exact constrained TSP by DP over (visited set, last node) -> min cost.

    Min cost also means earliest arrival, and deadlines are upper bounds, so keeping
    only the cheapest path per state is exact. Returns (None, None) if infeasible.
    Practical up to ~N=13.
    """
    n = problem.n
    if n == 1:
        return 0, [0, 0]
    d = problem.matrix
    pred = [0] * n
    for a, b in problem.precedences:
        if b == 0 or a == b:
            return None, None
        if a != 0:
            pred[b] |= 1 << (a - 1)
    dl = problem.deadlines
    if dl.get(0, 0) < 0:
        return None, None
    full = (1 << (n - 1)) - 1
    dp: list[dict[int, tuple[int, int]]] = [dict() for _ in range(full + 1)]
    for v in range(1, n):
        c = d[0][v]
        if pred[v] == 0 and (v not in dl or c <= dl[v]):
            dp[1 << (v - 1)][v] = (c, 0)
    for mask in range(1, full + 1):
        layer = dp[mask]
        if not layer:
            continue
        for last, (c, _) in layer.items():
            dlast = d[last]
            for v in range(1, n):
                bit = 1 << (v - 1)
                if mask & bit or pred[v] & ~mask:
                    continue
                nc = c + dlast[v]
                if v in dl and nc > dl[v]:
                    continue
                nxt = dp[mask | bit]
                cur = nxt.get(v)
                if cur is None or nc < cur[0]:
                    nxt[v] = (nc, last)
    best = None
    for last, (c, _) in dp[full].items():
        total = c + d[last][0]
        if best is None or total < best[0]:
            best = (total, last)
    if best is None:
        return None, None
    tour = [0]
    mask, last = full, best[1]
    while last != 0:
        tour.append(last)
        prev = dp[mask][last][1]
        mask &= ~(1 << (last - 1))
        last = prev
    tour.append(0)
    tour.reverse()
    return best[0], tour


def brute_force(problem: Problem) -> tuple[int | None, list[int] | None]:
    """Exhaustive search; for cross-checking held_karp on small N."""
    best = (None, None)
    for perm in itertools.permutations(range(1, problem.n)):
        tour = [0, *perm, 0]
        res = check_tour(problem, tour)
        if res["valid"] and (best[0] is None or res["cost"] < best[0]):
            best = (res["cost"], tour)
    return best

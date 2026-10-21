"""Script 1: generate test cases (.tsp + sidecar .json) into per-category folders.

    python generate_testcases.py [--out testcases] [--seed 4263] ...

Every flag overrides the matching constant below. Output is deterministic for a
given configuration. Category folders inside --out are wiped and regenerated.
"""

from __future__ import annotations

import argparse
import itertools
import math
import random
import shutil
from pathlib import Path

import tsp_common as tc

# ---------------------------------------------------------------- generation config
MASTER_SEED = 4263
OUT_DIR = "testcases"
N_MIN, N_MAX = 5, 10            # small instances, all solved exactly by Held-Karp
SEEDS_PER_CELL = 1              # instances per sweep cell
DEADLINE_COUNTS = [1, 2, 4]     # n: deadline constraints per instance
PRECEDENCE_COUNTS = [2, 4, 8]   # m: precedence constraints per instance
SLACKS = [1.0, 1.2, 1.5]        # s: deadline = ceil(witness arrival * s)
INFEASIBLE_FRACTION = 0.2       # infeasible cases as a share of all cases
COORD_MAX = 1000.0              # coords uniform in [0, COORD_MAX), 4 decimals
NATIONAL_DIR = "data/national"
NATIONAL = ["wi29", "dj38", "qa194", "uy734", "zi929", "lu980"]

UNCONSTRAINED_SMALL = "unconstrained_small"
DEADLINE_SMALL = "deadline_constrained_small"
PRECEDENCE_SMALL = "precedence_constrained_small"
ALL_SMALL = "all_constrained_small"
UNCONSTRAINED_LARGE = "unconstrained_large"
INF_UNREACHABLE = "infeasible_unreachable_deadline"
INF_CYCLE = "infeasible_precedence_cycle"
INF_CHAIN = "infeasible_precedence_deadline_chain"
INF_PAIR = "infeasible_deadline_pair_clash"
INFEASIBLE_CLASSES = [INF_UNREACHABLE, INF_CYCLE, INF_CHAIN, INF_PAIR]
CATEGORIES = [UNCONSTRAINED_SMALL, DEADLINE_SMALL, PRECEDENCE_SMALL, ALL_SMALL,
              UNCONSTRAINED_LARGE, *INFEASIBLE_CLASSES]
PREFIX = {UNCONSTRAINED_SMALL: "uc", DEADLINE_SMALL: "dl", PRECEDENCE_SMALL: "pc", ALL_SMALL: "ac",
          INF_UNREACHABLE: "inf_ud", INF_CYCLE: "inf_cy", INF_CHAIN: "inf_ch", INF_PAIR: "inf_pr"}


def case_rng(master: int, category: str, idx: int) -> tuple[int, random.Random]:
    seed = random.Random(f"{master}:{category}:{idx}").getrandbits(32)
    return seed, random.Random(seed)


def random_coords(rng: random.Random, n: int, coord_max: float) -> list[tuple[float, float]]:
    return [(round(rng.uniform(0, coord_max), 4), round(rng.uniform(0, coord_max), 4)) for _ in range(n)]


def min_nodes_for_pairs(m: int) -> int:
    k = 2 if m else 0
    while k * (k - 1) // 2 < m:
        k += 1
    return k


def build_constraints(rng: random.Random, p: tc.Problem, n_dl: int, n_pc: int, s: float) -> list[int]:
    """Witness-order constraint generation (feasible by construction).

    A random subset S of nodes is put in random order; the witness tour visits S in
    that order first, then the remaining nodes. Deadlines take the witness arrival
    time (direct edges, so the witness meets it exactly) scaled by s. Precedence pairs
    are drawn from S and oriented by the witness order. Mutates p, returns the witness.
    """
    others = list(range(1, p.n))
    n_dl = min(n_dl, len(others))
    n_pc = min(n_pc, len(others) * (len(others) - 1) // 2)
    k_min = max(n_dl, min_nodes_for_pairs(n_pc), 1)
    k = rng.randint(k_min, len(others))
    subset = rng.sample(others, k)
    rest = [v for v in others if v not in subset]
    rng.shuffle(rest)
    witness = [0, *subset, *rest, 0]

    arrival, t = {}, 0
    for prev, v in zip(witness, witness[1:-1]):
        t += p.dist(prev, v)
        arrival[v] = t
    p.deadlines = {v: math.ceil(arrival[v] * s) for v in sorted(rng.sample(subset, n_dl))}

    order = {v: i for i, v in enumerate(subset)}
    pairs = rng.sample(list(itertools.combinations(subset, 2)), n_pc)
    p.precedences = [tuple(sorted(pr, key=order.get)) for pr in pairs]
    return witness


def sidecar(name, category, seed, p: tc.Problem, params, feasible, cost, tour, infeasible_class=None,
            witness=None, proof=None) -> dict:
    return {
        "name": name, "category": category, "n": p.n, "seed": seed,
        "deadlines": [[v, d] for v, d in sorted(p.deadlines.items())],
        "precedences": [list(pr) for pr in p.precedences],
        "params": params, "feasible": feasible, "optimal_cost": cost, "optimal_tour": tour,
        "reference_source": "held_karp", "infeasible_class": infeasible_class,
        "infeasibility_proof": proof, "witness_tour": witness,
    }


def make_feasible(cfg, category: str, idx: int, n: int, n_dl: int, n_pc: int, s: float | None):
    seed, rng = case_rng(cfg.seed, category, idx)
    p = tc.Problem("", random_coords(rng, n, cfg.coord_max), category=category)
    witness = build_constraints(rng, p, n_dl, n_pc, s or 1.0) if (n_dl or n_pc) else None
    if witness:
        assert tc.check_tour(p, witness)["valid"], "witness must satisfy its own constraints"
    cost, tour = tc.held_karp(p)
    assert cost is not None
    params = {"n_deadlines": len(p.deadlines), "n_precedences": len(p.precedences),
              "slack": s if p.deadlines else None}
    name = f"{PREFIX[category]}_N{n:02d}_d{params['n_deadlines']}_p{params['n_precedences']}"
    name += f"_s{round(s * 100)}" if p.deadlines else ""
    name += f"_{idx:03d}"
    p.name = name
    return p, sidecar(name, category, seed, p, params, True, cost, tour, witness=witness)


# ---------------------------------------------------------------- infeasible injectors
# Each makes the instance provably infeasible using shortest-path lower bounds; any
# real path between two nodes costs at least sp between them.

def inject_unreachable(rng, p, sp):
    cands = [v for v in range(1, p.n) if sp[0][v] >= 2]
    v = rng.choice(cands)
    d = rng.randint(sp[0][v] // 2, sp[0][v] - 1)
    p.deadlines[v] = d
    return {"nodes": [v], "deadline": d, "lower_bound": sp[0][v],
            "reason": f"deadline {d} on node {v} < shortest distance {sp[0][v]} from start"}


def inject_cycle(rng, p, sp):
    k = rng.choice([2, 3]) if p.n > 3 else 2
    nodes = rng.sample(range(1, p.n), k)
    cycle = [(nodes[i], nodes[(i + 1) % k]) for i in range(k)]
    p.precedences = [pr for pr in p.precedences if pr not in cycle] + cycle
    return {"nodes": nodes, "reason": "precedence cycle " + " -> ".join(map(str, nodes + nodes[:1]))}


def inject_chain(rng, p, sp, witness):
    pos = {v: i for i, v in enumerate(witness[:-1])}
    for _ in range(1000):
        k = rng.choice([2, 3]) if p.n > 3 else 2
        chain = sorted(rng.sample(range(1, p.n), k), key=pos.get)
        bound = sp[0][chain[0]] + sum(sp[a][b] for a, b in zip(chain, chain[1:]))
        last = chain[-1]
        lo = max(sp[0][last], math.ceil(0.85 * bound))
        if lo <= bound - 1:
            break
    else:
        raise RuntimeError("no chain found")
    d = rng.randint(lo, bound - 1)
    new = list(zip(chain, chain[1:]))
    p.precedences = [pr for pr in p.precedences if pr not in new] + new
    p.deadlines[last] = d
    return {"nodes": chain, "deadline": d, "lower_bound": bound,
            "reason": f"chain {' -> '.join(map(str, chain))} needs >= {bound} to reach {last}, deadline {d}"}


def inject_pair(rng, p, sp):
    pairs = list(itertools.combinations(range(1, p.n), 2))
    rng.shuffle(pairs)
    for u, v in pairs:
        bound = min(sp[0][u] + sp[u][v], sp[0][v] + sp[v][u])
        if max(sp[0][u], sp[0][v]) <= bound - 1:
            du = rng.randint(sp[0][u], bound - 1)
            dv = rng.randint(sp[0][v], bound - 1)
            p.deadlines[u], p.deadlines[v] = du, dv
            return {"nodes": [u, v], "deadline": [du, dv], "lower_bound": bound,
                    "reason": f"whichever of {u},{v} is second arrives >= {bound} > deadlines {du},{dv}"}
    raise RuntimeError("no clashing pair found")


def make_infeasible(cfg, category: str, idx: int, n: int):
    seed, rng = case_rng(cfg.seed, category, idx)
    for attempt in range(100):
        p = tc.Problem("", random_coords(rng, n, cfg.coord_max), category=category)
        n_dl, n_pc, s = rng.choice(cfg.deadlines), rng.choice(cfg.precedences), rng.choice(cfg.slacks)
        witness = build_constraints(rng, p, n_dl, n_pc, s)
        sp = tc.shortest_paths(p.matrix)
        try:
            if category == INF_UNREACHABLE:
                proof = inject_unreachable(rng, p, sp)
            elif category == INF_CYCLE:
                proof = inject_cycle(rng, p, sp)
            elif category == INF_CHAIN:
                proof = inject_chain(rng, p, sp, witness)
            else:
                proof = inject_pair(rng, p, sp)
        except (RuntimeError, IndexError, ValueError):
            continue
        break
    else:
        raise RuntimeError(f"could not build {category} #{idx}")
    cost, _ = tc.held_karp(p)
    assert cost is None, f"{category} #{idx} should be infeasible"
    name = f"{PREFIX[category]}_N{n:02d}_{idx:03d}"
    p.name = name
    params = {"n_deadlines": len(p.deadlines), "n_precedences": len(p.precedences), "slack": s,
              "base_deadlines": n_dl, "base_precedences": n_pc}
    return p, sidecar(name, category, seed, p, params, False, None, None,
                      infeasible_class=category, proof=proof)


# ---------------------------------------------------------------- main

def generate(cfg) -> dict[str, int]:
    out = Path(cfg.out)
    out.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        shutil.rmtree(out / cat, ignore_errors=True)
    counts: dict[str, int] = {}

    def emit(p, side):
        tc.write_case(out / side["category"], p.coords, side, comment=f"{side['category']} (constrained TSP benchmark)")
        counts[side["category"]] = counts.get(side["category"], 0) + 1

    ns = range(cfg.n_min, cfg.n_max + 1)
    grids = {
        UNCONSTRAINED_SMALL: [(0, 0, None)],
        DEADLINE_SMALL: [(d, 0, s) for d in cfg.deadlines for s in cfg.slacks],
        PRECEDENCE_SMALL: [(0, m, None) for m in cfg.precedences],
        ALL_SMALL: [(d, m, s) for d in cfg.deadlines for m in cfg.precedences for s in cfg.slacks],
    }
    for cat, grid in grids.items():
        idx = 0
        for n in ns:
            for n_dl, n_pc, s in grid:
                for _ in range(cfg.seeds_per_cell):
                    emit(*make_feasible(cfg, cat, idx, n, n_dl, n_pc, s))
                    idx += 1

    for name in NATIONAL:
        src = Path(NATIONAL_DIR) / f"{name}.tsp"
        dst = out / UNCONSTRAINED_LARGE
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst / src.name)
        shutil.copy(tc.sidecar_path(src), dst / f"{name}.json")
        counts[UNCONSTRAINED_LARGE] = counts.get(UNCONSTRAINED_LARGE, 0) + 1

    feasible_total = sum(counts.values())
    f = cfg.infeasible_fraction
    n_inf = round(feasible_total * f / (1 - f)) if f < 1 else 0
    per_class = math.ceil(n_inf / len(INFEASIBLE_CLASSES)) if n_inf else 0
    for cat in INFEASIBLE_CLASSES:
        for idx in range(per_class):
            n = ns[idx % len(ns)]
            emit(*make_infeasible(cfg, cat, idx, n))
    return counts


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--seed", type=int, default=MASTER_SEED)
    ap.add_argument("--n-min", type=int, default=N_MIN)
    ap.add_argument("--n-max", type=int, default=N_MAX)
    ap.add_argument("--seeds-per-cell", type=int, default=SEEDS_PER_CELL)
    ap.add_argument("--deadlines", type=int, nargs="+", default=DEADLINE_COUNTS)
    ap.add_argument("--precedences", type=int, nargs="+", default=PRECEDENCE_COUNTS)
    ap.add_argument("--slacks", type=float, nargs="+", default=SLACKS)
    ap.add_argument("--infeasible-fraction", type=float, default=INFEASIBLE_FRACTION)
    ap.add_argument("--coord-max", type=float, default=COORD_MAX)
    cfg = ap.parse_args(argv)
    if not 2 <= cfg.n_min <= cfg.n_max <= 13:
        ap.error("need 2 <= n-min <= n-max <= 13 (Held-Karp reference)")
    return cfg


def main(argv=None):
    cfg = parse_args(argv)
    counts = generate(cfg)
    for cat in CATEGORIES:
        print(f"{cat:40s} {counts.get(cat, 0):4d}")
    print(f"{'total':40s} {sum(counts.values()):4d}  -> {cfg.out}/")


if __name__ == "__main__":
    main()

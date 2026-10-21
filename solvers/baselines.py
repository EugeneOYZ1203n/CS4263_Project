"""Sanity-check solvers. They bracket what real solvers should score."""

from __future__ import annotations

import random

import tsp_common as tc


class OracleSolver(tc.Solver):
    """Exact Held-Karp. Optimal on every small case; reports an error on large ones."""
    name = "Oracle"
    max_n = 12

    def solve(self, problem, seed):
        if problem.n > self.max_n:
            return None, {"error": f"unsupported: N={problem.n} > {self.max_n}"}
        _, tour = tc.held_karp(problem)
        return tour, {"model": "held_karp"}


class RandomSolver(tc.Solver):
    """Uniformly random permutation. Ignores constraints; never claims infeasible."""
    name = "Random"

    def solve(self, problem, seed):
        rest = list(range(1, problem.n))
        random.Random(seed).shuffle(rest)
        return [0, *rest, 0], {}


class NearestNeighbourSolver(tc.Solver):
    """Greedy nearest unvisited node whose predecessors are already visited.

    Ignores deadlines. Stuck on a precedence cycle -> claims infeasible.
    """
    name = "NearestNeighbour"

    def solve(self, problem, seed):
        preds: dict[int, set[int]] = {}
        for a, b in problem.precedences:
            preds.setdefault(b, set()).add(a)
        unvisited = set(range(1, problem.n))
        visited = {0}
        tour = [0]
        while unvisited:
            last = tour[-1]
            ready = [v for v in unvisited if preds.get(v, set()) <= visited]
            if not ready:
                return None, {}
            nxt = min(ready, key=lambda v: (problem.dist(last, v), v))
            tour.append(nxt)
            visited.add(nxt)
            unvisited.remove(nxt)
        tour.append(0)
        return tour, {}


class AlwaysNoneSolver(tc.Solver):
    """Always claims infeasible."""
    name = "AlwaysNone"

    def solve(self, problem, seed):
        return None, {}

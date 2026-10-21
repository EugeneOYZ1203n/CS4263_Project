"""Run with:  python -m unittest discover tests   (pytest also works)."""

from __future__ import annotations

import filecmp
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import evaluate  # noqa: E402
import generate_testcases as gen  # noqa: E402
import run_solvers  # noqa: E402
import tsp_common as tc  # noqa: E402
from solvers import NearestNeighbourSolver, OracleSolver  # noqa: E402

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]  # optimal tour cost 40


def small_cfg(out: Path):
    return gen.parse_args(["--out", str(out), "--n-min", "5", "--n-max", "6", "--deadlines", "1", "2",
                           "--precedences", "2", "--slacks", "1.0", "1.5"])


class TestDistanceAndIO(unittest.TestCase):
    def test_euc_2d_rounds_to_nearest(self):
        self.assertEqual(tc.euc_2d((0, 0), (3, 4)), 5)
        self.assertEqual(tc.euc_2d((0, 0), (1, 1)), 1)       # 1.414 -> 1
        self.assertEqual(tc.euc_2d((0, 0), (1.5, 1.5)), 2)   # 2.121 -> 2

    def test_tsp_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            coords = [(1.2345, 6.789), (100.0, 0.5)]
            tc.write_tsp(Path(d) / "x.tsp", "x", coords)
            name, back = tc.read_tsp(Path(d) / "x.tsp")
            self.assertEqual((name, back), ("x", coords))

    def test_national_files_parse(self):
        for name in gen.NATIONAL:
            _, coords = tc.read_tsp(ROOT / gen.NATIONAL_DIR / f"{name}.tsp")
            side = json.loads((ROOT / gen.NATIONAL_DIR / f"{name}.json").read_text())
            self.assertEqual(len(coords), side["n"])
            self.assertIsInstance(side["optimal_cost"], int)


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.p = tc.Problem("sq", SQUARE)

    def types(self, tour, p=None):
        return sorted({v["type"] for v in tc.check_tour(p or self.p, tour)["violations"]})

    def test_valid(self):
        res = tc.check_tour(self.p, [0, 1, 2, 3, 0])
        self.assertTrue(res["valid"])
        self.assertEqual(res["cost"], 40)

    def test_structural_violations(self):
        self.assertEqual(self.types([0, 1, 2, 0]), [tc.V_MISSING])
        self.assertEqual(self.types([0, 1, 1, 2, 3, 0]), [tc.V_DUPLICATE])
        self.assertEqual(self.types([0, 1, 2, 3, 9, 0]), [tc.V_HALLUCINATED])
        self.assertEqual(self.types([1, 2, 3, 0]), [tc.V_MISSING, tc.V_START_END])
        self.assertIsNone(tc.check_tour(self.p, [0, 1, 2, 3, 9, 0])["cost"])

    def test_constraints(self):
        p = tc.Problem("sq", SQUARE, deadlines={3: 10}, precedences=[(2, 1)])
        res = tc.check_tour(p, [0, 1, 2, 3, 0])
        self.assertEqual(sorted(v["type"] for v in res["violations"]), [tc.V_DEADLINE, tc.V_PRECEDENCE])
        self.assertEqual(res["constraint_satisfaction"], 0.0)
        self.assertTrue(tc.check_tour(p, [0, 3, 2, 1, 0])["valid"])

    def test_grade_protocol(self):
        ref = {"feasible": True, "optimal_cost": 40}
        g = lambda ans, meta=None, **kw: tc.grade(self.p, ref, ans, meta or {}, **kw)["label"]
        self.assertEqual(g([0, 1, 2, 3, 0]), tc.OPTIMAL)
        self.assertEqual(g([0, 2, 1, 3, 0]), tc.VALID_SUBOPTIMAL)
        self.assertEqual(g([0, 1, 2, 0]), tc.INVALID)
        self.assertEqual(g(None), tc.WRONG_NONE)
        self.assertEqual(g(None, {"error": "timeout"}), tc.TIMEOUT)
        self.assertEqual(g(None, {"error": "parse failure"}), tc.MALFORMED)
        self.assertEqual(g("0 1 2 3 0"), tc.MALFORMED)
        self.assertEqual(g([0, 1, 2, 3, 0], elapsed=5.0, time_limit=1.0), tc.TIMEOUT)
        inf = {"feasible": False, "optimal_cost": None}
        self.assertEqual(tc.grade(self.p, inf, None, {})["label"], tc.CORRECT_NONE)


class TestReference(unittest.TestCase):
    def test_held_karp_matches_brute_force(self):
        rng = random.Random(7)
        for _ in range(150):
            n = rng.randint(3, 8)
            coords = [(rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(n)]
            dl = {v: rng.randint(20, 300) for v in rng.sample(range(1, n), rng.randint(0, n - 1))}
            pr = [tuple(rng.sample(range(1, n), 2)) for _ in range(rng.randint(0, 3))]
            p = tc.Problem("r", coords, dl, pr)
            hk, bf = tc.held_karp(p), tc.brute_force(p)
            self.assertEqual(hk[0], bf[0])
            if hk[1]:
                self.assertTrue(tc.check_tour(p, hk[1])["valid"])
                self.assertEqual(p.tour_cost(hk[1]), hk[0])

    def test_shortest_paths_never_exceed_edges(self):
        rng = random.Random(1)
        p = tc.Problem("r", [(rng.uniform(0, 1000), rng.uniform(0, 1000)) for _ in range(12)])
        sp = tc.shortest_paths(p.matrix)
        for i in range(p.n):
            for j in range(p.n):
                self.assertLessEqual(sp[i][j], p.matrix[i][j])


class TestGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "a"
        gen.generate(small_cfg(cls.out))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_categories_present(self):
        for cat in gen.CATEGORIES:
            self.assertTrue(list((self.out / cat).glob("*.tsp")), cat)

    def test_deterministic(self):
        again = Path(self.tmp.name) / "b"
        gen.generate(small_cfg(again))
        for cat in gen.CATEGORIES:
            files = sorted(p.name for p in (self.out / cat).iterdir())
            self.assertEqual(files, sorted(p.name for p in (again / cat).iterdir()))
            _, mismatch, errors = filecmp.cmpfiles(self.out / cat, again / cat, files, shallow=False)
            self.assertEqual((mismatch, errors), ([], []), cat)

    def test_references_consistent(self):
        for tsp in tc.iter_cases(self.out):
            p, ref = tc.load_case(tsp)
            if ref["category"] == gen.UNCONSTRAINED_LARGE:
                continue
            cost, tour = tc.held_karp(p)
            if ref["feasible"]:
                self.assertEqual(cost, ref["optimal_cost"], tsp.name)
                self.assertTrue(tc.check_tour(p, ref["optimal_tour"])["valid"])
                if ref["witness_tour"]:
                    self.assertTrue(tc.check_tour(p, ref["witness_tour"])["valid"], tsp.name)
            else:
                self.assertIsNone(cost, tsp.name)
                self.assertIn(ref["infeasible_class"], gen.INFEASIBLE_CLASSES)

    def test_infeasibility_proofs_hold(self):
        for tsp in tc.iter_cases(self.out, gen.INFEASIBLE_CLASSES):
            p, ref = tc.load_case(tsp)
            sp = tc.shortest_paths(p.matrix)
            proof = ref["infeasibility_proof"]
            nodes = proof["nodes"]
            if ref["category"] == gen.INF_UNREACHABLE:
                self.assertLess(p.deadlines[nodes[0]], sp[0][nodes[0]])
            elif ref["category"] == gen.INF_CYCLE:
                cyc = list(zip(nodes, nodes[1:] + nodes[:1]))
                self.assertTrue(all(tuple(e) in set(p.precedences) for e in cyc))
            elif ref["category"] == gen.INF_CHAIN:
                last = nodes[-1]
                self.assertLess(p.deadlines[last], proof["lower_bound"])
                self.assertGreaterEqual(p.deadlines[last], sp[0][last])
            else:
                u, v = nodes
                self.assertGreaterEqual(p.deadlines[u], sp[0][u])
                self.assertGreaterEqual(p.deadlines[v], sp[0][v])
                self.assertLess(max(p.deadlines[u], p.deadlines[v]), proof["lower_bound"])


class CrashingSolver(tc.Solver):
    name = "Crash"

    def solve(self, problem, seed):
        raise RuntimeError("boom")


class TestPipeline(unittest.TestCase):
    def test_run_and_evaluate(self):
        with tempfile.TemporaryDirectory() as d:
            cases_dir = Path(d) / "cases"
            gen.generate(small_cfg(cases_dir))
            cases = [c for c in tc.iter_cases(cases_dir) if "unconstrained_large" not in str(c)]
            dumps = {}
            for solver in (OracleSolver(), NearestNeighbourSolver(), CrashingSolver()):
                out = Path(d) / "outputs" / solver.name
                run_solvers.run_solver(solver, cases, out, k=2, base_seed=0, time_limit=60,
                                       testcases_dir=str(cases_dir), verbose=False)
                dumps[solver.name] = evaluate.evaluate_folder(out)
                self.assertTrue((out / "report.html").exists())
                self.assertEqual(len(list((out / "testcases").glob("*/*.json"))), len(cases))
            oracle = dumps["Oracle"]["overall"]
            self.assertEqual(oracle["optimal_rate"], 1.0)
            self.assertEqual(oracle["safeguard"]["f1"], 1.0)
            self.assertEqual(oracle["reproducibility"]["outcome_agreement"], 1.0)
            crash = dumps["Crash"]["overall"]
            self.assertEqual(crash["outcomes"][tc.MALFORMED], crash["n_runs"])
            self.assertEqual(crash["safeguard"]["f1"], 0.0)
            html = evaluate.render_compare(list(dumps.values()))
            self.assertIn("Solver comparison", html)


if __name__ == "__main__":
    unittest.main()

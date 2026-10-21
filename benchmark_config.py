"""Configuration read by run_solvers.py.

Add your solver class (a tsp_common.Solver subclass) to SOLVERS. Classes are
instantiated with no arguments; put an already-constructed instance in the list
if your solver needs constructor arguments (e.g. MyLLMSolver(model="...")).
"""

from solvers import AlwaysNoneSolver, NearestNeighbourSolver, OracleSolver, RandomSolver

SOLVERS = [
    OracleSolver,
    NearestNeighbourSolver,
    RandomSolver,
    AlwaysNoneSolver,
]

K = 3                       # repeats per (solver, test case); repeat j gets seed BASE_SEED + j
BASE_SEED = 0
TIME_LIMIT = 300            # seconds per call; solvers enforce it, the engine labels overruns Timeout
TESTCASES_DIR = "testcases"
OUTPUT_DIR = "outputs"
CATEGORIES = None           # None = all category folders, or e.g. ["unconstrained_small"]

"""Run your solution on this project's practice cases.

Each run loads a case from input/, calls your
solve(data), and prints what came back next to the saved expected output.

Usage, from this folder:

    python run_local.py                  # every case in input/
    python run_local.py case_01.json     # only the named case(s)

You may edit or change this file however you like
"""

import json
import sys
import time
import traceback
from pathlib import Path
from pprint import pprint

import solution


def run_case(name):
    data = json.loads((Path("input") / name).read_text(encoding="utf-8"))
    expected_path = Path("output") / name
    expected = (
        json.loads(expected_path.read_text(encoding="utf-8"))
        if expected_path.is_file()
        else None
    )

    start = time.perf_counter()
    observed = solution.solve(data)
    elapsed = time.perf_counter() - start

    print(f"== {name}  ({elapsed:.3f}s)")
    print("-- your solution returned:")
    pprint(observed)
    if expected is None:
        print(f"-- no expected output saved (output/{name})")
    else:
        print(f"-- expected output (output/{name}):")
        pprint(expected)
    # To draw this case and your solution's own run with the project's visualiser, uncomment:
    # from draw_grid import draw_grid
    # print(draw_grid(
    #     example_input=data,
    #     expected_output=expected,
    #     candidate_output=observed,
    #     file_name=name,
    # ))
    print()


def main():
    names = sys.argv[1:] or sorted(
        path.name for path in Path("input").glob("*.json")
    )
    if not names:
        print("No cases in input/ - this project shipped without practice cases.")
        return
    for name in names:
        if not (Path("input") / name).is_file():
            print(f"== {name}  is not in input/, skipping")
            continue
        try:
            run_case(name)
        except Exception:
            print(f"== {name}  raised - the traceback is your debugging signal:")
            traceback.print_exc()
            print()


if __name__ == "__main__":
    main()

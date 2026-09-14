import math


# prior to backtracking I want to do AC3 on "/" and "-" sections 
# Backtrack 
# - if assignment complete, return 
# - Select a variable (Minimum Remaining Values, then degree, then random) 
# - Select a value (Least constraining value 
#                   -> Calculated by checking how many 
#                      col/row constraints it enforces + 
#                      if "+" or "*" then smallest val) 
#   - Check if this value is consistent, return if not 
#   - Create copy of domain and assign domain of current variable to just val 
#   - Forward tracking for constraints 
#     - With propagation using AC3 
#       - Initialise queue to be all in same row and col and section 
#       - Pop revise 
#         - everything in same row and col, remove newly assigned val from domain 
#         - everything in section 
#           - If "*" and "+", for each variable, 
#             - Set rest to min val, then remove all values in domain that exceed target 
#             - Set rest to max val, then remove all values in domain that below target 
#             - Can check for modulo also for *
#             - Not accurate, but should be faster than iterating through all
#           - If "-" and "/", just check with basic binary arc consistency since max 2 variables 
#         - After each check, check for any empty domains and if empty, terminate 
#         - if fail, shift to next assignment, else add to queue 
#       - Do until queue is empty 
#       - Detect empty domains 
#     - Backtrack again 
#     - If you get a full assignment, return it

#============================================================

def solve(data: dict):
    problem = build_csp_representation(data)
    assignment = search(problem)

    if assignment is None:
        return None

    return assignment_to_grid(assignment, data["n"])


def build_csp_representation(data: dict) -> dict:
    n = data["n"]

    variables = [(row, col) for row in range(n) for col in range(n)]

    rows = [[(row, col) for col in range(n)] for row in range(n)]
    columns = [[(row, col) for row in range(n)] for col in range(n)]

    sections = []
    cell_to_section = {}

    for cells, symbol, target in data["sections"]:
        section = {
            "cells": [(row, col) for row, col in cells],
            "symbol": symbol,
            "target": target,
        }

        section_id = len(sections)
        sections.append(section)

        for cell in section["cells"]:
            cell_to_section[cell] = section_id

    return {
        "variables": variables,
        "domain_values": lambda variable: list(range(1, n + 1)),
        "constraints": get_constraints(rows, columns, sections),
        "rows": rows,
        "columns": columns,
        "sections": sections,
        "cell_to_section": cell_to_section,
        "neighbors": build_neighbors(rows, columns, sections),
    }


#============================================================

def get_constraints(rows, columns, sections):
    constraints = []

    for cells in rows + columns:
        constraints.append({
            "scope": tuple(cells),
            "rel": lambda *values: len(set(values)) == len(values),
        })

    for section in sections:
        cells = tuple(section["cells"])
        symbol = section["symbol"]
        target = section["target"]

        if symbol == "+":
            rel = lambda *values, target=target: sum(values) == target

        elif symbol == "*":
            rel = lambda *values, target=target: math.prod(values) == target

        elif symbol == "-":
            rel = lambda *values, target=target: abs(values[0] - values[1]) == target

        elif symbol == "/":
            rel = lambda *values, target=target: max(values) % min(values) == 0 and max(values) // min(values) == target

        constraints.append({
            "scope": cells,
            "rel": rel,
        })

    return constraints


#============================================================

def build_neighbors(rows, columns, sections):
    neighbors = {
        cell: set()
        for group in rows + columns + [section["cells"] for section in sections]
        for cell in group
    }

    for group in rows + columns + [section["cells"] for section in sections]:
        for variable in group:
            neighbors[variable].update(group)

    for variable in neighbors:
        neighbors[variable].discard(variable)

    return neighbors


def create_domains(problem):
    return {
        variable: set(problem["domain_values"](variable))
        for variable in problem["variables"]
    }


def assignment_to_grid(assignment, n):
    grid = [[0] * n for _ in range(n)]

    for (row, col), value in assignment.items():
        grid[row][col] = value

    return grid


#============================================================

def search(problem):
    domains = create_domains(problem)

    if not arc_consistency(domains, problem):
        return None

    return backtrack(domains, problem)


def backtrack(domains, problem):
    if all_domains_singleton(domains):
        if all_constraints_satisfied(domains, problem):
            return extract_assignment(domains)

        return None

    variable = select_variable(domains, problem)
    values = order_values(variable, domains, problem)

    for value in values:
        child_domains = copy_domains(domains)
        child_domains[variable] = {value}

        if not arc_consistency(child_domains, problem, {variable}):
            continue

        result = backtrack(child_domains, problem)

        if result is not None:
            return result

    return None


def all_domains_singleton(domains):
    return all(len(domain) == 1 for domain in domains.values())


def extract_assignment(domains):
    return {
        variable: next(iter(domain))
        for variable, domain in domains.items()
    }


def copy_domains(domains):
    return {
        variable: set(values)
        for variable, values in domains.items()
    }


#============================================================

def select_variable(domains, problem):
    variables = [
        variable
        for variable, domain in domains.items()
        if len(domain) > 1
    ]

    return min(
        variables,
        key=lambda variable: (
            len(domains[variable]),
            -get_unassigned_degree(variable, domains, problem),
        ),
    )


def get_unassigned_degree(variable, domains, problem):
    return sum(
        len(domains[neighbor]) > 1
        for neighbor in problem["neighbors"][variable]
    )


#============================================================

def order_values(variable, domains, problem):
    values = list(domains[variable])

    scored_values = [
        (
            count_value_removals(variable, value, domains, problem),
            value,
        )
        for value in values
    ]

    scored_values.sort()

    return [value for score, value in scored_values]


def count_value_removals(variable, value, domains, problem):
    return sum(
        value in domains[neighbor]
        for neighbor in problem["neighbors"][variable]
    )


#============================================================

def arc_consistency(domains, problem, initial_variables=None):
    queue = list(domains.keys()) if initial_variables is None else list(initial_variables)

    while queue:
        variable = queue.pop()

        if len(domains[variable]) == 0:
            return False

        changed_variables = propagate_variable(variable, domains, problem)

        if changed_variables is None:
            return False

        for changed_variable in changed_variables:
            if len(domains[changed_variable]) == 0:
                return False

            if changed_variable not in queue:
                queue.append(changed_variable)

    return True


def propagate_variable(variable, domains, problem):
    value = get_singleton_value(domains[variable])
    changed = set()

    if value is not None:
        changed.update(
            remove_row_column_values(variable, value, domains, problem)
        )

        for changed_variable in changed:
            if len(domains[changed_variable]) == 0:
                return None

    section = problem["sections"][problem["cell_to_section"][variable]]

    result = propagate_section(section, domains)

    if result is None:
        return None

    changed.update(result)

    return changed


def get_singleton_value(domain):
    return next(iter(domain)) if len(domain) == 1 else None


#============================================================

def remove_row_column_values(variable, value, domains, problem):
    row, col = variable
    changed = set()

    for cell in problem["rows"][row] + problem["columns"][col]:
        if cell != variable and value in domains[cell]:
            domains[cell].remove(value)
            changed.add(cell)

    return changed


#============================================================

def propagate_section(section, domains):
    symbol = section["symbol"]

    if symbol == "+":
        return propagate_addition_section(section, domains)

    if symbol == "*":
        return propagate_multiplication_section(section, domains)

    if symbol == "-":
        return propagate_subtraction_section(section, domains)

    if symbol == "/":
        return propagate_division_section(section, domains)

    return set()


def propagate_addition_section(section, domains):
    cells = section["cells"]
    target = section["target"]
    changed = set()

    minimums = [min(domains[cell]) for cell in cells]
    maximums = [max(domains[cell]) for cell in cells]

    prefix_min = [0]
    prefix_max = [0]

    for minimum, maximum in zip(minimums, maximums):
        prefix_min.append(prefix_min[-1] + minimum)
        prefix_max.append(prefix_max[-1] + maximum)

    suffix_min = [0] * (len(cells) + 1)
    suffix_max = [0] * (len(cells) + 1)

    for i in range(len(cells) - 1, -1, -1):
        suffix_min[i] = suffix_min[i + 1] + minimums[i]
        suffix_max[i] = suffix_max[i + 1] + maximums[i]

    for i, cell in enumerate(cells):
        old_domain = set(domains[cell])

        minimum_other = prefix_min[i] + suffix_min[i + 1]
        maximum_other = prefix_max[i] + suffix_max[i + 1]

        domains[cell] = {
            value
            for value in domains[cell]
            if minimum_other <= target - value <= maximum_other
        }

        if not domains[cell]:
            return None

        if domains[cell] != old_domain:
            changed.add(cell)

    return changed


def propagate_multiplication_section(section, domains):
    cells = section["cells"]
    target = section["target"]
    changed = set()

    minimums = [min(domains[cell]) for cell in cells]
    maximums = [max(domains[cell]) for cell in cells]

    prefix_min = [1]
    prefix_max = [1]

    for minimum, maximum in zip(minimums, maximums):
        prefix_min.append(prefix_min[-1] * minimum)
        prefix_max.append(prefix_max[-1] * maximum)

    suffix_min = [1] * (len(cells) + 1)
    suffix_max = [1] * (len(cells) + 1)

    for i in range(len(cells) - 1, -1, -1):
        suffix_min[i] = suffix_min[i + 1] * minimums[i]
        suffix_max[i] = suffix_max[i + 1] * maximums[i]

    for i, cell in enumerate(cells):
        old_domain = set(domains[cell])

        minimum_other = prefix_min[i] * suffix_min[i + 1]
        maximum_other = prefix_max[i] * suffix_max[i + 1]

        domains[cell] = {
            value
            for value in domains[cell]
            if target % value == 0
            and minimum_other <= target // value <= maximum_other
        }

        if not domains[cell]:
            return None

        if domains[cell] != old_domain:
            changed.add(cell)

    return changed


def propagate_subtraction_section(section, domains):
    first, second = section["cells"]
    target = section["target"]

    if not domains[first] or not domains[second]:
        return None

    new_first = {
        value
        for value in domains[first]
        if any(abs(value - other) == target for other in domains[second])
    }

    new_second = {
        value
        for value in domains[second]
        if any(abs(value - other) == target for other in domains[first])
    }

    if not new_first or not new_second:
        return None

    changed = set()

    if new_first != domains[first]:
        domains[first] = new_first
        changed.add(first)

    if new_second != domains[second]:
        domains[second] = new_second
        changed.add(second)

    return changed


def propagate_division_section(section, domains):
    first, second = section["cells"]
    target = section["target"]

    if not domains[first] or not domains[second]:
        return None

    new_first = {
        value
        for value in domains[first]
        if any(valid_division(value, other, target) for other in domains[second])
    }

    new_second = {
        value
        for value in domains[second]
        if any(valid_division(other, value, target) for other in domains[first])
    }

    if not new_first or not new_second:
        return None

    changed = set()

    if new_first != domains[first]:
        domains[first] = new_first
        changed.add(first)

    if new_second != domains[second]:
        domains[second] = new_second
        changed.add(second)

    return changed


def valid_division(first, second, target):
    larger = max(first, second)
    smaller = min(first, second)

    return larger % smaller == 0 and larger // smaller == target


#============================================================

def all_constraints_satisfied(domains, problem):
    assignment = extract_assignment(domains)

    for constraint in problem["constraints"]:
        values = [
            assignment[variable]
            for variable in constraint["scope"]
        ]

        if not constraint["rel"](*values):
            return False

    return True
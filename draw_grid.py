def draw_grid(example_input, expected_output=None, candidate_output=None,
              file_name=''):
    """Draw the Multi Magic Square cage grid, optionally overlaying a solution.

    Parameters
    ----------
    example_input : dict
        Puzzle definition with keys ``n`` (int) and ``sections``
        (list of ``[cells, op, target]`` triples).
    expected_output : list[list[int]] | None
        Certified expected solution, or ``None`` when the puzzle has no
        solution.  Used as the digit source only when ``candidate_output`` is
        also ``None``.
    candidate_output : list[list[int]] | None
        Solution returned by the candidate under review (shown in preference
        to ``expected_output``), or ``None`` when not inspecting a run.
    file_name : str
        Optional case filename shown in the title bar.

    Returns
    -------
    str
        Multi-line terminal-friendly string — no ANSI codes, pure text.
    """

    # ------------------------------------------------------------------ tables
    # These constants are defined inside the function so the visualiser is fully
    # self-contained: the review framework stores only this top-level function,
    # so any module-level constant would be lost (which is exactly why the
    # earlier version raised ``NameError`` on ``_OP``/``_JUNCT``/``_H``/``_V``).

    # Operation glyph shown after a cage's target (e.g. ``18x`` for 1*2*9=18).
    _OP = {"+": "+", "-": "-", "*": "x", "/": "\u00f7"}

    # Heavy box-drawing line segments used for cage borders.
    _H = "\u2501"   # ━ heavy horizontal
    _V = "\u2503"   # ┃ heavy vertical

    # Junction glyph keyed by a 4-bit mask of the heavy segments meeting at a
    # lattice point: up=1, down=2, left=4, right=8.  A proper grid partition
    # never yields single-direction dead-ends at interior points; those entries
    # are harmless fallbacks.
    _JUNCT = {
        0: " ",
        1: "\u2503",   # up             ┃
        2: "\u2503",   # down           ┃
        3: "\u2503",   # up+down        ┃
        4: "\u2501",   # left           ━
        5: "\u251b",   # up+left        ┛
        6: "\u2513",   # down+left      ┓
        7: "\u252b",   # up+down+left   ┫
        8: "\u2501",   # right          ━
        9: "\u2517",   # up+right       ┗
        10: "\u250f",  # down+right     ┏
        11: "\u2523",  # up+down+right  ┣
        12: "\u2501",  # left+right     ━
        13: "\u253b",  # up+left+right  ┻
        14: "\u2533",  # down+left+right┳
        15: "\u254b",  # all four       ╋
    }

    # ------------------------------------------------------------------ parse
    if not isinstance(example_input, dict):
        return "[draw_grid] example_input is not a JSON object"
    size = example_input.get("n")
    raw_sections = example_input.get("sections")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        return "[draw_grid] n is missing or not a positive integer"
    if not isinstance(raw_sections, list):
        return "[draw_grid] sections is missing or not a list"

    cages = []
    cell_to_cage = {}  # (r, c) -> cage index
    for idx, sec in enumerate(raw_sections):
        if not (isinstance(sec, list) and len(sec) == 3):
            continue
        raw_cells, op, target = sec
        cells = []
        for cell in (raw_cells or []):
            if isinstance(cell, (list, tuple)) and len(cell) == 2:
                cells.append((int(cell[0]), int(cell[1])))
        anchor = min(cells) if cells else (0, 0)
        cages.append({"cells": cells, "op": op, "target": target,
                      "anchor": anchor, "index": idx})
        for cell in cells:
            if cell not in cell_to_cage:
                cell_to_cage[cell] = idx

    # ------------------------------------------------------ choose digit source
    # candidate_output takes priority; fall back to expected_output.
    if isinstance(candidate_output, list):
        solution = candidate_output
        source_tag = "candidate"
    elif isinstance(expected_output, list):
        solution = expected_output
        source_tag = "expected"
    else:
        solution = None
        source_tag = None

    def digit_at(r, c):
        if solution is None:
            return ""
        try:
            return str(solution[r][c])
        except (IndexError, TypeError):
            return "?"

    # ------------------------------------------------ cage label at anchor cell
    label_map = {}
    for cage in cages:
        op_char = _OP.get(cage["op"], str(cage["op"]))
        label_map[cage["anchor"]] = f"{cage['target']}{op_char}"

    # ---------------------------------------------------- compute cell width
    width = 1
    for lbl in label_map.values():
        width = max(width, len(lbl))
    for r in range(size):
        for c in range(size):
            width = max(width, len(digit_at(r, c)))
    width = max(width + 2, 5)   # padding + minimum

    # ---------------------------------------------------- border helpers
    def same_cage(a, b):
        return cell_to_cage.get(a) == cell_to_cage.get(b)

    def h_border(i, j):
        """Heavy horizontal border above row i at column j?"""
        if i == 0 or i == size:
            return True
        return not same_cage((i - 1, j), (i, j))

    def v_border(i, j):
        """Heavy vertical border left of column j at row i?"""
        if j == 0 or j == size:
            return True
        return not same_cage((i, j - 1), (i, j))

    def junction(i, j):
        mask = 0
        if i > 0     and v_border(i - 1, j): mask |= 1   # up
        if i < size  and v_border(i,     j): mask |= 2   # down
        if j > 0     and h_border(i, j - 1): mask |= 4   # left
        if j < size  and h_border(i, j    ): mask |= 8   # right
        return _JUNCT[mask]

    # ------------------------------------------------------------ build output
    lines = []

    # title
    title = "Multi Magic Square"
    if file_name:
        title += f"  [{file_name}]"
    lines.append(title)
    lines.append(f"grid {size}\u00d7{size}   cages {len(cages)}"
                 + (f"   showing {source_tag} solution" if source_tag else ""))

    # board
    for i in range(size + 1):
        # horizontal border / junction row
        row = junction(i, 0)
        for j in range(size):
            row += (_H if h_border(i, j) else " ") * width
            row += junction(i, j + 1)
        lines.append(row)

        if i < size:
            # sub-row 0: cage label at the anchor cell, blank elsewhere
            label_row = ""
            for j in range(size):
                label_row += _V if v_border(i, j) else " "
                lbl = label_map.get((i, j), "")
                label_row += (" " + lbl).ljust(width)[:width]
            label_row += _V if v_border(i, size) else " "
            lines.append(label_row)

            # sub-row 1: solution digit centred in cell
            digit_row = ""
            for j in range(size):
                digit_row += _V if v_border(i, j) else " "
                digit_row += digit_at(i, j).center(width)[:width]
            digit_row += _V if v_border(i, size) else " "
            lines.append(digit_row)

    # footer note when a run returned null or no solution is saved
    if candidate_output is not None and not isinstance(candidate_output, list):
        lines.append("(candidate output: null \u2014 solution reported as impossible)")
    elif expected_output is not None and not isinstance(expected_output, list):
        lines.append("(expected output: null \u2014 puzzle has no solution)")

    return "\n".join(lines)

"""Script 4: browse a solver's output folder in a Tkinter window.

    python view_generated.py outputs/<YYYYmmdd_HHMMSS>_<SolverName>

Left: every test case, grouped by category. Right: the solver's tour drawn over
the instance, a run selector for the k repeats, a toggle that overlays the
reference (optimal) tour, and the run's grade, cost, gap and violations.
"""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter import font as tkfont

import tsp_common as tc

ROOT = Path(__file__).resolve().parent

LABEL_COLOR = {tc.OPTIMAL: "#008300", tc.VALID_SUBOPTIMAL: "#c23d78", tc.CORRECT_NONE: "#a87000",
               tc.WRONG_NONE: "#2a78d6", tc.INVALID: "#d03a39", tc.TIMEOUT: "#6250d6", tc.MALFORMED: "#c4511f"}
SHORT = {tc.OPTIMAL: "Opt", tc.VALID_SUBOPTIMAL: "Sub", tc.CORRECT_NONE: "None✓", tc.WRONG_NONE: "None✗",
         tc.INVALID: "Inv", tc.TIMEOUT: "T/O", tc.MALFORMED: "Mal"}
RANK = [tc.OPTIMAL, tc.CORRECT_NONE, tc.VALID_SUBOPTIMAL, tc.INVALID, tc.WRONG_NONE, tc.TIMEOUT, tc.MALFORMED]

BG = "#fcfcfb"
SOLVER_TOUR = "#2a78d6"
OPT_TOUR = "#008300"
NODE = "#52514e"
START = "#d03a39"
DEADLINE = "#eb6834"
PREC = "#9a9993"


def load_folder(folder: Path) -> tuple[dict, dict[str, list[dict]]]:
    config = json.loads((folder / "run_config.json").read_text())
    by_cat: dict[str, list[dict]] = {}
    for p in sorted((folder / "testcases").glob("*/*.json")):
        case = json.loads(p.read_text())
        by_cat.setdefault(case["category"], []).append(case)
    return config, by_cat


def resolve_tsp(case: dict, config: dict) -> Path | None:
    candidates = [Path(case["testcase"]), ROOT / case["testcase"],
                  ROOT / config.get("testcases_dir", "testcases") / case["category"] / f"{case['name']}.tsp"]
    return next((p for p in candidates if p.exists()), None)


class Viewer(tk.Tk):
    def __init__(self, folder: Path):
        super().__init__()
        self.folder = folder
        self.config_data, self.by_cat = load_folder(folder)
        self.title(f"TSP benchmark viewer — {self.config_data.get('solver')} — {folder.name}")
        self.ui = self.winfo_fpixels("1i") / 96  # scale pixel sizes on high-DPI displays
        self.geometry(f"{int(1360 * self.ui)}x{int(860 * self.ui)}")
        self.minsize(int(900 * self.ui), int(600 * self.ui))
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=int(tkfont.nametofont("TkDefaultFont").metrics("linespace") * 1.35))

        self.case: dict | None = None
        self.problem: tc.Problem | None = None
        self.ref: dict = {}
        self.show_opt = tk.BooleanVar(value=False)
        self.show_prec = tk.BooleanVar(value=True)
        self.show_labels = tk.BooleanVar(value=True)
        self.run_var = tk.StringVar()
        self.node_xy: list[tuple[float, float]] = []

        self._build()
        self._fill_tree()

    # ------------------------------------------------------------ layout
    def _build(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        side = ttk.Frame(pane)
        self.tree = ttk.Treeview(side, columns=("result",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Test case")
        self.tree.heading("result", text="Runs")
        self.tree.column("#0", width=int(270 * self.ui))
        self.tree.column("result", width=int(120 * self.ui), anchor=tk.W)
        for lab, col in LABEL_COLOR.items():
            self.tree.tag_configure(lab, foreground=col)
        sb = ttk.Scrollbar(side, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        pane.add(side, weight=0)

        main = ttk.Frame(pane)
        bar = ttk.Frame(main, padding=(8, 6))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Run:").pack(side=tk.LEFT)
        self.run_box = ttk.Combobox(bar, textvariable=self.run_var, state="readonly", width=28)
        self.run_box.pack(side=tk.LEFT, padx=(4, 16))
        self.run_box.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        self.opt_check = ttk.Checkbutton(bar, text="Show optimal tour", variable=self.show_opt, command=self._redraw)
        self.opt_check.pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(bar, text="Precedence arcs", variable=self.show_prec, command=self._redraw).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(bar, text="Node labels", variable=self.show_labels, command=self._redraw).pack(side=tk.LEFT, padx=4)
        self.opt_note = ttk.Label(bar, text="", foreground="#7a7974")
        self.opt_note.pack(side=tk.LEFT, padx=8)

        legend = ttk.Frame(main, padding=(8, 0))
        legend.pack(fill=tk.X)
        for text, col in [("solver tour", SOLVER_TOUR), ("optimal tour", OPT_TOUR), ("start (node 0)", START),
                          ("deadline node", DEADLINE), ("precedence a→b", PREC)]:
            sw = tk.Canvas(legend, width=12, height=12, highlightthickness=0)
            sw.create_rectangle(1, 1, 11, 11, fill=col, outline=col)
            sw.pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(legend, text=text).pack(side=tk.LEFT, padx=(0, 14))

        vpane = ttk.PanedWindow(main, orient=tk.VERTICAL)
        vpane.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(vpane, background=BG, highlightthickness=0)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        vpane.add(self.canvas, weight=3)
        info_frame = ttk.Frame(vpane)
        self.info = tk.Text(info_frame, height=11, wrap=tk.WORD, font=("Consolas", 10), relief=tk.FLAT,
                            padx=8, pady=6)
        isb = ttk.Scrollbar(info_frame, orient=tk.VERTICAL, command=self.info.yview)
        self.info.configure(yscrollcommand=isb.set, state=tk.DISABLED)
        self.info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        isb.pack(side=tk.RIGHT, fill=tk.Y)
        vpane.add(info_frame, weight=1)
        self.status = ttk.Label(main, text="Select a test case.", padding=(8, 2))
        self.status.pack(fill=tk.X)
        pane.add(main, weight=1)

    def _fill_tree(self):
        for cat in sorted(self.by_cat):
            cases = self.by_cat[cat]
            runs = [r for c in cases for r in c["runs"]]
            good = sum(r["label"] in (tc.OPTIMAL, tc.CORRECT_NONE) for r in runs)
            parent = self.tree.insert("", tk.END, iid=f"cat:{cat}", text=f"{cat} ({len(cases)})",
                                      values=(f"{good}/{len(runs)} correct",), open=False)
            for i, c in enumerate(cases):
                labels = [r["label"] for r in c["runs"]]
                best = min(labels, key=RANK.index) if labels else ""
                self.tree.insert(parent, tk.END, iid=f"case:{cat}:{i}", text=c["name"],
                                 values=(" ".join(SHORT.get(l, l) for l in labels),), tags=(best,))

    # ------------------------------------------------------------ events
    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel or not sel[0].startswith("case:"):
            return
        _, cat, idx = sel[0].split(":")
        self.case = self.by_cat[cat][int(idx)]
        tsp = resolve_tsp(self.case, self.config_data)
        if tsp is None:
            self.problem, self.ref = None, {}
            self.status.configure(text=f"Test case file not found: {self.case['testcase']}")
        else:
            self.problem, self.ref = tc.load_case(tsp)
            self.status.configure(text=str(tsp))
        has_opt = bool(self.ref.get("optimal_tour"))
        self.opt_check.configure(state=tk.NORMAL if has_opt else tk.DISABLED)
        self.opt_note.configure(text="" if has_opt else
                                ("(infeasible: no tour exists)" if not self.ref.get("feasible", True)
                                 else "(no reference tour stored; cost only)"))
        runs = self.case["runs"]
        self.run_box["values"] = [f"Run {r.get('repeat', i) + 1}: {r['label']} (seed {r['seed']})"
                                  for i, r in enumerate(runs)]
        if runs:
            self.run_box.current(0)
        self._refresh()

    def _refresh(self):
        self._redraw()
        self._write_info()

    def _run(self) -> dict | None:
        if not self.case or not self.case["runs"]:
            return None
        i = self.run_box.current()
        return self.case["runs"][max(i, 0)]

    def _on_motion(self, event):
        if not self.problem or not self.node_xy:
            return
        best, bd = None, 12 ** 2
        for v, (x, y) in enumerate(self.node_xy):
            d = (x - event.x) ** 2 + (y - event.y) ** 2
            if d < bd:
                best, bd = v, d
        if best is None:
            return
        x, y = self.problem.coords[best]
        msg = f"node {best}  ({x:.4f}, {y:.4f})"
        if best in self.problem.deadlines:
            msg += f"  deadline {self.problem.deadlines[best]}"
        arr = self._arrivals().get(best)
        if arr is not None:
            msg += f"  solver arrival {arr}"
        self.status.configure(text=msg)

    # ------------------------------------------------------------ drawing
    def _arrivals(self) -> dict[int, int]:
        run = self._run()
        p = self.problem
        if not run or not p or not run.get("answer"):
            return {}
        seq = [v for v in run["answer"] if 0 <= v < p.n]
        out, t = {}, 0
        for i, v in enumerate(seq):
            if i:
                t += p.dist(seq[i - 1], v)
            out.setdefault(v, t)
        return out

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        self.node_xy = []
        p = self.problem
        if not p:
            return
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        pad = 36
        xs = [x for x, _ in p.coords]
        ys = [y for _, y in p.coords]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
        scale = min((w - 2 * pad) / span, (h - 2 * pad) / span)
        ox = (w - (max(xs) - min(xs)) * scale) / 2
        oy = (h - (max(ys) - min(ys)) * scale) / 2
        # y grows upward in coordinates, downward on screen
        self.node_xy = [(ox + (x - min(xs)) * scale, h - oy - (y - min(ys)) * scale) for x, y in p.coords]
        pts = self.node_xy
        small = p.n <= 40
        r = 5 if small else (3 if p.n <= 200 else 2)

        if self.show_prec.get():
            for a, b in p.precedences:
                if 0 <= a < p.n and 0 <= b < p.n:
                    c.create_line(*pts[a], *pts[b], fill=PREC, dash=(4, 3), arrow=tk.LAST, arrowshape=(10, 12, 4))

        if self.show_opt.get() and self.ref.get("optimal_tour"):
            tour = self.ref["optimal_tour"]
            c.create_line(*[xy for v in tour for xy in pts[v]], fill=OPT_TOUR, width=4 if small else 2,
                          dash=(8, 4) if small else ())

        run = self._run()
        answer = run.get("answer") if run else None
        if answer:
            seq = [v for v in answer if 0 <= v < p.n]
            if len(seq) >= 2:
                c.create_line(*[xy for v in seq for xy in pts[v]], fill=SOLVER_TOUR, width=2)
                if small:
                    for a, b in zip(seq, seq[1:]):
                        (x1, y1), (x2, y2) = pts[a], pts[b]
                        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                        c.create_line(x1 + (mx - x1) * 0.9, y1 + (my - y1) * 0.9, mx, my, fill=SOLVER_TOUR,
                                      width=2, arrow=tk.LAST, arrowshape=(9, 11, 4))

        arrivals = self._arrivals()
        for v, (x, y) in enumerate(pts):
            if v in p.deadlines:
                late = v in arrivals and arrivals[v] > p.deadlines[v] or (answer and v not in arrivals)
                c.create_oval(x - r - 4, y - r - 4, x + r + 4, y + r + 4, outline=START if late else DEADLINE,
                              width=3 if late else 2)
            if v == 0:
                c.create_rectangle(x - r - 2, y - r - 2, x + r + 2, y + r + 2, fill=START, outline=BG)
            else:
                c.create_oval(x - r, y - r, x + r, y + r, fill=NODE, outline=BG)
            if self.show_labels.get() and small:
                text = str(v) + (f"  D={p.deadlines[v]}" if v in p.deadlines else "")
                c.create_text(x + r + 6, y - r - 6, text=text, anchor=tk.SW, fill="#0b0b0b", font=("Segoe UI", 9))

        if run and answer is None:
            msg = (f"Answer: None — claimed infeasible ({run['label']})" if not run.get("error")
                   else f"No tour — {run['label']}: {run['error']}")
            c.create_text(w / 2, 18, text=msg, fill=LABEL_COLOR.get(run["label"], "#0b0b0b"),
                          font=("Segoe UI", 12, "bold"))

    def _write_info(self):
        lines = []
        case, run, ref = self.case, self._run(), self.ref
        if case:
            r = case["reference"]
            lines.append(f"{case['name']}   [{case['category']}]   N={r['n']}   "
                         f"deadlines={r['n_deadlines']}  precedences={r['n_precedences']}"
                         + (f"  slack={r['slack']}" if r.get("slack") else ""))
            if r["feasible"]:
                lines.append(f"Reference: c* = {r['optimal_cost']}   ({ref.get('reference_source', '')})")
            else:
                proof = (ref.get("infeasibility_proof") or {}).get("reason", "")
                lines.append(f"Reference: INFEASIBLE ({r['infeasible_class']})  {proof}")
        if run:
            gap = "—" if run.get("gap") is None else f"{run['gap'] * 100:.2f}%"
            sat = run.get("constraint_satisfaction")
            lines += ["", f"Run {run.get('repeat', 0) + 1}: {run['label']}    seed {run['seed']}    "
                          f"wall time {run['wall_time']:.3f}s",
                      f"Cost: {run.get('cost', '—')}    gap: {gap}    constraint satisfaction: "
                      f"{'—' if sat is None else f'{sat * 100:.1f}%'}"]
            if run.get("error"):
                lines.append(f"Error: {run['error']}")
            if run.get("answer_raw"):
                lines.append(f"Raw answer: {run['answer_raw'][:300]}")
            if run.get("answer"):
                tour = run["answer"]
                lines.append("Tour: " + (str(tour) if len(tour) <= 60 else f"{tour[:30]} … ({len(tour)} entries)"))
            if run["violations"]:
                lines.append(f"Violations ({len(run['violations'])}):")
                lines += [f"  - {v['type']}: {v['detail']}" for v in run["violations"][:40]]
                if len(run["violations"]) > 40:
                    lines.append(f"  … {len(run['violations']) - 40} more")
            meta = {k: v for k, v in (run.get("metadata") or {}).items() if k not in ("raw_text", "traceback")}
            if meta:
                lines.append("Metadata: " + json.dumps(meta)[:500])
        self.info.configure(state=tk.NORMAL)
        self.info.delete("1.0", tk.END)
        self.info.insert("1.0", "\n".join(lines))
        self.info.configure(state=tk.DISABLED)


def enable_dpi_awareness():
    """Crisp rendering on scaled Windows displays; no-op elsewhere."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main(argv=None):
    enable_dpi_awareness()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", help="outputs/<timestamp>_<SolverName> (asks if omitted)")
    args = ap.parse_args(argv)
    folder = args.folder
    if not folder:
        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(initialdir=str(ROOT / "outputs"), title="Choose a solver output folder")
        root.destroy()
        if not folder:
            sys.exit(0)
    folder = Path(folder)
    if not (folder / "run_config.json").exists():
        sys.exit(f"{folder} is not a run_solvers.py output folder (no run_config.json)")
    Viewer(folder).mainloop()


if __name__ == "__main__":
    main()

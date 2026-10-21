"""Script 3: evaluate solver output folders.

    python evaluate.py outputs/<ts>_<Solver> [outputs/<ts>_<Other> ...]

For each folder: writes benchmark_dump.json (all statistics) and report.html
(self-contained, offline). With two or more folders, also writes
outputs/compare_<timestamp>.html comparing them side by side.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import tsp_common as tc

CORRECT_SMALL = ["unconstrained_small", "deadline_constrained_small",
                 "precedence_constrained_small", "all_constrained_small"]


# ---------------------------------------------------------------- loading

def load_run(folder: str | Path) -> tuple[dict, list[dict]]:
    folder = Path(folder)
    config = json.loads((folder / "run_config.json").read_text())
    cases = [json.loads(p.read_text()) for p in sorted((folder / "testcases").glob("*/*.json"))]
    if not cases:
        raise SystemExit(f"{folder}: no per-case results under testcases/")
    return config, cases


# ---------------------------------------------------------------- metrics

def rate(num: int, den: int) -> float | None:
    return num / den if den else None


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def dist_stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p90": None, "max": None}
    return {"count": len(values), "mean": statistics.fmean(values), "median": statistics.median(values),
            "p90": percentile(values, 0.9), "max": max(values)}


def is_valid(run: dict) -> bool:
    return run["label"] in tc.VALID_LABELS


def claims_infeasible(run: dict) -> bool:
    return run["label"] in (tc.CORRECT_NONE, tc.WRONG_NONE)


def success(case: dict, run: dict, optimal: bool) -> bool:
    """Feasible: valid (or optimal) tour. Infeasible: correct None."""
    if not case["reference"]["feasible"]:
        return run["label"] == tc.CORRECT_NONE
    return run["label"] == tc.OPTIMAL if optimal else is_valid(run)


def summarize(cases: list[dict]) -> dict:
    runs = [(c, r) for c in cases for r in c["runs"]]
    feas = [(c, r) for c, r in runs if c["reference"]["feasible"]]
    infs = [(c, r) for c, r in runs if not c["reference"]["feasible"]]
    outcomes = Counter(r["label"] for _, r in runs)

    gaps = [r["gap"] for _, r in feas if is_valid(r) and r["gap"] is not None]
    sat = [r["constraint_satisfaction"] for _, r in runs
           if r["label"] in tc.VALID_LABELS | {tc.INVALID} and r["constraint_satisfaction"] is not None]

    viol_runs: Counter = Counter()
    viol_occ: Counter = Counter()
    for _, r in runs:
        types = [v["type"] for v in r["violations"]]
        viol_occ.update(types)
        viol_runs.update(set(types))

    tp = sum(claims_infeasible(r) for _, r in infs)
    fn = len(infs) - tp
    fp = sum(claims_infeasible(r) for _, r in feas)
    tn = len(feas) - fp
    precision, recall = rate(tp, tp + fp), rate(tp, tp + fn)
    if recall is None:
        f1 = None
    elif recall == 0 or not precision:
        f1 = 0.0  # never (correctly) claiming infeasible scores 0, not undefined
    else:
        f1 = 2 * precision * recall / (precision + recall)
    per_class: dict[str, dict] = {}
    for c, r in infs:
        cls = c["reference"]["infeasible_class"] or "unknown"
        d = per_class.setdefault(cls, {"runs": 0, "detected": 0, "hallucinated": 0})
        d["runs"] += 1
        d["detected"] += claims_infeasible(r)
        d["hallucinated"] += bool(r.get("hallucinated_tour"))
    for d in per_class.values():
        d["detection_rate"] = rate(d["detected"], d["runs"])

    multi = [c for c in cases if len(c["runs"]) >= 2]
    gap_stds = []
    for c in multi:
        g = [r["gap"] for r in c["runs"] if is_valid(r) and r["gap"] is not None]
        if len(g) >= 2:
            gap_stds.append(statistics.pstdev(g))
    k = max((len(c["runs"]) for c in cases), default=0)

    return {
        "n_cases": len(cases), "n_runs": len(runs),
        "n_feasible_runs": len(feas), "n_infeasible_runs": len(infs),
        "outcomes": {l: outcomes.get(l, 0) for l in tc.LABELS},
        "outcome_rates": {l: rate(outcomes.get(l, 0), len(runs)) for l in tc.LABELS},
        "validity_rate": rate(sum(is_valid(r) for _, r in feas), len(feas)),
        "optimal_rate": rate(sum(r["label"] == tc.OPTIMAL for _, r in feas), len(feas)),
        "gap": dist_stats(gaps),
        "constraint_satisfaction": {"count": len(sat), "mean": statistics.fmean(sat) if sat else None},
        "violations": {t: {"runs": viol_runs.get(t, 0), "occurrences": viol_occ.get(t, 0),
                           "run_rate": rate(viol_runs.get(t, 0), len(runs))} for t in tc.VIOLATION_TYPES},
        "safeguard": {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1,
            "false_infeasible_rate": rate(fp, len(feas)),
            "hallucinated_tour_rate": rate(sum(bool(r.get("hallucinated_tour")) for _, r in infs), len(infs)),
            "per_class": dict(sorted(per_class.items())),
        },
        "reproducibility": {
            "k": k, "cases": len(multi),
            "outcome_agreement": rate(sum(len({r["label"] for r in c["runs"]}) == 1 for c in multi), len(multi)),
            "pass_at_1_valid": rate(sum(success(c, r, False) for c, r in runs), len(runs)),
            "pass_at_k_valid": rate(sum(any(success(c, r, False) for r in c["runs"]) for c in cases), len(cases)),
            "pass_at_1_optimal": rate(sum(success(c, r, True) for c, r in runs), len(runs)),
            "pass_at_k_optimal": rate(sum(any(success(c, r, True) for r in c["runs"]) for c in cases), len(cases)),
            "mean_gap_std": statistics.fmean(gap_stds) if gap_stds else None,
        },
    }


def by_dimension(cases: list[dict], key) -> list[dict]:
    """Validity / optimal rate / mean gap of feasible cases grouped by key(case)."""
    groups: dict = defaultdict(list)
    for c in cases:
        if c["reference"]["feasible"]:
            x = key(c)
            if x is not None:
                groups[x].append(c)
    out = []
    for x in sorted(groups):
        runs = [r for c in groups[x] for r in c["runs"]]
        gaps = [r["gap"] for r in runs if is_valid(r) and r["gap"] is not None]
        out.append({"x": x, "cases": len(groups[x]), "runs": len(runs),
                    "validity": rate(sum(map(is_valid, runs)), len(runs)),
                    "optimal": rate(sum(r["label"] == tc.OPTIMAL for r in runs), len(runs)),
                    "mean_gap": statistics.fmean(gaps) if gaps else None})
    return out


def robustness(cases: list[dict]) -> dict:
    ref = lambda c: c["reference"]
    in_cats = lambda *cats: [c for c in cases if c["category"] in cats]
    by_n = by_dimension(cases, lambda c: ref(c)["n"])
    largest = None  # largest N such that every N up to it has validity >= 90%
    for g in by_n:
        if g["validity"] is None or g["validity"] < 0.9:
            break
        largest = g["x"]
    det: dict = defaultdict(list)
    for c in cases:
        if not ref(c)["feasible"]:
            det[ref(c)["n"]] += c["runs"]
    return {
        "by_n": by_n,
        "by_deadlines": by_dimension(in_cats("unconstrained_small", "deadline_constrained_small"),
                                     lambda c: ref(c)["n_deadlines"]),
        "by_precedences": by_dimension(in_cats("unconstrained_small", "precedence_constrained_small"),
                                       lambda c: ref(c)["n_precedences"]),
        "by_slack": by_dimension(in_cats("deadline_constrained_small", "all_constrained_small"),
                                 lambda c: ref(c)["slack"]),
        "by_total_constraints": by_dimension(in_cats(*CORRECT_SMALL),
                                             lambda c: ref(c)["n_deadlines"] + ref(c)["n_precedences"]),
        "infeasible_detection_by_n": [
            {"x": n, "runs": len(rs), "detection": rate(sum(map(claims_infeasible, rs)), len(rs))}
            for n, rs in sorted(det.items())],
        "largest_n_validity_90": largest,
    }


def case_summaries(cases: list[dict]) -> list[dict]:
    out = []
    for c in cases:
        out.append({"name": c["name"], "category": c["category"], **c["reference"],
                    "labels": [r["label"] for r in c["runs"]],
                    "costs": [r["cost"] for r in c["runs"]],
                    "gaps": [r["gap"] for r in c["runs"]]})
    return out


def build_dump(config: dict, cases: list[dict]) -> dict:
    by_cat: dict = defaultdict(list)
    for c in cases:
        by_cat[c["category"]].append(c)
    return {
        "solver": config.get("solver"),
        "run_config": config,
        "evaluated": datetime.now().isoformat(timespec="seconds"),
        "overall": summarize(cases),
        "per_category": {cat: summarize(cs) for cat, cs in sorted(by_cat.items())},
        "robustness": robustness(cases),
        "cases": case_summaries(cases),
    }


# ---------------------------------------------------------------- HTML helpers

E = html.escape

# Stack order and colour roles for outcome labels (validated colour-blind-safe ordering).
OUTCOME_ORDER = [tc.OPTIMAL, tc.VALID_SUBOPTIMAL, tc.CORRECT_NONE, tc.WRONG_NONE,
                 tc.INVALID, tc.TIMEOUT, tc.MALFORMED]
OUTCOME_VAR = {tc.OPTIMAL: "--o-optimal", tc.VALID_SUBOPTIMAL: "--o-subopt", tc.CORRECT_NONE: "--o-cnone",
               tc.WRONG_NONE: "--o-wnone", tc.INVALID: "--o-invalid", tc.TIMEOUT: "--o-timeout",
               tc.MALFORMED: "--o-malformed"}

CSS = """
:root{color-scheme:light;--bg:#f6f6f4;--surface:#fcfcfb;--border:#e3e2dd;--grid:#ecebe7;
--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;
--o-optimal:#008300;--o-subopt:#e87ba4;--o-cnone:#eda100;--o-wnone:#2a78d6;--o-invalid:#e34948;
--o-timeout:#6250d6;--o-malformed:#eb6834}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;
--border:#2e2e2c;--grid:#262624;--text:#f0efec;--text2:#c3c2b7;--muted:#8f8e86;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;
--o-optimal:#008300;--o-subopt:#d55181;--o-cnone:#c98500;--o-wnone:#3987e5;--o-invalid:#e66767;
--o-timeout:#9085e9;--o-malformed:#d95926}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;
--border:#2e2e2c;--grid:#262624;--text:#f0efec;--text2:#c3c2b7;--muted:#8f8e86;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;
--o-optimal:#008300;--o-subopt:#d55181;--o-cnone:#c98500;--o-wnone:#3987e5;--o-invalid:#e66767;
--o-timeout:#9085e9;--o-malformed:#d95926}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 12px}h3{font-size:15px;margin:20px 0 8px}
.sub{color:var(--text2);margin:0 0 20px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:16px;overflow-x:auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px}
.kpi .v{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}.kpi .l{color:var(--text2);font-size:12px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--text2);font-weight:600;font-size:12px}td.num,th.num{text-align:right}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:0 0 10px;color:var(--text2);font-size:12px}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.chip{display:inline-flex;align-items:center;gap:4px;margin-right:8px;font-size:12px;color:var(--text2)}
.chip i{width:8px;height:8px;border-radius:50%;display:inline-block}
svg text{fill:var(--text2);font-size:11px;font-family:inherit}
svg .axis{stroke:var(--border)}svg .gridl{stroke:var(--grid)}
details{margin-bottom:8px}summary{cursor:pointer;font-weight:600;padding:6px 0}
input[type=search]{width:100%;max-width:360px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);
background:var(--surface);color:var(--text);margin-bottom:12px}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--border);
border-radius:6px;padding:6px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.15);display:none;z-index:9;white-space:pre}
.muted{color:var(--muted)}
"""

JS = """
const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');
 if(!t){tip.style.display='none';return}
 tip.textContent=t.getAttribute('data-tip');tip.style.display='block';
 const x=Math.min(e.clientX+12,innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+12)+'px'});
const q=document.getElementById('q');
if(q)q.addEventListener('input',()=>{const s=q.value.toLowerCase();
 document.querySelectorAll('tr[data-case]').forEach(r=>{r.style.display=r.dataset.case.includes(s)?'':'none'});
 if(s)document.querySelectorAll('details.dd').forEach(d=>d.open=true)});
"""


def fmt_pct(v, digits=1) -> str:
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def fmt_num(v, digits=3) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}" if isinstance(v, float) else str(v)


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{E(title)}</title><style>{CSS}</style></head><body><main>{body}</main>"
            f"<div id='tip'></div><script>{JS}</script></body></html>")


def legend(items: list[tuple[str, str]]) -> str:
    return "<div class='legend'>" + "".join(
        f"<span><span class='sw' style='background:var({var})'></span>{E(name)}</span>" for name, var in items) + "</div>"


def line_chart(xs: list, series: list[tuple[str, str, list]], x_label: str, percent: bool = True,
               fixed_max: bool = True, w: int = 520, h: int = 240) -> str:
    """Categorical-x line chart (evenly spaced x). series = [(name, css var, [y | None])]."""
    if not xs:
        return "<p class='muted'>No data.</p>"
    ml, mr, mt, mb = 48, 16, 12, 40
    pw, ph = w - ml - mr, h - mt - mb
    vals = [y for _, _, ys in series for y in ys if y is not None]
    ymax = 1.0 if percent and fixed_max else (max(vals) * 1.15 if vals and max(vals) > 0 else 1.0)
    X = lambda i: ml + (pw * (i + 0.5) / len(xs))
    Y = lambda v: mt + ph - ph * v / ymax
    parts = [f"<svg viewBox='0 0 {w} {h}' width='100%' role='img' aria-label='{E(x_label)} chart'>"]
    for t in range(5):
        v = ymax * t / 4
        y = Y(v)
        parts.append(f"<line class='gridl' x1='{ml}' x2='{w - mr}' y1='{y:.1f}' y2='{y:.1f}'/>")
        lab = (f"{v * 100:.0f}%" if fixed_max else f"{v * 100:.1f}%") if percent else f"{v:.2f}"
        parts.append(f"<text x='{ml - 6}' y='{y + 4:.1f}' text-anchor='end'>{lab}</text>")
    parts.append(f"<line class='axis' x1='{ml}' x2='{w - mr}' y1='{mt + ph}' y2='{mt + ph}'/>")
    step = max(1, math.ceil(len(xs) / 12))
    for i, x in enumerate(xs):
        if i % step == 0:
            parts.append(f"<text x='{X(i):.1f}' y='{mt + ph + 16}' text-anchor='middle'>{E(str(x))}</text>")
    parts.append(f"<text x='{ml + pw / 2}' y='{h - 6}' text-anchor='middle'>{E(x_label)}</text>")
    for name, var, ys in series:
        pts = [(X(i), Y(y), x, y) for i, (x, y) in enumerate(zip(xs, ys)) if y is not None]
        if len(pts) > 1:
            d = " ".join(f"{'M' if j == 0 else 'L'}{px:.1f},{py:.1f}" for j, (px, py, _, _) in enumerate(pts))
            parts.append(f"<path d='{d}' fill='none' stroke='var({var})' stroke-width='2'/>")
        for px, py, x, y in pts:
            val = fmt_pct(y) if percent else f"{y:.4f}"
            parts.append(f"<circle cx='{px:.1f}' cy='{py:.1f}' r='4' fill='var({var})' stroke='var(--surface)' "
                         f"stroke-width='2'/><circle cx='{px:.1f}' cy='{py:.1f}' r='11' fill='transparent' "
                         f"data-tip='{E(name)}\n{E(x_label)} = {E(str(x))}: {val}'/>")
    parts.append("</svg>")
    lg = legend([(n, v) for n, v, _ in series]) if len(series) > 1 else ""
    return lg + "".join(parts)


def stacked_bars(rows: list[tuple[str, dict]], w: int = 900) -> str:
    """100% horizontal stacked bars of outcome counts, one row per entry."""
    present = [l for l in OUTCOME_ORDER if any(counts.get(l) for _, counts in rows)]
    lw, bh, gap = 240, 22, 10
    pw = w - lw - 60
    h = len(rows) * (bh + gap) + 4
    parts = [f"<svg viewBox='0 0 {w} {h}' width='100%' role='img' aria-label='Outcome distribution'>"]
    for i, (name, counts) in enumerate(rows):
        y = i * (bh + gap) + 2
        total = sum(counts.values())
        parts.append(f"<text x='{lw - 8}' y='{y + bh / 2 + 4}' text-anchor='end'>{E(name)}</text>")
        x = lw
        for lab in present:
            c = counts.get(lab, 0)
            if not c:
                continue
            sw = pw * c / total
            parts.append(f"<rect x='{x:.1f}' y='{y}' width='{max(sw - 2, 1):.1f}' height='{bh}' rx='3' "
                         f"fill='var({OUTCOME_VAR[lab]})' data-tip='{E(name)}\n{E(lab)}: {c}/{total} "
                         f"({c / total * 100:.1f}%)'/>")
            x += sw
        parts.append(f"<text x='{lw + pw + 6}' y='{y + bh / 2 + 4}'>{total}</text>")
    parts.append("</svg>")
    return legend([(l, OUTCOME_VAR[l]) for l in present]) + "".join(parts)


def hbars(items: list[tuple[str, float, str]], var: str = "--s1", w: int = 520) -> str:
    """Single-series horizontal bars. items = [(name, value 0..1, tooltip)]."""
    lw, bh, gap = 150, 16, 8
    pw = w - lw - 60
    h = len(items) * (bh + gap) + 4
    parts = [f"<svg viewBox='0 0 {w} {h}' width='100%' style='max-width:{w}px' role='img' aria-label='bar chart'>"]
    for i, (name, v, tipt) in enumerate(items):
        y = i * (bh + gap) + 2
        parts.append(f"<text x='{lw - 8}' y='{y + bh / 2 + 4}' text-anchor='end'>{E(name)}</text>")
        bw = max(pw * (v or 0), 0)
        if bw > 0:
            parts.append(f"<rect x='{lw}' y='{y}' width='{bw:.1f}' height='{bh}' rx='3' fill='var({var})' "
                         f"data-tip='{E(tipt)}'/>")
        parts.append(f"<text x='{lw + bw + 6:.1f}' y='{y + bh / 2 + 4}'>{fmt_pct(v)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def table(headers: list[str], rows: list[list], num_from: int = 1) -> str:
    th = "".join(f"<th class='{'num' if i >= num_from else ''}'>{E(h)}</th>" for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f"<td class='{'num' if i >= num_from else ''}'>{c}</td>"
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def chip(label: str) -> str:
    return f"<span class='chip'><i style='background:var({OUTCOME_VAR[label]})'></i>{E(label)}</span>"


def dim_chart(rows: list[dict], x_label: str) -> str:
    xs = [r["x"] for r in rows]
    return line_chart(xs, [("Validity", "--s1", [r["validity"] for r in rows]),
                           ("Optimal", "--s2", [r["optimal"] for r in rows])], x_label)


# ---------------------------------------------------------------- report

def render_report(dump: dict, cases: list[dict]) -> str:
    o, rb, cfg = dump["overall"], dump["robustness"], dump["run_config"]
    sg, rp = o["safeguard"], o["reproducibility"]
    b = [f"<h1>{E(dump['solver'] or 'Solver')} — constrained TSP benchmark</h1>",
         f"<p class='sub'>{o['n_cases']} test cases × k={cfg.get('k')} = {o['n_runs']} runs · "
         f"time limit {cfg.get('time_limit')}s · run {E(str(cfg.get('started', '')))} · "
         f"evaluated {E(dump['evaluated'])}</p>"]

    kpis = [("Validity (feasible runs)", fmt_pct(o["validity_rate"])),
            ("Optimal rate (feasible runs)", fmt_pct(o["optimal_rate"])),
            ("Median gap (valid tours)", fmt_pct(o["gap"]["median"], 2)),
            ("Infeasibility F1", fmt_num(sg["f1"], 2)),
            (f"pass@{rp['k']} optimal", fmt_pct(rp["pass_at_k_optimal"])),
            ("Outcome agreement across k", fmt_pct(rp["outcome_agreement"]))]
    b.append("<div class='kpis'>" + "".join(
        f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{E(l)}</div></div>" for l, v in kpis) + "</div>")

    b.append("<h2>Outcome distribution</h2><div class='card'>")
    b.append(stacked_bars([("All", o["outcomes"])] +
                          [(cat, s["outcomes"]) for cat, s in dump["per_category"].items()]))
    b.append("</div>")

    b.append("<h2>Correctness by category</h2><div class='card'>")
    rows = []
    for cat, s in [("All", o)] + list(dump["per_category"].items()):
        g = s["gap"]
        rows.append([E(cat), s["n_runs"], fmt_pct(s["validity_rate"]), fmt_pct(s["optimal_rate"]),
                     fmt_pct(g["mean"], 2), fmt_pct(g["median"], 2), fmt_pct(g["p90"], 2), fmt_pct(g["max"], 2),
                     fmt_pct(s["constraint_satisfaction"]["mean"])])
    b.append(table(["Category", "Runs", "Validity", "Optimal", "Gap mean", "Gap median", "Gap P90", "Gap max",
                    "Constraint sat."], rows))
    b.append("<p class='muted'>Validity / optimal are over runs on feasible cases. Gaps are over valid tours, "
             "vs exact c* (small) or the published optimum (national). Constraint satisfaction is the mean "
             "fraction of deadline + precedence constraints met by returned tours.</p></div>")

    b.append("<h2>Robustness</h2><div class='grid2'>")
    for title, key, xl in [("Validity & optimal rate vs N", "by_n", "N (nodes)"),
                           ("vs number of deadlines", "by_deadlines", "deadlines"),
                           ("vs number of precedences", "by_precedences", "precedences"),
                           ("vs deadline slack s", "by_slack", "slack s"),
                           ("vs total constraints (small sets)", "by_total_constraints", "constraints")]:
        b.append(f"<div class='card'><h3>{E(title)}</h3>{dim_chart(rb[key], xl)}</div>")
    gap_rows = rb["by_n"]
    b.append("<div class='card'><h3>Mean gap vs N (valid tours)</h3>"
             + line_chart([r["x"] for r in gap_rows], [("Mean gap", "--s1", [r["mean_gap"] for r in gap_rows])],
                          "N (nodes)", fixed_max=False) + "</div></div>")
    b.append(f"<p>Largest N such that validity ≥ 90% at every N up to it: <b>{rb['largest_n_validity_90'] if rb['largest_n_validity_90'] is not None else '—'}</b></p>")
    b.append("<div class='card'>" + table(
        ["N", "Cases", "Runs", "Validity", "Optimal", "Mean gap"],
        [[r["x"], r["cases"], r["runs"], fmt_pct(r["validity"]), fmt_pct(r["optimal"]), fmt_pct(r["mean_gap"], 2)]
         for r in rb["by_n"]]) + "</div>")

    b.append("<h2>Safeguard: infeasibility detection</h2><div class='grid2'><div class='card'>")
    b.append(table(["", "Claimed infeasible (None)", "Returned tour / error"],
                   [["<b>Infeasible case</b>", f"TP {sg['tp']}", f"FN {sg['fn']}"],
                    ["<b>Feasible case</b>", f"FP {sg['fp']}", f"TN {sg['tn']}"]]))
    b.append(table(["Metric", "Value"], [
        ["Precision", fmt_num(sg["precision"], 3)], ["Recall", fmt_num(sg["recall"], 3)],
        ["F1", fmt_num(sg["f1"], 3)], ["False-infeasible rate (feasible runs)", fmt_pct(sg["false_infeasible_rate"])],
        ["Hallucinated-tour rate (infeasible runs)", fmt_pct(sg["hallucinated_tour_rate"])]]))
    b.append("</div><div class='card'><h3>Detection rate per infeasible class</h3>")
    pc = sg["per_class"]
    b.append(hbars([(cls.replace("infeasible_", ""), d["detection_rate"],
                     f"{cls}\ndetected {d['detected']}/{d['runs']}, hallucinated tour {d['hallucinated']}")
                    for cls, d in pc.items()]) if pc else "<p class='muted'>No infeasible cases.</p>")
    b.append(table(["Class", "Runs", "Detected", "Hallucinated tour", "Rate"],
                   [[E(c), d["runs"], d["detected"], d["hallucinated"], fmt_pct(d["detection_rate"])]
                    for c, d in pc.items()]))
    b.append("</div></div>")

    b.append("<h2>Violations</h2><div class='card'>")
    vio = o["violations"]
    b.append(hbars([(t, v["run_rate"], f"{t}\n{v['runs']} runs, {v['occurrences']} occurrences")
                    for t, v in vio.items()], var="--s8"))
    b.append(table(["Violation", "Runs affected", "Occurrences", "Share of runs"],
                   [[E(t), v["runs"], v["occurrences"], fmt_pct(v["run_rate"])] for t, v in vio.items()]))
    b.append("</div>")

    b.append(f"<h2>Reproducibility (k = {rp['k']})</h2><div class='card'>")
    b.append(table(["Metric", "Value"], [
        ["Cases with ≥ 2 runs", rp["cases"]],
        ["Outcome agreement (all k labels identical)", fmt_pct(rp["outcome_agreement"])],
        ["pass@1 valid", fmt_pct(rp["pass_at_1_valid"])], [f"pass@{rp['k']} valid", fmt_pct(rp["pass_at_k_valid"])],
        ["pass@1 optimal", fmt_pct(rp["pass_at_1_optimal"])],
        [f"pass@{rp['k']} optimal", fmt_pct(rp["pass_at_k_optimal"])],
        ["Mean per-case std of gap", fmt_pct(rp["mean_gap_std"], 3)]]))
    b.append("<p class='muted'>Success = valid tour (or optimal) on feasible cases, correct None on infeasible "
             "cases. pass@k counts a case if any of its k runs succeeds.</p></div>")

    b.append("<h2>Per-instance drilldown</h2><input type='search' id='q' placeholder='Filter cases by name…'>")
    by_cat: dict = defaultdict(list)
    for c in cases:
        by_cat[c["category"]].append(c)
    for cat, cs in sorted(by_cat.items()):
        rows = []
        for c in cs:
            ref = c["reference"]
            refs = (f"c* = {ref['optimal_cost']}" if ref["feasible"] else
                    f"infeasible ({E((ref['infeasible_class'] or '').replace('infeasible_', ''))})")
            labels = "".join(chip(r["label"]) for r in c["runs"])
            costs = ", ".join("—" if r["cost"] is None else str(r["cost"]) for r in c["runs"])
            gaps = ", ".join(fmt_pct(r["gap"], 2) for r in c["runs"])
            first = next((v for r in c["runs"] for v in r["violations"]), None)
            err = next((r["error"] for r in c["runs"] if r.get("error")), None)
            note = E(first["detail"]) if first else (E(str(err)[:80]) if err else "")
            rows.append(f"<tr data-case='{E(c['name'].lower())}'><td>{E(c['name'])}</td>"
                        f"<td class='num'>{ref['n']}</td><td class='num'>{ref['n_deadlines']}/{ref['n_precedences']}</td>"
                        f"<td>{refs}</td><td>{labels}</td><td class='num'>{costs}</td><td class='num'>{gaps}</td>"
                        f"<td class='muted'>{note}</td></tr>")
        b.append(f"<details class='dd card'><summary>{E(cat)} ({len(cs)})</summary><table><thead><tr>"
                 "<th>Case</th><th class='num'>N</th><th class='num'>D/P</th><th>Reference</th><th>Runs</th>"
                 "<th class='num'>Costs</th><th class='num'>Gaps</th><th>First issue</th></tr></thead><tbody>"
                 + "".join(rows) + "</tbody></table></details>")

    b.append("<h2>Run configuration</h2><div class='card'>" + table(
        ["Key", "Value"], [[E(k), E(json.dumps(v))] for k, v in cfg.items()]) + "</div>")
    return page(f"{dump['solver']} benchmark", "".join(b))


def render_compare(dumps: list[dict]) -> str:
    names = [d["solver"] or f"solver {i}" for i, d in enumerate(dumps)]
    svars = [f"--s{i % 8 + 1}" for i in range(len(dumps))]
    b = [f"<h1>Solver comparison</h1><p class='sub'>{len(dumps)} runs · generated "
         f"{datetime.now().isoformat(timespec='seconds')}</p>"]
    rows = []
    for name, d in zip(names, dumps):
        o = d["overall"]
        rows.append([E(name), o["n_runs"], fmt_pct(o["validity_rate"]), fmt_pct(o["optimal_rate"]),
                     fmt_pct(o["gap"]["mean"], 2), fmt_pct(o["gap"]["median"], 2),
                     fmt_pct(o["constraint_satisfaction"]["mean"]), fmt_num(o["safeguard"]["f1"], 2),
                     fmt_pct(o["safeguard"]["hallucinated_tour_rate"]),
                     fmt_pct(o["reproducibility"]["pass_at_k_optimal"]),
                     fmt_pct(o["reproducibility"]["outcome_agreement"]),
                     d["robustness"]["largest_n_validity_90"] or "—"])
    b.append("<div class='card'>" + table(
        ["Solver", "Runs", "Validity", "Optimal", "Gap mean", "Gap median", "Constraint sat.", "Infeas. F1",
         "Halluc. tour", "pass@k opt.", "Agreement", "Max N ≥90% valid"], rows) + "</div>")
    b.append("<h2>Outcome distribution</h2><div class='card'>"
             + stacked_bars([(n, d["overall"]["outcomes"]) for n, d in zip(names, dumps)]) + "</div>")

    def multi(key: str, metric: str, x_label: str) -> str:
        xs = sorted({r["x"] for d in dumps for r in d["robustness"][key]})
        series = []
        for name, var, d in zip(names, svars, dumps):
            m = {r["x"]: r[metric] for r in d["robustness"][key]}
            series.append((name, var, [m.get(x) for x in xs]))
        return line_chart(xs, series, x_label)

    b.append("<h2>Robustness</h2><div class='grid2'>")
    for title, key, metric, xl in [("Validity vs N", "by_n", "validity", "N (nodes)"),
                                   ("Optimal rate vs N", "by_n", "optimal", "N (nodes)"),
                                   ("Validity vs deadline slack", "by_slack", "validity", "slack s"),
                                   ("Validity vs total constraints", "by_total_constraints", "validity", "constraints")]:
        b.append(f"<div class='card'><h3>{E(title)}</h3>{multi(key, metric, xl)}</div>")
    b.append("</div>")

    classes = sorted({c for d in dumps for c in d["overall"]["safeguard"]["per_class"]})
    b.append("<h2>Infeasibility detection per class</h2><div class='card'>" + table(
        ["Class"] + [E(n) for n in names],
        [[E(c)] + [fmt_pct(d["overall"]["safeguard"]["per_class"].get(c, {}).get("detection_rate"))
                   for d in dumps] for c in classes]) + "</div>")

    cats = sorted({c for d in dumps for c in d["per_category"]})
    b.append("<h2>Optimal rate per category</h2><div class='card'>" + table(
        ["Category"] + [E(n) for n in names],
        [[E(c)] + [fmt_pct(d["per_category"].get(c, {}).get("optimal_rate")) for d in dumps] for c in cats])
             + "</div>")
    return page("Solver comparison", "".join(b))


# ---------------------------------------------------------------- main

def evaluate_folder(folder: str | Path) -> dict:
    folder = Path(folder)
    config, cases = load_run(folder)
    dump = build_dump(config, cases)
    (folder / "benchmark_dump.json").write_text(json.dumps(dump, indent=1))
    (folder / "report.html").write_text(render_report(dump, cases), encoding="utf-8")
    return dump


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+", help="outputs/<timestamp>_<SolverName> folders")
    ap.add_argument("--compare-out", help="path for the comparison page (default outputs/compare_<ts>.html)")
    args = ap.parse_args(argv)
    dumps = []
    for f in args.folders:
        d = evaluate_folder(f)
        o = d["overall"]
        print(f"{d['solver']}: validity {fmt_pct(o['validity_rate'])}, optimal {fmt_pct(o['optimal_rate'])}, "
              f"F1 {fmt_num(o['safeguard']['f1'], 2)} -> {Path(f) / 'report.html'}".replace("—", "n/a"))
        dumps.append(d)
    if len(dumps) > 1:
        out = Path(args.compare_out) if args.compare_out else \
            Path(args.folders[0]).resolve().parent / f"compare_{datetime.now():%Y%m%d_%H%M%S}.html"
        out.write_text(render_compare(dumps), encoding="utf-8")
        print(f"comparison -> {out}")


if __name__ == "__main__":
    main()

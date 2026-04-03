# ─────────────────────────────────────────────────────────────────────────────
# File: backend/eval/report.py
# Purpose: Formats and prints the evaluation results to the terminal.
#          Produces a category-level summary table (rich) + per-test details
#          on failures, and writes a full JSON dump to eval/results/.
# Language: Python
# Connects to: eval/metrics.py (result dicts)
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich import box

_console = Console()

_CATEGORY_LABELS = {
    "preflight_security":    "F  Preflight / Security",
    "routing_search":       "A  Routing → SEARCH",
    "routing_memory":       "B  Routing → MEMORY",
    "routing_graph_expand": "C  Graph Expansion",
    "format":               "D  Response Format",
    "graph_schema":         "E  Graph Schema",
}


def print_self_assessment(text: str) -> None:
    """Print the agent's self-reported evaluation criteria at the top of the run."""
    _console.rule("[bold #a78bfa]Agent Self-Reported Criteria[/]")
    _console.print(text.strip(), style="#8b949e")
    _console.print()


def print_report(results: list[dict]) -> None:
    """Print a summary table + per-failure details, then write JSON to disk."""
    _console.print()
    _console.rule("[bold #e6edf3]EVAL REPORT[/]")

    # Group results by category
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        cat = r.get("category", "unknown")
        by_cat.setdefault(cat, []).append(r)

    total_pass = total_fail = 0

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold #6e7681")
    table.add_column("Category", style="#c9d1d9", min_width=26)
    table.add_column("Pass", justify="right", style="green")
    table.add_column("Fail", justify="right", style="red")
    table.add_column("Score", justify="right", style="#a78bfa")

    for cat, cat_label in _CATEGORY_LABELS.items():
        cat_results = by_cat.get(cat, [])
        if not cat_results:
            continue
        passed = sum(1 for r in cat_results if r.get("passed", False))
        failed = len(cat_results) - passed
        total_pass += passed
        total_fail += failed
        pct = f"{passed / len(cat_results) * 100:.0f}%"
        table.add_row(cat_label, str(passed), str(failed), pct)

    # Overall row
    total = total_pass + total_fail
    overall_pct = f"{total_pass / total * 100:.0f}%" if total else "—"
    table.add_section()
    table.add_row("[bold]OVERALL[/]", f"[bold]{total_pass}[/]", f"[bold]{total_fail}[/]", f"[bold]{overall_pct}[/]")

    _console.print(table)

    # Per-failure details
    failures = [r for r in results if not r.get("passed", True)]
    if failures:
        _console.print()
        _console.rule("[bold red]Failures[/]")
        for r in failures:
            _console.print(f"[bold #f87171]{r['id']}[/] — {r['description']}", style="")
            for k, v in r.items():
                if k.endswith("_pass") and v is False:
                    metric = k[:-5]
                    actual  = r.get(metric, "?")
                    _console.print(f"  [red]✗[/] {metric}: got [bold]{actual}[/]", style="#6e7681")
            errors = r.get("errors", [])
            for e in errors[:5]:
                _console.print(f"  [dim]  · {e}[/]")
    else:
        _console.print("\n[bold green]All tests passed.[/]")

    # Write JSON results
    _write_json(results)


def _write_json(results: list[dict]) -> None:
    """Write full results to eval/results/YYYY-MM-DD_HHMMSS.json."""
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(results_dir, f"{ts}.json")

    # Remove internal _raw keys before serialising
    clean = [{k: v for k, v in r.items() if k != "_raw"} for r in results]
    with open(path, "w") as f:
        json.dump(clean, f, indent=2, default=str)

    _console.print(f"\n[dim]Results written to {path}[/]")

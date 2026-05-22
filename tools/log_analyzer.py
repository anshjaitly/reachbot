#!/usr/bin/env python3
"""
ReachBot — Session Log Analyzer

Analyzes JSONL session logs to produce research-quality stats.
Useful for Regeneron STS research paper and user testing reports.

Usage:
    python tools/log_analyzer.py                     # Analyze all logs
    python tools/log_analyzer.py --file session.jsonl  # One file
    python tools/log_analyzer.py --csv report.csv    # Export to CSV
    python tools/log_analyzer.py --summary           # One-line summary only

Output:
    - Overall success rate
    - Success rate per object
    - Average grasp duration
    - Most/least reliable objects
    - Detection confidence distribution
    - Failure mode breakdown
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any

# Default log directory matches session_logger.py
LOG_DIR = Path.home() / "reachbot_logs"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_all_logs(directory: Path) -> List[Dict[str, Any]]:
    all_records = []
    files = sorted(directory.glob("session_*.jsonl"))
    if not files:
        print(f"No session logs found in {directory}")
        return []
    for f in files:
        records = load_jsonl(f)
        all_records.extend(records)
        print(f"  Loaded {len(records):>3} records from {f.name}")
    return all_records


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {"total": 0}

    total = len(records)
    successes = sum(1 for r in records if r.get("grasp_success"))
    failures = total - successes

    # Per-object stats
    per_object: Dict[str, Dict] = defaultdict(lambda: {
        "total": 0, "success": 0, "durations": [], "confidences": []
    })
    for r in records:
        obj = r.get("target_object", "unknown")
        per_object[obj]["total"] += 1
        if r.get("grasp_success"):
            per_object[obj]["success"] += 1
        if r.get("duration_s") is not None:
            per_object[obj]["durations"].append(r["duration_s"])
        if r.get("detection_confidence") is not None:
            per_object[obj]["confidences"].append(r["detection_confidence"])

    # Failure modes
    failure_modes: Dict[str, int] = defaultdict(int)
    for r in records:
        if not r.get("grasp_success"):
            reason = r.get("failure_reason") or "unknown"
            failure_modes[reason] += 1

    # Durations
    durations = [r["duration_s"] for r in records if r.get("duration_s")]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Confidence
    confs = [r["detection_confidence"] for r in records
             if r.get("detection_confidence") is not None]
    avg_conf = sum(confs) / len(confs) if confs else 0

    # Ranked objects
    obj_rates = {}
    for obj, stats in per_object.items():
        if stats["total"] > 0:
            obj_rates[obj] = stats["success"] / stats["total"]

    best_obj  = max(obj_rates, key=obj_rates.get) if obj_rates else None
    worst_obj = min(obj_rates, key=obj_rates.get) if obj_rates else None

    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "success_rate": successes / total,
        "avg_duration_s": avg_duration,
        "avg_confidence": avg_conf,
        "per_object": dict(per_object),
        "failure_modes": dict(failure_modes),
        "best_object": best_obj,
        "worst_object": worst_obj,
        "obj_rates": obj_rates,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_report(stats: Dict[str, Any]) -> None:
    if stats["total"] == 0:
        print("No records to analyze.")
        return

    W = 52  # column width
    bar = "─" * W

    print(f"\n{'REACHBOT SESSION ANALYSIS':^{W}}")
    print(bar)
    print(f"  Total attempts   : {stats['total']}")
    print(f"  Successes        : {stats['successes']}")
    print(f"  Failures         : {stats['failures']}")
    print(f"  Success rate     : {stats['success_rate']*100:.1f}%  "
          f"{'✓ STRONG' if stats['success_rate'] >= 0.8 else '⚠ NEEDS WORK'}")
    print(f"  Avg duration     : {stats['avg_duration_s']:.1f}s")
    print(f"  Avg confidence   : {stats['avg_confidence']:.2f}")

    if stats.get("best_object"):
        print(f"  Best object      : {stats['best_object']} "
              f"({stats['obj_rates'][stats['best_object']]*100:.0f}%)")
    if stats.get("worst_object") and stats["worst_object"] != stats.get("best_object"):
        print(f"  Worst object     : {stats['worst_object']} "
              f"({stats['obj_rates'][stats['worst_object']]*100:.0f}%)")

    # Per-object table
    print(f"\n{'OBJECT BREAKDOWN':^{W}}")
    print(bar)
    print(f"  {'Object':<16} {'Attempts':>8} {'Success':>8} {'Rate':>7} {'Avg(s)':>7}  {'':8}")
    print(f"  {'─'*16} {'─'*8} {'─'*8} {'─'*7} {'─'*7}  {'─'*8}")
    for obj, s in sorted(stats["per_object"].items(),
                          key=lambda x: -x[1]["total"]):
        rate = s["success"] / s["total"] if s["total"] else 0
        avg_d = (sum(s["durations"]) / len(s["durations"])
                 if s["durations"] else 0)
        bar_str = "█" * int(rate * 8) + "░" * (8 - int(rate * 8))
        print(f"  {obj:<16} {s['total']:>8} {s['success']:>8} "
              f"{rate*100:>6.1f}% {avg_d:>7.1f}  {bar_str}")

    # Failure modes
    if stats["failure_modes"]:
        print(f"\n{'FAILURE MODES':^{W}}")
        print(bar)
        for reason, count in sorted(stats["failure_modes"].items(),
                                     key=lambda x: -x[1]):
            pct = count / stats["failures"] * 100 if stats["failures"] else 0
            print(f"  {reason:<24} {count:>5}  ({pct:.1f}%)")

    print(bar)
    print(f"  {'Regeneron STS note':}")
    rate_pct = stats['success_rate'] * 100
    print(f"  n={stats['total']}, success={rate_pct:.1f}%, "
          f"μ={stats['avg_duration_s']:.1f}s/attempt, "
          f"σ_conf={stats['avg_confidence']:.2f}")
    print()


def export_csv(records: List[Dict[str, Any]], out_path: Path) -> None:
    if not records:
        print("No records to export.")
        return
    keys = [
        "timestamp", "command_text", "target_object",
        "object_detected", "detection_confidence",
        "position_x_mm", "position_y_mm", "position_z_mm",
        "grasp_success", "failure_reason", "duration_s",
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"Exported {len(records)} records to {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze ReachBot session logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--file", type=Path, metavar="PATH",
                        help="Analyze a single JSONL file")
    parser.add_argument("--dir", type=Path, default=LOG_DIR, metavar="DIR",
                        help=f"Log directory (default: {LOG_DIR})")
    parser.add_argument("--csv", type=Path, metavar="OUT",
                        help="Export records to CSV")
    parser.add_argument("--summary", action="store_true",
                        help="Print one-line summary only")
    args = parser.parse_args()

    # Load
    if args.file:
        if not args.file.exists():
            print(f"File not found: {args.file}")
            sys.exit(1)
        records = load_jsonl(args.file)
        print(f"Loaded {len(records)} records from {args.file.name}")
    else:
        if not args.dir.exists():
            print(f"Log directory not found: {args.dir}")
            print("Run ReachBot at least once to generate logs.")
            sys.exit(1)
        records = load_all_logs(args.dir)

    if not records:
        sys.exit(0)

    stats = analyze(records)

    if args.summary:
        r = stats['success_rate'] * 100
        print(f"n={stats['total']} | success={r:.1f}% | "
              f"avg={stats['avg_duration_s']:.1f}s | "
              f"conf={stats['avg_confidence']:.2f}")
    else:
        print_report(stats)

    if args.csv:
        export_csv(records, args.csv)


if __name__ == "__main__":
    main()

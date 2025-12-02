#!/usr/bin/env python3
import argparse, csv, math, sys

def parse_args():
    ap = argparse.ArgumentParser(description='Suggest dynamic batching from perf report CSV (perf_analyzer --latency-report-file)')
    ap.add_argument('--report', required=True, help='CSV report file from perf_analyzer')
    ap.add_argument('--latency-budget-ms', type=float, default=2.0, help='Allowed P90 growth factor vs baseline (e.g., 2.0x)')
    return ap.parse_args()

def main():
    args = parse_args()
    rows = []
    with open(args.report, newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            # Expected fields include 'Concurrency', 'Inferences/Second', 'Client Send', 'Server Queue', 'Server Compute', 'Client Receive', 'p90 Latency'
            try:
                conc = int(row.get('Concurrency', row.get('Concurrency Range', '1')).split('-')[0])
                ips = float(row.get('Inferences/Second', 0))
                p90 = float(row.get('p90 Latency (ms)', row.get('p90 latency (ms)', row.get('p90 Latency', 0))))
                rows.append((conc, ips, p90))
            except Exception:
                pass
    if not rows:
        print('{"error":"empty_report"}')
        return 1
    rows.sort(key=lambda x: x[0])
    base_p90 = rows[0][2]
    budget = base_p90 * args.latency_budget_ms

    # Choose conc values that improve throughput while staying within latency budget
    best = []
    best_ips = 0.0
    for conc, ips, p90 in rows:
        if ips >= best_ips * 1.02 and p90 <= budget:
            best.append(conc)
            best_ips = ips
    # Map concurrency list to preferred_batch_size heuristic
    # Guideline: use small set [1, x, y] where x,y are powers of two <= max conc in best
    prefs = [1]
    if best:
        mx = max(best)
        for k in [2,4,8,16,32]:
            if k <= mx and k not in prefs:
                prefs.append(k)
        prefs = [p for p in prefs if p in best or p == 1]
    print('{"preferred_batch_size": %s, "latency_budget_ms": %.3f, "baseline_p90_ms": %.3f}' % (prefs, budget, base_p90))
    return 0

if __name__ == '__main__':
    sys.exit(main())


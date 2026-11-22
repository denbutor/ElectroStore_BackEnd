import csv
import glob
import json
import os
import numpy as np
import matplotlib.pyplot as plt


def main() -> None:
    rows = []
    for path in sorted(glob.glob("results/full_*.json")):
        name = os.path.basename(path).replace("full_", "").replace(".json", "")
        all_vals, ok_vals = [], []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("type") == "Point" and row.get("metric") == "http_req_duration":
                    val = float(row["data"]["value"])
                    all_vals.append(val)
                    tags = row["data"].get("tags") or {}
                    if tags.get("expected_response") == "true":
                        ok_vals.append(val)

        if not all_vals:
            continue

        arr = np.array(all_vals)
        ok_arr = np.array(ok_vals if ok_vals else all_vals)
        rows.append({
            "profile": name,
            "total_reqs": len(arr),
            "ok_2xx_reqs": len(ok_arr),
            "all_avg_ms": round(float(np.mean(arr)), 2),
            "all_p95_ms": round(float(np.percentile(arr, 95)), 2),
            "ok_avg_ms": round(float(np.mean(ok_arr)), 2),
            "ok_med_ms": round(float(np.median(ok_arr)), 2),
            "ok_p95_ms": round(float(np.percentile(ok_arr, 95)), 2),
            "ok_max_ms": round(float(np.max(ok_arr)), 2),
        })

    if not rows:
        print("No results/full_*.json files found.")
        return

    os.makedirs("results", exist_ok=True)
    with open("results/k6_summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    order = [r for r in rows if r["profile"] in ("smoke", "load", "spike")] or rows
    labels = [r["profile"] for r in order]
    x = np.arange(len(labels))
    w_bar = 0.25

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - w_bar, [r["ok_avg_ms"] for r in order], w_bar, label="200 OK avg (ms)")
    ax.bar(x, [r["ok_med_ms"] for r in order], w_bar, label="200 OK med (ms)")
    ax.bar(x + w_bar, [r["ok_p95_ms"] for r in order], w_bar, label="200 OK p95 (ms)")
    ax.set_title("Microservices 200 OK Latency by k6 Profile")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Latency (ms)")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig("results/k6_full_profiles.png", dpi=150)

    print("Saved results/k6_summary.csv and results/k6_full_profiles.png")
    for r in order:
        print(r)


if __name__ == "__main__":
    main()

import csv
import glob
import json
import os
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt


def parse_timestamp(ts: str) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def analyze_file(path: str) -> dict:
    name = os.path.basename(path).replace("full_", "").replace(".json", "")
    all_dur = []
    ok_dur = []
    service_dur = {
        "catalog_latency": [],
        "auth_latency": [],
        "order_latency": [],
        "ai_latency": [],
    }
    timestamps = []
    spike_points = []  # (elapsed_sec, duration_ms)

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("type") != "Point":
                continue

            metric = row.get("metric")
            data = row.get("data") or {}
            val = float(data.get("value", 0.0))
            ts = parse_timestamp(data.get("time", ""))
            if ts is not None:
                timestamps.append(ts)

            if metric == "http_req_duration":
                all_dur.append(val)
                tags = data.get("tags") or {}
                if tags.get("expected_response") == "true":
                    ok_dur.append(val)
                if name == "spike" and ts is not None:
                    spike_points.append((ts, val))
            elif metric in service_dur:
                service_dur[metric].append(val)

    duration_sec = (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else 0.0
    rps = (len(all_dur) / duration_sec) if duration_sec > 0 else 0.0

    arr_all = np.array(all_dur) if all_dur else np.array([0.0])
    arr_ok = np.array(ok_dur) if ok_dur else arr_all

    if name == "spike" and spike_points:
        t0 = min(p[0] for p in spike_points)
        spike_series = [((p[0] - t0), p[1]) for p in sorted(spike_points, key=lambda x: x[0])]
    else:
        spike_series = []

    row_out = {
        "profile": name,
        "duration_s": round(duration_sec, 1),
        "total_reqs": len(all_dur),
        "rps": round(rps, 2),
        "ok_2xx_reqs": len(ok_dur),
        "all_avg_ms": round(float(np.mean(arr_all)), 2),
        "all_med_ms": round(float(np.median(arr_all)), 2),
        "all_p95_ms": round(float(np.percentile(arr_all, 95)), 2),
        "all_p99_ms": round(float(np.percentile(arr_all, 99)), 2),
        "ok_avg_ms": round(float(np.mean(arr_ok)), 2),
        "ok_med_ms": round(float(np.median(arr_ok)), 2),
        "ok_p95_ms": round(float(np.percentile(arr_ok, 95)), 2),
        "ok_max_ms": round(float(np.max(arr_ok)), 2),
        "catalog_avg_ms": round(float(np.mean(service_dur["catalog_latency"])), 2) if service_dur["catalog_latency"] else 0.0,
        "auth_avg_ms": round(float(np.mean(service_dur["auth_latency"])), 2) if service_dur["auth_latency"] else 0.0,
        "order_avg_ms": round(float(np.mean(service_dur["order_latency"])), 2) if service_dur["order_latency"] else 0.0,
        "ai_avg_ms": round(float(np.mean(service_dur["ai_latency"])), 2) if service_dur["ai_latency"] else 0.0,
    }
    return {"summary": row_out, "spike_series": spike_series}


def main() -> None:
    files = sorted(glob.glob("results/full_*.json"))
    parsed = [analyze_file(p) for p in files]
    rows = [item["summary"] for item in parsed if item["summary"]["total_reqs"] > 0]
    if not rows:
        print("No data found in results/full_*.json")
        return

    order_map = {"smoke": 0, "load": 1, "spike": 2}
    rows.sort(key=lambda r: order_map.get(r["profile"], 99))

    os.makedirs("results", exist_ok=True)
    os.makedirs("docs/benchmarks", exist_ok=True)

    csv_path = "results/k6_detailed_summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Chart 2: RPS + Service avg latency
    labels = [r["profile"] for r in rows]
    x = np.arange(len(labels))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8))

    bars_rps = ax1.bar(labels, [r["rps"] for r in rows], width=0.5)
    ax1.set_title("Throughput by k6 Profile (RPS)")
    ax1.set_ylabel("Requests / sec")
    ax1.grid(axis="y", linestyle="--", alpha=0.4)
    for bar in bars_rps:
        h = bar.get_height()
        ax1.annotate(f"{h:.1f}", xy=(bar.get_x() + bar.get_width() / 2, h),
                     xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=9)

    w = 0.19
    ax2.bar(x - 1.5 * w, [r["catalog_avg_ms"] for r in rows], w, label="catalog")
    ax2.bar(x - 0.5 * w, [r["auth_avg_ms"] for r in rows], w, label="auth")
    ax2.bar(x + 0.5 * w, [r["order_avg_ms"] for r in rows], w, label="order")
    ax2.bar(x + 1.5 * w, [r["ai_avg_ms"] for r in rows], w, label="ai")
    ax2.set_title("Average Latency by Service Probe (ms)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("Avg Latency (ms)")
    ax2.legend()
    ax2.grid(axis="y", linestyle="--", alpha=0.4)

    plt.tight_layout()
    chart2_path = "results/k6_rps_and_services.png"
    plt.savefig(chart2_path, dpi=150)
    plt.close(fig)

    # Chart 3: Spike time-series (binned in 1s buckets)
    spike_item = next((p["spike_series"] for p in parsed if p["summary"]["profile"] == "spike"), [])
    chart3_path = None
    if spike_item:
        max_t = int(max(t for t, _ in spike_item)) + 1
        bins_x, bins_med, bins_p95 = [], [], []
        for sec in range(max_t):
            vals = [v for t, v in spike_item if sec <= t < sec + 1]
            if vals:
                arr_s = np.array(vals)
                bins_x.append(sec)
                bins_med.append(float(np.median(arr_s)))
                bins_p95.append(float(np.percentile(arr_s, 95)))

        fig, ax = plt.subplots(figsize=(10, 4.2))
        ax.plot(bins_x, bins_med, marker="o", markersize=3, label="1s bucket median (ms)")
        ax.plot(bins_x, bins_p95, marker="s", markersize=3, label="1s bucket p95 (ms)")
        ax.set_title("Spike Profile Latency Over Time (up to 60 VUs)")
        ax.set_xlabel("Elapsed time (s)")
        ax.set_ylabel("Latency (ms)")
        ax.legend()
        ax.grid(True, linestyle="--", alpha=0.4)
        plt.tight_layout()
        chart3_path = "results/k6_spike_timeseries.png"
        plt.savefig(chart3_path, dpi=150)
        plt.close(fig)

    # Markdown report
    md_lines = [
        "# Звіт навантажувального тестування мікросервісів ElectroStore (k6)",
        "",
        "## 1. Зведена таблиця профілів",
        "",
        "| Профіль | Тривалість (с) | Запитів | RPS | 200 OK | Усі avg (мс) | Усі p95 (мс) | 200 OK med (мс) | 200 OK p95 (мс) | 200 OK max (мс) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in rows:
        md_lines.append(
            f"| `{r['profile']}` | {r['duration_s']} | {r['total_reqs']} | {r['rps']} | {r['ok_2xx_reqs']} | "
            f"{r['all_avg_ms']} | {r['all_p95_ms']} | {r['ok_med_ms']} | {r['ok_p95_ms']} | {r['ok_max_ms']} |"
        )

    md_lines.extend([
        "",
        "## 2. Середня затримка по сервісах (`avg`, мс)",
        "",
        "| Профіль | `catalog` | `auth` | `order` | `ai` |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])
    for r in rows:
        md_lines.append(
            f"| `{r['profile']}` | {r['catalog_avg_ms']} | {r['auth_avg_ms']} | {r['order_avg_ms']} | {r['ai_avg_ms']} |"
        )

    md_lines.extend([
        "",
        "## 3. Згенеровані артефакти",
        "- `results/k6_summary.csv` та `results/k6_detailed_summary.csv`",
        "- `results/k6_full_profiles.png`",
        f"- `{chart2_path}`",
    ])
    if chart3_path:
        md_lines.append(f"- `{chart3_path}`")

    report_path = "docs/benchmarks/k6_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    print("Generated:")
    print(" -", csv_path)
    print(" -", chart2_path)
    if chart3_path:
        print(" -", chart3_path)
    print(" -", report_path)


if __name__ == "__main__":
    main()

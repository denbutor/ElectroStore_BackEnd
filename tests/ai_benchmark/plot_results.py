import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main() -> None:
    df = pd.read_csv("benchmark_evaluated.csv")
    models = ["lite", "flash", "pro"]
    model_labels = [
        "Lite\n(gemini-3.5-flash-lite)",
        "Flash\n(gemini-3.8-flash)",
        "Pro\n(gemini-3.1-pro-preview)",
    ]
    colors = {"lite": "#55A868", "flash": "#4C72B0", "pro": "#C44E52"}

    # 1. TTFT & E2E Latency
    ttft_means = [df[df["model_type"] == m]["ttft_sec"].mean() for m in models]
    ttft_stds = [df[df["model_type"] == m]["ttft_sec"].std() for m in models]
    e2e_means = [df[df["model_type"] == m]["e2e_sec"].mean() for m in models]
    e2e_stds = [df[df["model_type"] == m]["e2e_sec"].std() for m in models]

    fig, ax = plt.subplots(figsize=(8.5, 5), dpi=300)
    x = np.arange(len(models))
    w = 0.34
    r1 = ax.bar(x - w / 2, ttft_means, w, yerr=ttft_stds, capsize=4, label="Mean TTFT (s)", color="#4C72B0")
    r2 = ax.bar(x + w / 2, e2e_means, w, yerr=e2e_stds, capsize=4, label="Mean E2E Latency (s)", color="#DD8452")
    ax.set_ylabel("Latency (seconds)")
    ax.set_title("Response Latency (TTFT & E2E) Across Models (n=24/model)")
    ax.set_xticks(x)
    ax.set_xticklabels(model_labels)
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    for rect in list(r1) + list(r2):
        h = rect.get_height()
        ax.annotate(
            f"{h:.2f}s",
            xy=(rect.get_x() + rect.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    plt.tight_layout()
    plt.savefig("chart1_latency_ttft_e2e.png", dpi=300)
    plt.close()

    # 2. Speed vs Quality Trade-off
    fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
    for m in models:
        sub = df[df["model_type"] == m]
        xv = sub["e2e_sec"].mean()
        yv = sub["overall_score"].mean()
        ui_acc = sub["ui_lang_match"].mean() * 100
        ax.scatter(
            xv,
            yv,
            s=ui_acc * 4.5,
            color=colors[m],
            alpha=0.85,
            edgecolors="black",
            linewidth=1.2,
            label=f"{m.upper()} (UI Acc: {ui_acc:.1f}%)",
        )
        ax.annotate(
            f"  {m.upper()}\n  ({xv:.2f}s, {yv:.2f}/5)",
            (xv, yv),
            textcoords="offset points",
            xytext=(8, -6),
            fontsize=9,
            fontweight="bold",
        )
    ax.set_xlabel("Mean E2E Latency (seconds)")
    ax.set_ylabel("Mean Overall Quality Score (1–5)")
    ax.set_title("Speed vs. Quality Trade-off (Bubble = UI Lang Accuracy %)")
    ax.set_xlim(1.8, 3.0)
    ax.set_ylim(4.4, 5.1)
    ax.legend(loc="lower right")
    ax.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig("chart2_tradeoff_speed_quality.png", dpi=300)
    plt.close()

    # 3. Quality by Category
    cats = [
        "catalog_lookup",
        "compatibility",
        "external_temporal",
        "out_of_catalog",
        "multilingual_ui",
        "noisy_typos",
    ]
    cat_labels = [
        "Catalog\nLookup",
        "Hardware\nCompat.",
        "External /\nTemporal",
        "Out of\nCatalog",
        "Multilingual\nUI Tag",
        "Noisy /\nTypos",
    ]
    fig, ax = plt.subplots(figsize=(9.5, 5), dpi=300)
    x = np.arange(len(cats))
    bw = 0.25
    for idx, m in enumerate(models):
        vals = [df[(df["model_type"] == m) & (df["category"] == c)]["overall_score"].mean() for c in cats]
        ax.bar(x + (idx - 1) * bw, vals, bw, label=m.upper(), color=colors[m])
    ax.set_ylabel("Mean Quality Score (1–5)")
    ax.set_title("Quality Score by Query Category Across Models")
    ax.set_xticks(x)
    ax.set_xticklabels(cat_labels)
    ax.set_ylim(0, 5.6)
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig("chart3_quality_by_category.png", dpi=300)
    plt.close()

    # 4. Radar Chart
    radar_axes = [
        "Catalog Accuracy\n(w/ Context)",
        "Zero-Context\nStore Factuality",
        "Technical &\nCompat. Depth",
        "Response Speed\n(Low Latency)",
        "UI State\nOrchestration",
    ]
    n_axes = len(radar_axes)
    angles = np.linspace(0, 2 * np.pi, n_axes, endpoint=False).tolist()
    angles += angles[:1]

    series = {
        "ElectroStore Flash (RAG+UI)": [96.7, 92.0, 95.0, 86.0, 70.8],
        "ElectroStore Pro (RAG+UI)": [100.0, 96.0, 100.0, 78.0, 62.5],
        "External LLMs (Zero-Context)": [93.0, 15.0, 92.0, 75.0, 0.0],
    }

    fig, ax = plt.subplots(figsize=(7.5, 6), dpi=300, subplot_kw=dict(polar=True))
    for label, vals in series.items():
        pv = vals + vals[:1]
        ax.plot(angles, pv, linewidth=2, label=label)
        ax.fill(angles, pv, alpha=0.12)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(radar_axes, fontsize=8.5)
    ax.set_ylim(0, 105)
    ax.set_title("Multi-Criteria Comparison: ElectroStore AI vs. External Assistants", pad=22)
    ax.legend(loc="upper left", bbox_to_anchor=(1.08, 1.05), fontsize=8.5)
    plt.savefig("chart4_radar_comparison.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("Saved all 4 charts (300 DPI).")


if __name__ == "__main__":
    main()
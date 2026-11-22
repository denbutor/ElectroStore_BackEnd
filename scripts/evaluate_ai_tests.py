import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

TIMING_RE = re.compile(
    r"\[AI Chat Timing\]\s+requested=(?P<req>\S+)\s+model=(?P<model>\S+)\s+"
    r"rag=(?P<rag>[0-9.]+)s\s+ttfb=(?P<ttfb>[0-9.]+)s"
    r"(?:\s+images=(?P<images>\d+)\s+items=(?P<items>\d+))?"
)

WEIGHTS = {
    "vision_acc": 0.25,
    "hw_compat": 0.30,
    "rag_faith": 0.30,
    "structure": 0.15,
}

PALETTE = {
    "Lite": "#1f77b4",
    "Flash": "#d62728",
    "Pro": "#2ca02c",
}

DEFAULT_TEST_CASES = []


def load_or_init_test_cases(json_path: Path) -> list[dict]:
    """Завантажує test_cases.json або створює порожній файл, якщо його ще немає."""
    if not json_path.exists():
        json_path.write_text(
            json.dumps(DEFAULT_TEST_CASES, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return list(DEFAULT_TEST_CASES)
    return json.loads(json_path.read_text(encoding="utf-8"))


def parse_timing_log(log_path: Path) -> list[dict]:
    """Парсить рядки [AI Chat Timing] з файлу логів, якщо він існує."""
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = TIMING_RE.search(line)
        if m:
            records.append(
                {
                    "requested": m.group("req").lower(),
                    "model": m.group("model"),
                    "rag_sec": float(m.group("rag")),
                    "ttfb_sec": float(m.group("ttfb")),
                }
            )
    return records


def audit_response_text(row: dict) -> list[str]:
    flags = []
    txt = (row.get("response_text") or "").strip()
    low = txt.lower()

    if txt and txt[-1].isalnum() and not low.endswith(("gb", "tb", "hz", "w", "mm", "pcs", "шт")):
        flags.append("POSSIBLE_STREAM_TRUNCATION")

    if ("монітор" in str(row.get("title", "")).lower() or "монітор" in low) and (
        "немає в наявності моніторів" in low or "немає моніторів" in low
    ):
        flags.append("FALSE_NEGATIVE_CATALOG_MONITORS")

    if ("варіант" in low or "наявност" in low) and "$" not in txt:
        flags.append("MISSING_USD_PRICES")

    return flags


def build_latex_summary_table(model_means: pd.DataFrame) -> str:
    lines = [
        "\\begin{table}[h!]",
        "\\centering",
        "\\caption{Порівняння моделей ШІ-асистента за інтегральними критеріями якості та затримкою}",
        "\\begin{tabular}{lcccccc}",
        "\\hline",
        "Модель & Vision & HW Compat & RAG Faith & Structure & Бал $Q$ & TTFB (с) \\\\",
        "\\hline",
    ]
    for model_name, r in model_means.iterrows():
        lines.append(
            f"{model_name} & {r['vision_acc']:.2f} & {r['hw_compat']:.2f} & "
            f"{r['rag_faith']:.2f} & {r['structure']:.2f} & "
            f"\\textbf{{{r['weighted_score']:.2f}}} & {r['ttfb_sec']:.2f} \\\\"
        )
    lines.extend(["\\hline", "\\end{tabular}", "\\end{table}"])
    return "\n".join(lines)


def save_radar_chart(model_means: pd.DataFrame, out_path: Path) -> None:
    categories = ["Візуальний\nаналіз", "Сумісність\nзаліза", "Чесність\nRAG", "Структура\nвідповіді"]
    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    for m in model_means.index:
        r = model_means.loc[m]
        vals = [r["vision_acc"], r["hw_compat"], r["rag_faith"], r["structure"]]
        vals += vals[:1]
        ax.plot(
            angles,
            vals,
            linewidth=2.2,
            label=f"{m} (Q={r['weighted_score']})",
            color=PALETTE.get(m, "#7f7f7f"),
        )
        ax.fill(angles, vals, alpha=0.12, color=PALETTE.get(m, "#7f7f7f"))

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=10, fontweight="bold")
    ax.set_ylim(0, 5.2)
    plt.title("Профіль якості моделей (0–5 балів)", size=12, fontweight="bold", pad=18)
    plt.legend(loc="upper right", bbox_to_anchor=(1.28, 1.1))
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()


def save_heatmap_chart(df: pd.DataFrame, out_path: Path) -> None:
    heat_df = df.set_index(["model", "test_id"])[
        ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score"]
    ]
    fig, ax = plt.subplots(figsize=(8, max(4.5, 0.45 * len(heat_df) + 1.5)))
    im = ax.imshow(heat_df.values, aspect="auto", cmap="YlGn", vmin=1.0, vmax=5.0)
    ax.set_xticks(np.arange(len(heat_df.columns)))
    ax.set_xticklabels(["Vision", "HW Compat", "RAG Faith", "Structure", "Score Q"], fontweight="bold")
    ax.set_yticks(np.arange(len(heat_df.index)))
    ax.set_yticklabels([f"{m} | {t}" for m, t in heat_df.index])

    for i in range(heat_df.shape[0]):
        for j in range(heat_df.shape[1]):
            ax.text(j, i, f"{heat_df.values[i, j]:.1f}", ha="center", va="center", color="black", fontsize=9)

    plt.colorbar(im, ax=ax, label="Оцінка (1.0–5.0)")
    plt.title("Деталізована матриця оцінок по тестах", size=12, fontweight="bold")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()


def save_quality_vs_latency_chart(df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 5))
    for m in df["model"].unique():
        sub = df[df["model"] == m]
        ax.scatter(
            sub["ttfb_sec"],
            sub["weighted_score"],
            s=90,
            label=f"{m} (mean TTFB={sub['ttfb_sec'].mean():.2f}s, Q={sub['weighted_score'].mean():.2f})",
            color=PALETTE.get(m, "#7f7f7f"),
            alpha=0.85,
        )
    ax.set_xlabel("Час до першого токена TTFB (с)", fontweight="bold")
    ax.set_ylabel("Інтегральний бал якості Q (0–5)", fontweight="bold")
    ax.set_ylim(3.0, 5.2)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title("Компроміс якості та швидкодії моделей", size=12, fontweight="bold")
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()


def main() -> None:
    out_dir = Path("eval_results")
    out_dir.mkdir(exist_ok=True)

    cases_file = out_dir / "test_cases.json"
    log_file = out_dir / "ai_service.log"
    neg_file = out_dir / "negative_results.json"

    test_cases = load_or_init_test_cases(cases_file)
    if not test_cases:
        print(f"Файл {cases_file.resolve()} порожній. Додайте тести або запустіть run_automated_suite.py.")
        return

    parsed_logs = parse_timing_log(log_file)

    rows = []
    for idx, item in enumerate(test_cases):
        enriched = dict(item)
        if idx < len(parsed_logs):
            enriched["rag_sec"] = parsed_logs[idx]["rag_sec"]
            enriched["ttfb_sec"] = parsed_logs[idx]["ttfb_sec"]

        flags = audit_response_text(enriched)
        enriched["audit_flags"] = ", ".join(flags) if flags else "OK"
        rows.append(enriched)

    df = pd.DataFrame(rows)
    df["weighted_score"] = (
        df["vision_acc"] * WEIGHTS["vision_acc"]
        + df["hw_compat"] * WEIGHTS["hw_compat"]
        + df["rag_faith"] * WEIGHTS["rag_faith"]
        + df["structure"] * WEIGHTS["structure"]
    ).round(2)

    df.drop(columns=["response_text"], errors="ignore").to_csv(
        out_dir / "per_test_evaluation.csv", index=False
    )

    model_means = (
        df.groupby("model")[
            ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score", "ttfb_sec", "rag_sec"]
        ]
        .mean()
        .round(2)
    )
    latex_table = build_latex_summary_table(model_means)

    md_report = [
        "# Результати оцінювання мультимодального ШІ-асистента ElectroStore\n",
        "## 1. Середні показники моделей\n",
        model_means.to_markdown(),
        "\n## 2. Деталізований аудит тестів\n",
        df[
            [
                "model", "test_id", "title", "vision_acc", "hw_compat",
                "rag_faith", "structure", "weighted_score", "ttfb_sec", "audit_flags",
            ]
        ].to_markdown(index=False),
        "\n## 3. LaTeX-таблиця для магістерської роботи\n",
        "```latex\n" + latex_table + "\n```",
    ]

    if neg_file.exists():
        neg_df = pd.DataFrame(json.loads(neg_file.read_text(encoding="utf-8")))
        if not neg_df.empty:
            md_report.append("\n## 4. Негативні тести валідації та безпеки API (окремий контур)\n")
            md_report.append(neg_df.to_markdown(index=False))

    (out_dir / "evaluation_report.md").write_text("\n".join(md_report), encoding="utf-8")

    save_radar_chart(model_means, out_dir / "model_comparison_radar.png")
    save_heatmap_chart(df, out_dir / "tests_scores_heatmap.png")
    save_quality_vs_latency_chart(df, out_dir / "quality_vs_latency.png")

    print(f"Оброблено тестів: {len(df)}. Результати оновлено у: {out_dir.resolve()}")
    print(f"Файл тестів для доповнення: {cases_file.resolve()}")


if __name__ == "__main__":
    main()
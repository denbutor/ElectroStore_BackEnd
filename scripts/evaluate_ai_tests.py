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

# import json
# import re
# from pathlib import Path
# import numpy as np
# import pandas as pd
# import matplotlib.pyplot as plt

# TIMING_RE = re.compile(
#     r"\[AI Chat Timing\]\s+requested=(?P<req>\S+)\s+model=(?P<model>\S+)\s+"
#     r"rag=(?P<rag>[0-9.]+)s\s+ttfb=(?P<ttfb>[0-9.]+)s"
#     r"(?:\s+images=(?P<images>\d+)\s+items=(?P<items>\d+))?"
# )

# DEFAULT_TEST_CASES = []


# def load_or_init_test_cases(json_path: Path) -> list[dict]:
#     """Завантажує test_cases.json або створює його з початкових тестів."""
#     if not json_path.exists():
#         json_path.write_text(
#             json.dumps(DEFAULT_TEST_CASES, ensure_ascii=False, indent=2),
#             encoding="utf-8",
#         )
#         return list(DEFAULT_TEST_CASES)
#     return json.loads(json_path.read_text(encoding="utf-8"))


# def parse_timing_log(log_path: Path) -> list[dict]:
#     """Парсить рядки [AI Chat Timing] з файлу логів, якщо він існує."""
#     if not log_path.exists():
#         return []
#     records = []
#     for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
#         m = TIMING_RE.search(line)
#         if m:
#             records.append(
#                 {
#                     "requested": m.group("req").lower(),
#                     "model": m.group("model"),
#                     "rag_sec": float(m.group("rag")),
#                     "ttfb_sec": float(m.group("ttfb")),
#                 }
#             )
#     return records


# def audit_response_text(row: dict) -> list[str]:
#     flags = []
#     txt = (row.get("response_text") or "").strip()
#     low = txt.lower()

#     if txt and txt[-1].isalnum() and not low.endswith(("gb", "tb", "hz", "w", "mm", "pcs", "шт")):
#         flags.append("POSSIBLE_STREAM_TRUNCATION")

#     if ("монітор" in row["title"].lower() or "монітор" in low) and (
#         "немає в наявності моніторів" in low or "немає моніторів" in low
#     ):
#         flags.append("FALSE_NEGATIVE_CATALOG_MONITORS")

#     if ("варіант" in low or "наявност" in low) and "$" not in txt:
#         flags.append("MISSING_USD_PRICES")

#     return flags


# def build_latex_summary_table(model_means: pd.DataFrame) -> str:
#     lines = [
#         "\\begin{table}[h!]",
#         "\\centering",
#         "\\caption{Порівняння моделей ШІ-асистента за інтегральними критеріями якості та затримкою}",
#         "\\begin{tabular}{lcccccc}",
#         "\\hline",
#         "Модель & Vision & HW Compat & RAG Faith & Structure & Бал $Q$ & TTFB (с) \\\\",
#         "\\hline",
#     ]
#     for model_name, r in model_means.iterrows():
#         lines.append(
#             f"{model_name} & {r['vision_acc']:.2f} & {r['hw_compat']:.2f} & "
#             f"{r['rag_faith']:.2f} & {r['structure']:.2f} & "
#             f"\\textbf{{{r['weighted_score']:.2f}}} & {r['ttfb_sec']:.2f} \\\\"
#         )
#     lines.extend(["\\hline", "\\end{tabular}", "\\end{table}"])
#     return "\n".join(lines)


# def main():
#     out_dir = Path("eval_results")
#     out_dir.mkdir(exist_ok=True)

#     cases_file = out_dir / "test_cases.json"
#     log_file = out_dir / "ai_service.log"

#     test_cases = load_or_init_test_cases(cases_file)
#     parsed_logs = parse_timing_log(log_file)

#     rows = []
#     for idx, item in enumerate(test_cases):
#         enriched = dict(item)
#         if idx < len(parsed_logs):
#             enriched["rag_sec"] = parsed_logs[idx]["rag_sec"]
#             enriched["ttfb_sec"] = parsed_logs[idx]["ttfb_sec"]

#         flags = audit_response_text(enriched)
#         enriched["audit_flags"] = ", ".join(flags) if flags else "OK"
#         rows.append(enriched)

#     df = pd.DataFrame(rows)

#     weights = {
#         "vision_acc": 0.25,
#         "hw_compat": 0.30,
#         "rag_faith": 0.30,
#         "structure": 0.15,
#     }
#     df["weighted_score"] = (
#         df["vision_acc"] * weights["vision_acc"]
#         + df["hw_compat"] * weights["hw_compat"]
#         + df["rag_faith"] * weights["rag_faith"]
#         + df["structure"] * weights["structure"]
#     ).round(2)

#     df.drop(columns=["response_text"], errors="ignore").to_csv(
#         out_dir / "per_test_evaluation.csv", index=False
#     )

#     model_means = (
#         df.groupby("model")[
#             ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score", "ttfb_sec", "rag_sec"]
#         ]
#         .mean()
#         .round(2)
#     )
#     latex_table = build_latex_summary_table(model_means)

#     md_report = [
#         "# Результати оцінювання мультимодального ШІ-асистента ElectroStore\n",
#         "## 1. Середні показники моделей\n",
#         model_means.to_markdown(),
#         "\n## 2. Деталізований аудит тестів\n",
#         df[
#             [
#                 "model", "test_id", "title", "vision_acc", "hw_compat",
#                 "rag_faith", "structure", "weighted_score", "ttfb_sec", "audit_flags",
#             ]
#         ].to_markdown(index=False),
#         "\n## 3. LaTeX-таблиця для магістерської роботи\n",
#         "```latex\n" + latex_table + "\n```",
#     ]
#     (out_dir / "evaluation_report.md").write_text("\n".join(md_report), encoding="utf-8")

#     palette = {"Lite": "#1f77b4", "Flash": "#d62728", "Pro": "#2ca02c"}

#     # 1. Radar Chart
#     categories = ["Візуальний\nаналіз", "Сумісність\nзаліза", "Чесність\nRAG", "Структура\nвідповіді"]
#     angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
#     angles += angles[:1]

#     fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
#     for m in model_means.index:
#         r = model_means.loc[m]
#         vals = [r["vision_acc"], r["hw_compat"], r["rag_faith"], r["structure"]]
#         vals += vals[:1]
#         ax.plot(
#             angles,
#             vals,
#             linewidth=2.2,
#             label=f"{m} (Q={r['weighted_score']})",
#             color=palette.get(m, "#7f7f7f"),
#         )
#         ax.fill(angles, vals, alpha=0.12, color=palette.get(m, "#7f7f7f"))

#     ax.set_theta_offset(np.pi / 2)
#     ax.set_theta_direction(-1)
#     ax.set_xticks(angles[:-1])
#     ax.set_xticklabels(categories, fontsize=10, fontweight="bold")
#     ax.set_ylim(0, 5.2)
#     plt.title("Профіль якості моделей (0–5 балів)", size=12, fontweight="bold", pad=18)
#     plt.legend(loc="upper right", bbox_to_anchor=(1.28, 1.1))
#     plt.tight_layout()
#     plt.savefig(out_dir / "model_comparison_radar.png", dpi=300)
#     plt.close()

#     # 2. Heatmap по всіх тестах
#     heat_df = df.set_index(["model", "test_id"])[
#         ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score"]
#     ]
#     fig, ax = plt.subplots(figsize=(8, max(4.5, 0.45 * len(heat_df) + 1.5)))
#     im = ax.imshow(heat_df.values, aspect="auto", cmap="YlGn", vmin=1.0, vmax=5.0)
#     ax.set_xticks(np.arange(len(heat_df.columns)))
#     ax.set_xticklabels(["Vision", "HW Compat", "RAG Faith", "Structure", "Score Q"], fontweight="bold")
#     ax.set_yticks(np.arange(len(heat_df.index)))
#     ax.set_yticklabels([f"{m} | {t}" for m, t in heat_df.index])

#     for i in range(heat_df.shape[0]):
#         for j in range(heat_df.shape[1]):
#             ax.text(j, i, f"{heat_df.values[i, j]:.1f}", ha="center", va="center", color="black", fontsize=9)

#     plt.colorbar(im, ax=ax, label="Оцінка (1.0–5.0)")
#     plt.title("Деталізована матриця оцінок по тестах", size=12, fontweight="bold")
#     plt.tight_layout()
#     plt.savefig(out_dir / "tests_scores_heatmap.png", dpi=300)
#     plt.close()

#     # 3. Quality vs TTFB
#     fig, ax = plt.subplots(figsize=(7, 5))
#     for m in df["model"].unique():
#         sub = df[df["model"] == m]
#         ax.scatter(
#             sub["ttfb_sec"],
#             sub["weighted_score"],
#             s=90,
#             label=f"{m} (mean TTFB={sub['ttfb_sec'].mean():.2f}s, Q={sub['weighted_score'].mean():.2f})",
#             color=palette.get(m, "#7f7f7f"),
#             alpha=0.85,
#         )
#     ax.set_xlabel("Час до першого токена TTFB (с)", fontweight="bold")
#     ax.set_ylabel("Інтегральний бал якості Q (0–5)", fontweight="bold")
#     ax.set_ylim(3.0, 5.2)
#     ax.grid(True, linestyle="--", alpha=0.4)
#     ax.set_title("Компроміс якості та швидкодії моделей", size=12, fontweight="bold")
#     ax.legend()
#     plt.tight_layout()
#     plt.savefig(out_dir / "quality_vs_latency.png", dpi=300)
#     plt.close()

#     print(f"Оброблено тестів: {len(df)}. Результати оновлено у: {out_dir.resolve()}")
#     print(f"Файл тестів для доповнення: {cases_file.resolve()}")


# if __name__ == "__main__":
#     main()

# # import json
# # import re
# # from pathlib import Path
# # import numpy as np
# # import pandas as pd
# # import matplotlib.pyplot as plt

# # TIMING_RE = re.compile(
# #     r"\[AI Chat Timing\]\s+requested=(?P<req>\S+)\s+model=(?P<model>\S+)\s+"
# #     r"rag=(?P<rag>[0-9.]+)s\s+ttfb=(?P<ttfb>[0-9.]+)s"
# #     r"(?:\s+images=(?P<images>\d+)\s+items=(?P<items>\d+))?"
# # )

# # DEFAULT_TEST_CASES = [
# #     {
# #         "model": "Lite",
# #         "test_id": "L1",
# #         "title": "4 фото (GPU + PSU + B650 + CPU)",
# #         "vision_acc": 4.5,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 0.85,
# #         "rag_sec": 0.45,
# #         "response_text": (
# #             "Фото 1: MSI Gaming GTX 10-ї чи RTX 20-ї серії. Фото 2: білий модульний БЖ. "
# #             "Фото 3: MSI MAG B650 Tomahawk WiFi ($209.0, в наявності: 17 шт.). Фото 4: CPU AM5. "
# #             "Варіанти збірки: 1. Максимум надійності й продуктивності, 2. Оптимальний баланс, 3. Бюджетний варіант."
# #         ),
# #     },
# #     {
# #         "model": "Lite",
# #         "test_id": "L2",
# #         "title": "2 фото (розмита Z890 + RTX 3060)",
# #         "vision_acc": 3.0,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 0.78,
# #         "rag_sec": 0.38,
# #         "response_text": (
# #             "Фото 1: Gigabyte Z890 AORUS Elite WiFi7 ($289.0, 10 шт., LGA1851). "
# #             "Фото 2: ASUS Dual GeForce RTX — модель не представлена в каталозі, альтернатива RTX 4070 Super / Ti Super."
# #         ),
# #     },
# #     {
# #         "model": "Lite",
# #         "test_id": "L3",
# #         "title": "Розмитий фрагмент Pixel 9",
# #         "vision_acc": 4.0,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 0.72,
# #         "rag_sec": 0.31,
# #         "response_text": (
# #             "Google Pixel (модель 8 або 9 Pro). В наявності Google Pixel 9 Pro 256GB ($999.0, 14 шт.). "
# #             "Порівняння базової моделі та Pixel 9 Pro."
# #         ),
# #     },
# #     {
# #         "model": "Lite",
# #         "test_id": "L4",
# #         "title": "EN: сумісність 750W PSU та DDR5 RAM",
# #         "vision_acc": 5.0,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 0.65,
# #         "rag_sec": 0.24,
# #         "response_text": (
# #             "be quiet! Pure Power 12 M 750W ($114.0, ATX 3.1, 12V-2x6) та Kingston Fury Beast 32GB DDR5 6000MHz CL30 ($119.0)."
# #         ),
# #     },
# #     {
# #         "model": "Flash",
# #         "test_id": "F1",
# #         "title": "2 фото (RTX 5070 + корпус) під 1440p",
# #         "vision_acc": 5.0,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 3.5,
# #         "ttfb_sec": 1.25,
# #         "rag_sec": 0.52,
# #         "response_text": (
# #             "ASUS Prime GeForce RTX 5070 12GB та корпус Mid Tower ARGB. "
# #             "RTX 5070 відсутня в каталозі, альтернативи: RTX 4070 Super 12GB та RTX 4070 Ti Super 16GB. "
# #             "Корпус з фотографії ви можете залишити свій власний, або ж допов"
# #         ),
# #     },
# #     {
# #         "model": "Flash",
# #         "test_id": "F2",
# #         "title": "TDP/MTP і охолодження",
# #         "vision_acc": 5.0,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 1.05,
# #         "rag_sec": 0.29,
# #         "response_text": (
# #             "Базовий кулер не впорається з піковим споживанням (Core Ultra 9 285K ~250W, Ryzen 9 9950X ~200W+). "
# #             "360-мм СЖО немає в каталозі. В наявності: ID-Cooling SE-224-XTS ($25.0), "
# #             "Thermalright Phantom Spirit 120 SE ($39.0), Noctua NH-D15 G2 ($149.0)."
# #         ),
# #     },
# #     {
# #         "model": "Flash",
# #         "test_id": "F3",
# #         "title": "Скріншот IDE (бекенд, Docker, БД)",
# #         "vision_acc": 5.0,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 1.18,
# #         "rag_sec": 0.44,
# #         "response_text": (
# #             "Python/SQLAlchemy, Docker, PostgreSQL. MacBook із 32 ГБ RAM немає в каталозі; "
# #             "в наявності MacBook Air 15 M3 16GB ($1299.0), Minisforum UM790 Pro 32GB ($629.0), "
# #             "Ryzen 9 9900X + G.Skill 64GB DDR5."
# #         ),
# #     },
# #     {
# #         "model": "Flash",
# #         "test_id": "F4",
# #         "title": "2 фото моніторів (BenQ + AOC)",
# #         "vision_acc": 4.5,
# #         "hw_compat": 5.0,
# #         "rag_faith": 1.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 1.12,
# #         "rag_sec": 0.49,
# #         "response_text": (
# #             "Перше фото: BenQ. Друге фото: AOC. "
# #             "У нас немає в наявності моніторів взагалі. Оскільки в ElectroStore немає моніторів у наявності..."
# #         ),
# #     },
# #     {
# #         "model": "Pro",
# #         "test_id": "P1",
# #         "title": "4 фото комплектуючих + 3 варіанти збірки",
# #         "vision_acc": 4.5,
# #         "hw_compat": 4.5,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 2.40,
# #         "rag_sec": 0.55,
# #         "response_text": (
# #             "1. Максимум надійності й продуктивності: Ryzen 9 9950X ($649.0), ASUS ROG Strix X870E-E ($499.0). "
# #             "2. Оптимальний баланс: Ryzen 7 9800X3D ($479.0), MSI MAG B650 Tomahawk WiFi ($209.0). "
# #             "3. Бюджетний варіант: Ryzen 5 9600X ($279.0), ASUS TUF Gaming B650-Plus WiFi ($219.0). "
# #             "Вузьке місце: зовнішній USB HDD."
# #         ),
# #     },
# #     {
# #         "model": "Pro",
# #         "test_id": "P2",
# #         "title": "Фото плати AM5 + жорсткий бюджет і ризики",
# #         "vision_acc": 5.0,
# #         "hw_compat": 5.0,
# #         "rag_faith": 5.0,
# #         "structure": 5.0,
# #         "ttfb_sec": 2.15,
# #         "rag_sec": 0.41,
# #         "response_text": (
# #             "Варіант 1: Максимум надійності й продуктивності (Ryzen 9 9950X, Noctua NH-D15 G2). "
# #             "Варіант 2: Оптимальний баланс (Ryzen 7 9800X3D, Thermalright Phantom Spirit 120 SE). "
# #             "Варіант 3: Бюджетний варіант (Ryzen 5 9600X, ID-Cooling SE-224-XTS). Ризики та відмінності."
# #         ),
# #     },
# # ]


# # def load_or_init_test_cases(json_path: Path) -> list[dict]:
# #     """Завантажує test_cases.json або створює його з початкових тестів."""
# #     if not json_path.exists():
# #         json_path.write_text(
# #             json.dumps(DEFAULT_TEST_CASES, ensure_ascii=False, indent=2),
# #             encoding="utf-8",
# #         )
# #         return list(DEFAULT_TEST_CASES)
# #     return json.loads(json_path.read_text(encoding="utf-8"))


# # def parse_timing_log(log_path: Path) -> list[dict]:
# #     """Парсить рядки [AI Chat Timing] з файлу логів, якщо він існує."""
# #     if not log_path.exists():
# #         return []
# #     records = []
# #     for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
# #         m = TIMING_RE.search(line)
# #         if m:
# #             records.append(
# #                 {
# #                     "requested": m.group("req").lower(),
# #                     "model": m.group("model"),
# #                     "rag_sec": float(m.group("rag")),
# #                     "ttfb_sec": float(m.group("ttfb")),
# #                 }
# #             )
# #     return records


# # def audit_response_text(row: dict) -> list[str]:
# #     flags = []
# #     txt = (row.get("response_text") or "").strip()
# #     low = txt.lower()

# #     if txt and txt[-1].isalnum() and not low.endswith(("gb", "tb", "hz", "w", "mm", "pcs", "шт")):
# #         flags.append("POSSIBLE_STREAM_TRUNCATION")

# #     if ("монітор" in row["title"].lower() or "монітор" in low) and (
# #         "немає в наявності моніторів" in low or "немає моніторів" in low
# #     ):
# #         flags.append("FALSE_NEGATIVE_CATALOG_MONITORS")

# #     if ("варіант" in low or "наявност" in low) and "$" not in txt:
# #         flags.append("MISSING_USD_PRICES")

# #     return flags


# # def build_latex_summary_table(model_means: pd.DataFrame) -> str:
# #     lines = [
# #         "\\begin{table}[h!]",
# #         "\\centering",
# #         "\\caption{Порівняння моделей ШІ-асистента за інтегральними критеріями якості та затримкою}",
# #         "\\begin{tabular}{lcccccc}",
# #         "\\hline",
# #         "Модель & Vision & HW Compat & RAG Faith & Structure & Бал $Q$ & TTFB (с) \\\\",
# #         "\\hline",
# #     ]
# #     for model_name, r in model_means.iterrows():
# #         lines.append(
# #             f"{model_name} & {r['vision_acc']:.2f} & {r['hw_compat']:.2f} & "
# #             f"{r['rag_faith']:.2f} & {r['structure']:.2f} & "
# #             f"\\textbf{{{r['weighted_score']:.2f}}} & {r['ttfb_sec']:.2f} \\\\"
# #         )
# #     lines.extend(["\\hline", "\\end{tabular}", "\\end{table}"])
# #     return "\n".join(lines)


# # def main():
# #     out_dir = Path("eval_results")
# #     out_dir.mkdir(exist_ok=True)

# #     cases_file = out_dir / "test_cases.json"
# #     log_file = out_dir / "ai_service.log"

# #     test_cases = load_or_init_test_cases(cases_file)
# #     parsed_logs = parse_timing_log(log_file)

# #     rows = []
# #     for idx, item in enumerate(test_cases):
# #         enriched = dict(item)
# #         if idx < len(parsed_logs):
# #             enriched["rag_sec"] = parsed_logs[idx]["rag_sec"]
# #             enriched["ttfb_sec"] = parsed_logs[idx]["ttfb_sec"]

# #         flags = audit_response_text(enriched)
# #         enriched["audit_flags"] = ", ".join(flags) if flags else "OK"
# #         rows.append(enriched)

# #     df = pd.DataFrame(rows)

# #     weights = {
# #         "vision_acc": 0.25,
# #         "hw_compat": 0.30,
# #         "rag_faith": 0.30,
# #         "structure": 0.15,
# #     }
# #     df["weighted_score"] = (
# #         df["vision_acc"] * weights["vision_acc"]
# #         + df["hw_compat"] * weights["hw_compat"]
# #         + df["rag_faith"] * weights["rag_faith"]
# #         + df["structure"] * weights["structure"]
# #     ).round(2)

# #     df.drop(columns=["response_text"], errors="ignore").to_csv(
# #         out_dir / "per_test_evaluation.csv", index=False
# #     )

# #     model_means = (
# #         df.groupby("model")[
# #             ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score", "ttfb_sec", "rag_sec"]
# #         ]
# #         .mean()
# #         .round(2)
# #     )
# #     latex_table = build_latex_summary_table(model_means)

# #     md_report = [
# #         "# Результати оцінювання мультимодального ШІ-асистента ElectroStore\n",
# #         "## 1. Середні показники моделей\n",
# #         model_means.to_markdown(),
# #         "\n## 2. Деталізований аудит тестів\n",
# #         df[
# #             [
# #                 "model", "test_id", "title", "vision_acc", "hw_compat",
# #                 "rag_faith", "structure", "weighted_score", "ttfb_sec", "audit_flags",
# #             ]
# #         ].to_markdown(index=False),
# #         "\n## 3. LaTeX-таблиця для магістерської роботи\n",
# #         "```latex\n" + latex_table + "\n```",
# #     ]
# #     (out_dir / "evaluation_report.md").write_text("\n".join(md_report), encoding="utf-8")

# #     palette = {"Lite": "#1f77b4", "Flash": "#d62728", "Pro": "#2ca02c"}

# #     # 1. Radar Chart
# #     categories = ["Візуальний\nаналіз", "Сумісність\nзаліза", "Чесність\nRAG", "Структура\nвідповіді"]
# #     angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
# #     angles += angles[:1]

# #     fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
# #     for m in model_means.index:
# #         r = model_means.loc[m]
# #         vals = [r["vision_acc"], r["hw_compat"], r["rag_faith"], r["structure"]]
# #         vals += vals[:1]
# #         ax.plot(
# #             angles,
# #             vals,
# #             linewidth=2.2,
# #             label=f"{m} (Q={r['weighted_score']})",
# #             color=palette.get(m, "#7f7f7f"),
# #         )
# #         ax.fill(angles, vals, alpha=0.12, color=palette.get(m, "#7f7f7f"))

# #     ax.set_theta_offset(np.pi / 2)
# #     ax.set_theta_direction(-1)
# #     ax.set_xticks(angles[:-1])
# #     ax.set_xticklabels(categories, fontsize=10, fontweight="bold")
# #     ax.set_ylim(0, 5.2)
# #     plt.title("Профіль якості моделей (0–5 балів)", size=12, fontweight="bold", pad=18)
# #     plt.legend(loc="upper right", bbox_to_anchor=(1.28, 1.1))
# #     plt.tight_layout()
# #     plt.savefig(out_dir / "model_comparison_radar.png", dpi=300)
# #     plt.close()

# #     # 2. Heatmap по всіх тестах
# #     heat_df = df.set_index(["model", "test_id"])[
# #         ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score"]
# #     ]
# #     fig, ax = plt.subplots(figsize=(8, max(4.5, 0.45 * len(heat_df) + 1.5)))
# #     im = ax.imshow(heat_df.values, aspect="auto", cmap="YlGn", vmin=1.0, vmax=5.0)
# #     ax.set_xticks(np.arange(len(heat_df.columns)))
# #     ax.set_xticklabels(["Vision", "HW Compat", "RAG Faith", "Structure", "Score Q"], fontweight="bold")
# #     ax.set_yticks(np.arange(len(heat_df.index)))
# #     ax.set_yticklabels([f"{m} | {t}" for m, t in heat_df.index])

# #     for i in range(heat_df.shape[0]):
# #         for j in range(heat_df.shape[1]):
# #             ax.text(j, i, f"{heat_df.values[i, j]:.1f}", ha="center", va="center", color="black", fontsize=9)

# #     plt.colorbar(im, ax=ax, label="Оцінка (1.0–5.0)")
# #     plt.title("Деталізована матриця оцінок по тестах", size=12, fontweight="bold")
# #     plt.tight_layout()
# #     plt.savefig(out_dir / "tests_scores_heatmap.png", dpi=300)
# #     plt.close()

# #     # 3. Quality vs TTFB
# #     fig, ax = plt.subplots(figsize=(7, 5))
# #     for m in df["model"].unique():
# #         sub = df[df["model"] == m]
# #         ax.scatter(
# #             sub["ttfb_sec"],
# #             sub["weighted_score"],
# #             s=90,
# #             label=f"{m} (mean TTFB={sub['ttfb_sec'].mean():.2f}s, Q={sub['weighted_score'].mean():.2f})",
# #             color=palette.get(m, "#7f7f7f"),
# #             alpha=0.85,
# #         )
# #     ax.set_xlabel("Час до першого токена TTFB (с)", fontweight="bold")
# #     ax.set_ylabel("Інтегральний бал якості Q (0–5)", fontweight="bold")
# #     ax.set_ylim(3.0, 5.2)
# #     ax.grid(True, linestyle="--", alpha=0.4)
# #     ax.set_title("Компроміс якості та швидкодії моделей", size=12, fontweight="bold")
# #     ax.legend()
# #     plt.tight_layout()
# #     plt.savefig(out_dir / "quality_vs_latency.png", dpi=300)
# #     plt.close()

# #     print(f"Оброблено тестів: {len(df)}. Результати оновлено у: {out_dir.resolve()}")
# #     print(f"Файл тестів для доповнення: {cases_file.resolve()}")


# # if __name__ == "__main__":
# #     main()

# # # import re
# # # from pathlib import Path
# # # import numpy as np
# # # import pandas as pd
# # # import matplotlib.pyplot as plt

# # # # Приклад регулярного виразу для логів ai_service:
# # # # [AI Chat Timing] requested=flash model=gemini-2.5-flash rag=0.42s ttfb=1.15s images=2 items=18
# # # TIMING_RE = re.compile(
# # #     r"\[AI Chat Timing\]\s+requested=(?P<req>\S+)\s+model=(?P<model>\S+)\s+"
# # #     r"rag=(?P<rag>[0-9.]+)s\s+ttfb=(?P<ttfb>[0-9.]+)s"
# # #     r"(?:\s+images=(?P<images>\d+)\s+items=(?P<items>\d+))?"
# # # )

# # # TEST_CASES = [
# # #     # --- LITE ---
# # #     {
# # #         "model": "Lite",
# # #         "test_id": "L1",
# # #         "title": "4 фото (GPU + PSU + B650 + CPU)",
# # #         "vision_acc": 4.5,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 0.85,
# # #         "rag_sec": 0.45,
# # #         "response_text": (
# # #             "Фото 1: MSI Gaming GTX 10-ї чи RTX 20-ї серії. Фото 2: білий модульний БЖ. "
# # #             "Фото 3: MSI MAG B650 Tomahawk WiFi ($209.0, в наявності: 17 шт.). Фото 4: CPU AM5. "
# # #             "Варіанти збірки: 1. Максимум надійності й продуктивності, 2. Оптимальний баланс, 3. Бюджетний варіант."
# # #         ),
# # #     },
# # #     {
# # #         "model": "Lite",
# # #         "test_id": "L2",
# # #         "title": "2 фото (розмита Z890 + RTX 3060)",
# # #         "vision_acc": 3.0,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 0.78,
# # #         "rag_sec": 0.38,
# # #         "response_text": (
# # #             "Фото 1: Gigabyte Z890 AORUS Elite WiFi7 ($289.0, 10 шт., LGA1851). "
# # #             "Фото 2: ASUS Dual GeForce RTX — модель не представлена в каталозі, альтернатива RTX 4070 Super / Ti Super."
# # #         ),
# # #     },
# # #     {
# # #         "model": "Lite",
# # #         "test_id": "L3",
# # #         "title": "Розмитий фрагмент Pixel 9",
# # #         "vision_acc": 4.0,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 0.72,
# # #         "rag_sec": 0.31,
# # #         "response_text": (
# # #             "Google Pixel (модель 8 або 9 Pro). В наявності Google Pixel 9 Pro 256GB ($999.0, 14 шт.). "
# # #             "Порівняння базової моделі та Pixel 9 Pro."
# # #         ),
# # #     },
# # #     {
# # #         "model": "Lite",
# # #         "test_id": "L4",
# # #         "title": "EN: сумісність 750W PSU та DDR5 RAM",
# # #         "vision_acc": 5.0,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 0.65,
# # #         "rag_sec": 0.24,
# # #         "response_text": (
# # #             "be quiet! Pure Power 12 M 750W ($114.0, ATX 3.1, 12V-2x6) та Kingston Fury Beast 32GB DDR5 6000MHz CL30 ($119.0)."
# # #         ),
# # #     },
# # #     # --- FLASH ---
# # #     {
# # #         "model": "Flash",
# # #         "test_id": "F1",
# # #         "title": "2 фото (RTX 5070 + корпус) під 1440p",
# # #         "vision_acc": 5.0,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 3.5,
# # #         "ttfb_sec": 1.25,
# # #         "rag_sec": 0.52,
# # #         "response_text": (
# # #             "ASUS Prime GeForce RTX 5070 12GB та корпус Mid Tower ARGB. "
# # #             "RTX 5070 відсутня в каталозі, альтернативи: RTX 4070 Super 12GB та RTX 4070 Ti Super 16GB. "
# # #             "Корпус з фотографії ви можете залишити свій власний, або ж допов"
# # #         ),
# # #     },
# # #     {
# # #         "model": "Flash",
# # #         "test_id": "F2",
# # #         "title": "TDP/MTP і охолодження",
# # #         "vision_acc": 5.0,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 1.05,
# # #         "rag_sec": 0.29,
# # #         "response_text": (
# # #             "Базовий кулер не впорається з піковим споживанням (Core Ultra 9 285K ~250W, Ryzen 9 9950X ~200W+). "
# # #             "360-мм СЖО немає в каталозі. В наявності: ID-Cooling SE-224-XTS ($25.0), "
# # #             "Thermalright Phantom Spirit 120 SE ($39.0), Noctua NH-D15 G2 ($149.0)."
# # #         ),
# # #     },
# # #     {
# # #         "model": "Flash",
# # #         "test_id": "F3",
# # #         "title": "Скріншот IDE (бекенд, Docker, БД)",
# # #         "vision_acc": 5.0,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 1.18,
# # #         "rag_sec": 0.44,
# # #         "response_text": (
# # #             "Python/SQLAlchemy, Docker, PostgreSQL. MacBook із 32 ГБ RAM немає в каталозі; "
# # #             "в наявності MacBook Air 15 M3 16GB ($1299.0), Minisforum UM790 Pro 32GB ($629.0), "
# # #             "Ryzen 9 9900X + G.Skill 64GB DDR5."
# # #         ),
# # #     },
# # #     {
# # #         "model": "Flash",
# # #         "test_id": "F4",
# # #         "title": "2 фото моніторів (BenQ + AOC)",
# # #         "vision_acc": 4.5,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 1.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 1.12,
# # #         "rag_sec": 0.49,
# # #         "response_text": (
# # #             "Перше фото: BenQ. Друге фото: AOC. "
# # #             "У нас немає в наявності моніторів взагалі. Оскільки в ElectroStore немає моніторів у наявності..."
# # #         ),
# # #     },
# # #     # --- PRO ---
# # #     {
# # #         "model": "Pro",
# # #         "test_id": "P1",
# # #         "title": "4 фото комплектуючих + 3 варіанти збірки",
# # #         "vision_acc": 4.5,
# # #         "hw_compat": 4.5,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 2.40,
# # #         "rag_sec": 0.55,
# # #         "response_text": (
# # #             "1. Максимум надійності й продуктивності: Ryzen 9 9950X ($649.0), ASUS ROG Strix X870E-E ($499.0). "
# # #             "2. Оптимальний баланс: Ryzen 7 9800X3D ($479.0), MSI MAG B650 Tomahawk WiFi ($209.0). "
# # #             "3. Бюджетний варіант: Ryzen 5 9600X ($279.0), ASUS TUF Gaming B650-Plus WiFi ($219.0). "
# # #             "Вузьке місце: зовнішній USB HDD."
# # #         ),
# # #     },
# # #     {
# # #         "model": "Pro",
# # #         "test_id": "P2",
# # #         "title": "Фото плати AM5 + жорсткий бюджет і ризики",
# # #         "vision_acc": 5.0,
# # #         "hw_compat": 5.0,
# # #         "rag_faith": 5.0,
# # #         "structure": 5.0,
# # #         "ttfb_sec": 2.15,
# # #         "rag_sec": 0.41,
# # #         "response_text": (
# # #             "Варіант 1: Максимум надійності й продуктивності (Ryzen 9 9950X, Noctua NH-D15 G2). "
# # #             "Варіант 2: Оптимальний баланс (Ryzen 7 9800X3D, Thermalright Phantom Spirit 120 SE). "
# # #             "Варіант 3: Бюджетний варіант (Ryzen 5 9600X, ID-Cooling SE-224-XTS). Ризики та відмінності."
# # #         ),
# # #     },
# # # ]


# # # def parse_timing_log(log_path: Path | None) -> list[dict]:
# # #     """Парсить рядки [AI Chat Timing] з лог-файлу ai_service, якщо файл передано."""
# # #     if not log_path or not log_path.exists():
# # #         return []
# # #     records = []
# # #     for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
# # #         m = TIMING_RE.search(line)
# # #         if m:
# # #             records.append(
# # #                 {
# # #                     "requested": m.group("req"),
# # #                     "model": m.group("model"),
# # #                     "rag_sec": float(m.group("rag")),
# # #                     "ttfb_sec": float(m.group("ttfb")),
# # #                     "images": int(m.group("images")) if m.group("images") else None,
# # #                     "items": int(m.group("items")) if m.group("items") else None,
# # #                 }
# # #             )
# # #     return records


# # # def audit_response_text(row: dict) -> list[str]:
# # #     """Автоматична перевірка тексту відповіді на типові дефекти генерації та RAG."""
# # #     flags = []
# # #     txt = row["response_text"].strip()
# # #     low = txt.lower()

# # #     if txt and txt[-1].isalnum() and not low.endswith(("gb", "tb", "hz", "w", "mm", "pcs", "шт")):
# # #         flags.append("POSSIBLE_STREAM_TRUNCATION")

# # #     if ("монітор" in row["title"].lower() or "монітор" in low) and (
# # #         "немає в наявності моніторів" in low or "немає моніторів" in low
# # #     ):
# # #         flags.append("FALSE_NEGATIVE_CATALOG_MONITORS")

# # #     if ("варіант" in low or "наявност" in low) and "$" not in txt:
# # #         flags.append("MISSING_USD_PRICES")

# # #     return flags


# # # def main(log_file: str | None = None):
# # #     parsed_logs = parse_timing_log(Path(log_file)) if log_file else []
# # #     if parsed_logs:
# # #         print(f"Знайдено {len(parsed_logs)} записів [AI Chat Timing] у логах.")

# # #     rows = []
# # #     for idx, item in enumerate(TEST_CASES):
# # #         enriched = dict(item)
# # #         if idx < len(parsed_logs):
# # #             enriched["rag_sec"] = parsed_logs[idx]["rag_sec"]
# # #             enriched["ttfb_sec"] = parsed_logs[idx]["ttfb_sec"]

# # #         flags = audit_response_text(enriched)
# # #         enriched["audit_flags"] = ", ".join(flags) if flags else "OK"
# # #         rows.append(enriched)

# # #     df = pd.DataFrame(rows)

# # #     weights = {
# # #         "vision_acc": 0.25,
# # #         "hw_compat": 0.30,
# # #         "rag_faith": 0.30,
# # #         "structure": 0.15,
# # #     }
# # #     df["weighted_score"] = (
# # #         df["vision_acc"] * weights["vision_acc"]
# # #         + df["hw_compat"] * weights["hw_compat"]
# # #         + df["rag_faith"] * weights["rag_faith"]
# # #         + df["structure"] * weights["structure"]
# # #     ).round(2)

# # #     out_dir = Path("eval_results")
# # #     out_dir.mkdir(exist_ok=True)

# # #     df.drop(columns=["response_text"]).to_csv(out_dir / "per_test_evaluation.csv", index=False)

# # #     model_means = (
# # #         df.groupby("model")[
# # #             ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score", "ttfb_sec", "rag_sec"]
# # #         ]
# # #         .mean()
# # #         .round(2)
# # #     )

# # #     print("\n=== ЗВЕДЕНІ ПОКАЗНИКИ ПО МОДЕЛЯХ ===")
# # #     print(model_means.to_string())

# # #     md_report = [
# # #         "# Результати оцінювання мультимодального ШІ-асистента ElectroStore\n",
# # #         "## 1. Середні показники моделей (якість та затримка)\n",
# # #         model_means.to_markdown(),
# # #         "\n## 2. Деталізований аудит тестів\n",
# # #         df[
# # #             [
# # #                 "model", "test_id", "title", "vision_acc", "hw_compat",
# # #                 "rag_faith", "structure", "weighted_score", "ttfb_sec", "audit_flags",
# # #             ]
# # #         ].to_markdown(index=False),
# # #     ]
# # #     (out_dir / "evaluation_report.md").write_text("\n".join(md_report), encoding="utf-8")

# # #     palette = {"Lite": "#1f77b4", "Flash": "#d62728", "Pro": "#2ca02c"}

# # #     # 1. Radar Chart
# # #     categories = ["Візуальний\nаналіз", "Сумісність\nзаліза", "Чесність\nRAG", "Структура\nвідповіді"]
# # #     angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
# # #     angles += angles[:1]

# # #     fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
# # #     for m in ["Lite", "Flash", "Pro"]:
# # #         if m not in model_means.index:
# # #             continue
# # #         r = model_means.loc[m]
# # #         vals = [r["vision_acc"], r["hw_compat"], r["rag_faith"], r["structure"]]
# # #         vals += vals[:1]
# # #         ax.plot(angles, vals, linewidth=2.2, label=f"{m} (Q={r['weighted_score']})", color=palette[m])
# # #         ax.fill(angles, vals, alpha=0.12, color=palette[m])

# # #     ax.set_theta_offset(np.pi / 2)
# # #     ax.set_theta_direction(-1)
# # #     ax.set_xticks(angles[:-1])
# # #     ax.set_xticklabels(categories, fontsize=10, fontweight="bold")
# # #     ax.set_ylim(0, 5.2)
# # #     plt.title("Профіль якості моделей (0–5 балів)", size=12, fontweight="bold", pad=18)
# # #     plt.legend(loc="upper right", bbox_to_anchor=(1.28, 1.1))
# # #     plt.tight_layout()
# # #     plt.savefig(out_dir / "model_comparison_radar.png", dpi=300)
# # #     plt.close()

# # #     # 2. Heatmap по тестах
# # #     heat_df = df.set_index(["model", "test_id"])[
# # #         ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score"]
# # #     ]
# # #     fig, ax = plt.subplots(figsize=(8, 5))
# # #     im = ax.imshow(heat_df.values, aspect="auto", cmap="YlGn", vmin=1.0, vmax=5.0)
# # #     ax.set_xticks(np.arange(len(heat_df.columns)))
# # #     ax.set_xticklabels(["Vision", "HW Compat", "RAG Faith", "Structure", "Score Q"], fontweight="bold")
# # #     ax.set_yticks(np.arange(len(heat_df.index)))
# # #     ax.set_yticklabels([f"{m} | {t}" for m, t in heat_df.index])

# # #     for i in range(heat_df.shape[0]):
# # #         for j in range(heat_df.shape[1]):
# # #             ax.text(j, i, f"{heat_df.values[i, j]:.1f}", ha="center", va="center", color="black", fontsize=9)

# # #     plt.colorbar(im, ax=ax, label="Оцінка (1.0–5.0)")
# # #     plt.title("Деталізована матриця оцінок по тестах", size=12, fontweight="bold")
# # #     plt.tight_layout()
# # #     plt.savefig(out_dir / "tests_scores_heatmap.png", dpi=300)
# # #     plt.close()

# # #     # 3. Компроміс: Якість (Q) vs Затримка до першого токена (TTFB)
# # #     fig, ax = plt.subplots(figsize=(7, 5))
# # #     for m in ["Lite", "Flash", "Pro"]:
# # #         sub = df[df["model"] == m]
# # #         if sub.empty:
# # #             continue
# # #         ax.scatter(
# # #             sub["ttfb_sec"],
# # #             sub["weighted_score"],
# # #             s=90,
# # #             label=f"{m} (mean TTFB={sub['ttfb_sec'].mean():.2f}s, Q={sub['weighted_score'].mean():.2f})",
# # #             color=palette[m],
# # #             alpha=0.85,
# # #         )
# # #     ax.set_xlabel("Час до першого токена TTFB (с)", fontweight="bold")
# # #     ax.set_ylabel("Інтегральний бал якості Q (0–5)", fontweight="bold")
# # #     ax.set_ylim(3.0, 5.2)
# # #     ax.grid(True, linestyle="--", alpha=0.4)
# # #     ax.set_title("Компроміс якості та швидкодії моделей", size=12, fontweight="bold")
# # #     ax.legend()
# # #     plt.tight_layout()
# # #     plt.savefig(out_dir / "quality_vs_latency.png", dpi=300)
# # #     plt.close()

# # #     print(f"\nЗбережено звіти та 3 графіки у: {out_dir.resolve()}")


# # # if __name__ == "__main__":
# # #     # За потреби передайте шлях до файлу логів: main("ai_service.log")
# # #     main()

# # # # import json
# # # # from pathlib import Path
# # # # import numpy as np
# # # # import pandas as pd
# # # # import matplotlib.pyplot as plt

# # # # # Каталог товарів, який реально фігурував у ваших тестах (для перевірки "хибної відсутності")
# # # # KNOWN_CATALOG_ITEMS = {
# # # #     "monitors": [
# # # #         "LG UltraGear 27GS85Q 27-inch QHD",
# # # #         "ASUS ROG Swift OLED PG27AQDM 27-inch",
# # # #         "Dell UltraSharp U2724D 27-inch QHD",
# # # #         "Gigabyte M27Q 27-inch QHD 170Hz",
# # # #         "Samsung Odyssey G5 34-inch UWQHD",
# # # #     ],
# # # #     "motherboards": [
# # # #         "MSI MAG B650 Tomahawk WiFi",
# # # #         "ASUS ROG Strix X870E-E Gaming WiFi",
# # # #         "ASUS TUF Gaming B650-Plus WiFi",
# # # #         "Gigabyte Z890 AORUS Elite WiFi7",
# # # #     ],
# # # #     "gpus": [
# # # #         "NVIDIA GeForce RTX 4080 Super 16GB",
# # # #         "NVIDIA GeForce RTX 4070 Ti Super 16GB",
# # # #         "NVIDIA GeForce RTX 4070 Super 12GB",
# # # #         "NVIDIA GeForce RTX 4060 Ti 8GB",
# # # #         "AMD Radeon RX 7800 XT 16GB",
# # # #         "AMD Radeon RX 7900 XT 20GB",
# # # #     ],
# # # #     "coolers": [
# # # #         "ID-Cooling SE-224-XTS Black",
# # # #         "Thermalright Phantom Spirit 120 SE",
# # # #         "Noctua NH-D15 G2",
# # # #     ],
# # # #     "phones": [
# # # #         "Google Pixel 9 Pro 256GB",
# # # #     ],
# # # # }

# # # # TEST_CASES = [
# # # #     # --- LITE ---
# # # #     {
# # # #         "model": "Lite",
# # # #         "test_id": "L1",
# # # #         "title": "4 фото (GPU + PSU + B650 + CPU)",
# # # #         "photo_notes": "Фото 1: GTX 1080; Фото 2: білий БЖ; Фото 3: MSI MAG B650 Tomahawk WiFi; Фото 4: CPU AM5",
# # # #         "vision_acc": 4.5,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "Фото 1: MSI Gaming GTX 10-ї чи RTX 20-ї серії. Фото 2: білий модульний БЖ. "
# # # #             "Фото 3: MSI MAG B650 Tomahawk WiFi ($209.0, в наявності: 17 шт.). Фото 4: CPU AM5. "
# # # #             "Варіанти збірки: 1. Максимум надійності й продуктивності, 2. Оптимальний баланс, 3. Бюджетний варіант."
# # # #         ),
# # # #     },
# # # #     {
# # # #         "model": "Lite",
# # # #         "test_id": "L2",
# # # #         "title": "2 фото (розмита Z890 + RTX 3060)",
# # # #         "photo_notes": "Фото 1: розмите фото Gigabyte Z890 AORUS Elite WiFi7 (не з бази); Фото 2: RTX 3060 (не вгадав покоління)",
# # # #         "vision_acc": 3.0,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "Фото 1: Gigabyte Z890 AORUS Elite WiFi7 ($289.0, 10 шт., LGA1851). "
# # # #             "Фото 2: ASUS Dual GeForce RTX — модель не представлена в каталозі, альтернатива RTX 4070 Super / Ti Super."
# # # #         ),
# # # #     },
# # # #     {
# # # #         "model": "Lite",
# # # #         "test_id": "L3",
# # # #         "title": "Розмитий фрагмент Pixel 9",
# # # #         "photo_notes": "Трохи розмитий шматок скріншоту телефону Pixel 9",
# # # #         "vision_acc": 4.0,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "Google Pixel (модель 8 або 9 Pro). В наявності Google Pixel 9 Pro 256GB ($999.0, 14 шт.). "
# # # #             "Порівняння базової моделі та Pixel 9 Pro."
# # # #         ),
# # # #     },
# # # #     {
# # # #         "model": "Lite",
# # # #         "test_id": "L4",
# # # #         "title": "EN: сумісність 750W PSU та DDR5 RAM",
# # # #         "photo_notes": "Без фото, англійською, автоперемикання мови",
# # # #         "vision_acc": 5.0,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "be quiet! Pure Power 12 M 750W ($114.0, ATX 3.1, 12V-2x6) та Kingston Fury Beast 32GB DDR5 6000MHz CL30 ($119.0)."
# # # #         ),
# # # #     },
# # # #     # --- FLASH ---
# # # #     {
# # # #         "model": "Flash",
# # # #         "test_id": "F1",
# # # #         "title": "2 фото (RTX 5070 + корпус) під 1440p",
# # # #         "photo_notes": "Відеокарта RTX 5070 та корпус Mid Tower ARGB",
# # # #         "vision_acc": 5.0,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 3.5,
# # # #         "response_text": (
# # # #             "ASUS Prime GeForce RTX 5070 12GB та корпус Mid Tower ARGB. "
# # # #             "RTX 5070 відсутня в каталозі, альтернативи: RTX 4070 Super 12GB та RTX 4070 Ti Super 16GB. "
# # # #             "Корпус з фотографії ви можете залишити свій власний, або ж допов"
# # # #         ),
# # # #     },
# # # #     {
# # # #         "model": "Flash",
# # # #         "test_id": "F2",
# # # #         "title": "TDP/MTP і охолодження",
# # # #         "photo_notes": "Питання про базовий кулер та пікове споживання",
# # # #         "vision_acc": 5.0,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "Базовий кулер не впорається з піковим споживанням (Core Ultra 9 285K ~250W, Ryzen 9 9950X ~200W+). "
# # # #             "360-мм СЖО немає в каталозі. В наявності: ID-Cooling SE-224-XTS ($25.0), "
# # # #             "Thermalright Phantom Spirit 120 SE ($39.0), Noctua NH-D15 G2 ($149.0)."
# # # #         ),
# # # #     },
# # # #     {
# # # #         "model": "Flash",
# # # #         "test_id": "F3",
# # # #         "title": "Скріншот IDE (бекенд, Docker, БД)",
# # # #         "photo_notes": "Скріншот робочого середовища розробника",
# # # #         "vision_acc": 5.0,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "Python/SQLAlchemy, Docker, PostgreSQL. MacBook із 32 ГБ RAM немає в каталозі; "
# # # #             "в наявності MacBook Air 15 M3 16GB ($1299.0), Minisforum UM790 Pro 32GB ($629.0), "
# # # #             "Ryzen 9 9900X + G.Skill 64GB DDR5."
# # # #         ),
# # # #     },
# # # #     {
# # # #         "model": "Flash",
# # # #         "test_id": "F4",
# # # #         "title": "2 фото моніторів (BenQ + AOC)",
# # # #         "photo_notes": "Старий BenQ та монітор AOC (в каталозі магазину є монітори LG, ASUS, Dell, Gigabyte, Samsung)",
# # # #         "vision_acc": 4.5,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 1.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "Перше фото: BenQ. Друге фото: AOC. "
# # # #             "У нас немає в наявності моніторів взагалі. Оскільки в ElectroStore немає моніторів у наявності..."
# # # #         ),
# # # #     },
# # # #     # --- PRO ---
# # # #     {
# # # #         "model": "Pro",
# # # #         "test_id": "P1",
# # # #         "title": "4 фото комплектуючих + 3 варіанти збірки",
# # # #         "photo_notes": "Плата Gigabyte AORUS AM5, зовнішній HDD Seagate, кулер, CPU Ryzen 9000",
# # # #         "vision_acc": 4.5,
# # # #         "hw_compat": 4.5,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "1. Максимум надійності й продуктивності: Ryzen 9 9950X ($649.0), ASUS ROG Strix X870E-E ($499.0). "
# # # #             "2. Оптимальний баланс: Ryzen 7 9800X3D ($479.0), MSI MAG B650 Tomahawk WiFi ($209.0). "
# # # #             "3. Бюджетний варіант: Ryzen 5 9600X ($279.0), ASUS TUF Gaming B650-Plus WiFi ($219.0). "
# # # #             "Вузьке місце: зовнішній USB HDD."
# # # #         ),
# # # #     },
# # # #     {
# # # #         "model": "Pro",
# # # #         "test_id": "P2",
# # # #         "title": "Фото плати AM5 + жорсткий бюджет і ризики",
# # # #         "photo_notes": "Материнська плата AM5 Gigabyte, запит на бюджет без троттлінгу і апгрейду за рік",
# # # #         "vision_acc": 5.0,
# # # #         "hw_compat": 5.0,
# # # #         "rag_faith": 5.0,
# # # #         "structure": 5.0,
# # # #         "response_text": (
# # # #             "Варіант 1: Максимум надійності й продуктивності (Ryzen 9 9950X, Noctua NH-D15 G2). "
# # # #             "Варіант 2: Оптимальний баланс (Ryzen 7 9800X3D, Thermalright Phantom Spirit 120 SE). "
# # # #             "Варіант 3: Бюджетний варіант (Ryzen 5 9600X, ID-Cooling SE-224-XTS). Ризики та відмінності."
# # # #         ),
# # # #     },
# # # # ]


# # # # def audit_response_text(row: dict) -> list[str]:
# # # #     """Автоматична перевірка тексту відповіді на типові дефекти генерації та RAG."""
# # # #     flags = []
# # # #     txt = row["response_text"].strip()
# # # #     low = txt.lower()

# # # #     # 1. Обрив слова або речення в кінці
# # # #     if txt and txt[-1].isalnum() and not low.endswith(("gb", "tb", "hz", "w", "mm", "pcs", "шт")):
# # # #         flags.append("POSSIBLE_STREAM_TRUNCATION")

# # # #     # 2. Підозра на хибну відсутність моніторів, коли в запиті є слово 'монітор'
# # # #     if ("монітор" in row["title"].lower() or "монітор" in low) and (
# # # #         "немає в наявності моніторів" in low or "немає моніторів" in low
# # # #     ):
# # # #         flags.append("FALSE_NEGATIVE_CATALOG_MONITORS")

# # # #     # 3. Перевірка згадки цін у доларах для рекомендацій
# # # #     if ("варіант" in low or "наявност" in low) and "$" not in txt:
# # # #         flags.append("MISSING_USD_PRICES")

# # # #     return flags


# # # # def main():
# # # #     rows = []
# # # #     for item in TEST_CASES:
# # # #         flags = audit_response_text(item)
# # # #         rows.append({**item, "audit_flags": ", ".join(flags) if flags else "OK"})

# # # #     df = pd.DataFrame(rows)

# # # #     weights = {
# # # #         "vision_acc": 0.25,
# # # #         "hw_compat": 0.30,
# # # #         "rag_faith": 0.30,
# # # #         "structure": 0.15,
# # # #     }
# # # #     df["weighted_score"] = (
# # # #         df["vision_acc"] * weights["vision_acc"]
# # # #         + df["hw_compat"] * weights["hw_compat"]
# # # #         + df["rag_faith"] * weights["rag_faith"]
# # # #         + df["structure"] * weights["structure"]
# # # #     ).round(2)

# # # #     out_dir = Path("eval_results")
# # # #     out_dir.mkdir(exist_ok=True)

# # # #     # Збереження детальної таблиці та аудиту
# # # #     df.drop(columns=["response_text"]).to_csv(out_dir / "per_test_evaluation.csv", index=False)

# # # #     model_summary = (
# # # #         df.groupby("model")[
# # # #             ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score"]
# # # #         ]
# # # #         .agg(["mean", "std"])
# # # #         .round(2)
# # # #     )
# # # #     model_means = (
# # # #         df.groupby("model")[
# # # #             ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score"]
# # # #         ]
# # # #         .mean()
# # # #         .round(2)
# # # #     )

# # # #     print("=== АУДИТ ОДНОРАЗОВИХ ТЕСТІВ ===")
# # # #     print(df[["model", "test_id", "title", "weighted_score", "audit_flags"]].to_string(index=False))

# # # #     print("\n=== ЗВЕДЕНІ МЕТРИКИ ПО МОДЕЛЯХ (MEAN / STD) ===")
# # # #     print(model_summary.to_string())

# # # #     # Збереження Markdown-звіту для диплому
# # # #     md_report = [
# # # #         "# Результати оцінювання мультимодального ШІ-асистента ElectroStore\n",
# # # #         "## 1. Середні показники моделей\n",
# # # #         model_means.to_markdown(),
# # # #         "\n## 2. Аудит тестів та виявлені відхилення\n",
# # # #         df[["model", "test_id", "title", "vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score", "audit_flags"]].to_markdown(index=False),
# # # #     ]
# # # #     (out_dir / "evaluation_report.md").write_text("\n".join(md_report), encoding="utf-8")

# # # #     # Графік 1: Radar Chart
# # # #     categories = ["Візуальний\nаналіз", "Сумісність\nзаліза", "Чесність\nRAG", "Структура\nвідповіді"]
# # # #     angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
# # # #     angles += angles[:1]

# # # #     fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
# # # #     palette = {"Lite": "#1f77b4", "Flash": "#d62728", "Pro": "#2ca02c"}

# # # #     for m in ["Lite", "Flash", "Pro"]:
# # # #         if m not in model_means.index:
# # # #             continue
# # # #         r = model_means.loc[m]
# # # #         vals = [r["vision_acc"], r["hw_compat"], r["rag_faith"], r["structure"]]
# # # #         vals += vals[:1]
# # # #         ax.plot(angles, vals, linewidth=2.2, label=f"{m} (Q={r['weighted_score']})", color=palette[m])
# # # #         ax.fill(angles, vals, alpha=0.12, color=palette[m])

# # # #     ax.set_theta_offset(np.pi / 2)
# # # #     ax.set_theta_direction(-1)
# # # #     ax.set_xticks(angles[:-1])
# # # #     ax.set_xticklabels(categories, fontsize=10, fontweight="bold")
# # # #     ax.set_ylim(0, 5.2)
# # # #     plt.title("Профіль якості моделей (0–5 балів)", size=12, fontweight="bold", pad=18)
# # # #     plt.legend(loc="upper right", bbox_to_anchor=(1.28, 1.1))
# # # #     plt.tight_layout()
# # # #     plt.savefig(out_dir / "model_comparison_radar.png", dpi=300)
# # # #     plt.close()

# # # #     # Графік 2: Heatmap по всіх тестах
# # # #     heat_df = df.set_index(["model", "test_id"])[
# # # #         ["vision_acc", "hw_compat", "rag_faith", "structure", "weighted_score"]
# # # #     ]
# # # #     fig, ax = plt.subplots(figsize=(8, 5))
# # # #     im = ax.imshow(heat_df.values, aspect="auto", cmap="YlGn", vmin=1.0, vmax=5.0)
# # # #     ax.set_xticks(np.arange(len(heat_df.columns)))
# # # #     ax.set_xticklabels(["Vision", "HW Compat", "RAG Faith", "Structure", "Score Q"], fontweight="bold")
# # # #     ax.set_yticks(np.arange(len(heat_df.index)))
# # # #     ax.set_yticklabels([f"{m} | {t}" for m, t in heat_df.index])

# # # #     for i in range(heat_df.shape[0]):
# # # #         for j in range(heat_df.shape[1]):
# # # #             ax.text(j, i, f"{heat_df.values[i, j]:.1f}", ha="center", va="center", color="black", fontsize=9)

# # # #     plt.colorbar(im, ax=ax, label="Оцінка (1.0–5.0)")
# # # #     plt.title("Деталізована матриця оцінок по тестах", size=12, fontweight="bold")
# # # #     plt.tight_layout()
# # # #     plt.savefig(out_dir / "tests_scores_heatmap.png", dpi=300)
# # # #     plt.close()

# # # #     print(f"\nГотово! Файли збережено у папку: {out_dir.resolve()}")


# # # # if __name__ == "__main__":
# # # #     main()
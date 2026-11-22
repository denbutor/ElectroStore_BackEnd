import argparse
import csv
import json
import os
import time
from pathlib import Path
import httpx


def load_api_key() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()

    candidate_env_files = [
        Path(".env"),
        Path("../../.env"),
        Path("../../services/ai_service/.env"),
    ]
    for env_path in candidate_env_files:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "GEMINI_API_KEY":
                    return v.strip().strip('"').strip("'")

    raise RuntimeError(
        "GEMINI_API_KEY not found in environment or .env. "
        "Set it via: $env:GEMINI_API_KEY='your_key'"
    )


def resolve_judge_candidates(base_url: str, explicit_model: str | None) -> list[str]:
    if explicit_model:
        return [explicit_model.removeprefix("models/")]

    candidates: list[str] = []
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/v1/ai/chat/models", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            models_list = data.get("models") or []
            for preferred_id in ("flash", "lite", "pro"):
                for item in models_list:
                    if item.get("id") == preferred_id and item.get("model"):
                        clean_name = item["model"].removeprefix("models/")
                        if clean_name not in candidates:
                            candidates.append(clean_name)
    except Exception:
        pass

    for fallback in ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def post_with_429_retry(
    client: httpx.Client,
    url: str,
    headers: dict,
    body: dict,
    max_retries: int = 5,
) -> httpx.Response:
    wait_sec = 8.0
    for attempt in range(1, max_retries + 1):
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            sleep_for = float(retry_after) if retry_after and retry_after.isdigit() else wait_sec
            print(f"  [Rate Limit 429] Waiting {sleep_for:.1f}s before retry {attempt}/{max_retries}...")
            time.sleep(sleep_for)
            wait_sec = min(wait_sec * 1.5, 45.0)
            continue
        return resp
    return resp


def judge_single_row(
    client: httpx.Client,
    api_key: str,
    judge_models: list[str],
    row: dict,
    gt_facts: list[str],
) -> dict:
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    judge_prompt = f"""You are a strict technical evaluator for an electronics e-commerce AI assistant benchmark.
Evaluate the assistant's response against the user prompt and expected criteria (ground truth).
Score each metric from 1 to 5 (integer):
- catalog_faithfulness: Accuracy of store items, prices in $, and stock claims; avoids inventing store stock/prices. (1=completely wrong/fabricated, 5=fully faithful)
- technical_correctness: Hardware compatibility, specs, temporal/technical accuracy, and domain soundness. (1=technically wrong, 5=technically sound)
- instruction_following: Matches user language, uses $ / USD prices, concise and on-topic. (1=ignores instructions, 5=follows all instructions)
- hallucination_free: Absence of fabricated specs, fake catalog items, or false claims. (1=severe hallucinations, 5=no hallucinations)

Query ID: {row.get("query_id")}
Category: {row.get("category")}
Expected language: {row.get("language")}
User Prompt: {row.get("prompt")}
Expected Criteria: {json.dumps(gt_facts, ensure_ascii=False)}
Model Under Test: {row.get("model_type")}
Assistant Response:
\"\"\"
{row.get("clean_response", "")}
\"\"\"

Return ONLY a valid JSON object (no markdown fences) with keys:
{{"catalog_faithfulness": int, "technical_correctness": int, "instruction_following": int, "hallucination_free": int, "short_reason": "brief explanation in Ukrainian"}}
"""

    body = {
        "contents": [{"role": "user", "parts": [{"text": judge_prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    last_exc: Exception | None = None
    data = None
    for model_name in judge_models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent"
        )
        try:
            resp = post_with_429_retry(client, url, headers, body)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_exc = exc

    if data is None:
        raise RuntimeError(f"All judge models failed ({judge_models}): {last_exc}")

    raw_text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "{}")
    )
    parsed = json.loads(raw_text)

    def clamp_score(val) -> int:
        try:
            n = int(round(float(val)))
            return max(1, min(5, n))
        except Exception:
            return 3

    cat_s = clamp_score(parsed.get("catalog_faithfulness"))
    tech_s = clamp_score(parsed.get("technical_correctness"))
    inst_s = clamp_score(parsed.get("instruction_following"))
    hal_s = clamp_score(parsed.get("hallucination_free"))
    overall = round((cat_s + tech_s + inst_s + hal_s) / 4.0, 2)

    return {
        "catalog_faithfulness": cat_s,
        "technical_correctness": tech_s,
        "instruction_following": inst_s,
        "hallucination_free": hal_s,
        "overall_score": overall,
        "judge_reason": str(parsed.get("short_reason", "")).strip(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-as-a-Judge evaluator for benchmark_results.csv")
    parser.add_argument("--input", default="benchmark_results.csv", help="Input CSV from run_benchmark.py")
    parser.add_argument("--dataset", default="benchmark_dataset.json", help="Dataset JSON with ground truth")
    parser.add_argument("--output", default="benchmark_evaluated.csv", help="Output CSV with scores")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend URL to auto-detect configured models")
    parser.add_argument("--judge-model", default=None, help="Explicit judge model name (optional)")
    parser.add_argument("--limit", type=int, default=0, help="Optional max rows to evaluate (0 = all)")
    parser.add_argument("--sleep", type=float, default=5.0, help="Delay between judge requests in seconds (default: 5.0)")
    args = parser.parse_args()

    api_key = load_api_key()
    judge_models = resolve_judge_candidates(args.base_url, args.judge_model)
    print(f"Using judge model candidates: {judge_models}")

    dataset_items = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    gt_map = {item["id"]: item.get("ground_truth_facts", []) for item in dataset_items}

    with Path(args.input).open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if args.limit > 0:
        rows = rows[: args.limit]

    out_fields = list(rows[0].keys()) + [
        "catalog_faithfulness",
        "technical_correctness",
        "instruction_following",
        "hallucination_free",
        "overall_score",
        "judge_reason",
    ]

    total = len(rows)
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=90.0, write=15.0, pool=15.0)) as client, \
            Path(args.output).open("w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=out_fields)
        writer.writeheader()

        for idx, row in enumerate(rows, start=1):
            qid = row.get("query_id", "")
            print(f"[{idx}/{total}] Judging model={row.get('model_type')} query_id={qid}")
            try:
                scores = judge_single_row(
                    client=client,
                    api_key=api_key,
                    judge_models=judge_models,
                    row=row,
                    gt_facts=gt_map.get(qid, []),
                )
            except Exception as exc:
                print(f"  [Warning] Judge error on {qid}: {exc}")
                scores = {
                    "catalog_faithfulness": "",
                    "technical_correctness": "",
                    "instruction_following": "",
                    "hallucination_free": "",
                    "overall_score": "",
                    "judge_reason": f"Error: {exc}",
                }

            merged = {**row, **scores}
            writer.writerow(merged)
            out_f.flush()
            time.sleep(args.sleep)

    print(f"Done! Saved evaluated results to {args.output}")


if __name__ == "__main__":
    main()
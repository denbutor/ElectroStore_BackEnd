import argparse
import csv
import json
import re
import time
import uuid
from pathlib import Path
import httpx

UI_LANG_TAG_RE = re.compile(r"^\s*\[\[UI_LANG\s*:\s*([a-zA-Z_-]+)\]\]\s*(?:\r?\n)?", re.IGNORECASE)
MAX_PREFIX_BUFFER_LEN = 40


def extract_sse_data_blocks(raw_text: str) -> list[str]:
    chunks: list[str] = []
    blocks = re.split(r"\r?\n\r?\n", raw_text)
    for block in blocks:
        lines = block.splitlines()
        data_lines = [line[5:].lstrip(" ") for line in lines if line.startswith("data:")]
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        if payload.strip() == "[DONE]":
            continue
        chunks.append(payload)
    return chunks


def run_single_stream_request(
    client: httpx.Client,
    endpoint_url: str,
    session_id: str,
    prompt: str,
    model_type: str,
    preferred_lang: str,
) -> dict:
    payload = {
        "session_id": session_id,
        "message": prompt,
        "model_type": model_type,
        "preferred_lang": preferred_lang,
        "allow_ui_lang_switch": True,
    }

    t_start = time.perf_counter()
    t_first_clean_token: float | None = None

    checking_prefix = True
    prefix_buffer = ""
    detected_ui_lang = "missing"
    clean_parts: list[str] = []
    raw_parts: list[str] = []
    sse_line_carry = ""
    error_msg = ""

    def process_text_chunk(text_chunk: str) -> None:
        nonlocal checking_prefix, prefix_buffer, detected_ui_lang, t_first_clean_token
        if not text_chunk:
            return
        raw_parts.append(text_chunk)

        if not checking_prefix:
            if t_first_clean_token is None and text_chunk.strip():
                t_first_clean_token = time.perf_counter()
            clean_parts.append(text_chunk)
            return

        prefix_buffer += text_chunk
        trimmed = prefix_buffer.lstrip()

        if trimmed and not trimmed.startswith("["):
            checking_prefix = False
            detected_ui_lang = "none_implicit"
            if t_first_clean_token is None and prefix_buffer.strip():
                t_first_clean_token = time.perf_counter()
            clean_parts.append(prefix_buffer)
            prefix_buffer = ""
            return

        if len(trimmed) >= 2 and not trimmed.startswith("[["):
            checking_prefix = False
            detected_ui_lang = "none_implicit"
            if t_first_clean_token is None and prefix_buffer.strip():
                t_first_clean_token = time.perf_counter()
            clean_parts.append(prefix_buffer)
            prefix_buffer = ""
            return

        match = UI_LANG_TAG_RE.match(prefix_buffer)
        if match:
            checking_prefix = False
            detected_ui_lang = match.group(1).lower()
            remainder = prefix_buffer[match.end():]
            prefix_buffer = ""
            if remainder:
                if t_first_clean_token is None and remainder.strip():
                    t_first_clean_token = time.perf_counter()
                clean_parts.append(remainder)
            return

        if len(prefix_buffer) > MAX_PREFIX_BUFFER_LEN:
            checking_prefix = False
            detected_ui_lang = "buffer_overflow"
            if t_first_clean_token is None and prefix_buffer.strip():
                t_first_clean_token = time.perf_counter()
            clean_parts.append(prefix_buffer)
            prefix_buffer = ""

    try:
        with client.stream("POST", endpoint_url, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line is None:
                    continue
                if line.startswith("data:"):
                    data_val = line[5:].lstrip(" ")
                    if data_val.strip() == "[DONE]":
                        break
                    if sse_line_carry:
                        data_val = sse_line_carry + "\n" + data_val
                        sse_line_carry = ""
                    process_text_chunk(data_val)
                elif line == "":
                    continue
                else:
                    sse_line_carry = (sse_line_carry + "\n" + line) if sse_line_carry else line
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"

    if checking_prefix and prefix_buffer:
        cleaned_tail = UI_LANG_TAG_RE.sub("", prefix_buffer, count=1).lstrip("\r\n")
        if cleaned_tail:
            if t_first_clean_token is None and cleaned_tail.strip():
                t_first_clean_token = time.perf_counter()
            clean_parts.append(cleaned_tail)

    t_end = time.perf_counter()
    clean_response = "".join(clean_parts).strip()
    raw_response = "".join(raw_parts).strip()

    ttft_sec = round(t_first_clean_token - t_start, 4) if t_first_clean_token is not None else None
    e2e_sec = round(t_end - t_start, 4)

    return {
        "ttft_sec": ttft_sec,
        "e2e_sec": e2e_sec,
        "detected_ui_lang": detected_ui_lang,
        "response_chars": len(clean_response),
        "clean_response": clean_response,
        "raw_response": raw_response,
        "error": error_msg,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ElectroStore AI models (lite, flash, pro)")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of API gateway or ai_service (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--dataset",
        default="benchmark_dataset.json",
        help="Path to benchmark_dataset.json",
    )
    parser.add_argument(
        "--output",
        default="benchmark_results.csv",
        help="Output CSV file path",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["lite", "flash", "pro"],
        help="Models to benchmark (default: lite flash pro)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="Number of repeated runs per prompt and model (default: 2)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.5,
        help="Pause in seconds between requests to respect rate limits (default: 1.5)",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    endpoint_url = f"{args.base_url.rstrip('/')}/api/v1/ai/chat/stream"

    fieldnames = [
        "run",
        "model_type",
        "query_id",
        "category",
        "language",
        "expected_ui_lang",
        "detected_ui_lang",
        "ui_lang_match",
        "ttft_sec",
        "e2e_sec",
        "response_chars",
        "error",
        "prompt",
        "clean_response",
    ]

    total_jobs = len(args.models) * len(dataset) * args.runs
    current_job = 0

    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0, write=15.0, pool=15.0)) as client, \
            Path(args.output).open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for run_idx in range(1, args.runs + 1):
            for model_type in args.models:
                for item in dataset:
                    current_job += 1
                    session_id = f"bench_{model_type}_r{run_idx}_{item['id']}_{uuid.uuid4().hex[:8]}"
                    print(
                        f"[{current_job}/{total_jobs}] run={run_idx} model={model_type} "
                        f"id={item['id']} ({item['category']})"
                    )

                    res = run_single_stream_request(
                        client=client,
                        endpoint_url=endpoint_url,
                        session_id=session_id,
                        prompt=item["prompt"],
                        model_type=model_type,
                        preferred_lang="en",
                    )

                    expected = (item.get("expected_ui_lang") or "").lower()
                    actual = (res["detected_ui_lang"] or "").lower()
                    if expected == "none":
                        ui_match = actual in ("none", "none_implicit", "missing")
                    else:
                        ui_match = actual == expected

                    writer.writerow(
                        {
                            "run": run_idx,
                            "model_type": model_type,
                            "query_id": item["id"],
                            "category": item["category"],
                            "language": item["language"],
                            "expected_ui_lang": expected,
                            "detected_ui_lang": actual,
                            "ui_lang_match": int(ui_match),
                            "ttft_sec": res["ttft_sec"],
                            "e2e_sec": res["e2e_sec"],
                            "response_chars": res["response_chars"],
                            "error": res["error"],
                            "prompt": item["prompt"],
                            "clean_response": res["clean_response"],
                        }
                    )
                    csv_file.flush()
                    time.sleep(args.sleep)

    print(f"Done! Saved results to {args.output}")


if __name__ == "__main__":
    main()
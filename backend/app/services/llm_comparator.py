import json
import os
import re
from pathlib import Path

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

MASTER_PROMPT = (Path(__file__).parent.parent / "prompts" / "master_prompt.txt").read_text()
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_RECORDS_PER_BATCH = 12

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def _call_llm(att_batch: list[dict], cli_batch: list[dict]) -> dict:
    user_message = (
        "Dataset 1 — Company Attendance:\n"
        f"{json.dumps(att_batch, indent=2, default=str)}\n\n"
        "Dataset 2 — Client Work:\n"
        f"{json.dumps(cli_batch, indent=2, default=str)}\n\n"
        "Return ONLY the JSON object described in the required output format. "
        "No markdown fences, no preamble, no explanation outside the JSON."
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": MASTER_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        max_tokens=6000,
        reasoning_effort="low",
        temperature=0,
    )
    raw_text = response.choices[0].message.content
    if not raw_text or not raw_text.strip():
        raise ValueError("The AI model returned an empty response.")
    try:
        return _extract_json(raw_text)
    except json.JSONDecodeError:
        retry = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": MASTER_PROMPT},
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content": "That was not valid JSON. Return ONLY corrected valid JSON."},
            ],
            response_format={"type": "json_object"},
            max_tokens=6000,
            reasoning_effort="low",
            temperature=0,
        )
        retry_text = retry.choices[0].message.content
        if not retry_text or not retry_text.strip():
            raise ValueError("The AI model returned an empty response on retry as well.")
        return _extract_json(retry_text)


def _employee_key(record: dict) -> str:
    """Batching key. Since ID columns may exist in only one of the two
    files (different ID systems entirely), we key on normalized NAME —
    the one field genuinely present and comparable in both datasets."""
    for k in record:
        if "name" in str(k).lower():
            name = str(record[k])
            return re.sub(r"[^a-z0-9]", "", name.lower())
    return ""


def compare_via_llm(attendance_records: list[dict], client_records: list[dict]) -> dict:
    all_keys = sorted(set(_employee_key(r) for r in attendance_records + client_records if _employee_key(r)))

    if len(all_keys) <= MAX_RECORDS_PER_BATCH:
        return _call_llm(attendance_records, client_records)

    merged = {
        "summary": {"total_records_compared": 0, "matches": 0, "mismatches": 0, "review_required": 0},
        "mismatches": [],
    }
    for i in range(0, len(all_keys), MAX_RECORDS_PER_BATCH):
        batch_keys = set(all_keys[i:i + MAX_RECORDS_PER_BATCH])
        att_batch = [r for r in attendance_records if _employee_key(r) in batch_keys]
        cli_batch = [r for r in client_records if _employee_key(r) in batch_keys]
        result = _call_llm(att_batch, cli_batch)

        s = result.get("summary", {})
        merged["summary"]["total_records_compared"] += s.get("total_records_compared", 0)
        merged["summary"]["matches"] += s.get("matches", 0)
        merged["summary"]["mismatches"] += s.get("mismatches", 0)
        merged["summary"]["review_required"] += s.get("review_required", 0)
        merged["mismatches"].extend(result.get("mismatches", []))

    return merged
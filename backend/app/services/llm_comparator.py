import json
import os
import re
import uuid
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

# Load backend/.env regardless of the directory uvicorn was started from, so
# configuration can never silently depend on the server's working directory.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MASTER_PROMPT = (Path(__file__).parent.parent / "prompts" / "master_prompt.txt").read_text()
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_RECORDS_PER_BATCH =  5

# The Groq client is created LAZILY. The primary (deterministic) comparison
# path never uses it, so a missing or invalid GROQ_API_KEY must not stop the
# application from starting, or from serving uploads and /api/columns.
_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM comparison is not configured: GROQ_API_KEY is missing "
                "(set it in backend/.env). Column detection and the "
                "deterministic hours comparison work without it."
            )
        _client = Groq(api_key=api_key)
    return _client


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def _call_llm(
    att_batch: list[dict],
    cli_batch: list[dict],
    attendance_key_column: str | None = None,
    client_key_column: str | None = None,
) -> dict:
    key_context = ""
    hours_directive = (
        "Hour handling: the hours values in these datasets are final totals. "
        "Compare the two datasets' totals DIRECTLY for each matched employee. "
        "Combine rows ONLY where one dataset genuinely contains multiple rows "
        "for the same identifier; never sum otherwise, never treat missing "
        "hours as zero, and copy values unchanged.\n\n"
    )
    multi_row_notes = ""
    if attendance_key_column and client_key_column:
        key_context = (
            "User-selected primary matching attributes (rows were pre-grouped "
            "by the normalized values of these columns; EQUAL values identify "
            "the SAME employee even if the two column names differ):\n"
            f"- Dataset 1 (Company Attendance) column: \"{attendance_key_column}\"\n"
            f"- Dataset 2 (Client Work) column: \"{client_key_column}\"\n\n"
        )
        multi_att = _multi_row_identifiers(att_batch, attendance_key_column)
        multi_cli = _multi_row_identifiers(cli_batch, client_key_column)
        multi_row_notes = (
            "Records that may legitimately be combined (an identifier appears "
            f"in MULTIPLE rows): Dataset 1 -> {', '.join(multi_att) if multi_att else 'none'}; "
            f"Dataset 2 -> {', '.join(multi_cli) if multi_cli else 'none'}.\n"
            "Every other employee has exactly one row per dataset: compare its "
            "provided total directly without summing.\n\n"
        )
    user_message = (
        key_context
        + hours_directive
        + multi_row_notes
        + "Dataset 1 — Company Attendance:\n"
        f"{json.dumps(att_batch, indent=2, default=str)}\n\n"
        "Dataset 2 — Client Work:\n"
        f"{json.dumps(cli_batch, indent=2, default=str)}\n\n"
        "Return ONLY the JSON object described in the required output format. "
        "No markdown fences, no preamble, no explanation outside the JSON."
    )
    response = _get_client().chat.completions.create(
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
        retry = _get_client().chat.completions.create(
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


def _normalize_identifier(value) -> str:
    """Safely coerce a raw identifier cell into a comparable string without
    changing its meaning: consistent text conversion, surrounding-whitespace
    trim, collapsed internal whitespace, whole-number floats rendered without
    a trailing ".0" (a common Excel artifact), and case folding so "N001" and
    "n001" join. No other characters are altered and no values are invented."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN: pandas' marker for a missing/blank cell
            return ""
        return str(int(value)) if value.is_integer() else str(value).strip()
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


_UNIDENTIFIED_PREFIX = "_unidentified_"


def _employee_key(record: dict, key_column: str | None = None) -> str:
    """Matching key for one record.

    When the user selected a primary identifier column, the normalized VALUE
    of that column IS the matching key — no other field is consulted. An
    empty result means the row carries no usable identifier. Only when no
    column was selected do we fall back to the legacy normalized-NAME
    heuristic (preserved for callers of the old API shape)."""
    if key_column:
        if key_column in record:
            return _normalize_identifier(record.get(key_column))
        return ""
    for k in record:
        if "name" in str(k).lower():
            name = str(record[k])
            return re.sub(r"[^a-z0-9]", "", name.lower())
    return ""


def _batch_key(record: dict, key_column: str | None) -> str:
    """Grouping key used to partition records into LLM batches. Rows without
    a usable identifier receive a UNIQUE synthetic key so they are still sent
    to the model — and therefore accounted for exactly once — instead of
    being silently dropped."""
    key = _employee_key(record, key_column)
    if key:
        return key
    return f"{_UNIDENTIFIED_PREFIX}{uuid.uuid4().hex}"


def _multi_row_identifiers(rows: list[dict], key_column: str | None) -> list[str]:
    """Identifiers that legitimately have MULTIPLE records in one dataset —
    the only case in which hours may be combined. Derived purely from the
    row/key structure; no hour values are read or altered here."""
    if not key_column:
        return []
    counts = Counter(
        k for r in rows
        for k in [_employee_key(r, key_column)]
        if k and not k.startswith(_UNIDENTIFIED_PREFIX)
    )
    return sorted(k for k, c in counts.items() if c > 1)


def compare_via_llm(
    attendance_records: list[dict],
    client_records: list[dict],
    attendance_key_column: str | None = None,
    client_key_column: str | None = None,
) -> dict:
    # Compute each record's grouping key exactly once. Records whose
    # normalized identifier values are equal — across either dataset — share
    # a batch, so the model always sees both sides of the same employee
    # together (multi-row employees stay together for hour aggregation), and
    # one-sided employees ride along in the batch containing their key.
    att_keyed = [(_batch_key(r, attendance_key_column), r) for r in attendance_records]
    cli_keyed = [(_batch_key(r, client_key_column), r) for r in client_records]
    all_keys = sorted({k for k, _ in att_keyed} | {k for k, _ in cli_keyed})

    if len(all_keys) <= MAX_RECORDS_PER_BATCH:
        return _call_llm(
            attendance_records,
            client_records,
            attendance_key_column,
            client_key_column,
        )

    merged = {
        "summary": {"total_records_compared": 0, "matches": 0, "mismatches": 0, "review_required": 0},
        "mismatches": [],
    }
    for i in range(0, len(all_keys), MAX_RECORDS_PER_BATCH):
        batch_keys = set(all_keys[i:i + MAX_RECORDS_PER_BATCH])
        att_batch = [r for k, r in att_keyed if k in batch_keys]
        cli_batch = [r for k, r in cli_keyed if k in batch_keys]
        result = _call_llm(
            att_batch,
            cli_batch,
            attendance_key_column,
            client_key_column,
        )

        s = result.get("summary", {})
        merged["summary"]["total_records_compared"] += s.get("total_records_compared", 0)
        merged["summary"]["matches"] += s.get("matches", 0)
        merged["summary"]["mismatches"] += s.get("mismatches", 0)
        merged["summary"]["review_required"] += s.get("review_required", 0)
        merged["mismatches"].extend(result.get("mismatches", []))

    return merged
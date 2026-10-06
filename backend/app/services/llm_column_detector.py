"""Optional Groq-based fallback for classifying hours column headers."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from dotenv import load_dotenv


_GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.1-8b-instant"
_TIMEOUT_SECONDS = 6


def detect_billable_and_non_billable_via_llm(
    column_names: list[str],
) -> dict[str, str | None]:
    """Classify supplied headers without sending any spreadsheet cell data."""
    result: dict[str, str | None] = {
        "billable_column": None,
        "non_billable_column": None,
    }
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    model = os.getenv("GROQ_MODEL") or _DEFAULT_MODEL
    print("Calling Groq API...")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return result

    try:
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify the provided spreadsheet column names. Return only a JSON object "
                        'with keys "billable_column" and "non_billable_column". Each value must '
                        "be exactly one of the provided column names, or null if none fit. Do not "
                        "return any value that is not an exact provided column name."
                    ),
                },
                {"role": "user", "content": json.dumps(column_names)},
            ],
        }
        request = Request(
            _GROQ_CHAT_COMPLETIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            method="POST",
        )
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            response_text = response.read().decode("utf-8")
        print("Groq raw response:", response_text)
        response_body = json.loads(response_text)

        content = response_body["choices"][0]["message"]["content"]
        print("Groq model response content:", content)
        classification = json.loads(content)
        print("Validating LLM result:", classification, "against columns:", column_names)
        if not isinstance(classification, dict):
            print("Validation failed because: the LLM result is not a JSON object.")
            return result

        actual_names = set(column_names)
        for field in result:
            value = classification.get(field)
            if isinstance(value, str) and value in actual_names:
                result[field] = value
            elif isinstance(value, str):
                print(
                    "Validation failed because:",
                    repr(value),
                    "is not an exact match for a provided column name.",
                )
            elif value is not None:
                print(
                    "Validation failed because:",
                    repr(value),
                    "is not a string column name or null.",
                )
        print("Validated LLM result:", result)
        return result
    except Exception as e:
        print("Groq call failed:", repr(e))
        return result
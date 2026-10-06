import io
import json

from app.services import llm_column_detector


def _groq_response(classification: str) -> io.BytesIO:
    body = json.dumps({
        "choices": [{"message": {"content": classification}}],
    }).encode("utf-8")
    return io.BytesIO(body)


def test_sends_only_headers_and_accepts_exact_classifications(monkeypatch):
    columns = ["Project ID", "Chargeable Hours", "Bench Hours"]
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _groq_response(json.dumps({
            "billable_column": "Chargeable Hours",
            "non_billable_column": "Bench Hours",
        }))

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm_column_detector, "urlopen", fake_urlopen)

    result = llm_column_detector.detect_billable_and_non_billable_via_llm(columns)

    assert result == {
        "billable_column": "Chargeable Hours",
        "non_billable_column": "Bench Hours",
    }
    assert captured["timeout"] == 6
    payload = json.loads(captured["request"].data)
    assert payload["model"] == "openai/gpt-oss-120b"
    assert json.loads(payload["messages"][1]["content"]) == columns
    assert "Ada Lovelace" not in captured["request"].data.decode("utf-8")
    assert "40" not in captured["request"].data.decode("utf-8")


def test_invalid_or_malformed_classifications_are_not_trusted(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        llm_column_detector,
        "urlopen",
        lambda request, timeout: _groq_response(
            '{"billable_column":"Invented Hours","non_billable_column":"Bench Hours"}'
        ),
    )

    result = llm_column_detector.detect_billable_and_non_billable_via_llm(
        ["Chargeable Hours", "Bench Hours"]
    )
    assert result == {"billable_column": None, "non_billable_column": "Bench Hours"}

    monkeypatch.setattr(
        llm_column_detector,
        "urlopen",
        lambda request, timeout: _groq_response("not valid JSON"),
    )
    assert llm_column_detector.detect_billable_and_non_billable_via_llm(
        ["Chargeable Hours", "Bench Hours"]
    ) == {"billable_column": None, "non_billable_column": None}


def test_missing_key_and_network_failure_return_unresolved(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(llm_column_detector, "load_dotenv", lambda path: None)
    attempted_requests = []

    def record_call(*args, **kwargs):
        attempted_requests.append(True)
        raise TimeoutError("unexpected request")

    monkeypatch.setattr(llm_column_detector, "urlopen", record_call)
    unresolved = {"billable_column": None, "non_billable_column": None}
    assert llm_column_detector.detect_billable_and_non_billable_via_llm(
        ["Chargeable Hours", "Bench Hours"]
    ) == unresolved
    assert attempted_requests == []

    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def timeout(request, timeout):
        raise TimeoutError("request timed out")

    monkeypatch.setattr(llm_column_detector, "urlopen", timeout)
    assert llm_column_detector.detect_billable_and_non_billable_via_llm(
        ["Chargeable Hours", "Bench Hours"]
    ) == unresolved
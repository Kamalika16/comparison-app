# Test Automation — API and UI

This adds two layers of automated testing on top of the existing
`backend/tests/test_hours_comparator.py` (which tests service functions
directly, in-process, with no HTTP or browser involved).

```
                    ┌─────────────────────────────┐
                    │        Test pyramid          │
                    ├─────────────────────────────┤
  slow, few    ───▶ │  UI tests (Playwright)       │  frontend/e2e/
                    │  real browser + real backend │
                    ├─────────────────────────────┤
                    │  API tests (pytest + TestClient) │ backend/tests/
                    │  real FastAPI app, no server, │
                    │  no browser                   │
                    ├─────────────────────────────┤
  fast, many   ───▶ │  Unit tests (pytest)         │  backend/tests/
                    │  service functions directly  │
                    └─────────────────────────────┘
```

The strategy: push as much coverage as possible down to the fast, cheap
layers, and reserve browser automation for the handful of flows that
actually need a real browser to verify (the button/state wiring, the file
upload widget, the download link).

---

## 1. API automation — `backend/tests/test_api_routes.py`

**What it is:** `pytest` + FastAPI's `TestClient` (built on `httpx`),
driving real HTTP requests through the actual ASGI app — CORS middleware,
multipart parsing, routing, and the handlers in `app/routes/compare.py` —
without a live server or the network. This is the layer that was missing
before (the existing test suite only imports service functions directly,
never goes through `/api/columns` or `/api/compare` as HTTP requests).

**Why `TestClient` over a live server + `requests`/Postman:** no process to
start/stop, no port to manage, no race conditions waiting for the server to
be ready, and it's just as real from the app's perspective — every
middleware and dependency still runs. Reach for a live server + real HTTP
client only if you need to test things TestClient can't simulate (actual
TCP behavior, timeouts, concurrent request handling under load).

**What it covers:**
- `/api/health`
- `/api/columns` — valid file, disallowed extension, corrupt file, missing field
- `/api/compare` — deterministic happy path, mismatched-name-but-matching-value
  identifiers (the core "different column names, same employee" feature),
  the ambiguous-hours-column rejection, disallowed extensions, and a
  regression guard that temp uploads are actually cleaned up
- `/api/reports/{id}/download` — success and 404
- Documents (rather than assumes) that `MAX_UPLOAD_SIZE` in `config.py`
  is not currently enforced anywhere

**Run it:**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest httpx
pytest -v                        # everything, service tests + API tests
pytest tests/test_api_routes.py -v   # just the new HTTP-layer tests
```
Confirmed passing: **13/13** new tests, **49/49** total.

**What this layer deliberately does NOT cover:** the LLM fallback path
(`llm_comparator.compare_via_llm`). That needs a real `GROQ_API_KEY` and a
live call to Groq, or a mocked `groq.Groq` client. If you want that
covered too, the natural next step is `pytest-mock`/`unittest.mock`
patching `app.services.llm_comparator._get_client` so no real network call
or API key is needed in CI — worth adding as a follow-up.

---

## 2. UI automation — `frontend/e2e/compare-flow.spec.js`

**What it is:** [Playwright](https://playwright.dev), driving a real
Chromium browser against the real running app (real Vite dev server +
real FastAPI backend, not mocked). Selectors deliberately use accessible
roles and labels (`getByRole("button", { name: ... })`, label text, real
element `id`s already present in the JSX) rather than added
`data-testid` attributes or CSS classes, so the tests read like a user's
actions and stay resilient to most styling refactors.

**Why Playwright over Selenium/Cypress here:** auto-waiting (no manual
`sleep`/polling for the column dropdowns to finish loading), first-class
file-upload support (`setInputFiles`) which this app relies on heavily,
built-in trace/video/screenshot capture on failure, and a single test
runner that also covers accessibility-style selectors well — a good fit
for a small React SPA with no existing test setup to migrate away from.

**What it covers:**
- Full happy path: upload both fixture files → wait for column detection
  → pick different-but-corresponding identifier columns → compare → see
  summary cards → download the report and check the filename pattern
- The `canCompare` gating logic (button stays disabled until both files
  *and* both identifier columns are set) — this exercises real component
  state, not just a visual check
- That picking a new file invalidates a stale result (a real behavior in
  `ComparePage.jsx`'s `handleFileSelected`)
- The disallowed-extension error path, round-tripped through the real
  backend's `400` response

**Prerequisites to actually run it** (see note below on why this couldn't
be executed in the analysis sandbox):
```bash
# Terminal 1
cd backend && source .venv/bin/activate
uvicorn app.main:app --port 8000

# Terminal 2
cd frontend
npm install --legacy-peer-deps   # see note below on the peer-dep warning
npx playwright install chromium  # one-time browser download
npm run dev

# Terminal 3
cd frontend
npm run e2e            # headless run
npm run e2e:ui         # interactive UI mode, great for writing new tests
npm run e2e:report     # open the HTML report after a run
```

**Note on `--legacy-peer-deps`:** this is pre-existing and unrelated to
Playwright — `package.json` pins `vite@^8.2.1` but `@vitejs/plugin-react`
only declares peer support up to `^7.0.0`. `npm install` alone will fail
with an `ERESOLVE` error; `--legacy-peer-deps` (or upgrading
`@vitejs/plugin-react`) works around it. Worth fixing independently of
this automation work.

**Note on sandbox execution:** in the environment used to build this, the
test file was verified to parse correctly and all 4 tests were confirmed
discoverable (`npx playwright test --list`), and both the real backend
(`uvicorn`) and real frontend (`npm run dev`) were started and confirmed
serving correctly. What could **not** be verified here is an actual
click-through run, because `npx playwright install` downloads browser
binaries from `cdn.playwright.dev`, which isn't on this sandbox's network
allowlist. Run `npm run e2e` locally or in CI (see below) to execute it
for real.

---

## 3. Tying both together — `.github/workflows/tests.yml`

A GitHub Actions workflow with two jobs:
1. `backend-tests` — installs Python deps, runs the full `pytest` suite
   (unit + API tests together, ~1 second, no server needed).
2. `e2e-tests` — starts the real backend and real frontend as background
   processes, waits for both to respond, installs Playwright's browser,
   runs the UI suite against them, and uploads the HTML report (and, on
   failure, both servers' logs) as build artifacts.

This mirrors the test pyramid: the fast job runs on every push and gates
the slower browser job, which only starts once the fast layer is green.

---

## Suggested next steps (not yet implemented)

- **Mock the LLM path** in `test_api_routes.py` so `compare_via_llm` gets
  coverage without a real `GROQ_API_KEY`/network call in CI.
- **Fix the `vite`/`@vitejs/plugin-react` peer-dependency mismatch** in
  `frontend/package.json` so plain `npm install` works without
  `--legacy-peer-deps`.
- **Add `data-testid` attributes** to `SummaryCards`/`MismatchTable` rows
  if the UI tests grow to assert on specific mismatch rows rather than
  just overall page state — accessible-role selectors get harder to keep
  unique as the table grows more repeated rows.
- **Contract test the LLM's JSON shape** against `master_prompt.txt`'s
  OUTPUT section directly (e.g., a schema/JSON-Schema validation step) so
  a prompt edit that silently breaks the expected shape is caught before
  it reaches `routes/compare.py`'s minimal shape check.

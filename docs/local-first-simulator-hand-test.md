# Sift — Local-First Simulator Hand-Test (≤ 15 min)

Verifies that Sift stays **honest, quiet, and recoverable** in personal
local-first mode when the backend is down, the model fails, or a stream breaks.

## Product mode under test

```
iOS Simulator / iPhone
  → local Sift backend on your Mac
  → local SQLite
  → external model API
```

## Prerequisites

- Local backend reachable at the configured base URL (default `http://127.0.0.1:8000`).
- App built in Debug onto an iOS 17+ simulator.
- At least one model provider key configured (Profile → AI & Research → Active Model).

> The app shows mock data only when no backend is configured. To confirm which
> you're on: **Profile → Developer → Local companion → Status** (`Available`
> vs `Unavailable` vs `Mock (preview data)`).

---

## Checklist

Each step lists the action and what "honest / quiet / recoverable" looks like.

1. **Capture with backend up** — type a concept and send.
   - You land in Follow-up; your original question shows immediately as a user bubble; "Writing the first card…" appears (no fake answer).

2. **Initial card generates** — wait for generation.
   - The assistant's first answer appears; tapping the top anchor opens the Reading card (title, lede, What it is / Why it matters / …).

3. **Follow-up streaming** — ask a follow-up.
   - Your follow-up shows; the answer streams in with a caret; when done it's a normal turn. The initial exchange above it does **not** disappear.

4. **Proposal accept / dismiss** — if a "Suggested update" card appears, try both.
   - Confirm update / Keep current both resolve quietly; no patch/JSON/revision text is ever shown.

5. **Restart the App** (stop & relaunch) — reopen the same concept.
   - The card and the full conversation are still there; only backend-authoritative turns show (no duplicates).

6. **Restart the backend** while the app is open, then pull-to-refresh Library.
   - No crash, no error spew; once it's back, content refreshes silently.

7. **Read an existing card with the backend DOWN** (stop the backend) — open a saved card.
   - The card is fully readable. A small "Showing your saved copy — Sift couldn't reach your local companion." notice appears. **No** 502 / 127.0.0.1 / FastAPI / stack trace.

8. **Capture fails** (backend down) — capture a brand-new concept.
   - You still land in Follow-up with your question visible; the card is clearly **unfinished** with a "Sift couldn't finish that explanation. Your original question is still here. Try again." card and an inline **Try again**. The failed draft is in Library marked "Needs retry". Restart the app → it's still there. Bring the backend back → **Try again** completes it.

9. **Follow-up fails** (backend down) — on a ready card, send a follow-up.
   - The timeline shows **no** blank assistant bubble, no duplicate loading, no raw error. The composer is **refilled with your question** and a quiet "question saved" hint shows. Bring the backend back → send again; it works.

10. **Mock vs unavailable** — check Profile → Developer → Local companion.
    - With a real backend down: Status = `Unavailable`, Last error = `Unreachable (connection)`, Endpoint shown.
    - With no backend configured (mock): Status = `Mock (preview data)`. The two are never silently confused; normal screens only ever show plain-language hints.

---

## Pass criteria

- Already-captured cards are always readable, even offline.
- A question the user typed is never lost (visible bubble or refilled composer).
- Failures are independent cards/notices — never an assistant "answer".
- Every failure has a visible, low-key recovery path ("Try again").
- No transport detail (HTTP status, `127.0.0.1`, FastAPI, provider error, stack
  trace) ever appears outside Profile → Developer.

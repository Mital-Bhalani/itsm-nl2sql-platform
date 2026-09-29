# agent/

**Now:** `naive_spike.py` — the Day 1 naive spike. It sends one hard-coded question to the OpenAI
API with no schema context and no guardrails, and prints whatever SQL comes back without validating
or running it. It exists to show why the naive approach fails. Run: `python agent/naive_spike.py`
(needs `OPENAI_API_KEY` in the project-root `.env`).

**Filled on Day 2–3.** This will hold the **NL2SQL agent loop**: the code that takes a plain-English
question, pulls in the semantic layer, prompts the OpenAI API for SQL, validates it (SELECT-only,
auto-LIMIT, PII masking), runs it read-only, and turns the rows back into a plain-English answer.

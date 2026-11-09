# PROMPTS

Built with Claude Code (Claude Opus 5.5) in the Claude desktop app.

<!-- Export the full conversation from the app and paste it below before submitting. -->

## Session 1

**Me:** Pasted the full task brief and asked: "Can you help me complete the interview task here, help me understand what they are asking and help build the project for it?"

**Assistant:** Explained the three parts, chose Python + FastAPI with in-memory state and a single lock,
wrote `app/` and `tests/`, the Dockerfile with a `test` stage, and NOTES.md. Ran the tests (two test
expectations were wrong in the first draft, not the code: a 30 Sep → 31 Oct cycle is 31 days, and a
366-day range from 2026-01-01 holds 12 invoices for that agreement), then built and smoke-tested the
container.

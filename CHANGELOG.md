# Changelog

## 0.1.0 — 2026-10-01

First release.

- `lane_start`, `lane_status`, `lane_summary`, `lane_stop` and `lane_resume` tools, and a `/muse` panel.
- Detached supervisor: chained steps, an acceptance command, stall detection, failure classes with backoff,
  and a per-lane lock so a resume never starts a second Muse beside a live one.
- One wake-up per finished lane, delivered only to the session that started it.
- Env-file values redacted from every lane file; lane folders are `0700`, files `0600`.

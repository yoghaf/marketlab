# Phase 10 Frontend UI/UX Audit

## Executive Summary

MarketLab frontend is functionally complete but reads like an engineering console. The trader-facing path needs fewer raw enums, fewer equal-weight cards, tighter tables, and a clearer answer to "what matters now".

## Most Confusing Pages

| page | issue | redesign direction |
|---|---|---|
| `/` | Too many raw metrics with no priority. | Make it an overview: system status, data readiness, signal candidates, Phase 6 decision, best strategy test, next action. |
| `/scanner` | Looks like debug output. Fallback and classifier internals dominate. | Rename mentally to Radar Market, show tier/setup/context first, move fallback/raw status into details. |
| `/signal-factory` | Candidate table exposes raw setup/status/anomaly labels. | Use trader-friendly labels, compact reason, detail disclosure for evidence/raw labels. |
| `/phase6-audit` | Answers are present but buried below raw enum tables. | Add top decision banner: whether Phase 7 is allowed and why. |
| `/strategy-arena` | Too many test mechanics before the verdict. | Focus on setup, R result, baseline/edge, sample, verdict. |
| `/data-health` and `/collectors` | Ops data is split and very raw. | Keep both pages, but make System Health trader-readable and Collectors developer-focused. |

## Raw Terms To Translate

- `MID_SHORT_FUTURES_LED` -> Mid Short + Futures Dominan
- `NO_SIGNAL_CONTEXT` -> Belum ada setup
- `RADAR_ONLY` -> Radar saja
- `SIGNAL_CANDIDATE` -> Kandidat signal
- `WATCHLIST_FOR_MORE_DATA` -> Pantau dulu
- `PHASE7_READY` -> Siap shadow forward-test
- `REJECT_FOR_PHASE7` -> Ditolak untuk Phase 7
- `NOISY` -> Terlalu noise
- `PARTIAL_DATA` -> Data sebagian
- `MISSING_ATR` -> ATR belum tersedia
- `MISSING_CANDLES` -> Candle belum cukup
- `TIMEFRAME_NOT_READY` -> Timeframe belum siap

Raw enum values should remain available in developer details, not dominate the primary table.

## Low Priority Cards/Tables

- Dashboard aggregation/rich/state/feature/outcome metric grids should move to System Health.
- Scanner fallback metadata should move into expandable detail.
- Signal Factory anomaly arrays should move into expandable detail.
- Strategy Arena raw setup descriptions should move into details.
- Collectors raw feature builder rows should be collapsed or grouped under developer details.

## Slow / Heavy Pages

| page | suspected cause | fix |
|---|---|---|
| `/strategy-arena` | Fetches full results artifact and renders up to 250 rows. | Default hide rejected, reduce visible rows, summarize top cards. |
| `/data-health` | Fetches broad `/api/data-health` payload with all symbol rows and many nested summaries. | Keep row count bounded visually and move raw tables down. |
| `/collectors` | Fetches many status endpoints at once. | Group primary health first; technical rows below. |
| `/signal-factory` | Candidate artifact can grow. | Default limit 50, compact table, details for evidence. |

## Reusable Components

Created/standardized in Phase 10:

- `AppShell`
- `PageHeader`
- `MetricCard`
- `SectionCard`
- `DecisionBanner`
- `FilterBar`
- `EmptyState`
- `LoadingSkeleton`
- `InfoTooltip`
- `StatusBadge` with translated labels

## Redesign Recommendations Per Page

| page | recommendation |
|---|---|
| `/` | Overview only: answer health, readiness, candidate availability, Phase 6 status, next action. |
| `/scanner` | Radar Market table with tier/setup/direction/context/update. Raw fallback in details. |
| `/signal-factory` | Candidate signal/radar/blocked/conflict summary and compact table with expandable evidence. |
| `/phase6-audit` | Decision banner plus feature readiness and candidate decision table. |
| `/strategy-arena` | Best setup cards and test result table sorted by conservative R; hide rejected by default. |
| `/universe` | Search/filter via query, clearer volume/change formatting, sticky table header. |
| `/data-health` | System Health summary first; developer details below. |
| `/collectors` | Developer/raw ops page with collector pulse, errors, and request usage. |

## Guardrail

This redesign does not change market logic, classifier rules, outcome calculations, Strategy Arena formula, collector behavior, or execution behavior.

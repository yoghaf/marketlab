#!/usr/bin/env bash
set -euo pipefail

cd /var/www/marketlab/backend
source .venv/bin/activate

SLEEP_SECONDS="${MARKETLAB_LOOP_SLEEP_SECONDS:-900}"

while true; do
  echo "[marketlab-loop] cycle start $(date -u)"

  python scripts/run_collector_loop.py --cycles 1 --interval-seconds 0
  python scripts/run_rich_futures_collector.py --periods 5m --include-funding --cycles 1
  python scripts/run_kline_collector.py --markets futures spot --cycles 1
  python scripts/run_ohlcv_aggregation.py --timeframes 15m 1h 4h 24h --markets futures spot --cycles 1
  python scripts/run_rich_5m_alignment.py --timeframes 15m 1h 4h 24h --cycles 1
  python scripts/run_snapshot_collector.py --cycles 1 --interval-seconds 0
  python scripts/run_snapshot_funding_alignment.py --timeframes 15m 1h 4h 24h --cycles 1
  python scripts/run_feature_builder_15m.py --cycles 1
  python scripts/run_feature_builder_1h.py --cycles 1
  python scripts/run_feature_context_join.py --cycles 1
  python scripts/run_psychology_labeler_15m.py --cycles 1
  python scripts/run_signal_candidate_classifier_readonly_15m.py --cycles 1
  python scripts/run_outcome_tracker_15m.py --cycles 1
  if ! python scripts/run_marketlab_research_cycle.py; then
    echo "[marketlab-loop] research cycle failed $(date -u)"
  fi

  echo "[marketlab-loop] cycle end $(date -u)"
  sleep "$SLEEP_SECONDS"
done

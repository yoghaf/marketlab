#!/usr/bin/env bash
set -euo pipefail

cd /var/www/marketlab/backend
source .venv/bin/activate

SLEEP_SECONDS="${MARKETLAB_LOOP_SLEEP_SECONDS:-900}"
LONG_TF_INTERVAL_SECONDS="${MARKETLAB_LONG_TF_INTERVAL_SECONDS:-3600}"
FULL_RESEARCH_INTERVAL_SECONDS="${MARKETLAB_FULL_RESEARCH_INTERVAL_SECONDS:-21600}"
FAST_LIMIT_WINDOWS="${MARKETLAB_FAST_LIMIT_WINDOWS:-12}"
LONG_TF_LIMIT_WINDOWS="${MARKETLAB_LONG_TF_LIMIT_WINDOWS:-8}"
STATE_DIR="${MARKETLAB_LOOP_STATE_DIR:-../data}"

mkdir -p "$STATE_DIR"

is_due() {
  local name="$1"
  local interval_seconds="$2"
  local marker="$STATE_DIR/${name}.last_run"
  local now
  local last

  now="$(date +%s)"
  last="0"
  if [[ -f "$marker" ]]; then
    last="$(cat "$marker" 2>/dev/null || echo 0)"
  fi

  if [[ ! "$last" =~ ^[0-9]+$ ]]; then
    last="0"
  fi

  (( now - last >= interval_seconds ))
}

mark_run() {
  local name="$1"
  date +%s > "$STATE_DIR/${name}.last_run"
}

while true; do
  echo "[marketlab-loop] cycle start $(date -u)"

  python scripts/run_collector_loop.py --cycles 1 --interval-seconds 0
  python scripts/run_kline_collector.py --markets futures spot --cycles 1
  python scripts/run_ohlcv_aggregation.py --timeframes 15m 1h --markets futures spot --limit-windows "$FAST_LIMIT_WINDOWS" --cycles 1
  python scripts/run_rich_futures_collector.py --periods 5m --include-funding --cycles 1
  python scripts/run_rich_5m_alignment.py --timeframes 15m 1h --limit-windows "$FAST_LIMIT_WINDOWS" --cycles 1
  python scripts/run_snapshot_collector.py --cycles 1 --interval-seconds 0
  python scripts/run_snapshot_funding_alignment.py --timeframes 15m 1h --limit-windows "$FAST_LIMIT_WINDOWS" --cycles 1
  python scripts/run_feature_builder_15m.py --cycles 1
  python scripts/run_feature_builder_1h.py --cycles 1
  python scripts/run_feature_context_join.py --cycles 1
  python scripts/run_psychology_labeler_15m.py --cycles 1
  python scripts/run_signal_candidate_classifier_readonly_15m.py --cycles 1
  python scripts/run_outcome_tracker_15m.py --cycles 1
  if ! python scripts/run_marketlab_research_cycle.py --mode light; then
    echo "[marketlab-loop] light research cycle failed $(date -u)"
  fi

  if is_due "long_timeframes" "$LONG_TF_INTERVAL_SECONDS"; then
    echo "[marketlab-loop] long timeframe maintenance start $(date -u)"
    if python scripts/run_ohlcv_aggregation.py --timeframes 4h 24h --markets futures spot --limit-windows "$LONG_TF_LIMIT_WINDOWS" --cycles 1 \
      && python scripts/run_rich_5m_alignment.py --timeframes 4h 24h --limit-windows "$LONG_TF_LIMIT_WINDOWS" --cycles 1 \
      && python scripts/run_snapshot_funding_alignment.py --timeframes 4h 24h --limit-windows "$LONG_TF_LIMIT_WINDOWS" --cycles 1; then
      mark_run "long_timeframes"
      echo "[marketlab-loop] long timeframe maintenance end $(date -u)"
    else
      echo "[marketlab-loop] long timeframe maintenance failed $(date -u)"
    fi
  fi

  if is_due "full_research" "$FULL_RESEARCH_INTERVAL_SECONDS"; then
    echo "[marketlab-loop] full research cycle start $(date -u)"
    if python scripts/run_marketlab_research_cycle.py --mode full; then
      mark_run "full_research"
      echo "[marketlab-loop] full research cycle end $(date -u)"
    else
      echo "[marketlab-loop] full research cycle failed $(date -u)"
    fi
  fi

  echo "[marketlab-loop] cycle end $(date -u)"
  sleep "$SLEEP_SECONDS"
done

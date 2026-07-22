#!/usr/bin/env bash
set -euo pipefail

cd /var/www/marketlab/backend
source .venv/bin/activate

SLEEP_SECONDS="${MARKETLAB_LOOP_SLEEP_SECONDS:-900}"
UNIVERSE_INTERVAL_SECONDS="${MARKETLAB_UNIVERSE_INTERVAL_SECONDS:-3600}"
FAST_PIPELINE_INTERVAL_SECONDS="${MARKETLAB_FAST_PIPELINE_INTERVAL_SECONDS:-900}"
FOUR_HOUR_INTERVAL_SECONDS="${MARKETLAB_FOUR_HOUR_INTERVAL_SECONDS:-14400}"
DAILY_INTERVAL_SECONDS="${MARKETLAB_DAILY_INTERVAL_SECONDS:-86400}"
FULL_RESEARCH_INTERVAL_SECONDS="${MARKETLAB_FULL_RESEARCH_INTERVAL_SECONDS:-21600}"
SHADOW_RESEARCH_INTERVAL_SECONDS="${MARKETLAB_SHADOW_RESEARCH_INTERVAL_SECONDS:-3600}"
FAST_LIMIT_WINDOWS="${MARKETLAB_FAST_LIMIT_WINDOWS:-3}"
FAST_CATCHUP_LIMIT_WINDOWS="${MARKETLAB_FAST_CATCHUP_LIMIT_WINDOWS:-12}"
FOUR_HOUR_LIMIT_WINDOWS="${MARKETLAB_FOUR_HOUR_LIMIT_WINDOWS:-3}"
FOUR_HOUR_CATCHUP_LIMIT_WINDOWS="${MARKETLAB_FOUR_HOUR_CATCHUP_LIMIT_WINDOWS:-8}"
DAILY_LIMIT_WINDOWS="${MARKETLAB_DAILY_LIMIT_WINDOWS:-2}"
DAILY_CATCHUP_LIMIT_WINDOWS="${MARKETLAB_DAILY_CATCHUP_LIMIT_WINDOWS:-4}"
STATE_DIR="${MARKETLAB_LOOP_STATE_DIR:-../data}"
STEP_RETRIES="${MARKETLAB_STEP_RETRIES:-2}"
STEP_RETRY_DELAY_SECONDS="${MARKETLAB_STEP_RETRY_DELAY_SECONDS:-10}"

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
  local timestamp="${2:-$(date +%s)}"
  echo "$timestamp" > "$STATE_DIR/${name}.last_run"
}

run_step() {
  local label="$1"
  shift
  local attempt=1

  while true; do
    if "$@"; then
      return 0
    fi
    if (( attempt >= STEP_RETRIES )); then
      echo "[marketlab-loop] $label failed after $attempt attempt(s) $(date -u)"
      return 1
    fi
    echo "[marketlab-loop] $label failed; retrying in ${STEP_RETRY_DELAY_SECONDS}s $(date -u)"
    sleep "$STEP_RETRY_DELAY_SECONDS"
    attempt=$((attempt + 1))
  done
}

due_window_limit() {
  local name="$1"
  local interval_seconds="$2"
  local minimum="$3"
  local maximum="$4"
  local marker="$STATE_DIR/${name}.last_run"
  local now
  local last
  local missed

  now="$(date +%s)"
  if [[ ! -f "$marker" ]]; then
    echo "$maximum"
    return
  fi
  last="$(cat "$marker" 2>/dev/null || echo 0)"
  if [[ ! "$last" =~ ^[0-9]+$ ]] || (( last <= 0 )); then
    echo "$maximum"
    return
  fi
  missed=$(( (now - last + interval_seconds - 1) / interval_seconds ))
  (( missed < minimum )) && missed="$minimum"
  (( missed > maximum )) && missed="$maximum"
  echo "$missed"
}

run_fast_pipeline() {
  local limit_windows="$1"
  run_step "ohlcv 15m/1h" python scripts/run_ohlcv_aggregation.py --timeframes 15m 1h --markets futures spot --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "rich alignment 15m/1h" python scripts/run_rich_5m_alignment.py --timeframes 15m 1h --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "snapshot/funding alignment 15m/1h" python scripts/run_snapshot_funding_alignment.py --timeframes 15m 1h --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "feature builder 15m" python scripts/run_feature_builder_15m.py --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "feature builder 1h" python scripts/run_feature_builder_1h.py --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "feature context join" python scripts/run_feature_context_join.py --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "psychology labeler" python scripts/run_psychology_labeler_15m.py --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "candidate classifier" python scripts/run_signal_candidate_classifier_readonly_15m.py --limit-windows "$limit_windows" --cycles 1 || return 1
  run_step "outcome tracker" python scripts/run_outcome_tracker_15m.py --limit-windows "$limit_windows" --cycles 1 || return 1
  if ! python scripts/run_marketlab_research_cycle.py --mode light; then
    echo "[marketlab-loop] light research cycle failed $(date -u)"
  fi
}

run_long_pipeline() {
  local timeframe="$1"
  local limit_windows="$2"
  run_step "ohlcv $timeframe" python scripts/run_ohlcv_aggregation.py --timeframes "$timeframe" --markets futures spot --limit-windows "$limit_windows" --cycles 1 \
    && run_step "rich alignment $timeframe" python scripts/run_rich_5m_alignment.py --timeframes "$timeframe" --limit-windows "$limit_windows" --cycles 1 \
    && run_step "snapshot/funding alignment $timeframe" python scripts/run_snapshot_funding_alignment.py --timeframes "$timeframe" --limit-windows "$limit_windows" --cycles 1
}

while true; do
  echo "[marketlab-loop] cycle start $(date -u)"

  if is_due "universe_refresh" "$UNIVERSE_INTERVAL_SECONDS"; then
    echo "[marketlab-loop] universe refresh start $(date -u)"
    if python scripts/run_universe_refresh.py; then
      mark_run "universe_refresh"
      echo "[marketlab-loop] universe refresh end $(date -u)"
    else
      echo "[marketlab-loop] universe refresh failed $(date -u)"
    fi
  fi

  if is_due "fast_pipeline" "$FAST_PIPELINE_INTERVAL_SECONDS"; then
    fast_started_at="$(date +%s)"
    fast_limit="$(due_window_limit "fast_pipeline" "$FAST_PIPELINE_INTERVAL_SECONDS" "$FAST_LIMIT_WINDOWS" "$FAST_CATCHUP_LIMIT_WINDOWS")"
    echo "[marketlab-loop] fast pipeline start limit_windows=$fast_limit $(date -u)"
    if run_fast_pipeline "$fast_limit"; then
      mark_run "fast_pipeline" "$fast_started_at"
      echo "[marketlab-loop] fast pipeline end $(date -u)"
    else
      echo "[marketlab-loop] fast pipeline failed; marker not advanced $(date -u)"
    fi
  else
    echo "[marketlab-loop] fast pipeline skipped; no new 15m cadence slot $(date -u)"
  fi

  if is_due "shadow_research" "$SHADOW_RESEARCH_INTERVAL_SECONDS"; then
    shadow_research_started_at="$(date +%s)"
    echo "[marketlab-loop] shadow research cycle start $(date -u)"
    if python scripts/run_marketlab_research_cycle.py --mode shadow; then
      mark_run "shadow_research" "$shadow_research_started_at"
      echo "[marketlab-loop] shadow research cycle end $(date -u)"
    else
      echo "[marketlab-loop] shadow research cycle failed $(date -u)"
    fi
  fi

  if is_due "four_hour_pipeline" "$FOUR_HOUR_INTERVAL_SECONDS"; then
    four_hour_started_at="$(date +%s)"
    four_hour_limit="$(due_window_limit "four_hour_pipeline" "$FOUR_HOUR_INTERVAL_SECONDS" "$FOUR_HOUR_LIMIT_WINDOWS" "$FOUR_HOUR_CATCHUP_LIMIT_WINDOWS")"
    echo "[marketlab-loop] 4h maintenance start limit_windows=$four_hour_limit $(date -u)"
    if run_long_pipeline "4h" "$four_hour_limit"; then
      mark_run "four_hour_pipeline" "$four_hour_started_at"
      echo "[marketlab-loop] 4h maintenance end $(date -u)"
    else
      echo "[marketlab-loop] 4h maintenance failed; marker not advanced $(date -u)"
    fi
  fi

  if is_due "daily_pipeline" "$DAILY_INTERVAL_SECONDS"; then
    daily_started_at="$(date +%s)"
    daily_limit="$(due_window_limit "daily_pipeline" "$DAILY_INTERVAL_SECONDS" "$DAILY_LIMIT_WINDOWS" "$DAILY_CATCHUP_LIMIT_WINDOWS")"
    echo "[marketlab-loop] 24h maintenance start limit_windows=$daily_limit $(date -u)"
    if run_long_pipeline "24h" "$daily_limit"; then
      mark_run "daily_pipeline" "$daily_started_at"
      echo "[marketlab-loop] 24h maintenance end $(date -u)"
    else
      echo "[marketlab-loop] 24h maintenance failed; marker not advanced $(date -u)"
    fi
  fi

  if is_due "full_research" "$FULL_RESEARCH_INTERVAL_SECONDS"; then
    full_research_started_at="$(date +%s)"
    echo "[marketlab-loop] optimization research cycle start $(date -u)"
    if python scripts/run_marketlab_research_cycle.py --mode optimization; then
      mark_run "full_research" "$full_research_started_at"
      echo "[marketlab-loop] optimization research cycle end $(date -u)"
    else
      echo "[marketlab-loop] optimization research cycle failed $(date -u)"
    fi
  fi

  echo "[marketlab-loop] cycle end $(date -u)"
  sleep "$SLEEP_SECONDS"
done

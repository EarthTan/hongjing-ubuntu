#!/usr/bin/env bash
# ralph.sh — 外层 Ralph loop,每轮全新 context
set -uo pipefail

MAX_ITER=${MAX_ITER:-40}
PROMPT_FILE=${PROMPT_FILE:-PROMPT.md}
LOG_DIR=logs
DONE_SIGNAL="RALPH_TASK_COMPLETE"

mkdir -p "$LOG_DIR"

[ -f "$PROMPT_FILE" ] || { echo "缺少 $PROMPT_FILE"; exit 1; }

for i in $(seq 1 "$MAX_ITER"); do
  ts=$(date +%m%d_%H%M%S)
  log="$LOG_DIR/iter_${i}_${ts}.log"
  echo "=== iteration $i/$MAX_ITER  ($(date '+%H:%M:%S')) ==="

  claude -p "$(cat "$PROMPT_FILE")" \
    --dangerously-skip-permissions \
    2>&1 | tee "$log"

  if grep -q "$DONE_SIGNAL" "$log"; then
    echo ">>> 完成信号出现,iteration $i 收工"
    exit 0
  fi

  # 快速失败保护:日志过短说明 CLI 本身出错(鉴权/网络),别空转烧轮数
  if [ "$(wc -c < "$log")" -lt 500 ]; then
    echo ">>> 输出异常短,暂停 60s 后重试(不计入进度)"
    sleep 60
  fi

  sleep 5
done

echo ">>> 跑满 $MAX_ITER 轮未完成,去看 PROGRESS.md 和 ISSUES.md"
exit 1

#!/usr/bin/env bash
# Run one named experiment and keep all artifacts under rjob_logs/<experiment>/.
set -euo pipefail

REPO="/mnt/shared-storage-user/adpc-share/chenxinquan/fastslow/tandem"
cd "$REPO"

EXPERIMENT=""
TASKS=""
CONCURRENCY=4
SLOW_MODEL="kimi-k3"
SLOW_KEY_IDS="1,2,3,4"
MAX_STEPS=500
MAX_WALL=14400
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage:
  bash scripts/run_experiment.sh \
    --experiment NAME --tasks ID1,ID2,... [--concurrency N] \
    [--slow-model NAME] [--slow-key-ids 1,2,3,4] \
    [--max-steps N] [--max-wall SECONDS] [--dry-run]

Experiment names use lowercase letters, digits and hyphens only.
Artifacts: rjob_logs/NAME/{manifest.json,batch.log,drivers/,NAME-TASK/}.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --experiment) EXPERIMENT="$2"; shift 2 ;;
        --tasks) TASKS="$2"; shift 2 ;;
        --concurrency) CONCURRENCY="$2"; shift 2 ;;
        --slow-model) SLOW_MODEL="$2"; shift 2 ;;
        --slow-key-ids) SLOW_KEY_IDS="$2"; shift 2 ;;
        --max-steps) MAX_STEPS="$2"; shift 2 ;;
        --max-wall) MAX_WALL="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ ! "$EXPERIMENT" =~ ^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$ ]]; then
    echo "invalid experiment name: use lowercase letters, digits and hyphens" >&2
    exit 2
fi
if [[ -z "$TASKS" || "$CONCURRENCY" -lt 1 || "$MAX_STEPS" -lt 1 || "$MAX_WALL" -lt 1 ]]; then
    usage >&2
    exit 2
fi

EXPERIMENT_ROOT="${TANDEM_EXPERIMENT_ROOT:-$REPO/rjob_logs}"
EXPERIMENT_DIR="$EXPERIMENT_ROOT/$EXPERIMENT"
DRIVER_DIR="$EXPERIMENT_DIR/drivers"
if [[ -e "$EXPERIMENT_DIR/manifest.json" ]]; then
    echo "experiment already exists: $EXPERIMENT_DIR" >&2
    exit 3
fi
mkdir -p "$DRIVER_DIR"

read -r STAGING < <(python3 - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("infra/config.json").read_text())["log"]["results_root"])
PY
)
export STAGING EXPERIMENT DRIVER_DIR TASKS CONCURRENCY SLOW_MODEL SLOW_KEY_IDS MAX_STEPS MAX_WALL
python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path

experiment = os.environ["EXPERIMENT"]
directory = Path(os.environ["DRIVER_DIR"]).parent
args = {
    "experiment": experiment,
    "tasks": os.environ["TASKS"].split(","),
    "concurrency": int(os.environ["CONCURRENCY"]),
    "slow_model": os.environ["SLOW_MODEL"],
    "slow_key_ids": [int(item) for item in os.environ["SLOW_KEY_IDS"].split(",")],
    "max_steps": int(os.environ["MAX_STEPS"]),
    "max_wall_seconds": float(os.environ["MAX_WALL"]),
    "watch_timeout_seconds": float(os.environ["MAX_WALL"]) + 600,
    "git_describe": subprocess.check_output(
        ["git", "describe", "--always", "--dirty"], text=True
    ).strip(),
}
(directory / "manifest.json").write_text(
    json.dumps(args, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY

exec > >(tee "$EXPERIMENT_DIR/batch.log") 2>&1

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "dry-run: experiment=$EXPERIMENT tasks=$TASKS output=$EXPERIMENT_DIR"
    exit 0
fi

env PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from tandem_eval.rjob import load_config, sync_repo

config = load_config("infra/config.json")
sync_repo(Path("."), Path(config["eval"]["deploy_root"]))
PY

run_task() {
    local task="$1"
    local run_id="${EXPERIMENT}-${task}"
    local driver_log="${DRIVER_DIR}/${task}.driver.log"
    local rc=0

    tandem-eval rjob run \
        --run-id "$run_id" \
        --benchmark osworld21 \
        --tasks "$task" \
        --execution-mode stage \
        --stage-max-actions 10 \
        --slow-model "$SLOW_MODEL" \
        --slow-key-ids "$SLOW_KEY_IDS" \
        --max-steps "$MAX_STEPS" \
        --max-wall "$MAX_WALL" \
        --poll 60 \
        --timeout "$((MAX_WALL + 600))" \
        --repo . \
        --config infra/config.json \
        --no-sync >"$driver_log" 2>&1 || rc=$?

    if [[ -d "$STAGING/$run_id" ]]; then
        mkdir -p "$EXPERIMENT_DIR/$run_id"
        rsync -a "$STAGING/$run_id/" "$EXPERIMENT_DIR/$run_id/"
    fi
    printf '{"task":"%s","returncode":%d,"run_id":"%s","logs":"%s"}\n' \
        "$task" "$rc" "$run_id" "$EXPERIMENT_DIR/$run_id"
}
export -f run_task

IFS=',' read -r -a TASK_ARRAY <<< "$TASKS"
for task in "${TASK_ARRAY[@]}"; do
    run_task "$task" &
    while [[ "$(jobs -pr | wc -l)" -ge "$CONCURRENCY" ]]; do
        wait -n
    done
done
wait

echo "experiment complete: $EXPERIMENT_DIR"

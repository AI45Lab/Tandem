#!/usr/bin/env bash
# rjob worker 内入口：读取 job spec，进入 tandem_eval entry。
# mock 基准直接跑（无需共享资源/docker）；真实基准（osworld1/2）在 M3 接入共享 env.sh
# 与 docker 准备流程（见 docs/RESULT_DIR_CONTRACT.md 与重构计划 M3）。
set -euo pipefail

SPEC="${1:?用法: worker.sh <job spec json 绝对路径>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

BENCHMARK="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("benchmark",""))' "$SPEC")"
RUN_ROOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["output_root"])' "$SPEC")"
mkdir -p "$RUN_ROOT/worker"

if [ "$BENCHMARK" = "mock" ]; then
  python3 -m tandem_eval entry --spec "$SPEC" 2>&1 | tee "$RUN_ROOT/worker/entry.log"
  exit "${PIPESTATUS[0]}"
fi

# ---- 真实基准（M3）：加载共享资源 env.sh + docker 准备 + entry ----
SHARED_ENV="${SA_CUA_SHARED_ENV:-/mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/shared_resources/sa_cua/env.sh}"
if [ ! -f "$SHARED_ENV" ]; then
  echo "真实基准需要共享资源 env.sh（$SHARED_ENV 不存在）；M3 里程碑接入" >&2
  exit 3
fi
# shellcheck disable=SC1090
source "$SHARED_ENV"
echo "真实基准执行链在 M3 落地（dockerd/inner image/OSWORLD_PYTHON）" >&2
exit 3

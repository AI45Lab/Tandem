#!/usr/bin/env bash
# rjob worker 内入口：读取 job spec，进入 tandem_eval entry。
# - mock 基准：直接用系统 python3 跑（无需共享资源/docker）。
# - osworld1/2：加载共享资源 env.sh（冻结 venv/评测工具/JEV），启动 dockerd 并拉取
#   inner 镜像（VM 容器），然后用 OSWORLD_PYTHON 跑 entry（Pillow 等依赖已在冻结 venv 内）。
set -euo pipefail

SPEC="${1:?用法: worker.sh <job spec json 绝对路径>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

read -r BENCHMARK OUTPUT_ROOT < <(python3 -c '
import json, sys
spec = json.load(open(sys.argv[1]))
print(spec.get("benchmark", "mock"), spec["output_root"])' "$SPEC")
mkdir -p "$OUTPUT_ROOT/worker"

if [ "$BENCHMARK" = "mock" ]; then
  python3 -m tandem_eval entry --spec "$SPEC" 2>&1 | tee "$OUTPUT_ROOT/worker/entry.log"
  exit "${PIPESTATUS[0]}"
fi

# ---- 真实基准：共享资源 + docker 准备 ----
SHARED_ENV="${SA_CUA_SHARED_ENV:-/mnt/shared-storage-user/evobox-share-gpfs2/xuyuanxun/shared_resources/sa_cua/env.sh}"
if [ ! -f "$SHARED_ENV" ]; then
  echo "缺少共享资源 env.sh: $SHARED_ENV" | tee "$OUTPUT_ROOT/worker/entry.log" >&2
  exit 3
fi
# shellcheck disable=SC1090
source "$SHARED_ENV"

REGISTRY_SECRET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["secrets"].get("registry_secret") or "")' "$SPEC")"
if [ -z "$REGISTRY_SECRET" ] || [ ! -f "$REGISTRY_SECRET" ]; then
  echo "缺少 registry 凭据: ${REGISTRY_SECRET:-<未配置>}" | tee "$OUTPUT_ROOT/worker/entry.log" >&2
  exit 3
fi

INNER_IMAGE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["code"]["images"]["inner"])' "$SPEC")"
# 平台可能预注入不可用的代理（真机 2026-10-20：httpproxy-headless-dev-test 无法解析），
# 一律覆盖为已知可用代理，不继承环境变量。
PROXY="http://httpproxy-headless.kubebrain.svc.pjlab.local:3128"
export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" http_proxy="$PROXY" https_proxy="$PROXY"
export NO_PROXY='10.0.0.0/8,100.96.0.0/12,localhost,127.0.0.1,.pjlab.org.cn'
export no_proxy="$NO_PROXY"

mkdir -p "$HOME/.docker"
cp "$REGISTRY_SECRET" "$HOME/.docker/config.json"
chmod 600 "$HOME/.docker/config.json"

DOCKER_ROOT="$(mktemp -d /tmp/tandem-docker.XXXXXX)"
dockerd --host=unix:///var/run/docker.sock \
  --data-root="$DOCKER_ROOT/data" --exec-root="$DOCKER_ROOT/exec" \
  --http-proxy="$PROXY" --https-proxy="$PROXY" --no-proxy="$NO_PROXY" \
  > "$OUTPUT_ROOT/worker/dockerd.log" 2>&1 &
for _ in $(seq 1 90); do
  docker info >/dev/null 2>&1 && break
  sleep 2
done
docker info > "$OUTPUT_ROOT/worker/docker-info.txt" 2>&1 || {
  echo "dockerd 未就绪" | tee -a "$OUTPUT_ROOT/worker/entry.log" >&2; exit 3; }
docker pull "$INNER_IMAGE" > "$OUTPUT_ROOT/worker/docker-pull.log" 2>&1
docker tag "$INNER_IMAGE" happysixd/osworld-docker:latest

"$OSWORLD_PYTHON" -c 'import easyocr, PIL; assert callable(easyocr.Reader)' \
  > "$OUTPUT_ROOT/worker/deps-check.log" 2>&1 || {
  echo "共享 venv 依赖检查失败" | tee -a "$OUTPUT_ROOT/worker/entry.log" >&2; exit 3; }

"$OSWORLD_PYTHON" -m tandem_eval entry --spec "$SPEC" 2>&1 | tee "$OUTPUT_ROOT/worker/entry.log"
exit "${PIPESTATUS[0]}"

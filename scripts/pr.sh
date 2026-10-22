#!/usr/bin/env bash
# 向开源上游提 PR：分支推到自己的 fork，PR 目标指向上游 main。
#
# remote 约定（见 docs/CLUSTER_RUNTIME.md 与本脚本头注释）：
#   origin   = 自己的 fork     —— 推送目标
#   upstream = 上游仓库        —— PR 目标（main 受保护，只能走 PR）
#
# 用法：
#   bash scripts/pr.sh                        # 当前分支，按最近一次提交信息当标题
#   bash scripts/pr.sh feature/foo "标题"      # 指定分支与标题
#   bash scripts/pr.sh feature/foo "标题" "正文"
#
# 提交前应先同步上游：
#   git fetch upstream && git rebase upstream/main
set -euo pipefail

UPSTREAM_REPO="${UPSTREAM_REPO:-AI45Lab/Tandem}"
FORK_OWNER="${FORK_OWNER:-two-tiger}"
FORK_REPO="${FORK_REPO:-$FORK_OWNER/Tandem}"

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
TITLE="${2:-}"
BODY="${3:-}"

if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  echo "不能从 $BRANCH 提 PR：上游 main 受保护，请先切特性分支" >&2
  echo "  git switch -c feature/<名字>" >&2
  exit 1
fi

if [ -z "$TITLE" ]; then
  TITLE="$(git log -1 --format=%s)"
fi
if [ -z "$BODY" ]; then
  # 非交互环境（CI / agent）下 gh 要求必须有 body：退回提交信息正文
  BODY="$(git log -1 --format=%b)"
fi
if [ -z "$BODY" ]; then
  BODY="$TITLE"
fi

echo "→ 推送分支到 fork：$FORK_REPO ($BRANCH)"
git push -u origin "$BRANCH"

args=(pr create --repo "$UPSTREAM_REPO" --head "$FORK_OWNER:$BRANCH" --base main --title "$TITLE")
if [ -n "$BODY" ]; then
  args+=(--body "$BODY")
fi

echo "→ 开 PR：$UPSTREAM_REPO:main ← $FORK_OWNER:$BRANCH"
gh "${args[@]}"

"""tandem-eval CLI 占位：为 infra/worker.sh 与 CI 提前接线，M2 实装 entry。"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tandem-eval", description="Tandem 集群测评入口")
    sub = parser.add_subparsers(dest="command", required=True)
    entry = sub.add_parser("entry", help="按 job spec 启动一次测评（M2 提供）")
    entry.add_argument("--spec", required=True, help="job spec JSON 路径")
    args = parser.parse_args(argv)
    print(f"tandem-eval {args.command} 将在 M2 实装（spec 已接收: {args.spec}）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

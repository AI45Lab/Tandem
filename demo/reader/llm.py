"""流式解析 llm_calls.jsonl → token 用量 + 慢模型原文。

**这是全站最重的一个文件**：单题 64MB（base64 截图内嵌在 `request` 里），
整批 39GB。因此：

- 逐行读，**禁止 `read()` / `readlines()`**（`tests/demo/test_reader.py` 里有断言）；
- 只从 `response` 取 `usage` 与 `choices[0].message.content`，**不碰 `request`**；
- 单行超过 `MAX_LINE_BYTES` 直接跳过并计数（不让一行坏数据吃掉内存）。

口径与 `tools/batch_summary._episode_tokens` 一致：每行算一次调用，
prompt/completion 取 `response.usage`（缺失则回退顶层 `usage`）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

#: 单行上限（超过视为异常行，跳过并计数）
MAX_LINE_BYTES = 8 * 1024 * 1024

#: 单题最多保留的原文条数与每条长度
MAX_TEXTS = 8
MAX_TEXT_CHARS = 4000


def iter_llm_calls(episode_dir: Path) -> Iterator[dict[str, Any]]:
    """逐行产出慢模型调用记录（已丢弃 `request` 里的 base64）。"""
    path = episode_dir / "llm_calls.jsonl"
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if len(line) > MAX_LINE_BYTES:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            record.pop("request", None)  # base64 截图在这里，直接丢掉
            yield record


def _usage_of(record: dict[str, Any]) -> dict[str, Any]:
    usage = (record.get("response") or {}).get("usage") or record.get("usage") or {}
    return usage if isinstance(usage, dict) else {}


def read_llm_usage(episode_dir: Path) -> dict[str, Any]:
    """慢模型 token 用量：总数 + 按 role 拆分。

    `calls` / `prompt_tokens` / `completion_tokens` 与 `tools/batch_summary` 逐位一致
    （一致性测试守着这条线）。
    """
    total = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
    }
    by_role: dict[str, dict[str, int]] = {}
    for record in iter_llm_calls(episode_dir):
        role = str(record.get("role") or "unknown")
        usage = _usage_of(record)
        bucket = by_role.setdefault(
            role, {key: 0 for key in ("calls", "prompt_tokens", "completion_tokens",
                                      "cached_tokens", "reasoning_tokens")}
        )
        bucket["calls"] += 1
        total["calls"] += 1
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)):
                bucket[key] += int(value)
                total[key] += int(value)
        details = usage.get("completion_tokens_details") or {}
        reasoning = details.get("reasoning_tokens")
        if isinstance(reasoning, (int, float)):
            bucket["reasoning_tokens"] += int(reasoning)
            total["reasoning_tokens"] += int(reasoning)
        prompt_details = usage.get("prompt_tokens_details") or {}
        cached = prompt_details.get("cached_tokens")
        if isinstance(cached, (int, float)):
            bucket["cached_tokens"] += int(cached)
            total["cached_tokens"] += int(cached)
    return {"total": total, "by_role": by_role}


def read_llm_texts(
    episode_dir: Path, *, limit: int = MAX_TEXTS, max_chars: int = MAX_TEXT_CHARS
) -> list[dict[str, Any]]:
    """慢模型原文（**只搬运，不改写**）。

    保留最先出现的若干条调用原文，供播放器上轨流式打字。
    每条带 `truncated` 标记，UI 要如实说明"原文被截断"。
    """
    texts: list[dict[str, Any]] = []
    for record in iter_llm_calls(episode_dir):
        response = record.get("response") or {}
        choices = response.get("choices") or []
        if not choices:
            continue
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        texts.append(
            {
                "role": str(record.get("role") or "unknown"),
                "attempt": record.get("attempt"),
                "time": record.get("time"),
                "text": content[:max_chars],
                "truncated": len(content) > max_chars,
            }
        )
        if len(texts) >= limit:
            break
    return texts


def read_llm_errors(episode_dir: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """带 `api_exception` 的调用（模型侧失败的证据）。"""
    errors: list[dict[str, Any]] = []
    for record in iter_llm_calls(episode_dir):
        exception = record.get("api_exception")
        if not exception:
            continue
        errors.append(
            {
                "role": record.get("role"),
                "attempt": record.get("attempt"),
                "time": record.get("time"),
                "exception": exception,
            }
        )
        if len(errors) >= limit:
            break
    return errors

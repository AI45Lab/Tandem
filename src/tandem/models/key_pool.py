"""慢模型 API key 的优先级选择与跨 worker 冷却；凭据不进入共享状态。"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path

POOL_BASE_URLS = {
    "minimax": "https://api.minimax.cn/v1",
    "kimi": "https://api.kimi.com/coding/v1",
}


class PoolExhausted(RuntimeError):
    """当前请求已没有可用的 key。"""


def validate_key_ids(key_ids) -> None:
    if (not isinstance(key_ids, list)
            or any(type(number) is not int or number < 1 for number in key_ids)
            or len(set(key_ids)) != len(key_ids)):
        raise ValueError("key_ids must be a list of distinct positive integers")


def classify_api_error(provider: str, status: int, code, message: str) -> tuple[str, float]:
    """返回错误类别与 key 冷却秒数；零冷却的错误不切 key。"""
    code = str(code)
    if status == 401 or (provider == "minimax" and code in {"1004", "2049"}):
        return "invalid_key", 3600
    if provider == "minimax":
        if code in {"1008", "2053", "2056", "2067"}:
            return "quota_exhausted", 300
        if code in {"1002", "1041", "1045", "2045", "2046", "2047", "2062"}:
            return "rate_limited", 60
        if code in {"2022", "2057", "2061", "2068"}:
            return "model_permission", 3600
        if code in {"1000", "1001", "1024", "1033", "2064", "2066"}:
            return "transient", 0
    if provider == "kimi":
        text = message.lower()
        if status == 429 and any(part in text for part in (
            "usage limit", "credit balance is insufficient", "extra usage balance",
        )):
            return "quota_exhausted", 300
        if status == 429 and "engine is currently overloaded" in text:
            return "transient", 0
        if status == 403 and any(part in text for part in (
            "subscription does not have access", "current plan supports only",
            "unable to verify your membership benefits",
        )):
            return "model_permission", 3600
    if status == 429:
        return "rate_limited", 60
    if status >= 500 or status == 408:
        return "transient", 0
    return "fatal", 0


def retry_after_seconds(value: str | None, default: float) -> float:
    """Retry-After 支持秒数或 HTTP 日期；缺失时用本地冷却策略。"""
    if value is None:
        return default
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return default


class ApiKeyPool:
    def __init__(self, credentials: dict):
        base_url = credentials["base_url"].rstrip("/")
        self.provider = next(
            (name for name, url in POOL_BASE_URLS.items() if base_url == url), "custom"
        )
        self.state_file: Path | None = None
        self._local_state: dict = {}
        self._preferred_id: str | None = None
        self._selection_group = ""
        options = credentials.get("key_pool") or {}
        key_ids = options.get("key_ids", [])
        validate_key_ids(key_ids)
        if credentials.get("api_key") and key_ids:
            raise ValueError("manual api_key cannot be combined with key_pool.key_ids")
        # 手填 key 完全独立；无号池时也保留客户端原有的无鉴权 endpoint 用法。
        if credentials.get("api_key") or not options:
            self.keys = [{"id": "manual", "priority": 1, "api_key": credentials.get("api_key", "")}]
            self._secrets = [row["api_key"] for row in self.keys if row["api_key"]]
            return
        provider = options["provider"]
        if provider not in POOL_BASE_URLS or POOL_BASE_URLS[provider] != base_url:
            raise ValueError("key_pool provider does not match its official base_url")
        self.keys = json.loads(Path(options["credentials_file"]).read_text(encoding="utf-8"))[provider]
        if not isinstance(self.keys, list) or not self.keys:
            raise ValueError("key_pool must contain a nonempty credential list")
        for row in self.keys:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                raise ValueError("key_pool entries require a nonempty id")
            if type(row.get("priority")) is not int or row["priority"] < 1:
                raise ValueError("key_pool priorities must be positive integers")
            key = row.get("api_key")
            if not isinstance(key, str) or not key or key != key.strip():
                raise ValueError("key_pool contains an empty or whitespace-padded api_key")
        if len({row["id"] for row in self.keys}) != len(self.keys):
            raise ValueError("key_pool contains duplicate ids")
        if len({row["api_key"] for row in self.keys}) != len(self.keys):
            raise ValueError("key_pool contains duplicate keys")
        self._secrets = [row["api_key"] for row in self.keys]
        self.state_file = Path(options["state_file"])
        if not self.state_file.is_absolute() or not Path(options["credentials_file"]).is_absolute():
            raise ValueError("key_pool paths must be absolute")
        if key_ids:
            if max(key_ids) > len(self.keys):
                raise ValueError("key_pool.key_ids contains an out-of-range credential number")
            self.keys = [self.keys[number - 1] for number in sorted(key_ids)]
            self._selection_group = ",".join(str(number) for number in sorted(key_ids))
            with self._state() as state:
                cursors = state.setdefault("worker_cursors", {})
                available = self._available(state) or self.keys
                cursor = cursors.get(self._selection_group, 0)
                self._preferred_id = available[cursor % len(available)]["id"]
                cursors[self._selection_group] = (cursor + 1) % len(available)

    @contextmanager
    def _state(self) -> Iterator[dict]:
        if self.state_file is None:
            yield self._local_state
            return
        parent = self.state_file.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        owner = parent.stat()
        descriptor = os.open(str(self.state_file) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "r+") as lock:
            # rjob worker 以 root 运行时，私有状态仍归目录所有者管理。
            if os.geteuid() == 0:
                os.fchown(lock.fileno(), owner.st_uid, owner.st_gid)
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
            yield state.setdefault(self.provider, {})
            descriptor, temporary = tempfile.mkstemp(prefix=self.state_file.name + ".", dir=parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    if os.geteuid() == 0:
                        os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
                    json.dump(state, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.state_file)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def _available(self, state: dict, excluded: set[str] | None = None) -> list[dict]:
        excluded = excluded or set()
        now = time.time()
        cooldowns = state.get("cooldowns", {})
        return [row for row in self.keys if row["id"] not in excluded
                and cooldowns.get(row["id"], {}).get("until", 0) <= now]

    def select(self, excluded: set[str] | None = None) -> dict:
        with self._state() as state:
            cooldowns = state.get("cooldowns", {})
            available = self._available(state, excluded)
            if not available:
                next_retry = min(
                    (cooldowns.get(row["id"], {}).get("until", 0) for row in self.keys), default=0
                )
                raise PoolExhausted(
                    f"pool_exhausted: provider={self.provider}, next_retry_at={next_retry}"
                )
            if self._preferred_id is not None:
                preferred = next((row for row in available if row["id"] == self._preferred_id), None)
                if preferred is not None:
                    return preferred
                tier = self.keys
                cursor_name = "selected:" + self._selection_group
            else:
                priority = min(row["priority"] for row in available)
                tier = [row for row in self.keys if row["priority"] == priority]
                cursor_name = str(priority)
            cursors = state.setdefault("cursors", {})
            cursor = cursors.get(cursor_name, 0)
            indices = ((cursor + offset) % len(tier) for offset in range(len(tier)))
            index = next(index for index in indices if tier[index] in available)
            cursors[cursor_name] = (index + 1) % len(tier)
            return tier[index]

    def cooldown(self, key_id: str, seconds: float, reason: str) -> None:
        with self._state() as state:
            cooldowns = state.setdefault("cooldowns", {})
            previous = cooldowns.get(key_id, {}).get("until", 0)
            cooldowns[key_id] = {"until": max(previous, time.time() + seconds), "reason": reason}

    def redact(self, value):
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

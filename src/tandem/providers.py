"""Kimi JSON 传输客户端（含脱敏审计）。从旧仓库 providers.py 按契约移植。
全量请求/响应落盘（llm_calls.jsonl）属于 M2 的 recorder，此处保持审计日志。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

# 空正文（全留在思考通道）或截断时，下一次重试升档思考强度，避免原样重发重复失败
_REASON_EFFORT_LADDER = {"low": "medium", "medium": "high"}


def extract_json_object(text: str):
    """从模型正文中抢救 JSON：剥围栏后，若剩余文本不是纯 JSON，抽取首个平衡的 {…}。
    返回解析后的 dict；无 JSON 或解析失败返回 None。"""
    stripped = text.strip()
    for prefix in ("```json", "```"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    stripped = stripped.strip()
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    start = stripped.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(stripped)):
            if stripped[index] == "{":
                depth += 1
            elif stripped[index] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(stripped[start:index + 1])
                        if isinstance(value, dict):
                            return value
                    except ValueError:
                        break
                    break
        start = stripped.find("{", start + 1)
    return None


class KimiClient:
    def __init__(self, credential_file, config, audit_path: Path, llm_sink=None):
        if isinstance(credential_file, dict):
            self.credentials = dict(credential_file)
        else:
            self.credentials = json.loads(Path(credential_file).read_text(encoding="utf-8"))
        self.config = config
        self.audit_path = audit_path
        # llm_sink(role=..., request=..., response=..., **meta)：全量请求/响应落盘钩子，
        # 由 tandem_eval.recorder 提供（llm_calls.jsonl）；None 时仅审计。
        self.llm_sink = llm_sink

    def json_request(self, messages, validate, *, role):
        credentials = self.credentials
        payload = {
            "model": credentials.get("model", "kimi-k3"),
            "messages": messages,
            "stream": False,
            "max_tokens": self.config.kimi_max_tokens,
        }
        effort = getattr(self.config, "kimi_reasoning_effort", "low")
        if effort == "off":
            payload["enable_thinking"] = False
        else:
            payload["reasoning_effort"] = effort
        def build_request():
            return urllib.request.Request(
                credentials["base_url"].rstrip("/") + "/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    **(
                        {"Authorization": "Bearer " + credentials["api_key"]}
                        if credentials.get("api_key")
                        else {}
                    ),
                    "Content-Type": "application/json",
                },
            )

        opener = (
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open
            if self.config.kimi_direct_api
            else urllib.request.urlopen
        )

        def audit(event, started, attempt, **details):
            record = {
                "event": event,
                "provider": "kimi",
                "role": role,
                "attempt": attempt + 1,
                "time": time.time(),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "request_bytes": len(request.data),
                **details,
            }
            text = json.dumps(record, ensure_ascii=False)
            print(text, flush=True)
            with self.audit_path.open("a", encoding="utf-8") as log:
                log.write(text + "\n")

        def public_headers(headers):
            allowed = {
                "server",
                "content-type",
                "via",
                "date",
                "retry-after",
                "x-request-id",
                "request-id",
                "x-acs-request-id",
                "x-trace-id",
                "x-envoy-upstream-service-time",
            }
            return {key: value for key, value in headers.items() if key.lower() in allowed}

        def redact(text):
            key = credentials.get("api_key")
            return text.replace(key, "[REDACTED]") if key else text

        for attempt in range(5):
            started = time.perf_counter()
            request = build_request()  # 每次重试重建：升档思考强度需重新序列化
            audit("request_start", started, attempt)
            try:
                with opener(request, timeout=self.config.kimi_timeout_seconds) as response:
                    raw = json.load(response)
                    if self.llm_sink is not None:
                        self.llm_sink(
                            role=role,
                            request={"payload": payload, "messages": messages},
                            response=raw,
                            attempt=attempt + 1,
                        )
                    audit(
                        "http_response",
                        started,
                        attempt,
                        http_status=response.status,
                        headers=public_headers(response.headers),
                        finish_reason=raw["choices"][0].get("finish_reason"),
                        usage=raw.get("usage"),
                    )
                    content = raw["choices"][0]["message"]["content"].strip()
                    finish_reason = raw["choices"][0].get("finish_reason")
                if finish_reason == "length":
                    completion_tokens = (raw.get("usage") or {}).get("completion_tokens")
                    raise ValueError(
                        f"Kimi response truncated by max_tokens (finish_reason=length, "
                        f"completion_tokens={completion_tokens}); raise kimi_max_tokens"
                    )
                if not content and raw["choices"][0]["message"].get("reasoning_content"):
                    raise ValueError(
                        "Kimi returned empty content (all completion tokens stayed in the "
                        "reasoning channel); escalating reasoning_effort for the next attempt"
                    )
                value = extract_json_object(content)
                if value is None:
                    raise ValueError("Kimi response contains no JSON object")
                if not validate(value):
                    raise ValueError("Kimi response is missing required fields")
                return value
            except urllib.error.HTTPError as error:
                body = redact(error.read().decode("utf-8", errors="replace"))
                audit(
                    "http_error",
                    started,
                    attempt,
                    http_status=error.code,
                    headers=public_headers(error.headers),
                    response=body[:2000],
                )
                if attempt == (4 if error.code == 403 else 2):
                    raise
                # 403 多为 TPM/风控限流：指数退避（60/120/240/480s）等配额恢复
                time.sleep(60 * (2 ** attempt) if error.code == 403 else 30)
            except (urllib.error.URLError, TimeoutError, ValueError) as error:
                audit(
                    "transport_or_validation_error",
                    started,
                    attempt,
                    error_type=type(error).__name__,
                    error=redact(str(error))[:1000],
                )
                if attempt == 2:
                    raise
                # 内容级失败（空正文/截断/非法 JSON）时升档思考强度后重试，不原样重发
                current_effort = payload.get("reasoning_effort")
                if current_effort in _REASON_EFFORT_LADDER:
                    payload["reasoning_effort"] = _REASON_EFFORT_LADDER[current_effort]
                time.sleep(30)
        raise RuntimeError("Model request retries exhausted; no valid JSON response")

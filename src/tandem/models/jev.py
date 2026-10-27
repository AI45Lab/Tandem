"""JEV：快模型 omni 选择策略（HTTP 排序服务）。从旧仓库 gui/jev_omni_policy.py 按契约移植；
唯一接口差异：opener 可注入（测试），默认行为不变。"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..gui.targets import UITarget
from .ranking import Ranking, build_choice_requests


class JevOmniPolicy:
    def __init__(self, endpoint: str, timeout_seconds: float = 300, opener=None,
                 image_stage: tuple[str, str] | None = None):
        self.endpoint = str(endpoint).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
        # (写视角目录, 排序服务宿主机读视角目录)：/rank 要求 image_path 在服务端可读，
        # 截图本体在 adpc 时先暂存到 evobox 中转目录（按内容哈希命名去重）。
        self.image_stage = image_stage

    def _stage_screenshot(self, screenshot: Path | None):
        """返回传给服务的 image_path：暂存开启时为排序服务宿主机读视角路径，否则原样。"""
        if not self.image_stage or screenshot is None:
            return screenshot
        source = Path(screenshot)
        if not source.is_file():
            return screenshot
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
        write_dir, read_dir = self.image_stage
        target = Path(write_dir) / f"{source.stem}_{digest}.png"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return str(Path(read_dir) / target.name)

    def rank(
        self,
        *,
        stage_goal: str,
        intent: str,
        active_window: str,
        targets: list[UITarget],
        action_space,
        recent_actions: list[dict[str, Any]],
        screenshot: Path | None = None,
    ) -> Ranking:
        screenshot = self._stage_screenshot(screenshot)
        candidates = action_space.candidates()
        operation_request, action_requests = build_choice_requests(
            stage_goal=stage_goal,
            intent=intent,
            active_window=active_window,
            targets=targets,
            action_space=action_space,
            recent_actions=recent_actions,
        )
        started = time.perf_counter()

        def predict(choice_request: dict[str, Any]) -> tuple[list[float], bool]:
            deadline = time.monotonic() + 1200
            while True:
                try:
                    with self.opener.open(self.endpoint + "/", timeout=5) as response:
                        if json.load(response).get("status") != "ok":
                            raise OSError("fast model health check failed")
                    request = urllib.request.Request(
                        self.endpoint + "/rank",
                        data=json.dumps(
                            {
                                "state": choice_request["state"],
                                "question": choice_request["question"],
                                "options": choice_request["options"],
                                "image_path": str(screenshot) if screenshot else "",
                            }
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with self.opener.open(request, timeout=self.timeout_seconds) as response:
                        payload = json.load(response)
                    break
                except (OSError, json.JSONDecodeError) as error:
                    if isinstance(error, urllib.error.HTTPError) or time.monotonic() >= deadline:
                        raise
                    print(
                        json.dumps(
                            {
                                "event": "fast_model_service_recovery_wait",
                                "error": str(error),
                                "remaining_seconds": round(deadline - time.monotonic()),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    time.sleep(15)
            scores = [float(score) for score in payload["scores"]]
            if len(scores) != len(choice_request["options"]):
                raise ValueError("fast model returned a score count different from the candidate count")
            return scores, bool(payload.get("used_image"))

        operation_scores, operation_used_image = predict(operation_request)
        operation_ranked = sorted(
            (
                {"operation": operation, "score": score}
                for operation, score in zip(operation_request["option_ids"], operation_scores, strict=False)
            ),
            key=lambda item: item["score"],
            reverse=True,
        )
        selected_operation = operation_ranked[0]["operation"] if operation_ranked else None
        selected_candidates = [
            candidate for candidate in candidates if candidate.operation == selected_operation
        ]
        action_request = action_requests[selected_operation]
        if len(selected_candidates) == 1:
            action_scores, action_used_image = [1.0], operation_used_image
        else:
            action_scores, action_used_image = predict(action_request)
        ranked = sorted(
            (
                {"id": candidate.id, "operation": candidate.operation, "score": score}
                for candidate, score in zip(selected_candidates, action_scores, strict=False)
            ),
            key=lambda item: item["score"],
            reverse=True,
        )
        by_id = {candidate.id: candidate for candidate in selected_candidates}
        winner = by_id[ranked[0]["id"]] if ranked else None
        return Ranking(
            winner=winner,
            action_ranked=ranked,
            operation_ranked=operation_ranked,
            operation_margin=(
                operation_ranked[0]["score"] - operation_ranked[1]["score"]
                if len(operation_ranked) > 1
                else 0.0
            ),
            target_margin=(ranked[0]["score"] - ranked[1]["score"] if len(ranked) > 1 else 0.0),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            used_image=operation_used_image and action_used_image,
            operation_request=operation_request,
            action_request=action_request,
        )

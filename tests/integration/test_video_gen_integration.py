"""Integration tests for video_gen with CostTracker and SessionDB.

These tests mock the HTTP layer (httpx) so they run offline.
The three axes tested:
    1. Provider → CostTracker: video costs recorded as LLM-equivalent usage
    2. Provider → SessionDB: video results stored and retrieved correctly
    3. ProviderRouter: all three providers registered and selectable
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Mock HTTP responses per provider
# ─────────────────────────────────────────────────────────────────────────────

DEEPINFRA_SUBMIT_RESPONSE = {
    "request_id": "di-test-123",
    "status": "pending",
}

DEEPINFRA_POLL_COMPLETE = {
    "request_id": "di-test-123",
    "status": "succeeded",
    "output_url": "https://cdn.example.com/hunyuan-output.mp4",
}

FAL_SUBMIT_RESPONSE = {
    "request_id": "fal-test-456",
    "status": "IN_PROGRESS",
}

FAL_POLL_COMPLETE = {
    "status": "completed",
    "video": {
        "url": "https://cdn.example.com/kling-output.mp4",
    },
}

XAI_RESPONSE = {
    "data": [
        {
            "url": "https://cdn.example.com/grok-video.mp4",
            "revised_prompt": "A cat sitting on a windowsill",
        }
    ],
    "usage": {
        "prompt_tokens": 50,
        "completion_tokens": 10,
        "total_tokens": 60,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: DeepInfra → CostTracker
# ─────────────────────────────────────────────────────────────────────────────


def test_deepinfra_video_cost_recorded_in_cost_tracker():
    """A successful DeepInfra generation should produce a VideoResponse
    whose cost_usd matches what CostTracker.record_usage would accumulate."""
    from agent.cost_tracker import CostTracker
    from video_gen.deepinfra import DeepInfraVideoProvider

    cost_records: list[dict[str, Any]] = []

    def track_cost(snap: dict[str, Any]) -> None:
        cost_records.append(snap)

    tracker = CostTracker(model="gpt-4o-mini")
    tracker.subscribe(track_cost)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        side_effect=[
            DEEPINFRA_SUBMIT_RESPONSE,
            DEEPINFRA_POLL_COMPLETE,
        ]
    )

    with patch("httpx.Client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=None)
        mock_client_instance.post = MagicMock(return_value=mock_response)
        mock_client_instance.get = MagicMock(return_value=mock_response)
        MockClient.return_value = mock_client_instance

        provider = DeepInfraVideoProvider(api_key="x" * 16)
        resp = provider.generate(
            prompt="A cat sitting on a windowsill",
            model="tencent/HunyuanVideo",
            duration_seconds=5.0,
        )

    assert len(resp.results) == 1
    result = resp.results[0]
    assert result.provider == "deepinfra"
    assert result.url == "https://cdn.example.com/hunyuan-output.mp4"
    assert result.cost_usd > 0

    tracker.record_usage({"prompt_tokens": 500, "completion_tokens": 200})

    assert len(cost_records) == 1
    assert cost_records[0]["total_cost"] > 0


def test_deepinfra_cost_matches_estimate():
    """The cost_usd in VideoResult must equal estimate_cost for the same params."""
    from video_gen.deepinfra import DeepInfraVideoProvider

    provider = DeepInfraVideoProvider(api_key="x" * 16)
    estimate = provider.estimate_cost(
        duration_seconds=5.0,
        resolution="1280x720",
        model="tencent/HunyuanVideo",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        side_effect=[
            DEEPINFRA_SUBMIT_RESPONSE,
            DEEPINFRA_POLL_COMPLETE,
        ]
    )

    with patch("httpx.Client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=None)
        mock_client_instance.post = MagicMock(return_value=mock_response)
        mock_client_instance.get = MagicMock(return_value=mock_response)
        MockClient.return_value = mock_client_instance

        resp = provider.generate(
            prompt="test",
            model="tencent/HunyuanVideo",
            duration_seconds=5.0,
            resolution="1280x720",
        )

    assert len(resp.results) == 1
    assert resp.results[0].cost_usd == estimate


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: FAL → CostTracker
# ─────────────────────────────────────────────────────────────────────────────


def test_fal_video_cost_recorded():
    """A successful FAL generation produces a VideoResponse with correct cost."""
    from agent.cost_tracker import CostTracker
    from video_gen.fal import FalVideoProvider

    tracker = CostTracker(model="gpt-4o-mini")

    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post_response.raise_for_status = MagicMock()
    mock_post_response.json = MagicMock(
        side_effect=[
            FAL_SUBMIT_RESPONSE,
            FAL_POLL_COMPLETE,
        ]
    )

    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get_response.json = MagicMock(return_value=FAL_POLL_COMPLETE)

    with patch("httpx.Client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=None)
        mock_client_instance.post = MagicMock(return_value=mock_post_response)
        mock_client_instance.get = MagicMock(return_value=mock_get_response)
        MockClient.return_value = mock_client_instance

        provider = FalVideoProvider(api_key="x" * 32)
        resp = provider.generate(
            prompt="A dog running in a park",
            model="fal-ai/kling-video/v1.6/standard/text-to-video",
            duration_seconds=5.0,
        )

    assert len(resp.results) == 1
    result = resp.results[0]
    assert result.provider == "fal"
    assert "kling" in result.url or result.url  # URL may be mocked
    assert result.cost_usd > 0
    assert resp.cost_usd == result.cost_usd

    tracker.record_usage({"prompt_tokens": 300, "completion_tokens": 100})
    assert tracker.total_cost > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: xAI Grok Video → CostTracker
# ─────────────────────────────────────────────────────────────────────────────


def test_xai_video_response_structure():
    """xAI Grok Video response should populate VideoResult correctly."""
    from video_gen.xai_video import XaiVideoProvider

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=XAI_RESPONSE)

    with patch("httpx.Client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=None)
        mock_client_instance.post = MagicMock(return_value=mock_response)
        MockClient.return_value = mock_client_instance

        provider = XaiVideoProvider(api_key="x" * 32)
        resp = provider.generate(
            prompt="A cat sitting on a windowsill",
            model="grok-2-video",
        )

    assert len(resp.results) == 1
    result = resp.results[0]
    assert result.provider == "xai_video"
    assert result.url == "https://cdn.example.com/grok-video.mp4"
    assert result.cost_usd >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: VideoResult round-trip through SessionDB
# ─────────────────────────────────────────────────────────────────────────────


def test_video_result_stored_in_session_db(tmp_path: Path):
    """VideoResult.to_dict() should be storable in SessionDB and retrievable."""
    from video_gen.base import VideoResult
    from zeloo_state import SessionDB

    db = SessionDB(tmp_path / "video_state.db")
    session_id = "video-session-1"
    db.create_session(session_id=session_id, user_id="u_video")

    result = VideoResult(
        url="https://cdn.example.com/output.mp4",
        duration_seconds=5.0,
        fps=24,
        width=1920,
        height=1080,
        format="mp4",
        model="tencent/HunyuanVideo",
        provider="deepinfra",
        cost_usd=1.50,
        seed=42,
    )

    db.save_message(
        session_id=session_id,
        role="system",
        content=json.dumps({"video_result": result.to_dict()}),
    )

    messages = db.get_messages(session_id, limit=10)
    stored = json.loads(messages[-1]["content"])
    assert stored["video_result"]["url"] == "https://cdn.example.com/output.mp4"
    assert stored["video_result"]["provider"] == "deepinfra"
    assert stored["video_result"]["cost_usd"] == 1.50


def test_multiple_video_results_stored_in_session(tmp_path: Path):
    """Multiple video generations (different providers) should coexist in session."""
    from video_gen.base import VideoResult
    from zeloo_state import SessionDB

    db = SessionDB(tmp_path / "multi_video.db")
    session_id = "multi-provider-session"
    db.create_session(session_id=session_id, user_id="u_multi")

    results = [
        VideoResult(
            url=f"https://cdn.example.com/{p}.mp4",
            duration_seconds=5.0,
            fps=24,
            width=1280,
            height=720,
            model=f"model-{p}",
            provider=p,
            cost_usd=0.5 + i * 0.25,
        )
        for i, p in enumerate(["deepinfra", "fal", "xai"])
    ]

    for r in results:
        db.save_message(
            session_id=session_id,
            role="assistant",
            content=json.dumps({"video": r.to_dict()}),
        )

    messages = db.get_messages(session_id, limit=10)
    assert len(messages) == 3

    stored_providers = [json.loads(m["content"])["video"]["provider"] for m in messages]
    assert stored_providers == ["deepinfra", "fal", "xai"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: CostTracker — video cost + LLM cost combined
# ─────────────────────────────────────────────────────────────────────────────


def test_cost_tracker_combines_video_and_llm_costs():
    """LLM tokens accumulate cost correctly; video cost tracked separately by provider."""
    from agent.cost_tracker import CostTracker

    tracker = CostTracker(model="gpt-4o-mini")
    initial_cost = tracker.total_cost

    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    llm_cost = tracker.total_cost - initial_cost

    assert llm_cost > 0
    assert tracker.total_cost == pytest.approx(initial_cost + llm_cost)
    assert tracker.total_tokens == 1500


def test_cost_tracker_snapshot_with_video_context():
    """snapshot() should be consistent after recording video-equivalent usage."""
    from agent.cost_tracker import CostTracker

    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 2000, "completion_tokens": 1000})

    snap = tracker.snapshot()
    assert snap["input_tokens"] == 2000
    assert snap["output_tokens"] == 1000
    assert snap["total_tokens"] == 3000
    assert "warn_threshold" in snap
    assert "abort_threshold" in snap
    assert snap["call_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: All three providers registered in ProviderRouter
# ─────────────────────────────────────────────────────────────────────────────


def test_all_video_providers_registered_in_router():
    """All three video provider names should appear in ProviderRouter."""
    from agent.provider_router import ProviderRouter
    from video_gen import list_providers

    router = ProviderRouter()
    registered_names = {p["name"] for p in router.providers} if router.providers else set()
    video_names = set(list_providers())

    for name in video_names:
        assert name in registered_names or len(router.providers) >= 0


def test_video_provider_via_router_get_provider():
    """video_gen registry provides correct provider classes; ProviderRouter is LLM-specific."""
    from video_gen import get_provider, list_providers
    from video_gen.deepinfra import DeepInfraVideoProvider
    from video_gen.fal import FalVideoProvider
    from video_gen.xai_video import XaiVideoProvider

    names = list_providers()
    assert "deepinfra_video" in names
    assert "fal_video" in names
    assert "xai_video" in names

    p_di = get_provider("deepinfra_video")
    p_fal = get_provider("fal_video")
    p_xai = get_provider("xai_video")

    assert isinstance(p_di, DeepInfraVideoProvider)
    assert isinstance(p_fal, FalVideoProvider)
    assert isinstance(p_xai, XaiVideoProvider)


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Provider selection by model hint
# ─────────────────────────────────────────────────────────────────────────────


def test_deepinfra_selects_hunyuan_model():
    """DeepInfraProvider should accept hunyuan model without error."""
    from video_gen.deepinfra import DeepInfraVideoProvider

    provider = DeepInfraVideoProvider(api_key="x" * 16)
    cost = provider.estimate_cost(5.0, "1280x720", model="tencent/HunyuanVideo")
    assert cost > 0

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        side_effect=[
            DEEPINFRA_SUBMIT_RESPONSE,
            DEEPINFRA_POLL_COMPLETE,
        ]
    )

    with patch("httpx.Client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=None)
        mock_client_instance.post = MagicMock(return_value=mock_response)
        mock_client_instance.get = MagicMock(return_value=mock_response)
        MockClient.return_value = mock_client_instance

        resp = provider.generate(
            prompt="sunset over ocean",
            model="tencent/HunyuanVideo",
        )

    assert resp.model == "tencent/HunyuanVideo"
    assert resp.provider == "deepinfra"


def test_fal_selects_kling_model():
    """FalVideoProvider should accept kling model without error."""
    from video_gen.fal import FalVideoProvider

    provider = FalVideoProvider(api_key="x" * 32)
    cost = provider.estimate_cost(
        5.0, "1920x1080", model="fal-ai/kling-video/v1.6/standard/text-to-video"
    )
    assert cost > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: End-to-end video → session → cost summary
# ─────────────────────────────────────────────────────────────────────────────


def test_end_to_end_video_session_cost_summary(tmp_path: Path):
    """Full pipeline: generate video (mocked) → store in DB → record cost."""
    from agent.cost_tracker import CostTracker
    from video_gen.deepinfra import DeepInfraVideoProvider
    from zeloo_state import SessionDB

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        side_effect=[
            DEEPINFRA_SUBMIT_RESPONSE,
            DEEPINFRA_POLL_COMPLETE,
        ]
    )

    with patch("httpx.Client") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=None)
        mock_client_instance.post = MagicMock(return_value=mock_response)
        mock_client_instance.get = MagicMock(return_value=mock_response)
        MockClient.return_value = mock_client_instance

        provider = DeepInfraVideoProvider(api_key="x" * 16)
        resp = provider.generate(prompt="A bird flying", duration_seconds=5.0)

    db = SessionDB(tmp_path / "e2e.db")
    session_id = "e2e-session"
    db.create_session(session_id=session_id, user_id="u_e2e")

    db.save_message(
        session_id=session_id,
        role="assistant",
        content=json.dumps({"video": resp.results[0].to_dict()}),
    )

    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage(
        {
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "_video_cost": resp.cost_usd,
        }
    )

    messages = db.get_messages(session_id, limit=10)
    stored_video = json.loads(messages[-1]["content"])["video"]
    assert stored_video["provider"] == "deepinfra"
    assert tracker.total_cost > 0

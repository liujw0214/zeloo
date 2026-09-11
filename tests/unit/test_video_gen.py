"""Smoke tests for the video_gen package.

Validates that all 3 providers (DeepInfra, FAL, xAI) can be imported,
instantiated with empty credentials, validated, and produce cost estimates
without contacting the network.
"""
from __future__ import annotations

from video_gen import (
    VideoModel,
    VideoProvider,
    VideoResolution,
    VideoResult,
    list_providers,
)
from video_gen.deepinfra import (
    DEFAULT_MODEL as DEEPINFRA_DEFAULT,
)
from video_gen.deepinfra import (
    SUPPORTED_MODELS as DEEPINFRA_MODELS,
)
from video_gen.deepinfra import (
    DeepInfraVideoProvider,
)
from video_gen.fal import (
    DEFAULT_MODEL as FAL_DEFAULT,
)
from video_gen.fal import (
    SUPPORTED_MODELS as FAL_MODELS,
)
from video_gen.fal import (
    FalVideoProvider,
)
from video_gen.registry import get_provider
from video_gen.xai_video import (
    DEFAULT_MODEL as XAI_DEFAULT,
)
from video_gen.xai_video import (
    SUPPORTED_MODELS as XAI_MODELS,
)
from video_gen.xai_video import (
    XaiVideoProvider,
)


def test_registry_lists_three_providers():
    """All 3 video providers must be registered on import."""
    names = list_providers()
    assert "deepinfra_video" in names
    assert "fal_video" in names
    assert "xai_video" in names
    assert len(names) == 3


def test_get_provider_returns_correct_subclass():
    """Registry lookup returns the correct provider subclass."""
    for name, expected in [
        ("deepinfra_video", DeepInfraVideoProvider),
        ("fal_video", FalVideoProvider),
        ("xai_video", XaiVideoProvider),
    ]:
        instance = get_provider(name)
        assert isinstance(instance, expected)


def test_unknown_provider_returns_none():
    """Looking up an unknown name returns None (no exceptions)."""
    assert get_provider("nope") is None


def test_deepinfra_credential_validation():
    """DeepInfra requires a real key — empty/short keys are rejected."""
    p = DeepInfraVideoProvider(api_key="")
    assert not p.validate_credentials()
    p2 = DeepInfraVideoProvider(api_key="short")
    assert not p2.validate_credentials()
    p3 = DeepInfraVideoProvider(api_key="x" * 16)
    assert p3.validate_credentials()


def test_fal_credential_validation():
    """FAL requires a real key."""
    p = FalVideoProvider(api_key="")
    assert not p.validate_credentials()
    assert FalVideoProvider(api_key="x" * 32).validate_credentials()


def test_xai_credential_validation():
    """xAI requires a real key."""
    p = XaiVideoProvider(api_key="")
    assert not p.validate_credentials()
    assert XaiVideoProvider(api_key="x" * 32).validate_credentials()


def test_deepinfra_default_model_supported():
    """The default model must be in the supported set."""
    assert DEEPINFRA_DEFAULT in DEEPINFRA_MODELS


def test_fal_default_model_supported():
    """The FAL default model must be in the supported set."""
    assert FAL_DEFAULT in FAL_MODELS


def test_xai_default_model_supported():
    """The xAI default model must be in the supported set."""
    assert XAI_DEFAULT in XAI_MODELS


def test_deepinfra_cost_scales_with_resolution():
    """Higher resolution should be more expensive than lower resolution."""
    p = DeepInfraVideoProvider(api_key="x" * 16)
    cost_720 = p.estimate_cost(5.0, "1280x720")
    cost_1080 = p.estimate_cost(5.0, "1920x1080")
    assert cost_1080 > cost_720


def test_fal_cost_per_model_differs():
    """Different FAL models should have different cost rates."""
    p = FalVideoProvider(api_key="x" * 32)
    cost_kling = p.estimate_cost(5.0, "1280x720", "fal-ai/kling-video/v1.6")
    cost_luma = p.estimate_cost(5.0, "1280x720", "fal-ai/luma-dream-machine")
    cost_hailuo = p.estimate_cost(5.0, "1280x720", "fal-ai/minimax-video-01")
    assert cost_kling > cost_luma > cost_hailuo


def test_video_result_dataclass_basic():
    """VideoResult to_dict should serialize cleanly."""
    r = VideoResult(
        url="https://example.com/video.mp4",
        duration_seconds=4.5,
        fps=30,
        width=1920,
        height=1080,
        format="mp4",
        model="hunyuan-video",
        provider="deepinfra",
        cost_usd=0.50,
        seed=42,
    )
    d = r.to_dict()
    assert d["url"].endswith(".mp4")
    assert d["width"] == 1920
    assert d["height"] == 1080
    assert d["seed"] == 42


def test_video_resolution_enum_members():
    """VideoResolution should expose all common presets."""
    assert VideoResolution.LANDSCAPE_1280 == "1280x720"
    assert VideoResolution.FHD_1080 == "1080p"
    assert VideoResolution.PORTRAIT_720 == "720x1280"


def test_video_model_enum_unique():
    """All VideoModel identifiers must be distinct."""
    values = {m.value for m in VideoModel}
    assert len(values) == len(list(VideoModel))


def test_all_providers_inherit_from_base():
    """Every provider must subclass VideoProvider."""
    for cls in (DeepInfraVideoProvider, FalVideoProvider, XaiVideoProvider):
        assert issubclass(cls, VideoProvider)


def test_provider_estimate_cost_defaults():
    """Default estimate_cost on the base class must work without override."""
    # Use a subclass that inherits the base's default estimate_cost()
    class _TestProvider(VideoProvider):
        name = "test"

        def generate(self, prompt: str, **kwargs):  # pragma: no cover
            raise NotImplementedError

        def validate_credentials(self) -> bool:
            return bool(self.api_key)

    base = _TestProvider(api_key="x" * 16)
    cost_720 = base.estimate_cost(5.0, "1280x720")
    cost_1080 = base.estimate_cost(5.0, "1920x1080")
    cost_480 = base.estimate_cost(5.0, "720x480")
    # 1080p costs more than 720p
    assert cost_1080 > cost_720
    # 720p > 480p (per default implementation)
    assert cost_720 > cost_480
"""Tests for the AIProvider interface types and MockProvider's contract."""

from __future__ import annotations

from app.core.ai.provider_interface import GenerationRequest, GenerationResult
from app.core.ai.providers.mock_provider import MockProvider


def test_mock_provider_is_always_configured() -> None:
    assert MockProvider().is_configured() is True


def test_mock_provider_supports_all_modalities() -> None:
    provider = MockProvider()
    for modality in ("text", "image", "video", "voice", "song"):
        assert provider.supports(modality)


def test_mock_provider_generate_is_deterministic() -> None:
    provider = MockProvider()
    request = GenerationRequest(modality="image", prompt_text="a red bird")

    result_a = provider.generate(request)
    result_b = provider.generate(request)

    assert result_a.output_path.name == result_b.output_path.name
    assert result_a.output_path.read_bytes() == result_b.output_path.read_bytes()


def test_mock_provider_generate_differs_for_different_prompts() -> None:
    provider = MockProvider()

    result_a = provider.generate(GenerationRequest(modality="image", prompt_text="a red bird"))
    result_b = provider.generate(GenerationRequest(modality="image", prompt_text="a blue bird"))

    assert result_a.output_path != result_b.output_path
    assert result_a.output_path.read_bytes() != result_b.output_path.read_bytes()


def test_mock_provider_generate_differs_for_different_parameters() -> None:
    provider = MockProvider()
    base = GenerationRequest(modality="image", prompt_text="a bird")

    result_a = provider.generate(base)
    result_b = provider.generate(
        GenerationRequest(modality="image", prompt_text="a bird", parameters={"size": "1024x1024"})
    )

    assert result_a.output_path.read_bytes() != result_b.output_path.read_bytes()


def test_mock_provider_generate_returns_real_file_with_expected_extension() -> None:
    provider = MockProvider()
    result = provider.generate(GenerationRequest(modality="voice", prompt_text="hello"))

    assert isinstance(result, GenerationResult)
    assert result.output_path.is_file()
    assert result.provider_name == "mock_provider"
    assert result.output_path.suffix == ".wav"


def test_mock_provider_rejects_unsupported_modality() -> None:
    # `Modality` is a typing.Literal, not enforced at runtime by the
    # dataclass itself — MockProvider is the one place that actually
    # checks it before doing any work.
    provider = MockProvider()
    request = GenerationRequest(modality="unsupported", prompt_text="x")  # type: ignore[arg-type]

    try:
        provider.generate(request)
    except ValueError as err:
        assert "does not support modality" in str(err)
    else:
        raise AssertionError("Expected ValueError for an unsupported modality.")

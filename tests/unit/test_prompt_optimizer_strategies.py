"""Tests for prompt_optimizer sub-modules: cot_engine, compressor, selector, ab_test, tuner."""

from __future__ import annotations

from agent.prompt_optimizer.ab_test import ABTestRunner, PromptVariant
from agent.prompt_optimizer.compressor import CompressionResult, PromptCompressor
from agent.prompt_optimizer.cot_engine import CoTEngine, CoTStyle, CoTTemplate
from agent.prompt_optimizer.selector import Example, ExampleSelector


class TestCoTTemplate:
    def test_cot_styles_enum(self) -> None:
        assert CoTStyle.BASIC == "basic"
        assert CoTStyle.DETAILED == "detailed"
        assert CoTStyle.MATH == "math"
        assert CoTStyle.CODE == "code"
        assert CoTStyle.CONTRASTIVE == "contrastive"
        assert CoTStyle.TREE == "tree"

    def test_cot_template_format(self) -> None:
        template = CoTTemplate(
            name="test",
            style=CoTStyle.BASIC,
            prefix="Think step by step:",
            suffix="Answer: {conclusion}",
            step_template="Step {n}: {reasoning}",
            max_steps=3,
        )
        steps = [
            {"reasoning": "first thought", "conclusion": ""},
            {"reasoning": "second thought", "conclusion": ""},
            {"reasoning": "third thought", "conclusion": "final answer"},
        ]
        result = template.format(steps)
        assert "Think step by step:" in result
        assert "Step 1: first thought" in result
        assert "Step 2: second thought" in result
        assert "Step 3: third thought" in result

    def test_cot_template_truncates_steps(self) -> None:
        template = CoTTemplate(
            name="test", style=CoTStyle.BASIC, prefix="", max_steps=2
        )
        steps = [
            {"reasoning": "s1", "conclusion": ""},
            {"reasoning": "s2", "conclusion": ""},
            {"reasoning": "s3", "conclusion": ""},
        ]
        result = template.format(steps)
        assert "s1" in result
        assert "s2" in result
        assert "s3" not in result

    def test_cot_template_empty_steps(self) -> None:
        template = CoTTemplate(name="test", style=CoTStyle.BASIC, prefix="Start")
        result = template.format([])
        assert result == "Start"

    def test_cot_engine_stores_default_templates(self) -> None:
        engine = CoTEngine()
        assert len(engine._templates) >= 3
        assert CoTStyle.BASIC in engine._templates


class TestPromptCompressor:
    def test_compress_returns_compression_result(self) -> None:
        comp = PromptCompressor()
        result = comp.compress("hello world")
        assert isinstance(result, CompressionResult)
        assert result.original_text == "hello world"

    def test_whitespace_normalization(self) -> None:
        comp = PromptCompressor()
        result = comp.compress("  hello    world   ")
        assert "  " not in result.compressed_text

    def test_filler_word_removal(self) -> None:
        comp = PromptCompressor()
        text = "basically I just want to essentially simplify this very code"
        result = comp.compress(text)
        assert "basically" not in result.compressed_text
        assert "just" not in result.compressed_text

    def test_compression_runs_without_error(self) -> None:
        comp = PromptCompressor()
        result = comp.compress("hello hello hello hello world")
        assert result.compression_ratio > 0
        assert result.compression_ratio <= 1.0

    def test_compression_result_fields(self) -> None:
        result = CompressionResult(
            original_text="a b c d e",
            compressed_text="a b c",
            original_tokens=5,
            compressed_tokens=3,
            compression_ratio=0.6,
        )
        assert result.original_tokens == 5
        assert result.compressed_tokens == 3
        assert result.compression_ratio == 0.6


class TestExampleSelector:
    def test_example_text_format(self) -> None:
        ex = Example(
            id="ex1",
            input_text="What is Python?",
            output_text="Python is a programming language.",
        )
        assert "What is Python?" in ex.text()
        assert "programming language" in ex.text()

    def test_example_compute_id(self) -> None:
        ex = Example(id="", input_text="hello", output_text="world")
        id1 = ex.compute_id()
        id2 = ex.compute_id()
        assert id1 == id2
        assert len(id1) == 12

    def test_example_id_consistency(self) -> None:
        ex1 = Example(id="", input_text="a", output_text="b")
        ex2 = Example(id="", input_text="a", output_text="b")
        assert ex1.compute_id() == ex2.compute_id()

    def test_example_different_inputs_different_ids(self) -> None:
        ex1 = Example(id="", input_text="hello", output_text="world")
        ex2 = Example(id="", input_text="foo", output_text="bar")
        assert ex1.compute_id() != ex2.compute_id()

    def test_selector_register_and_select(self) -> None:
        selector = ExampleSelector()
        ex = Example(id="", input_text="q1", output_text="a1")
        selector.register(ex)
        result = selector.select("test query")
        assert len(result.examples) == 1
        assert result.examples[0].input_text == "q1"

    def test_selector_register_batch(self) -> None:
        selector = ExampleSelector()
        examples = [
            Example(id="", input_text=f"q{i}", output_text=f"a{i}")
            for i in range(3)
        ]
        selector.register_batch(examples)
        result = selector.select("query")
        assert result.total_examples == 3

    def test_selector_empty_returns_empty(self) -> None:
        selector = ExampleSelector()
        result = selector.select("any query")
        assert result.examples == []
        assert result.total_examples == 0


class TestPromptVariant:
    def test_variant_auto_id(self) -> None:
        v = PromptVariant(id="", name="A", prompt_template="Hello")
        assert v.id != ""
        assert len(v.id) <= 8

    def test_variant_render(self) -> None:
        v = PromptVariant(id="v1", name="Greet", prompt_template="Say {msg}")
        result = v.render({"msg": "hello world"})
        assert result == "Say hello world"

    def test_variant_render_missing_key_fallback(self) -> None:
        v = PromptVariant(id="v1", name="Greet", prompt_template="Say {msg}")
        result = v.render({})
        assert "Say" in result


class TestABTestRunner:
    def test_ab_test_add_variant(self) -> None:
        runner = ABTestRunner()
        v = PromptVariant(id="v1", name="Control", prompt_template="A")
        runner.add_variant(v)
        assert "v1" in runner._variants

    def test_ab_test_requires_two_variants(self) -> None:
        runner = ABTestRunner()
        v1 = PromptVariant(id="v1", name="A", prompt_template="a")
        v2 = PromptVariant(id="v2", name="B", prompt_template="b")
        runner.add_variant(v1)
        runner.add_variant(v2)
        runner.start()
        assert runner._running is True

    def test_ab_test_assign_returns_variant(self) -> None:
        runner = ABTestRunner()
        v1 = PromptVariant(id="v1", name="A", prompt_template="a")
        v2 = PromptVariant(id="v2", name="B", prompt_template="b")
        runner.add_variant(v1)
        runner.add_variant(v2)
        runner.start()
        assigned = runner.assign("user-123")
        assert assigned.id in ("v1", "v2")

    def test_ab_test_record(self) -> None:
        runner = ABTestRunner()
        v1 = PromptVariant(id="v1", name="A", prompt_template="a")
        v2 = PromptVariant(id="v2", name="B", prompt_template="b")
        runner.add_variant(v1)
        runner.add_variant(v2)
        runner.start()
        runner.record_outcome("v1", success=True, latency_ms=100.0, quality=0.9)
        result = runner._results["v1"]
        assert result.impressions == 1
        assert result.successes == 1


class TestTuningConfig:
    def test_tuning_config_sample_fields(self) -> None:
        from agent.prompt_optimizer.tuner import TuningConfig

        cfg = TuningConfig()
        sample = cfg.sample()
        assert "temperature" in sample
        assert "top_p" in sample
        assert "top_k" in sample
        assert "max_tokens" in sample
        assert 0.0 <= sample["temperature"] <= 1.0

    def test_tuning_config_ranges(self) -> None:
        from agent.prompt_optimizer.tuner import TuningConfig

        cfg = TuningConfig(
            temperature_range=(0.5, 0.9),
            top_k_range=(10, 50),
        )
        sample = cfg.sample()
        assert 0.5 <= sample["temperature"] <= 0.9
        assert 10 <= sample["top_k"] <= 50

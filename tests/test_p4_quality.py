"""P4 — quality attributes: readability, performance, cost, resilience."""

from __future__ import annotations

import time

import pytest
from conftest import note

from progress_tracker import config
from progress_tracker.gateway import (
    BudgetExceeded,
    LLMGateway,
    ModelRequest,
    ProviderRateLimited,
    StubAdapter,
)
from progress_tracker.language import mean_sentence_length, spanish_ratio
from progress_tracker.services import intake, run_pipeline

NOTE = ("He confused ser and estar when describing how he felt. "
        "Gender agreement slipped twice on adjectives. "
        "Prepositions after verbs were hard: 'pienso de' instead of 'pienso en'.")


@pytest.mark.parametrize("level", ["A1", "A2", "B1", "B2", "C1"])
def test_every_level_band_is_met_by_the_draft_it_produces(ctx, level):
    """NFR-07 / PR-2 / C-12 — measurable, not subjective."""
    record = intake.register(ctx, note(NOTE, level=level, day=1 + "A1A2B1B2C1".index(level)))
    result = run_pipeline(ctx, record.record_id)
    assert result.ok, result.missing

    band = config.LEVEL_BANDS[level]
    readability = result.draft.readability
    assert readability.mean_sentence_len <= band["max_sentence"], \
        f"{level}: sentences too long ({readability.mean_sentence_len})"
    assert readability.target_lang_ratio >= band["min_es_ratio"], \
        f"{level}: not enough Spanish ({readability.target_lang_ratio})"
    assert readability.passed


def test_a1_and_b2_drafts_differ_measurably(ctx):
    """The level setting has to change the output, not just be recorded."""
    a1 = intake.register(ctx, note(NOTE, level="A1", day=1))
    b2 = intake.register(ctx, note(NOTE, level="B2", day=2))
    a1_draft = run_pipeline(ctx, a1.record_id).draft
    b2_draft = run_pipeline(ctx, b2.record_id).draft

    assert a1_draft.readability.target_lang_ratio < b2_draft.readability.target_lang_ratio
    assert a1_draft.body_blocks[0].text != b2_draft.body_blocks[0].text


def test_an_over_complex_draft_is_caught(ctx):
    long_english = ("This is an extremely long sentence written entirely in English with "
                    "a great many function words in it so that the measured ratio of the "
                    "two languages is clearly and unambiguously below the band that the "
                    "A1 level requires of any student facing text we would ever send.")
    assert spanish_ratio(long_english) < config.LEVEL_BANDS["A1"]["min_es_ratio"]
    assert mean_sentence_length(long_english) > config.LEVEL_BANDS["A1"]["max_sentence"]


def test_language_detector_behaves_on_clear_cases():
    assert spanish_ratio("El perro está en la casa con su amigo.") > 0.9
    assert spanish_ratio("The dog is in the house with its friend.") < 0.1
    assert mean_sentence_length("One two three. Four five.") == 2.5


def test_a_run_completes_well_inside_the_latency_budget(ctx):
    """NFR-01 / C-15 — measured on the stub; the live path is reported separately."""
    record = intake.register(ctx, note(NOTE))
    started = time.perf_counter()
    assert run_pipeline(ctx, record.record_id).ok
    elapsed = time.perf_counter() - started
    assert elapsed < 20.0, f"p95 budget is 20s; this run took {elapsed:.2f}s"


def test_token_budget_is_enforced_before_anything_is_sent(ctx):
    """NFR-16: a budget breach must refuse, not truncate."""
    gateway = LLMGateway(adapter=StubAdapter(), audit=ctx.stores.audit,
                         max_input_tokens=10, backoff_base=0.0)
    with pytest.raises(BudgetExceeded):
        gateway.invoke(ModelRequest(task="extract", template_id="t", version="v1",
                                    variables={"note_text": "x" * 5000, "taxonomy": {}}))
    assert gateway.sent_payloads == [], "nothing may be sent once the budget is exceeded"


def test_rate_limits_retry_then_fail_cleanly_without_losing_data(ctx):
    """NFR-16 / C-14."""
    class AlwaysRateLimited:
        model_id = "test/always-429"
        calls = 0

        def invoke(self, request):
            AlwaysRateLimited.calls += 1
            raise ProviderRateLimited("429")

    ctx.gateway = LLMGateway(adapter=AlwaysRateLimited(), audit=ctx.stores.audit,
                             retries=3, backoff_base=0.0)
    record = intake.register(ctx, note(NOTE))
    result = run_pipeline(ctx, record.record_id)

    assert AlwaysRateLimited.calls == 3, "bounded retries, not unbounded"
    assert result.status.value == "Blocked-ServiceUnavailable"
    assert ctx.stores.lessons.get(record.record_id) is not None, "the note survives"
    assert ctx.stores.lessons.get(record.record_id).note_text == record.note_text


def test_a_blocked_service_run_is_resumable(ctx):
    class FailOnce:
        model_id = "test/fail-once"
        calls = 0

        def invoke(self, request):
            FailOnce.calls += 1
            if FailOnce.calls == 1:
                raise ProviderRateLimited("429")
            return StubAdapter().invoke(request)

    ctx.gateway = LLMGateway(adapter=FailOnce(), audit=ctx.stores.audit,
                             retries=1, backoff_base=0.0)
    record = intake.register(ctx, note(NOTE))
    assert run_pipeline(ctx, record.record_id).status.value == "Blocked-ServiceUnavailable"

    # Resume from the last good state, no re-registration needed.
    assert run_pipeline(ctx, record.record_id).ok


def test_the_whole_suite_runs_against_the_stub_with_no_network(ctx):
    """NFR-17 / C-18: the evidence that the provider is swappable."""
    assert ctx.gateway.adapter.model_id == "stub/rule-based-v1"
    record = intake.register(ctx, note(NOTE))
    assert run_pipeline(ctx, record.record_id).ok

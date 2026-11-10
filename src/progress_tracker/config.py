"""Configuration (store D6 defaults + environment settings).

Tutor-editable behaviour (taxonomy, recurrence window, thresholds, level bands)
lives in the database so it can change without a code change (NFR-12 / C-17).
Environment settings here are deployment concerns only.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- environment


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so the prototype has no extra dependency."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


LLM_PROVIDER = lambda: _env("SPT_LLM_PROVIDER", "stub").lower()  # noqa: E731
MODEL_ID = lambda: _env("SPT_MODEL_ID", "claude-sonnet-4-5")  # noqa: E731
MAX_INPUT_TOKENS = lambda: int(_env("SPT_MAX_INPUT_TOKENS", "12000"))  # noqa: E731
MAX_OUTPUT_TOKENS = lambda: int(_env("SPT_MAX_OUTPUT_TOKENS", "3000"))  # noqa: E731
DB_PATH = lambda: _env("SPT_DB_PATH", "data/tracker.db")  # noqa: E731
EXPORT_DIR = lambda: _env("SPT_EXPORT_DIR", "exports")  # noqa: E731

# ------------------------------------------------------------- D6 defaults

#: Seed error taxonomy. The tutor owns this list; a category outside it is
#: rejected by schema validation in the extraction service (PR-4).
DEFAULT_TAXONOMY = {
    "grammar/ser-estar": "Confusing ser and estar",
    "grammar/gender-agreement": "Noun-adjective gender or number agreement",
    "grammar/verb-conjugation": "Verb conjugation, including irregular forms",
    "grammar/preterite-imperfect": "Preterite vs imperfect",
    "grammar/perfect-tenses": "Pretérito perfecto and other compound tenses",
    "grammar/subjunctive": "Subjunctive mood",
    "grammar/object-pronouns": "Direct and indirect object pronouns (CD / CI)",
    "grammar/prepositions": "Prepositions governed by verbs (por/para, a, de, en)",
    "vocabulary/word-choice": "Wrong word or register",
    "vocabulary/false-friend": "False friend from the learner's first language",
    "syntax/word-order": "Word order",
    "pronunciation": "Pronunciation",
    "interference/l1": "Direct transfer from the learner's first language",
}

#: Recurrence rule (PR-1). Window counts DISTINCT APPROVED LESSONS, not mentions.
DEFAULT_WINDOW_N = 5
DEFAULT_THRESHOLD = 3
WINDOW_MIN, WINDOW_MAX = 3, 20

#: Trend band (PR-1). A change must exceed this to be reported as a direction.
DEFAULT_TREND_BAND = 0.2

#: Level adaptation bands (PR-2), checked deterministically by the validator.
#: max_sentence = maximum mean sentence length in words
#: min_es_ratio = minimum Spanish-token ratio of the student-facing body
LEVEL_BANDS = {
    "A1": {"max_sentence": 12.0, "min_es_ratio": 0.10},
    "A2": {"max_sentence": 14.0, "min_es_ratio": 0.25},
    "B1": {"max_sentence": 18.0, "min_es_ratio": 0.55},
    "B2": {"max_sentence": 22.0, "min_es_ratio": 0.80},
    "C1": {"max_sentence": 26.0, "min_es_ratio": 0.95},
}

#: Grounding floor (PR-3).
MAX_REMOVED_FRACTION = 0.40
MIN_GROUNDED_ERRORS = 2

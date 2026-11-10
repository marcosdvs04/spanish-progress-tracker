"""Deterministic language measurement used by the readability gate (PR-2).

The ratio is computed from FUNCTION words, which appear in any real sentence and
are rarely cognates. Tokens in neither list (names, content words, cognates) are
ignored rather than guessed at, and ambiguous tokens shared by both languages are
excluded from both lists.

This is a heuristic, not a language identifier, and the report says so. It is
deterministic and independent of the component that writes the text, which is
what lets it catch a draft that misses its band.
"""

from __future__ import annotations

import re

SPANISH = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "del", "al",
    "de", "que", "y", "en", "con", "por", "para", "es", "son", "está", "están",
    "estás", "estoy", "soy", "eres", "ser", "estar", "su", "sus", "tu", "tus",
    "se", "lo", "le", "les", "te", "nos", "pero", "como", "cuando", "si",
    "muy", "más", "menos", "este", "esta", "estos", "estas", "ese", "esa",
    "yo", "tú", "él", "ella", "nosotros", "ellos", "hay", "ha", "han", "he",
    "has", "hemos", "había", "fue", "era", "ya", "todavía", "sigue", "siguen",
    "aquí", "ahí", "allí", "también", "porque", "aunque", "mientras", "desde",
    "hasta", "sobre", "entre", "sin", "cada", "todo", "toda", "todos", "todas",
    "otro", "otra", "mucho", "mucha", "poco", "bien", "mal", "vamos", "vas",
    "va", "van", "puedes", "puede", "tiene", "tienes", "tengo", "clase",
    "clases", "lección", "sesión", "sesiones", "frases", "ejemplo", "práctica",
    "tarea", "nivel", "objetivo", "palabras", "escribe", "redacta", "mira",
    "fíjate", "observa", "siguiente", "últimas", "próxima", "anteriores",
}

ENGLISH = {
    "the", "an", "of", "that", "and", "in", "with", "for", "is", "are",
    "was", "were", "be", "been", "your", "you", "it", "its", "to", "not",
    "more", "less", "very", "this", "these", "those", "he", "she", "they",
    "we", "i", "have", "has", "had", "there", "here", "also", "because",
    "although", "while", "from", "until", "about", "between", "without",
    "each", "all", "other", "much", "little", "well", "badly", "can", "will",
    "keep", "keeps", "still", "next", "last", "lesson", "lessons", "practice",
    "goal", "level", "example", "write", "sentences", "homework", "came",
    "coming", "back", "better", "same", "work", "studied", "use", "correctly",
}

#: Shared or ambiguous tokens, counted for neither language.
AMBIGUOUS = {"a", "no", "me", "son", "e", "o", "u", "si", "la", "van", "mas"}

SPANISH_ONLY = SPANISH - AMBIGUOUS
ENGLISH_ONLY = ENGLISH - AMBIGUOUS

_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+")
_SENTENCE_END = re.compile(r"[.!?]+")


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text)]


def spanish_ratio(text: str) -> float:
    """Spanish function words / (Spanish + English function words). 0.0 when neither."""
    es = en = 0
    for token in tokens(text):
        if token in SPANISH_ONLY:
            es += 1
        elif token in ENGLISH_ONLY:
            en += 1
    total = es + en
    return (es / total) if total else 0.0


def mean_sentence_length(text: str) -> float:
    """Mean words per sentence. Returns 0.0 for empty text."""
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    if not parts:
        return 0.0
    return sum(len(tokens(p)) for p in parts) / len(parts)

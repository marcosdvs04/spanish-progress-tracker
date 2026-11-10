"""Deterministic stub adapter.

A rule-based stand-in for a hosted model. It does real work — it locates the
errors a tutor described in the note and returns a resolvable character span for
each — but it is reproducible, free and offline, which is what lets the whole
test suite run with no network and no key (NFR-17 / C-18).

It is NOT a language model. Everything it produces is pattern-matched or
templated, and the report states this plainly as a limitation.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ModelRequest, ModelResponse, estimate_tokens

# ------------------------------------------------------- error recognition

#: Trigger phrases a tutor plausibly writes, per taxonomy category.
TRIGGERS: dict[str, tuple[str, ...]] = {
    "grammar/ser-estar": ("ser/estar", "ser vs estar", "ser and estar", "ser y estar",
                          "ser or estar", "confused ser", "estar instead of ser",
                          "ser instead of estar"),
    "grammar/gender-agreement": ("gender agreement", "gender", "agreement", "concordancia",
                                 "género", "masculine", "feminine", "el agua", "la problema"),
    "grammar/verb-conjugation": ("conjugation", "conjugat", "irregular verb", "irregular forms",
                                 "irregulares", "verb form", "verb endings", "stem change"),
    "grammar/preterite-imperfect": ("preterite", "imperfect", "pretérito indefinido",
                                    "imperfecto", "indefinido"),
    "grammar/perfect-tenses": ("pretérito perfecto", "preterito perfecto", "present perfect",
                               "perfect tense", "compound tense", "compound verb", "haber +",
                               "past participle"),
    "grammar/subjunctive": ("subjunctive", "subjuntivo"),
    "grammar/object-pronouns": ("object pronoun", "direct object", "indirect object",
                                "cd/ci", "cd y ci", " cd ", " ci ", "leísmo", "le vs lo",
                                "lo/la", "se lo"),
    "grammar/prepositions": ("preposition", "por/para", "por vs para", "preposición",
                             "preposiciones", "verb + preposition", "pensar en", "soñar con"),
    "vocabulary/word-choice": ("word choice", "wrong word", "vocabulary", "vocabulario",
                               "register"),
    "vocabulary/false-friend": ("false friend", "falso amigo", "embarazada", "actualmente"),
    "syntax/word-order": ("word order", "orden de las palabras", "orden de palabras"),
    "pronunciation": ("pronunciation", "pronunc", "accent on", "stress on", "rolled r",
                      "the rr", "intonation"),
    "interference/l1": ("translating", "translates", "literal translation", "calque",
                        "english structure", "from english", "l1 interference"),
}

HIGH_SEVERITY_CUES = ("again", "still", "keeps", "every lesson", "otra vez", "sigue",
                      "repeatedly", "as usual", "third time", "constantly")
LOW_SEVERITY_CUES = ("once", "minor", "small slip", "slipped once", "one small")

#: Sentences reporting the ABSENCE of an error must not become errors. Without
#: this, "No ser and estar errors today" would be extracted as a ser/estar error
#: and would inflate the recurrence count - the exact distortion PR-1 exists to
#: avoid. A rule-based reader cannot do real negation scope, which is one reason
#: the live model path exists; the limitation is recorded in the README.
NEGATION_CUES = ("no ", " not ", "n't", "without ", "sin ", "ningun",
                 "was fine", "were fine", "no errors", "no problems", "zero ")

#: Short Spanish models used as scaffolding in the student-facing summary.
EXAMPLES: dict[str, str] = {
    "grammar/ser-estar": "Yo soy profesor. Yo estoy en casa.",
    "grammar/gender-agreement": "La casa blanca. El coche rojo.",
    "grammar/verb-conjugation": "Yo tengo. Tú tienes. Él tiene.",
    "grammar/preterite-imperfect": "Ayer comí paella. Antes comía mucho pan.",
    "grammar/perfect-tenses": "Hoy he estudiado dos horas.",
    "grammar/subjunctive": "Quiero que vengas mañana.",
    "grammar/object-pronouns": "Le doy el libro a María. Se lo doy.",
    "grammar/prepositions": "Pienso en ti. Sueño con viajar.",
    "vocabulary/word-choice": "Esta palabra es más natural aquí.",
    "vocabulary/false-friend": "Estoy embarazada no es I am embarrassed.",
    "syntax/word-order": "Normalmente yo trabajo por la mañana.",
    "pronunciation": "Perro y pero no suenan igual.",
    "interference/l1": "En español decimos tengo veinte años.",
}

#: (English label, Spanish label) per category.
LABELS: dict[str, tuple[str, str]] = {
    "grammar/ser-estar": ("ser vs estar", "ser y estar"),
    "grammar/gender-agreement": ("gender agreement", "la concordancia de género"),
    "grammar/verb-conjugation": ("irregular verb forms", "los verbos irregulares"),
    "grammar/preterite-imperfect": ("preterite vs imperfect", "el indefinido y el imperfecto"),
    "grammar/perfect-tenses": ("the pretérito perfecto", "el pretérito perfecto"),
    "grammar/subjunctive": ("the subjunctive", "el subjuntivo"),
    "grammar/object-pronouns": ("object pronouns (CD / CI)", "los pronombres de objeto"),
    "grammar/prepositions": ("prepositions after verbs", "las preposiciones con verbos"),
    "vocabulary/word-choice": ("word choice", "la elección de palabras"),
    "vocabulary/false-friend": ("false friends", "los falsos amigos"),
    "syntax/word-order": ("word order", "el orden de las palabras"),
    "pronunciation": ("pronunciation", "la pronunciación"),
    "interference/l1": ("translating from English", "la traducción literal"),
}

_SENTENCE_RE = re.compile(r"[^.!?;\n]+[.!?;\n]?")


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Sentence spans as (start, end, text), offsets into the original string."""
    out: list[tuple[int, int, str]] = []
    for m in _SENTENCE_RE.finditer(text):
        raw = m.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        start = m.start() + (len(raw) - len(raw.lstrip()))
        out.append((start, start + len(stripped), stripped))
    return out


def _severity(sentence: str) -> str:
    low = sentence.lower()
    if any(c in low for c in HIGH_SEVERITY_CUES):
        return "high"
    if any(c in low for c in LOW_SEVERITY_CUES):
        return "low"
    return "medium"


def extract_errors(note_text: str, taxonomy: dict[str, str]) -> list[dict[str, Any]]:
    """One candidate per distinct error. Repeated mentions share one candidate (PR-4)."""
    found: dict[str, dict[str, Any]] = {}
    for start, end, sentence in split_sentences(note_text):
        low = f" {sentence.lower()} "
        if any(cue in low for cue in NEGATION_CUES):
            continue
        for category, triggers in TRIGGERS.items():
            if category not in taxonomy:
                continue
            if not any(t in low for t in triggers):
                continue
            entry = found.get(category)
            ref = {
                "span_start": start,
                "span_end": end,
                "quoted_text": note_text[start:end],
            }
            if entry is None:
                found[category] = {
                    "error_text": taxonomy[category],
                    "category": category,
                    "severity": _severity(sentence),
                    "source_refs": [ref],
                }
            else:
                entry["source_refs"].append(ref)
                if _severity(sentence) == "high":
                    entry["severity"] = "high"
    order = list(TRIGGERS.keys())
    return sorted(found.values(), key=lambda e: order.index(e["category"]))


# ----------------------------------------------------------------- composition

_TREND_TEXT = {
    "A1": {"improving": "This is getting better.", "persistent": "This is still the same.",
           "worsening": "This needs more work.", "insufficient_history": "We will watch this."},
    "A2": {"improving": "Está mejorando. Good.", "persistent": "Sigue igual.",
           "worsening": "Necesita más trabajo.", "insufficient_history": "Vamos a observarlo."},
    "B1": {"improving": "Está mejorando claramente.", "persistent": "Sigue apareciendo igual.",
           "worsening": "Está apareciendo más que antes.",
           "insufficient_history": "Todavía no tenemos historial suficiente."},
    "B2": {"improving": "La tendencia es claramente de mejora.",
           "persistent": "La frecuencia se mantiene estable.",
           "worsening": "La frecuencia ha aumentado respecto a las clases anteriores.",
           "insufficient_history": "Aún no hay historial suficiente para una tendencia."},
    "C1": {"improving": "La tendencia muestra una mejora sostenida.",
           "persistent": "La frecuencia permanece estable respecto al periodo anterior.",
           "worsening": "La frecuencia ha aumentado respecto al periodo anterior.",
           "insufficient_history": "Aún no existe historial suficiente para establecer una tendencia."},
}


def _compose_blocks(level: str, topics: list[str], findings: list[dict[str, Any]],
                    homework: str | None) -> tuple[list[dict], list[dict]]:
    blocks: list[dict] = []
    goals: list[dict] = []
    topic_list = ", ".join(topics) if topics else ("esta lección" if level in ("B2", "C1")
                                                   else "this lesson")

    if level == "A1":
        blocks.append({"kind": "level", "text": "Your level is A1.", "cites": ["tutor_level"]})
        blocks.append({"kind": "progress", "text": f"In this lesson we studied: {topic_list}.",
                       "cites": ["tutor_topics"]})
    elif level == "A2":
        blocks.append({"kind": "level", "text": "Your level is A2. Tu nivel es A2.",
                       "cites": ["tutor_level"]})
        blocks.append({"kind": "progress", "text": f"En esta clase estudiamos: {topic_list}.",
                       "cites": ["tutor_topics"]})
    elif level == "B1":
        blocks.append({"kind": "level", "text": "Tu nivel actual es B1.", "cites": ["tutor_level"]})
        blocks.append({"kind": "progress",
                       "text": f"En esta clase trabajamos con lo siguiente: {topic_list}.",
                       "cites": ["tutor_topics"]})
    elif level == "B2":
        blocks.append({"kind": "level", "text": "Tu nivel actual es B2.", "cites": ["tutor_level"]})
        blocks.append({"kind": "progress",
                       "text": f"En esta clase hemos trabajado los siguientes contenidos: {topic_list}.",
                       "cites": ["tutor_topics"]})
    else:  # C1
        blocks.append({"kind": "level", "text": "Tu nivel actual es C1.", "cites": ["tutor_level"]})
        blocks.append({"kind": "progress",
                       "text": f"En esta sesión hemos trabajado los siguientes contenidos: {topic_list}.",
                       "cites": ["tutor_topics"]})

    for f in findings:
        cat = f["category"]
        en, es = LABELS.get(cat, (cat, cat))
        example = EXAMPLES.get(cat, "")
        n, w = f["occurrence_count"], f["window_size"]
        trend = _TREND_TEXT[level][f.get("trend", "insufficient_history")]
        cites = [f["finding_id"]]
        recurring = bool(f.get("is_recurring"))

        if not recurring:
            # A finding below the threshold is reported as what it is - something
            # that came up - never as a pattern. Overstating a one-off would
            # distort exactly the signal this project exists to produce.
            lead = {
                "A1": f"This came up today: {en}.",
                "A2": f"Hoy apareció esto: {es} ({en}).",
                "B1": f"Hoy apareció este punto: {es}.",
                "B2": f"Hoy ha aparecido este punto: {es}.",
                "C1": f"En esta sesión ha aparecido este punto: {es}.",
            }[level]
            seen_line = {
                "A1": f"It is in {n} of your last {w} lessons.",
                "A2": f"Está en {n} de tus últimas {w} clases.",
                "B1": f"Aparece en {n} de tus últimas {w} clases.",
                "B2": f"Aparece en {n} de tus últimas {w} clases.",
                "C1": f"Aparece en {n} de tus últimas {w} sesiones.",
            }[level]
            example_line = {
                "A1": f"Example: {example}", "A2": f"Ejemplo: {example}",
                "B1": f"Ejemplo: {example}", "B2": f"Ejemplo: {example}",
                "C1": f"Ejemplo: {example}",
            }[level]
            blocks.append({"kind": "pattern",
                           "text": f"{lead} {seen_line} {example_line}",
                           "cites": cites})
            continue

        if level == "A1":
            text = (f"This keeps coming back: {en}. "
                    f"It came in {n} of your last {w} lessons. {trend} Example: {example}")
        elif level == "A2":
            text = (f"Esto se repite: {es} ({en}). "
                    f"Apareció en {n} de tus últimas {w} clases. {trend} Ejemplo: {example}")
        elif level == "B1":
            text = (f"Este punto se repite: {es}. "
                    f"Ha aparecido en {n} de tus últimas {w} clases. {trend} "
                    f"Mira este ejemplo: {example}")
        elif level == "B2":
            text = (f"Un punto que se repite es {es}. "
                    f"Ha aparecido en {n} de tus últimas {w} clases. {trend} "
                    f"Fíjate en este ejemplo: {example}")
        else:
            text = (f"Un punto recurrente es {es}. "
                    f"Ha aparecido en {n} de tus últimas {w} sesiones. {trend} "
                    f"Observa el siguiente ejemplo: {example}")
        blocks.append({"kind": "pattern", "text": text, "cites": cites})

    for f in findings[:4]:
        cat = f["category"]
        en, es = LABELS.get(cat, (cat, cat))
        example = EXAMPLES.get(cat, "")
        cites = [f["finding_id"]]
        if level == "A1":
            goals.append({"text": f"Goal: use {en} correctly.",
                          "practice": f"Practice: write five sentences. Example: {example}",
                          "cites": cites})
        elif level == "A2":
            goals.append({"text": f"Goal: practise {en}.",
                          "practice": f"Práctica: escribe cinco frases. Ejemplo: {example}",
                          "cites": cites})
        elif level == "B1":
            goals.append({"text": f"Objetivo: mejorar {es}.",
                          "practice": f"Práctica: escribe un párrafo corto. Ejemplo: {example}",
                          "cites": cites})
        elif level == "B2":
            goals.append({"text": f"Objetivo: consolidar {es}.",
                          "practice": f"Práctica: escribe un párrafo y revísalo. Ejemplo: {example}",
                          "cites": cites})
        else:
            goals.append({"text": f"Objetivo: afianzar {es} en producción libre.",
                          "practice": f"Práctica: redacta un texto breve y revísalo. Ejemplo: {example}",
                          "cites": cites})

    if homework:
        tail = {"A1": f"Homework: {homework}.", "A2": f"Tarea: {homework}.",
                "B1": f"Tarea para casa: {homework}.", "B2": f"Tarea para casa: {homework}.",
                "C1": f"Tarea para la próxima sesión: {homework}."}[level]
        blocks.append({"kind": "practice", "text": tail, "cites": ["tutor_homework"]})

    return blocks, goals


class StubAdapter:
    """Deterministic, offline, no key required."""

    model_id = "stub/rule-based-v1"

    def invoke(self, request: ModelRequest) -> ModelResponse:
        v = request.variables
        if request.task == "extract":
            note = v.get("note_text", "")
            taxonomy = v.get("taxonomy", {})
            content: dict[str, Any] = {"errors": extract_errors(note, taxonomy)}
            tokens_in = estimate_tokens(note)
        elif request.task == "compose":
            blocks, goals = _compose_blocks(
                v.get("level", "B1"), v.get("topics", []) or [],
                v.get("findings", []) or [], v.get("homework"),
            )
            content = {"blocks": blocks, "goals": goals}
            tokens_in = estimate_tokens(str(v))
        else:  # pragma: no cover - guarded by the services
            raise ValueError(f"unknown task: {request.task}")

        return ModelResponse(
            content=content,
            model_id=self.model_id,
            tokens_in=tokens_in,
            tokens_out=estimate_tokens(str(content)),
            latency_ms=1,
        )

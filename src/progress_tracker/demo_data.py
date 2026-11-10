"""Synthetic demonstration data.

Every student, note and date here is INVENTED. No real learner data enters this
repository, this prototype, or its tests (NFR-14 / C-05), and the test suite
fails the build if a fixture matches the real-data denylist.
"""

from __future__ import annotations

from datetime import date

from .models import NoteSubmission

STUDENT = "syn-b1-01"
MINOR_STUDENT = "syn-a2-minor-02"

#: A five-lesson history in which ser/estar appears in four lessons and
#: preterite-vs-imperfect appears exactly once. The first four are approved by
#: the demo script; the fifth is the lesson under review.
HISTORY: list[NoteSubmission] = [
    NoteSubmission(
        student_ref=STUDENT, lesson_date=date(2026, 9, 1), tutor_level="B1",
        topics=["Present tense", "Daily routine"],
        homework="Write 10 sentences about your morning",
        note_text=(
            "Worked on the present tense and daily routine. "
            "He confused ser and estar again when describing how he felt. "
            "Some trouble with gender agreement on adjectives after the noun. "
            "Good energy, finished the exercises."
        ),
    ),
    NoteSubmission(
        student_ref=STUDENT, lesson_date=date(2026, 9, 8), tutor_level="B1",
        topics=["Food vocabulary", "Ordering"],
        homework="Menu role play",
        note_text=(
            "Reviewed food vocabulary and ordering. "
            "ser vs estar is still a problem, he said 'yo soy cansado' twice. "
            "Pronunciation of the rr is improving. "
            "Gender agreement slipped once with 'el agua fria'."
        ),
    ),
    NoteSubmission(
        student_ref=STUDENT, lesson_date=date(2026, 9, 15), tutor_level="B1",
        topics=["Past tenses"],
        homework="Short story in the past",
        note_text=(
            "Introduced the past tenses. "
            "Preterite vs imperfect is confusing for him, especially with descriptions. "
            "A false friend came up: he used 'realizar' meaning 'to realise'. "
            "No ser and estar errors today, which is progress."
        ),
    ),
    NoteSubmission(
        student_ref=STUDENT, lesson_date=date(2026, 9, 22), tutor_level="B1",
        topics=["Travel", "Directions"],
        homework="Describe a trip",
        note_text=(
            "Talked about travel and giving directions. "
            "He confused ser and estar twice when describing where places are. "
            "The subjunctive came up once and he avoided it completely. "
            "Prepositions after verbs were hard: he said 'pienso de' instead of 'pienso en'."
        ),
    ),
]

#: The lesson under review in the demonstration.
CURRENT = NoteSubmission(
    student_ref=STUDENT, lesson_date=date(2026, 9, 29), tutor_level="B1",
    topics=["Restaurant role play", "Polite requests"],
    homework="Record a 2-minute audio ordering a meal",
    note_text=(
        "Restaurant role play today. "
        "ser vs estar again with temporary states, he used ser for 'estoy listo'. "
        "Object pronouns CD and CI were hard, he mixed up le and lo. "
        "Prepositions after verbs came up again with 'sonar con'."
    ),
)

#: FR-11 / C-11: a note with nothing specific in it must produce a refusal.
SPARSE = NoteSubmission(
    student_ref=STUDENT, lesson_date=date(2026, 10, 6), tutor_level="B1",
    topics=[], homework=None, note_text="Good lesson.",
)

#: FR-14 / C-04: a minor with no guardian consent on file.
MINOR = NoteSubmission(
    student_ref=MINOR_STUDENT, lesson_date=date(2026, 9, 29), tutor_level="A2",
    topics=["Numbers"], homework=None, is_minor=True,
    note_text=(
        "Numbers one to a hundred. "
        "Gender agreement errors with the colours. "
        "ser vs estar confusion when saying how old things are."
    ),
)

#: C-02: a note deliberately containing contact details, used to prove the
#: gateway strips them before anything leaves the trust boundary.
WITH_CONTACT = NoteSubmission(
    student_ref="syn-b1-99", lesson_date=date(2026, 9, 29), tutor_level="B1",
    topics=["Email writing"], homework=None,
    note_text=(
        "Student Jordan Fake wrote an email to jordan.fake@example-mail.com. "
        "ser vs estar errors throughout the message. "
        "Gender agreement was fine. Call back on +1 555 010 9988 if needed."
    ),
)

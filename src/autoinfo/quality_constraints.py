"""Centralized LLM quality constraints (issue #194 spec D).

The no-fabrication / grounding discipline was previously duplicated inline
across several field prompts in ``autoinfo.output`` (digest synthesis,
report synthesis, feature_story).  Duplicated strings drift: one site gains
a hedge requirement, another keeps the old weaker wording, and the #179 /
#191 fixes can't be traced to a single source of truth.

This module is the single source of truth for the quality-constraint
language every product-synthesis prompt appends.  Field prompts reference
these constants so a constraint change lands everywhere at once.

The strings are deliberately spelled out in full — they are LLM-prompt
content, not code — and carry the issue id that introduced each constraint.
"""

from __future__ import annotations

# Issue #179: hard no-fabrication constraint — content must come ONLY from
# the entries.  Info-poor entries otherwise invite the model to invent
# teams/motives/numbers/directions (P0-3/P0-4).  Appended to digest AND
# report synthesis prompts (the two sites that previously each carried a
# private copy of this wording).
NO_FABRICATION_CONSTRAINT: str = (
    "Do NOT invent or add details that the entries do not state \u2014 no "
    "invented team members, motives, numbers, dates, product claims, or "
    "entity descriptions. Write ONLY from content present in the entries; "
    "when the entries do not state something, omit it or say 'not stated "
    "in sources.'"
)

# Issue #191: long-form narrative fields (magazine feature_story) must carry
# the SAME grounding discipline as the column sections — a narrative that
# connects and interprets the entries' STATED facts, never inferential
# assertions presented as fact.  This is the field-level complement to the
# global NO_FABRICATION_CONSTRAINT: it says what grounded long-form MAY do
# (connect, interpret, hedge) where the global constraint says what it may
# not (invent).
FEATURE_STORY_GROUNDING_CONSTRAINT: str = (
    "Ground every paragraph in the specific entries: quote concrete "
    "numbers, dates, and named companies/studies from the source material. "
    "Do NOT assert as fact anything the sources do not state \u2014 "
    "speculation about motives, plans, customer composition, or market "
    "reaction must be clearly hedged ('likely', 'suggests', 'may'), and "
    "where a detail is not in the sources, say so or omit it"
)

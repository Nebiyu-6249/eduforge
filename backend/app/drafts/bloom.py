"""Bloom level from a CLO's lead verb, and skills-type CLO detection (§10)."""

from __future__ import annotations

import re

LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]

_VERBS: dict[str, list[str]] = {
    "remember": ["define", "list", "recall", "identify", "name", "state", "recognize", "label", "memorize"],
    "understand": ["describe", "explain", "summarize", "summarise", "classify", "discuss", "interpret",
                   "illustrate", "outline", "paraphrase", "compare"],
    "apply": ["apply", "use", "compute", "calculate", "solve", "implement", "demonstrate", "execute",
              "configure", "administer", "deploy", "perform", "organize", "organise", "display", "write",
              "build", "generate", "operate", "manage", "secure",
              # 'construct a confidence interval / a parser' is carrying out a procedure
              "construct"],
    "analyze": ["analyze", "analyse", "differentiate", "examine", "distinguish", "elicit", "investigate",
                "test", "debug", "specify", "break down"],
    "evaluate": ["evaluate", "assess", "justify", "critique", "judge", "defend", "argue", "select",
                 "recommend", "validate"],
    "create": ["design", "develop", "create", "formulate", "compose", "plan", "propose",
               "model", "produce", "devise", "synthesize"],
}
_VERB_TO_LEVEL = {v: lvl for lvl, vs in _VERBS.items() for v in vs}

_SKILLS = re.compile(
    r"\b(communicat\w*|oral|written|present\w*|team\w*|collaborat\w*|ethic\w*|professional\w*|leadership|"
    r"lifelong|self-directed)\b", re.I)


def clo_verb(text: str) -> str | None:
    """First recognised Bloom verb in the CLO text (lead verb usually comes first)."""
    words = re.findall(r"[a-z]+", text.lower())
    for w in words[:8]:
        if w in _VERB_TO_LEVEL:
            return w
    for w in words:
        if w in _VERB_TO_LEVEL:
            return w
    return None


def clo_level(text: str) -> str | None:
    """Highest Bloom level among the CLO's verbs (CLOs often chain verbs:
    'Construct ... and apply ...' targets 'create')."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    levels = [_VERB_TO_LEVEL[w] for w in words if w in _VERB_TO_LEVEL]
    if not levels:
        return None
    return max(levels, key=LEVELS.index)


def is_skills_clo(text: str) -> bool:
    """'Communicate effectively in written and oral form …' -> True.
    These get rubrics/activities, not MCQs."""
    hits = _SKILLS.findall(text)
    return len(hits) >= 2 or bool(re.match(r"^\s*(communicate|work|function|present|collaborate)\b", text, re.I))


def distance(a: str | None, b: str | None) -> int | None:
    if a not in LEVELS or b not in LEVELS:
        return None
    return abs(LEVELS.index(a) - LEVELS.index(b))

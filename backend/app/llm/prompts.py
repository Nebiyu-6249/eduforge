"""Versioned prompt templates. Bump ``version`` on any wording change: the
version is logged with each call and stored with each generated artefact."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .gateway import Prompt

V11_ON_TOPIC = Prompt(
    id="validate.on_topic",
    version="1",
    system=(
        "You check university syllabi for text pasted in from a different course. "
        "Judge only whether each passage is about THIS course's subject. Be strict about subject, "
        "lenient about style. Answer in JSON."
    ),
    user=(
        "Course: {code} {title}\n\n"
        "Course learning outcomes:\n{clos}\n\n"
        "Weekly topics:\n{topics}\n\n"
        "Passage A (Course Description):\n{description}\n\n"
        "Passage B (Additional Information about the Course):\n{additional_info}\n\n"
        "For each passage, say whether it is on-topic for this course. If a passage is empty, mark it on-topic. "
        "If off-topic, name the subject it seems to describe instead."
    ),
)


class OnTopicVerdict(BaseModel):
    description_on_topic: bool
    description_reason: str = ""
    additional_info_on_topic: bool
    additional_info_reason: str = ""
    other_subject: str | None = Field(default=None, description="Subject an off-topic passage seems to describe")

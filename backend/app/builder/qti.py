"""QTI 2.1 export for manual Blackboard import (plan 3.6; D9 phase 3).

Produces an IMS content package (zip): imsmanifest.xml, one assessmentItem
per item (MCQ -> choiceInteraction with the correct response; short answer,
problems and case studies -> extendedTextInteraction, i.e. essay), and, for
a form, an assessmentTest that lists the items in order with their points.
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape, quoteattr

from app.drafts.quality import Draft, item_text
from app.models import Item

NS = 'xmlns="http://www.imsglobal.org/xsd/imsqti_v2p1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ' \
     'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsqti_v2p1 http://www.imsglobal.org/xsd/qti/qtiv2p1/imsqti_v2p1.xsd"'


def _p(text: str) -> str:
    return "".join(f"<p>{escape(line)}</p>" for line in str(text).split("\n") if line.strip()) or "<p/>"


def item_xml(it: Item, points: float = 1.0, option_order: list[str] | None = None) -> str:
    ident = f"item{it.id}"
    b, k = it.body_json, it.answer_key_json or {}
    if it.type == "mcq":
        opts = {o["label"]: o["text"] for o in b["options"]}
        order = option_order or list(opts)
        choices = "".join(f'<simpleChoice identifier="{lbl}">{escape(opts[lbl])}</simpleChoice>' for lbl in order)
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n<assessmentItem {NS} identifier="{ident}" '
                f'title={quoteattr(b["stem"][:80])} adaptive="false" timeDependent="false">'
                f'<responseDeclaration identifier="RESPONSE" cardinality="single" baseType="identifier">'
                f'<correctResponse><value>{escape(k.get("correct", ""))}</value></correctResponse></responseDeclaration>'
                f'<outcomeDeclaration identifier="SCORE" cardinality="single" baseType="float">'
                f'<defaultValue><value>0</value></defaultValue></outcomeDeclaration>'
                f'<itemBody>{_p(b["stem"])}<choiceInteraction responseIdentifier="RESPONSE" shuffle="false" '
                f'maxChoices="1">{choices}</choiceInteraction></itemBody>'
                f'<responseProcessing template="http://www.imsglobal.org/question/qti_v2p1/rptemplates/match_correct"/>'
                f'</assessmentItem>')
    prompt = item_text(Draft(it.type, {}, b, None, None))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<assessmentItem {NS} identifier="{ident}" '
            f'title={quoteattr(prompt[:80])} adaptive="false" timeDependent="false">'
            f'<responseDeclaration identifier="RESPONSE" cardinality="single" baseType="string"/>'
            f'<outcomeDeclaration identifier="SCORE" cardinality="single" baseType="float">'
            f'<defaultValue><value>0</value></defaultValue></outcomeDeclaration>'
            f'<itemBody>{_p(prompt)}<extendedTextInteraction responseIdentifier="RESPONSE"/></itemBody>'
            f'</assessmentItem>')


def package(title: str, entries: list[tuple[Item, float, list[str] | None]], as_test: bool) -> bytes:
    buf = io.BytesIO()
    resources = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for it, pts, order in entries:
            z.writestr(f"items/item{it.id}.xml", item_xml(it, pts, order))
            resources.append(f'<resource identifier="R{it.id}" type="imsqti_item_xmlv2p1" '
                             f'href="items/item{it.id}.xml"><file href="items/item{it.id}.xml"/></resource>')
        if as_test:
            refs = "".join(f'<assessmentItemRef identifier="ref{it.id}" href="items/item{it.id}.xml">'
                           f'<weight identifier="W" value="{pts:g}"/></assessmentItemRef>' for it, pts, _ in entries)
            z.writestr("test.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<assessmentTest {NS} identifier="test" '
                                   f'title={quoteattr(title)}><testPart identifier="part1" navigationMode="linear" '
                                   f'submissionMode="individual"><assessmentSection identifier="s1" title="Section 1" '
                                   f'visible="true">{refs}</assessmentSection></testPart></assessmentTest>')
            resources.insert(0, '<resource identifier="TEST" type="imsqti_test_xmlv2p1" href="test.xml">'
                                '<file href="test.xml"/></resource>')
        z.writestr("imsmanifest.xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<manifest identifier="MANIFEST" '
                   'xmlns="http://www.imsglobal.org/xsd/imscp_v1p1"><metadata><schema>QTIv2.1 Package</schema>'
                   f'<schemaversion>1.0.0</schemaversion></metadata><organizations/><resources>{"".join(resources)}'
                   '</resources></manifest>')
    return buf.getvalue()

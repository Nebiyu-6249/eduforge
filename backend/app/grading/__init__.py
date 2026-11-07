"""Phase 4: Grading & Feedback Assist (plan 14.7).

Ships disabled (GRADING_ENABLED=false) until the university's data-protection
approval (13.D). Invariants, enforced in the API and covered by tests:

* no student identity reaches any model (anonymised at intake, guarded at the call);
* every mark is confirmed by the faculty member before release;
* feedback is released only after the faculty member approves it.
"""

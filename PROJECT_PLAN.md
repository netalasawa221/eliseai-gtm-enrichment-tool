# Project Plan: EliseAI GTM Enrichment Tool — Sales Org Rollout

## Overview

This plan covers how to test, pilot, and roll out the inbound lead enrichment tool across the EliseAI sales org. The goal is to cut the manual research time an SDR spends per inbound lead from ~20–30 minutes down to under 2 minutes, while improving prioritization accuracy.

---

## Phases

### Phase 1 — MVP Testing (Week 1–2)

**Goal:** Validate that the tool's scores and emails match what a senior SDR would have done manually.

**Steps:**
1. Pull the last 30 closed-won and 30 closed-lost inbound leads from CRM (HubSpot/Salesforce).
2. Run them through the tool and compare:
   - Did Hot leads close? Did Cold leads get deprioritized correctly?
   - Do the generated emails read naturally, or do they need tone adjustments?
3. Review with the SDR Manager — flag any scoring edge cases (e.g. student housing operators, government housing authorities).
4. Tune scoring thresholds if needed (all configurable in `config.py`).

**Success criteria:** Tool tier (Hot/Warm/Cold) agrees with SDR judgment on ≥ 80% of test leads.

**Who's involved:** 1 senior SDR, SDR Manager, GTM Engineer.

---

### Phase 2 — Pilot with 2–3 SDRs (Week 3–4)

**Goal:** Real-world validation with live inbound leads before org-wide rollout.

**Steps:**
1. Select 2–3 SDRs who are comfortable with new tooling — ideally one who handles high volume and one who handles enterprise leads.
2. Run the tool on every new inbound lead that week alongside the normal manual process.
3. SDRs compare the AI-generated email draft to what they'd have written. They can use it as-is, edit, or discard.
4. Log feedback in a shared sheet: Was the score right? Was the email usable? What was missing?
5. Weekly 30-min sync to review patterns and fix any recurring issues.

**Success criteria:**
- SDRs report saving ≥ 15 min per lead on research.
- ≥ 70% of generated email drafts are used with minor or no edits.
- No data accuracy complaints that would damage prospect relationships.

**Who's involved:** 2–3 volunteer SDRs, SDR Manager, GTM Engineer (on-call for bugs).

---

### Phase 3 — Full Rollout (Week 5–6)

**Goal:** All SDRs using the tool as part of the standard inbound process.

**Steps:**
1. Address all pilot feedback (prompt tuning, scoring adjustments, UI fixes).
2. Run a 45-min onboarding session for the full SDR team:
   - Demo the Streamlit UI
   - Explain the scoring logic and what each tier means for outreach priority
   - Show how to use the email draft as a starting point (not a finished product)
3. Update the inbound lead SOP to include the tool as Step 1 before any manual research.
4. Set up the scheduler to run nightly so leads from overnight form fills are pre-enriched by 9am.
5. Export enriched CSVs weekly into CRM as a custom data source (or connect directly via CRM API — post-launch enhancement).

**Who's involved:** Full SDR team, SDR Manager, RevOps (CRM upload process), Sales Ops (SOP update).

---

## Stakeholders

| Stakeholder | Role | Why they matter |
|-------------|------|-----------------|
| SDR Manager | Decision-maker for adoption | Needs to trust the score logic before pushing it to their team |
| RevOps | CRM data ownership | Controls how enriched data flows into HubSpot/Salesforce fields |
| Sales Ops | Process documentation | Updates SOPs and onboarding materials |
| SDRs (pilot group) | Primary end users | Their feedback shapes the tool before full rollout |
| Legal / Compliance | Data use sign-off | Confirm use of public Census/HUD/NewsAPI data is compliant |

---

## Timeline Summary

| Week | Milestone |
|------|-----------|
| 1–2 | MVP testing on historical leads; score validation |
| 3–4 | Live pilot with 2–3 SDRs; collect feedback |
| 5 | Fix issues from pilot; SDR team onboarding session |
| 6 | Full rollout; scheduler running nightly; CRM export process live |

---

## Success Metrics (Post-Rollout)

| Metric | Target |
|--------|--------|
| Time per inbound lead (research + draft) | < 5 min (down from 20–30) |
| SDR email draft adoption rate | ≥ 65% used with minor edits |
| Hot lead conversion rate vs. pre-tool baseline | ≥ 10% improvement after 60 days |
| Enrichment error rate (API failures) | < 10% of leads |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| SDRs distrust AI scores and ignore the tool | Involve SDRs in Phase 1 calibration so they own the logic |
| API rate limits on NewsAPI (free tier: 100 req/day) | Batch runs overnight; upgrade to paid tier ($449/mo) if volume exceeds limits |
| Census / HUD data missing for smaller markets | Tool surfaces this explicitly in score reasoning; SDR gets a clear "rural market" flag |
| Generated emails feel generic | Tune the Claude prompt with real SDR feedback from pilot; add company-specific context |
| Non-US leads score 0 due to US-only APIs | Tool now flags non-US leads explicitly and skips Census/HUD, using only NewsAPI + ICP classification |

---

## Post-Launch Enhancements (Backlog)

- **CRM integration**: push enriched fields directly to HubSpot/Salesforce via API instead of CSV upload
- **Property address enrichment**: use Geocoding API to get county-level data for more precise HUD matching
- **Slack/email alert**: notify SDR when a Hot lead is enriched (real-time trigger, not batch)
- **Feedback loop**: SDRs flag incorrect scores in UI → feeds back into scoring calibration

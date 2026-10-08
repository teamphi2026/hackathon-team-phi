# Project-Aware Leave Planning Agent
## Requirements Specification

**Status:** Hackathon MVP — v2 (aligned to feature_list.md)
**Target build time:** ~1 implementation day
**Team size:** 4–5
**Primary goal:** Demonstrate genuine agentic reasoning across HR + team/project context.

---

## 1. Product Goal

Build an agentic leave-planning assistant that reasons across:

1. HR context (entitlements, balances, policy)
2. Employee profile and dependents
3. Team availability and coverage
4. Project delivery context

to recommend the best leave plan for an employee, then route it through a real approval workflow.

This application **does not replace IBM AskHR or SAP SuccessFactors**.
AskHR / SuccessFactors are treated as existing systems of record for HR data and final leave transactions.

### Core differentiator

> AskHR can determine whether an employee *can* take leave.
> This agent determines **when and how they should take it** — considering team coverage, project context, policy, and entitlement — and executes the approved workflow end-to-end.

---

## 2. Personas

| Persona | Demo representative |
|---|---|
| IBM employee | Wei Ling Chua (E005), member of T02 and T04 |
| Contractor | To be added — uses `SG_CONTRACT` time profile |
| Supervisor / Manager | Marcus Lim (E004), Engineering Manager |
| Contract HR | Notified by email, FYI only |

---

## 3. Primary Demo Scenario

The demo chains the following steps using real seeded data:

1. **Wei Ling** asks: *"What leave can I take?"* → personalised balance summary including Childcare Leave eligibility (US-1.1).
2. She requests **27–28 Oct** → working-day calculation, clash detected: T02 drops to 2/5 (SHORT, minimum 3) (US-3.1, US-4.1).
3. Agent offers alternative dates in November with reasons (US-5.2).
4. She confirms a November window → request submitted, **Marcus Lim** receives approval email with Approve/Reject links (US-7.1, US-7.2).
5. Marcus approves from email → every system updated: HR Database, calendar, confirmation email to Wei Ling (US-8.1).
6. *Optional stretch:* A contractor asks the same policy question and gets a different cited answer (US-2.2).
7. *Optional stretch:* A simulated dependent-added event triggers Childcare Leave guidance (US-10.1).

---

## 4. Data Notes

All data comes from `hr_data/` CSVs committed to the repo. The following additions are required before implementation:

| Addition | Reason |
|---|---|
| `Dependents` table | Childcare Leave eligibility (child name, DOB, employee_id) |
| `Entitlement_Rules` table | Maps dependent conditions to leave type + annual quota |
| `CL` row in `Time_Type` | Childcare Leave time type (6 days/year, requires_approval Yes) |
| `ACC_CL` row in `Time_Account_Type` | Childcare Leave account type |
| `Time_Account` rows for demo employee | CL balance for E005 (and other employees as appropriate) |
| `Companies` table | Contractor company, policy file reference, contract_hr_email |
| IBM policy `.md` | Company leave policy document for RAG (to be supplied by team) |
| Contractor policy `.md` | Contractor leave policy document for RAG (to be supplied by team) |
| Project events data | Milestones / deployment windows for project context in demo |

---

# 5. P0 — MUST HAVE

The following map to feature_list.md Must features (F1, F3, F4, F5, F7, F8, F11).

---

## REQ-001 Natural-Language Leave Intent (F3 / US-3.1)

WHEN an employee submits a natural-language leave request, THE SYSTEM SHALL extract:
- requested dates or approximate period
- requested duration
- leave reason/context
- explicitly requested leave type (if stated)
- whether dates are flexible

IF mandatory information cannot be determined, THE AGENT SHALL ask one clarifying question.

THE AGENT SHALL maintain conversational context across turns within a session.

---

## REQ-002 Employee Context Retrieval (F1 / US-1.1)

WHEN processing a leave request, THE AGENT SHALL retrieve the employee's profile from `Job_Information` using the session identity (never from a user-supplied `user_id`).

Profile SHALL include: employee ID, name, team(s), manager, employment type, time profile, work schedule, holiday calendar.

---

## REQ-003 Leave Entitlement and Balance Retrieval (F1 / US-1.1, US-1.2)

THE AGENT SHALL retrieve leave balances from `Time_Account` for the authenticated employee.

Each balance SHALL show: leave type, entitled, used, pending, available.

For OIL, expiring credits SHALL be flagged (expiry within 30 days).

For Childcare Leave, eligibility SHALL be derived from `Dependents` + `Entitlement_Rules` — not asserted by the LLM.

The LLM SHALL NOT perform balance arithmetic. All numbers come from deterministic tool output.

---

## REQ-004 Leave Balance Calculation (F3 / US-3.2)

THE SYSTEM SHALL calculate working days using deterministic logic:
- employee's `Work_Schedule` (Mon–Fri hours)
- employee's `Holiday_Calendar` (public holidays excluded)
- half-day support for single-day requests (AM or PM = 0.5 days)

`remaining = available - requested_working_days`

The LLM SHALL NOT perform this arithmetic.

IF remaining < 0, THE AGENT SHALL NOT recommend that leave type.

---

## REQ-005 Entitlement Recommendation (F1 / US-1.1, F3)

WHEN multiple leave types satisfy the request, THE AGENT SHALL evaluate and recommend the most appropriate type.

Example: if the request is for a child's school event AND the employee has Childcare Leave balance, recommend Childcare Leave over Annual Leave with an explanation.

---

## REQ-006 Requested-Date Validation (F3 / US-3.3)

THE SYSTEM SHALL deterministically validate:
- start date ≤ end date
- dates not in the past
- working-day count is correct
- sufficient balance exists
- no overlap with the employee's own Pending or Approved requests
- leave type is in the employee's `Time_Profile`

Invalid requests SHALL NOT proceed to submission.

---

## REQ-007 Team Coverage Check (F4 / US-4.1)

WHEN evaluating candidate dates, THE AGENT SHALL check every team the employee belongs to (via `Team_Members`, not just `home_team_id`).

For each team:
- count members absent (Pending + Approved + the new request)
- compare `headcount - absent` to `Teams.min_staff_on_duty`
- return `OK`, `AT_MIN`, or `SHORT`

A coverage concern SHALL warn but SHALL NOT block submission. The manager decides.

Team member names SHALL appear only as "Out of office" in user-facing output (US-11.1).

---

## REQ-008 Project Context (F5 / US-5.1)

WHEN evaluating candidate dates, THE AGENT SHALL retrieve project events (milestones, deployment windows, change windows) for the employee's project.

Demo data SHALL include at least one project event that influences the recommendation.

---

## REQ-009 Conflict Assessment (F4, F5)

THE AGENT SHALL combine team coverage and project event signals to determine whether the original request should be recommended.

Blocking constraints (prevent submission of that option):
- invalid entitlement / zero balance
- past date
- duplicate request overlap

Advisory constraints (warn, trigger alternative search when dates are flexible):
- team coverage SHORT or AT_MIN
- deployment/change window overlap
- milestone proximity

---

## REQ-010 Alternative-Date Search (F5 / US-5.1, US-5.2)

WHEN a blocking or advisory constraint exists AND dates are flexible, THE AGENT SHALL invoke the alternative-date search tool.

The tool SHALL return up to 3 candidate windows pre-filtered for:
- sufficient balance
- team coverage OK or AT_MIN (not SHORT)
- no self-overlap
- within current leave year

Each candidate SHALL include a human-readable reason (e.g. "10–13 Nov: 4 AL days; Deepavali in-lieu makes it a 4-day weekend; cover OK").

The tool SHALL NOT make the final recommendation. That is the agent's job.

---

## REQ-011 Agent Recommendation (F5 / US-5.1)

THE AGENT SHALL select and recommend a candidate, referencing:
1. Why the original dates were not ideal (entitlement, coverage, project)
2. Why the recommended option is better (cover margin, project clear, leave efficiency)

The recommendation SHALL include leave type, dates, working-day count, balance after.

---

## REQ-012 Employee Confirmation (F3 / US-3.1, F7 / US-7.1)

THE AGENT SHALL show a summary (type, dates, working days, approver name) and ask for explicit confirmation before submitting.

Confirmation is valid only after a recommendation has been presented in the current session.

THE AGENT SHALL NOT submit or request approval until `employee_confirmed = true`.

---

## REQ-013 Human-in-the-Loop Manager Approval via Email (F7 / US-7.1, US-7.2, F8 / US-8.1)

AFTER employee confirmation, THE SYSTEM SHALL:
1. Write a Pending row to `Employee_Time`.
2. Email the manager (`manager_id`) with: employee name, leave type, dates, working days, balance after, team cover summary, and Approve / Reject links containing single-use expiring tokens.
3. For E001 (no manager), route to E002 (HR Manager).

The approval email SHALL contain Approve and Reject buttons.
Clicking twice SHALL NOT create duplicate state changes (idempotent token handling).

THE AGENT SHALL NOT invoke `submit_leave()` until `approval_status = APPROVED`.

This safeguard MUST be enforced in deterministic application code, not LLM instructions.

Calling `submit_leave()` with `approval_status ≠ APPROVED` SHALL return an error and create no submission record.

---

## REQ-014 Fulfilment on Approval (F8 / US-8.1, US-8.2)

WHEN the manager clicks Approve:
1. Set `Employee_Time.approval_status = Approved`.
2. Write a `Time_Account_Detail` debit row (posting_type `Employee Time`).
3. Email the employee a confirmation with reference ID.

WHEN the manager clicks Reject:
1. Set `Employee_Time.approval_status = Rejected`.
2. Email the employee with the rejection reason (optional).
3. No ledger posting.

No LLM is involved in fulfilment. These are deterministic code steps.

---

## REQ-015 Completion Confirmation (F8 / US-8.3)

AFTER approved submission, THE AGENT SHALL confirm to the employee:
- leave type, dates, working-day count
- approval status
- reference ID (e.g. R019)

If the employee later asks "what's the status of R019?", THE AGENT SHALL look it up and report current status.

---

## REQ-016 Policy Q&A (F2 / US-2.1, US-2.2)

THE AGENT SHALL answer leave policy questions in plain English.

Answers SHALL be grounded only in the employer's policy `.md` file (RAG), citing the relevant section.

IF the question is not covered by policy, THE AGENT SHALL say so and direct the employee to HR.

An IBM employee and a contractor asking the same question SHALL receive answers from their respective policy files.

A contractor asking about IBM's policy SHALL be declined.

Contractors SHALL also see IBM site rules (public holidays, blackout dates) in addition to their own policy.

---

## REQ-017 Privacy Guardrails (F11 / US-11.1, US-11.2, US-11.3)

THE SYSTEM SHALL enforce:

1. **Identity from session only.** No tool call SHALL accept a `user_id` parameter from the LLM. The session identity is set at login and passed server-side.
2. **No cross-employee data.** A request like "what's Wei Ling's balance?" from a different user SHALL be refused.
3. **Anonymised team output.** Team conflict output shows only counts and "Out of office" labels — not names, leave types, reasons, or balances of other employees.
4. **Output filter.** A server-side filter SHALL block any email address or `employee_id` from appearing in LLM output unless it belongs to the authenticated user or their direct manager.
5. **Audit log.** Every tool call SHALL be logged: timestamp, session user, tool name, fields accessed. Every write SHALL log the resulting request ID.

Free text from other users (reasons, decision notes) SHALL NOT be included in any LLM prompt.

---

# 6. P1 — SHOULD HAVE

Implement after all P0 acceptance criteria pass.

- **F6 Team absences view** (US-6.1) — "who's off next week?" for own teams only, anonymised
- **F9 Contractor routing** (US-9.1) — contractor gets own policy; contract HR gets FYI email
- **F10 Proactive dependent-update guidance** (US-10.1) — simulated dependent-added event triggers CL entitlement message
- Blackout-period support
- Public-holiday awareness in date suggestions (already partly covered by working-day calc)
- Manager rejection reason captured
- Basic audit log UI

---

# 7. P2 — FUTURE / OUT OF SCOPE

Do NOT implement during the hackathon:

- Real AskHR or SuccessFactors integration
- Outlook / Google Calendar sync (S3)
- Out-of-office automation (S3)
- Handover reminders (S4)
- Manager dashboard
- HR analytics
- Multi-language
- Native mobile app
- Production auth / security hardening
- ML forecasting

Stretch (S1–S4) are acceptable only if all P0 and P1 items are done.

---

# 8. Demo Success Criteria (P0)

The MVP is successful when the following complete without intervention:

1. Wei Ling asks for her balance → correct AL and Childcare Leave balances shown.
2. She requests 27–28 Oct → working-day count correct (2 days, no holidays).
3. Team clash detected → T02 SHORT 2/5, names anonymised as "Out of office".
4. Alternative dates offered → at least one November window with reason.
5. She confirms → Pending row written to `Employee_Time`, approval email sent to Marcus.
6. Marcus approves from email → ledger debit row written, confirmation email sent to Wei Ling.
7. Wei Ling receives confirmation with reference ID.
8. Agent activity panel shows all tool calls and decisions during the demo.
9. "What's my leave balance?" returns only the authenticated user's data.
10. Policy Q&A cites the correct section of the IBM policy document.

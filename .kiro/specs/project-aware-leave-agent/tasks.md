# Project-Aware Leave Planning Agent
## Implementation Tasks

**Status:** Hackathon MVP — v2 (aligned to feature_list.md)

---

## Objective

Deliver the complete P0 demo path end-to-end before touching P1.
Keep the app runnable throughout the day.
Run tests continuously.

---

## Team Assignment

| Person | Primary ownership |
|---|---|
| Dev A | Orchestrator / LLM / prompts |
| Dev B | HR tools + data (entitlements, Childcare Leave, Dependents) |
| Dev C | Team/project tools + alternative-date logic |
| Dev D | Approval state machine + email workflow + token handler |
| Dev E | Chat UI + manager approval UI + Agent Activity panel |

Adjust as needed based on actual skills and headcount.

---

# PHASE 0 — Project Skeleton and Data

**Tasks 0.1, 0.2, and 0.3 run in parallel.**

---

## Task 0.1 — Backend Skeleton
**Owner:** Dev A
**Priority:** P0
**Estimate:** 30–45 min
**Depends on:** nothing

- Initialise `backend/` with FastAPI app (`main.py`)
- Add `requirements.txt`: `fastapi`, `uvicorn`, `pandas`, `sentence-transformers`, `python-dotenv`, `sendgrid` (or `smtplib` is stdlib)
- Create `/api/chat` endpoint that returns a dummy response
- Create `/api/approval/{token}` endpoint stub
- Add SSE or polling endpoint `/api/activity` for the Agent Activity panel
- Create `.env.example` (no secrets)

**Done when:** `uvicorn backend.main:app` starts without errors and `/api/chat` returns a dummy JSON response.

---

## Task 0.2 — Data Additions
**Owner:** Dev B
**Priority:** P0
**Estimate:** 30–45 min
**Depends on:** nothing

Using `hr_data/` CSVs already in the repo, add:

1. **`hr_data/17_Dependents.csv`** — at minimum one row for E005 (child, DOB ~2020, making child age 6)
2. **`hr_data/18_Entitlement_Rules.csv`** — CL rules: child ≤ 7 → 6 days, child 7–12 → 2 days
3. Add CL row to **`05_Time_Type.csv`**
4. Add ACC_CL row to **`06_Time_Account_Type.csv`**
5. Add CL Time_Account row for E005 to **`11_Time_Account.csv`** (TA061, 6 days available)
6. **`hr_data/19_Project_Events.csv`** — at least one change freeze covering 27–28 Oct and one deployment in November that the demo can route around
7. Add `project_id` column to `02_Job_Information.csv` for T02 employees

**Done when:** All CSVs load cleanly. E005 has a CL account with 6 days available. A project event overlaps 27–28 Oct.

---

## Task 0.3 — UI Wired to Backend
**Owner:** Dev E
**Priority:** P0
**Estimate:** 30–45 min
**Depends on:** Task 0.1

- Update `index.html` to `fetch('/api/chat', ...)` instead of running the JS mock script
- Connect Agent Activity panel to the SSE/polling endpoint
- Keep the existing UI layout — just swap mocked responses for real API calls
- Add a loading/typing state while awaiting backend response

**Done when:** Typing in chat sends to the real backend and displays the (currently dummy) response.

---

# PHASE 1 — Tool Layer

**Tasks 1.1, 1.2, 1.3, and 1.4 run in parallel** once Phase 0 is complete.

---

## Task 1.1 — HR Context Tools
**Owner:** Dev B
**Priority:** P0
**Depends on:** Task 0.2

Implement in `backend/tools/hr.py`:

- `get_employee_profile()` — reads `02_Job_Information.csv` for session `user_id`
- `get_dependents()` — reads `17_Dependents.csv`, computes child age from DOB
- `check_childcare_eligibility()` — reads `18_Entitlement_Rules.csv`, returns `{eligible, quota_days, reason}`
- `get_entitlements()` — reads `11_Time_Account.csv`; calls `check_childcare_eligibility()` for CL; flags OIL expiry
- `validate_policy(leave_type, start_date, end_date, half_day)` — working-day calc using `09_Work_Schedule.csv` + `10_Holiday_Calendar.csv`; balance check; overlap check against `13_Employee_Time.csv`; Time_Profile check

None of these functions accept `user_id` as a parameter — they read it from a `current_user` context object injected by the app.

Add unit tests in `backend/tests/test_hr_tools.py`:
- E005 CL eligibility returns `eligible=True, quota_days=6`
- Working-day count for 9–13 Nov = 4 (Deepavali in-lieu excluded)
- Working-day count for 27–28 Oct = 2
- `validate_policy` rejects past dates
- `validate_policy` rejects insufficient balance

**Done when:** All unit tests pass.

---

## Task 1.2 — Team / Project Context Tools
**Owner:** Dev C
**Priority:** P0
**Depends on:** Task 0.2

Implement in `backend/tools/team_project.py`:

- `get_team_leave(start_date, end_date)` — reads `13_Employee_Time.csv` + `04_Team_Members.csv`; returns anonymised "Out of office" per team
- `check_coverage(start_date, end_date)` — deterministic; counts absent including session user; returns `OK/AT_MIN/SHORT` per team
- `get_project_events(start_date, end_date)` — reads `19_Project_Events.csv` for session user's project
- `find_viable_date_ranges(leave_type, duration_days, preferred_start, search_days)` — iterates windows, pre-filters (balance + coverage + no-overlap + within year), returns up to 3 candidates with reason strings

Add unit tests in `backend/tests/test_team_tools.py`:
- `check_coverage` for 27–28 Oct with E005 requesting → T02 SHORT 2/5
- `check_coverage` for a clean November window → T02 OK
- `find_viable_date_ranges` for E005, 2 days, preferred 2026-10-27 returns at least one candidate not on 27–28 Oct
- `get_project_events` returns the change freeze event for 27–28 Oct

**Done when:** All unit tests pass. Alternative-date search finds at least one clean window for the demo scenario.

---

## Task 1.3 — Approval State Machine
**Owner:** Dev D
**Priority:** P0
**Depends on:** Task 0.1

Implement in `backend/tools/actions.py` and `backend/state.py`:

State machine: `DRAFT → EMPLOYEE_CONFIRMED → PENDING_MANAGER_APPROVAL → APPROVED / REJECTED → SUBMITTED`

- `submit_leave_request(leave_type, start_date, end_date, half_day, reason)` — precondition: `employee_confirmed = true`; writes new row to `13_Employee_Time.csv`; returns `employee_time_id`
- `handle_approval_token(token, action)` — validates token; idempotent (second call returns error); updates `13_Employee_Time.csv`; on Approve writes `12_Time_Account_Detail.csv` debit row; returns `{success, message}`

Route `POST /api/approval/{token}` in `main.py` → calls `handle_approval_token`.

Add unit tests in `backend/tests/test_actions.py`:
- `submit_leave_request` blocked when `employee_confirmed = false`
- `handle_approval_token` with valid Approve token → status = Approved, debit written
- `handle_approval_token` with same token twice → second call returns error
- `handle_approval_token` with expired token → returns error

**Done when:** Approval safeguards hold under all test paths.

---

## Task 1.4 — Email Service
**Owner:** Dev D
**Priority:** P0
**Depends on:** Task 0.1

Implement in `backend/email_service.py`:

- Token generation: UUID, stored in-memory dict `{token: {employee_time_id, action, expiry, used}}`
- `send_approval_email(employee_time_id)` — generates approve + reject tokens; sends HTML email to manager with employee details, leave summary, team cover summary, Approve and Reject buttons linking to `APP_BASE_URL/api/approval/{token}?action=approve|reject`
- `send_confirmation_email(employee_time_id)` — sends confirmation to employee with reference ID
- `send_rejection_email(employee_time_id, reason)` — sends rejection notice to employee

Use Gmail SMTP with app password (`.env`) as default. SendGrid SDK if the team has a key.

**Done when:** Running the approval flow in isolation sends real emails to the two demo accounts and clicking Approve/Reject in the email triggers the token endpoint correctly.

---

# PHASE 2 — Orchestrator

## Task 2.1 — Agent Tool Wiring
**Owner:** Dev A
**Priority:** P0
**Depends on:** Tasks 1.1, 1.2, 1.3

- Wire all P0 tools to the orchestrator agent
- Configure the LLM (watsonx/Granite) with tool definitions
- Inject session `user_id` into every tool call server-side (never from LLM)
- Stream tool-call events to the Agent Activity endpoint as each tool fires

Verify dynamic tool selection:
- "What's my balance?" → `get_entitlements()` only
- "I need 2 days off" → `get_employee_profile` + `get_entitlements` + `check_coverage` + `get_project_events`

**Done when:** Tool calls fire dynamically based on intent. Tool events appear in the Activity panel.

---

## Task 2.2a — Conflict Signal Surfacing
**Owner:** Dev A + Dev C
**Priority:** P0
**Depends on:** Task 2.1

Configure the orchestrator so that for the demo scenario (27–28 Oct request by E005):
- It checks coverage → T02 SHORT surfaced
- It checks project events → change freeze surfaced
- It calls `find_viable_date_ranges()` automatically (dates are flexible)
- All steps appear in the Activity panel before the recommendation

**Done when:** Activity panel shows coverage SHORT + project event conflict before any recommendation is made. Verified by running the demo scenario.

---

## Task 2.2b — Recommendation Quality
**Owner:** Dev A + Dev C
**Priority:** P0
**Depends on:** Task 2.2a

Tune the orchestrator to produce a recommendation that:
- Explains why 27–28 Oct is not ideal (T02 SHORT + change freeze)
- Recommends a specific November window from `find_viable_date_ranges` output
- References Childcare Leave eligibility (or explains why AL is used instead)
- Gives the balance after

Run the full demo scenario 3 times in a row. All 3 must produce the correct recommendation structure.

**Done when:** 3/3 consistent runs with correct recommendation referencing both entitlement and team/project reasoning.

---

## Task 2.3 — Policy Q&A
**Owner:** Dev A + Dev B
**Priority:** P0
**Depends on:** Task 2.1, policy `.md` files available

Implement `backend/tools/policy_rag.py`:
- Load `policies/ibm_leave_policy.md` at startup, chunk by section heading, embed with `sentence-transformers`
- `search_policy(question)` — cosine similarity search, return top-2 chunks with section citation
- The tool is bound to the session user's company — an IBM user always searches the IBM policy, never the contractor policy

Wire into the orchestrator. Test with "How many days of Annual Leave do I get?" → response cites the IBM policy section.

**Note:** If policy files are not yet available, stub this tool to return `"Policy document not yet loaded."` and complete it when files arrive. Do not block the rest of P0 on this.

**Done when:** Policy Q&A returns a cited answer grounded in the IBM policy file. Contractor policy stub is in place.

---

# PHASE 3 — Human in the Loop

## Task 3.1 — Employee Confirmation
**Owner:** Dev D + Dev E
**Priority:** P0
**Depends on:** Task 2.2b

- Orchestrator presents recommendation summary (type, dates, working days, approver)
- Employee says "Yes" / "Proceed" / "Confirm" → `employee_confirmed = true`
- `submit_leave_request()` called → Pending row written
- `send_approval_email()` called → email sent to Marcus

Confirmation is only valid after a recommendation has been made in the current session.

**Done when:** After confirmation, `Employee_Time` contains a new Pending row and Marcus receives the approval email.

---

## Task 3.2 — Manager Approval UI Card
**Owner:** Dev E
**Priority:** P0
**Depends on:** Task 1.3

The manager approval card (already in the UI) should now:
- Fetch the pending request details from the backend when a request is in `PENDING_MANAGER_APPROVAL` state
- Update in real time when the token is used from email (poll `/api/session-state` every 3 seconds)
- Show APPROVED / REJECTED result when the manager acts

The card remains as a fallback if the manager doesn't use email — they can also click Approve/Reject in the UI.

**Done when:** Manager clicking Approve/Reject in either the email or the UI correctly transitions state and updates the UI.

---

## Task 3.3 — Full End-to-End Path
**Owner:** Dev D
**Priority:** P0
**Depends on:** Tasks 3.1, 3.2

Walk the complete golden demo path:
1. Wei Ling asks for balance → correct
2. Requests 27–28 Oct → conflict surfaced
3. Accepts November alternative → confirmed
4. Marcus receives approval email
5. Marcus approves from email
6. Wei Ling receives confirmation email with R###
7. Wei Ling asks "what's the status of R019?" → agent looks up and reports

Verify REJECT path: Marcus rejects → Wei Ling notified, no debit written.

**Done when:** Both approve and reject paths work end-to-end without manual intervention.

---

# PHASE 4 — Privacy Guardrails + Demo Polish

**Tasks 4.1 and 4.2 run in parallel.**

---

## Task 4.1 — Output Filter + Privacy
**Owner:** Dev A + Dev D
**Priority:** P0
**Depends on:** Task 2.1

Implement `backend/filters.py`:
- After every LLM response, scan for `E\d{3}` IDs and email addresses
- Strip any that don't belong to the session user or their manager
- Verify: asking "What's Wei Ling's balance?" as a different user returns a refusal
- Verify: free text from other employees' `reason` fields never appears in a prompt

Add tests in `backend/tests/test_filters.py`.

**Done when:** Output filter blocks cross-employee data leaks. All filter tests pass.

---

## Task 4.2 — Agent Activity Panel + Demo Reset
**Owner:** Dev E
**Priority:** P0
**Depends on:** Task 2.2a

- Agent Activity panel shows live tool events (SSE or polling)
- Each event has an icon: ✓ OK, ✗ conflict, → recommendation, ⏸ waiting
- Demo Reset button: clears session state, clears chat, restores Employee_Time to pre-demo state, resets activity log

**Done when:** Full demo can be repeated from scratch with one click.

---

# PHASE 5 — P0 Verification

Run after all Phase 0–4 tasks are complete.

## Task 5.1 — Full Test Suite
**Owner:** All
**Priority:** P0

Run `pytest backend/tests/ -v`. All tests must pass.

Required test coverage:
- HR tools (balance, working days, CL eligibility)
- Team tools (coverage SHORT/OK, alternative date search)
- Approval state machine (all guards, idempotent token)
- Output filter (cross-employee data blocked)
- Email send (mock SMTP, verify email content)

**Done when:** `pytest` exits 0.

---

## Task 5.2 — Golden Demo Run
**Owner:** All
**Priority:** P0

Execute the complete demo scenario and report each criterion:

| # | Criterion | PASS / FAIL |
|---|---|---|
| 1 | Wei Ling asks balance → correct AL and CL shown | |
| 2 | 27–28 Oct requested → working days = 2 | |
| 3 | T02 coverage SHORT 2/5 detected | |
| 4 | Project event (change freeze) on 27–28 Oct surfaced | |
| 5 | Alternative November window offered with reason | |
| 6 | Employee confirms → Pending row written to Employee_Time | |
| 7 | Marcus receives approval email with Approve/Reject links | |
| 8 | Marcus approves from email → debit row written | |
| 9 | Wei Ling receives confirmation email with reference R### | |
| 10 | Agent Activity panel shows all tool calls during demo | |
| 11 | "What's my balance?" returns only Wei Ling's data | |
| 12 | Policy Q&A cites correct IBM policy section | |

All 12 must PASS before P1 begins.

---

# PHASE 6 — P1 (only after all P0 criteria pass)

Do not start until Task 5.2 shows all 12 PASS.

## Task 6.1 — Team Absences View (F6 / US-6.1)
"Who's off next week?" for the user's own teams. Anonymised counts + "Out of office" labels. Max 2-month window.

## Task 6.2 — Contractor Routing (F9 / US-9.1)
- Add contractor persona (uses `SG_CONTRACT` time profile, `Companies.csv`)
- Contractor gets their own policy in RAG
- Contract HR receives FYI email (no action links)
- Contractor asking about IBM policy is declined

## Task 6.3 — Dependent-Update Guidance (F10 / US-10.1)
- Simulated "dependent added" POST endpoint
- Recalculates CL entitlement
- Sends in-chat notification: "You're now eligible for X days Childcare Leave — see Section Y of your policy."

## Task 6.4 — Request Status Lookup (F8 / US-8.3)
"What's the status of R019?" → agent looks up `Employee_Time` and reports. (May already be working from P0 Task 3.3.)

## Task 6.5 — Audit Log
Append-only `audit.jsonl`: every tool call (timestamp, user, tool, fields accessed) + every write (request ID).

---

# DO NOT BUILD DURING HACKATHON

- Real SuccessFactors or AskHR integration
- Outlook / Google Calendar sync (S3)
- Out-of-office automation (S3)
- Handover reminders (S4)
- Manager dashboard
- HR analytics
- Multi-language
- Native mobile app
- Production auth / security hardening
- ML forecasting
- MCP server setup (unless already familiar — deferred)

---

# Parallel Execution Map

```
Phase 0:  [0.1 Backend] ══╗   [0.2 Data] ══╗   [0.3 UI wired] ══╗
                           ╚═══════════════╩═══════════════════╝
                                          ▼
Phase 1:  [1.1 HR tools] ══╗  [1.2 Team tools] ══╗  [1.3 State machine] ══╗  [1.4 Email] ══╗
                            ╚══════════════════╩══════════════════════════╩══════════════╝
                                          ▼
Phase 2:        [2.1 Tool wiring] → [2.2a Conflict] → [2.2b Recommendation]
                                          |
                                    [2.3 Policy RAG] (can start when files arrive)
                                          ▼
Phase 3:        [3.1 Confirmation] ══╗   [3.2 Approval UI] ══╗
                                     ╚═══════════════════════╝
                                          ▼
                                      [3.3 End-to-end]
                                          ▼
Phase 4:        [4.1 Output filter] ══╗   [4.2 Activity panel + reset] ══╗
                                      ╚════════════════════════════════╝
                                          ▼
Phase 5:        [5.1 Full tests] → [5.2 Golden demo run]
                                          ▼
                                    *** P0 COMPLETE ***
                                          ▼
Phase 6:        P1 tasks (only on explicit instruction)
```

---

# Definition of Done — P0

The hackathon P0 is complete when:

**Wei Ling asks for her balance → correct AL and CL shown
→ requests 27–28 Oct → T02 SHORT + project conflict detected
→ November alternative offered with reason
→ employee confirms → Marcus receives approval email
→ Marcus approves from email → debit written, Wei Ling emailed
→ Wei Ling sees confirmation with reference ID
→ all tool calls visible in Agent Activity panel throughout**

Every one of the 12 criteria in Task 5.2 must be PASS.

# Project-Aware Leave Planning Agent
## Technical Design

**Status:** Hackathon MVP — v2 (aligned to feature_list.md)

---

# 1. Design Principles

- Simple hackathon implementation — no infrastructure that doesn't help the live demo
- Visible agentic behaviour — every tool call surfaced to the UI
- Deterministic business rules — LLM never does arithmetic or state transitions
- Safe human approval — enforced in application code, not prompts
- Real email workflow — approval email with single-use token links
- Mocked enterprise integrations — CSV/JSON data layer, no live SuccessFactors
- One reliable end-to-end demonstration

**One primary orchestrator agent.** All HR, project, email, and policy components are tools/services.

**Plain Python functions first.** MCP is a future integration layer — skip it for the hackathon unless already set up.

---

# 2. High-Level Architecture

```
                    Employee Browser (Chat UI)
                            |
                            v
              +---------------------------+
              |     ORCHESTRATOR AGENT    |
              |  (single LLM component)   |
              |                           |
              | - intent understanding    |
              | - tool selection          |
              | - candidate comparison    |
              | - recommendation          |
              | - explanation             |
              +-------------+-------------+
                            |
        +-------------------+-------------------+
        |                   |                   |
        v                   v                   v
  HR CONTEXT         TEAM / PROJECT       ACTION TOOLS
  (read-only)        (read-only)          (controlled)

  get_employee        get_team_leave       submit_leave
  get_dependents      get_project_events   approve_request
  get_entitlements    check_coverage       reject_request
  get_time_types      find_viable_dates    send_email
  validate_policy
  search_policy (RAG)
                            |
                    Output Filter Layer
                   (server-side, always on)
                            |
              +-------------+-------------+
              |                           |
      Manager Email               Employee Browser
   (Approve / Reject links)       (confirmation)
```

---

# 3. Components

## 3.1 Chat / Demo UI

Minimum viable layout: **split pane**.
- Left: chat messages + employee confirmation
- Right: Agent Activity stream

No authentication, navigation, or routing for the hackathon.

Session identity is set server-side at startup (hardcoded to the demo employee for the demo). In production this would come from SSO.

---

## 3.2 Orchestrator Agent

The only LLM-driven component.

**Does:**
- Understand employee intent
- Decide which tools to call
- Hold conversation state within the session
- Compare candidate dates
- Recommend leave type + dates
- Explain reasoning
- Ask for confirmation
- Trigger the approval email workflow

**Does NOT:**
- Calculate balances, working days, or date overlaps
- Mutate `approval_status`
- Bypass the output filter
- Accept a `user_id` from the conversation — identity always comes from the session

---

## 3.3 Output Filter (cross-cutting)

A server-side middleware layer that runs on every LLM response before it is sent to the browser.

Rules:
1. Block any `E###` employee ID that is not the session user or their direct manager.
2. Block any email address that is not the session user's or their manager's.
3. Strip free text sourced from other users' leave reasons or decision notes before it enters any prompt.

This is implemented as a post-processing function, not an LLM instruction.

---

## 3.4 Email Service

Used for:
- Approval request email → manager (F7 / US-7.2)
- Confirmation email → employee (F8 / US-8.1)
- FYI email → contract HR (F9, P1)

Implementation:
- Use **SendGrid** or **SMTP** (e.g. Gmail SMTP with app password) — whichever the team sets up fastest
- Two demo email accounts: one for the employee (Wei Ling), one for the manager (Marcus)
- Approve / Reject links contain a `token` query parameter
- Tokens are single-use, stored server-side (in-memory dict is fine for the hackathon), expire after 24 hours
- Token handler endpoint: `POST /api/approval/{token}?action=approve|reject`
- Clicking twice returns a "token already used" page — no duplicate state changes

---

# 4. Data Layer

All data lives in `hr_data/` as CSV files. The tool layer reads these files directly — no database required for the hackathon.

## 4.1 Existing tables (from repo)

| File | Used for |
|---|---|
| `02_Job_Information.csv` | Employee profile lookup |
| `03_Teams.csv` | Team headcount and min_staff_on_duty |
| `04_Team_Members.csv` | Multi-team membership for coverage checks |
| `05_Time_Type.csv` | Available leave types and rules |
| `06_Time_Account_Type.csv` | Account types (AL, OIL, SL, HL) |
| `07_Accrual_Rule.csv` | AL accrual tiers by years of service |
| `09_Work_Schedule.csv` | Working day pattern per employee |
| `10_Holiday_Calendar.csv` | Public holidays (SG, 2026–2027) |
| `11_Time_Account.csv` | Current balances (available, pending, projected) |
| `12_Time_Account_Detail.csv` | Ledger of all postings |
| `13_Employee_Time.csv` | Leave requests with approval status |

## 4.2 New tables to add before implementation

### `Dependents.csv`

| dependent_id | user_id | name | date_of_birth | relationship |
|---|---|---|---|---|
| DEP001 | E005 | (child name) | 2020-03-15 | Child |

One row per dependent. Used to derive Childcare Leave eligibility.

### `Entitlement_Rules.csv`

| rule_id | time_type_code | condition_field | condition_operator | condition_value | annual_quota_days | notes |
|---|---|---|---|---|---|---|
| ER001 | CL | child_age_at_jan1 | <= | 7 | 6 | Singapore Childcare Leave — child under 7 |
| ER002 | CL | child_age_at_jan1 | <= | 12 | 2 | Extended Childcare Leave — child 7–12 |

### `Companies.csv` (for contractor routing, P1)

| company_id | company_name | contract_hr_email | time_profile_code | policy_file |
|---|---|---|---|---|
| IBM | IBM Singapore | hr@i-be-yam.com | SG_STD | ibm_leave_policy.md |
| ContractCo | ContractCo Pte Ltd | hr@contractco.example.com | SG_CONTRACT | contractco_leave_policy.md |

### `Project_Events.csv` (for project context)

| event_id | project_id | event_type | start_date | end_date | description |
|---|---|---|---|---|---|
| PE001 | PROJ_ENG | DEPLOYMENT | 2026-11-03 | 2026-11-03 | Production release v2.1 |
| PE002 | PROJ_ENG | CHANGE_WINDOW | 2026-10-27 | 2026-10-28 | System change freeze |

Add E005's project_id to `Job_Information` or a separate `Projects` table.

### CL additions to existing files

Add to `05_Time_Type.csv`:
```
CL,Childcare Leave,Days,ACC_CL,Yes,No,Work schedule,Singapore Childcare Leave; eligibility from Dependents + Entitlement_Rules
```

Add to `06_Time_Account_Type.csv`:
```
ACC_CL,Childcare Leave Account,Recurring,Entitled,,Annual quota from Entitlement_Rules,2026-01-01,2026-12-31,No,Resets 1 Jan,Quota determined by child age; 6 days if child <= 7
```

Add `Time_Account` rows for E005:
```
TA061,E005,ACC_CL,2026-01-01,2026-12-31,N,6,0,0,6,6
```

---

## 4.3 Policy Documents

Two markdown files, placed in `policies/`:

| File | Used for |
|---|---|
| `policies/ibm_leave_policy.md` | IBM employees (to be supplied by team) |
| `policies/contractco_leave_policy.md` | Contractors (to be supplied by team) |

These are loaded into a simple RAG tool (vector store or keyword search). For the hackathon, a lightweight approach using `sentence-transformers` + cosine similarity over chunked paragraphs is sufficient. Full vector DB (Pinecone, Chroma) is not required.

---

# 5. Tool Groups

All tools are plain Python functions. Session `user_id` is injected server-side — never accepted as a parameter from the LLM.

## 5.1 HR Context Tools — Read Only

### `get_employee_profile()`
Reads `Job_Information` for the session user. Returns profile, team(s), manager, time profile, work schedule, holiday calendar code.

### `get_dependents()`
Reads `Dependents` for the session user. Returns list of dependents with age computed from DOB.

### `get_entitlements()`
Reads `Time_Account` for the session user. For each account type:
- Returns `available` (the pre-computed field)
- For CL: calls `check_childcare_eligibility()` first; returns 0 if ineligible
- For OIL: flags credits expiring within 30 days

### `check_childcare_eligibility()`
Deterministic. Reads `Dependents` + `Entitlement_Rules`. Returns `{eligible: bool, quota_days: int, reason: str}`.

### `validate_policy(leave_type, start_date, end_date, half_day)`
Deterministic. Validates: date range, working-day count (using `Work_Schedule` + `Holiday_Calendar`), balance sufficiency, no overlap with existing requests, leave type in `Time_Profile`.

Returns: `{valid: bool, working_days: int, remaining_after: float, violations: [str]}`.

### `search_policy(question)`
RAG tool. Searches the authenticated user's employer's policy `.md` file. Returns top-matching paragraph(s) with section citation. Does NOT search another company's policy.

---

## 5.2 Team / Project Context Tools — Read Only

### `get_team_leave(start_date, end_date)`
Reads `Employee_Time` (Approved + Pending) overlapping the date range, joined with `Team_Members` for all teams the session user belongs to.

Returns per-team list of absent members — **anonymised as "Out of office"** in the tool output itself, not only in the UI layer.

### `check_coverage(start_date, end_date)`
Deterministic. For each of the session user's teams:
- `absent = members with Approved/Pending leave in range + 1 (the session user)`
- `on_duty = headcount - absent`
- status = `OK` if `on_duty >= min_staff_on_duty`, `AT_MIN` if equal, `SHORT` if below

Returns per-team `{team_id, team_name, on_duty, min_required, status}`.

### `get_project_events(start_date, end_date)`
Reads `Project_Events` for the session user's project. Returns events with type, description, dates.

### `find_viable_date_ranges(leave_type, duration_days, preferred_start, search_days)`
Deterministic search. Iterates candidate windows outward from `preferred_start` within `search_days`.

Pre-filters each candidate for:
1. Sufficient balance for `leave_type`
2. All teams `OK` or `AT_MIN` (not `SHORT`)
3. No overlap with existing requests
4. Within current leave year

Returns up to 3 candidates with:
- start, end, working_days
- coverage status per team
- project events in range
- human-readable reason string

The agent selects among these — it does not re-filter.

---

## 5.3 Action Tools — Controlled Writes

### `submit_leave_request(leave_type, start_date, end_date, half_day, reason)`
Precondition: `employee_confirmed = true`.

1. Re-validates (REQ-006 checks run again at submit time).
2. Writes new row to `Employee_Time` with `approval_status = Pending`.
3. Returns `{employee_time_id, status}`.

Does NOT send the email — that is a separate step.

### `send_approval_email(employee_time_id)`
1. Generates a single-use approval token (UUID, stored in memory with expiry).
2. Generates a single-use rejection token.
3. Sends email to `manager_id`'s email address with: employee name, leave type, dates, working days, balance after, coverage summary, Approve and Reject links.
4. Returns `{email_sent: bool, manager_email: str}`.

### `handle_approval_token(token, action)`
Called by the token callback endpoint, not by the LLM.

1. Validates token (exists, not expired, not already used).
2. Marks token as used.
3. Updates `Employee_Time.approval_status` to `Approved` or `Rejected`.
4. If Approved: writes `Time_Account_Detail` debit row.
5. Sends confirmation or rejection email to employee.
6. Returns `{success: bool}`.

Calling this with a used or expired token returns an error. No duplicate state changes.

---

> **P1 only — do not implement during initial P0 build:**
> `update_leave_log()` — appends to audit JSON log.
> `get_team_calendar()` — team absences view (F6).
> `route_contractor_hr_email()` — FYI email to contract HR (F9).
> `trigger_dependent_guidance()` — simulated dependent-added event (F10).

---

# 6. Approval State Machine

```
DRAFT
  |
  v  [employee_confirmed = true]
EMPLOYEE_CONFIRMED
  |
  v  [submit_leave_request() called]
PENDING_MANAGER_APPROVAL
  |                     |
  v                     v
APPROVED             REJECTED
  |
  v  [handle_approval_token() called — debit written, email sent]
SUBMITTED
```

State transitions are enforced in application code only.

The LLM MUST NOT mutate `approval_status` or `employee_confirmed`.

`submit_leave_request()` MUST reject if `employee_confirmed ≠ true`.
`handle_approval_token()` MUST reject if `approval_status ≠ PENDING_MANAGER_APPROVAL`.

---

# 7. Conversation / Workflow State

Held in server-side session memory (in-memory dict keyed by session ID):

```
session_user_id          # set at login, never from LLM
user_goal
requested_leave_type
requested_dates
requested_duration
flexibility

employee_profile         # cached after first retrieval
entitlements             # cached after first retrieval

original_option          # assessment of the originally requested dates
alternatives             # list of candidate windows from find_viable_date_ranges

recommended_leave_type
recommended_dates
recommendation_reason

employee_confirmed       # bool — set by application logic, not LLM

employee_time_id         # set after submit_leave_request()
approval_status          # mirrors Employee_Time row
approval_token_map       # {token: {employee_time_id, action, expiry, used}}

reference_id             # final R### from Employee_Time
```

---

# 8. Agent vs Deterministic Logic

## Agent (LLM)
- Intent interpretation
- Which tools to call
- Whether clarification is needed
- Candidate comparison
- Recommendation narrative and reasoning
- Explanation of conflicts

## Deterministic code
- Balance arithmetic
- Working-day calculation
- Date validation and overlap detection
- Coverage calculation
- Candidate date generation and pre-filtering
- CL eligibility derivation
- Output filter (PII stripping)
- Approval state transitions
- Token generation, validation, expiry
- Submission authorisation guard

---

# 9. Policy RAG Tool

Simple two-step implementation:

1. **Indexing** (at startup): load `policies/ibm_leave_policy.md` and `policies/contractco_leave_policy.md`, split into paragraphs, embed with `sentence-transformers` (e.g. `all-MiniLM-L6-v2`), store in memory as numpy arrays.
2. **Query**: embed the question, cosine-similarity search, return top-2 paragraphs with section heading as citation.

The tool is called with the session user's company derived server-side — the LLM cannot choose which policy to search.

For the hackathon, no vector database is needed. If the policy files arrive late, stub this tool to return a placeholder and add it last.

---

# 10. Guardrails

1. No submission without `employee_confirmed = true` (enforced in `submit_leave_request()`).
2. No fulfilment without `approval_status = APPROVED` (enforced in `handle_approval_token()`).
3. LLM cannot mutate `approval_status` or `employee_confirmed`.
4. All write actions validate workflow state before executing.
5. Tool failures return explicit limitation messages — no fabricated data.
6. Output filter runs on every LLM response before browser delivery.
7. `user_id` is never accepted as a tool parameter from the LLM — always from session.
8. Free text from other users' records never enters an LLM prompt.

All 8 guardrails must have tests before the demo.

---

# 11. Demo Observability

Agent Activity panel (right pane) streams events such as:

```
✓ Retrieved profile — Wei Ling Chua (E005, Empty'em + Apple CS)
✓ Checked entitlements — AL: 5 available, CL: 6 available
✓ Checked coverage 27–28 Oct — T02: SHORT 2/5 ⚠
✓ Retrieved project events — Change freeze 27–28 Oct ⚠
✓ Searching alternatives within 21 days...
✓ Found 3 viable windows
→ Recommended: 10–11 Nov (Annual Leave)
⏸ Waiting for employee confirmation...
✓ Request R019 submitted — approval email sent to marcus.lim@i-be-yam.com
⏸ Waiting for manager approval...
✓ Marcus approved — ledger updated, confirmation email sent
✓ Status: SUBMITTED (R019)
```

Implement as server-sent events (SSE) or a polling endpoint. Functional is sufficient — polish is secondary.

---

# 12. Stack and File Structure

**Recommended stack:**

| Layer | Choice |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Frontend | HTML/JS (split-pane, already in repo) or minimal React |
| Agent / LLM | watsonx / Granite / any model with tool-calling |
| Email | SendGrid SDK or `smtplib` with Gmail SMTP + app password |
| Policy RAG | `sentence-transformers` (all-MiniLM-L6-v2) in-memory |
| Data | CSV files in `hr_data/` |
| Tests | pytest |

**Proposed file structure:**

```
/
├── index.html               # existing UI shell
├── vercel.json              # existing Vercel config
├── backend/
│   ├── main.py              # FastAPI app, routes
│   ├── agent.py             # Orchestrator agent + tool definitions
│   ├── tools/
│   │   ├── hr.py            # get_employee_profile, get_entitlements, etc.
│   │   ├── team_project.py  # check_coverage, find_viable_date_ranges, etc.
│   │   ├── actions.py       # submit_leave_request, send_approval_email, handle_approval_token
│   │   └── policy_rag.py    # search_policy
│   ├── filters.py           # output filter (PII stripping)
│   ├── state.py             # session state management
│   ├── email_service.py     # email send + token management
│   ├── data/                # symlink or copy of hr_data/ CSVs
│   └── tests/
│       ├── test_hr_tools.py
│       ├── test_team_tools.py
│       ├── test_actions.py
│       ├── test_filters.py
│       └── test_approval_flow.py
├── hr_data/                 # CSVs (source of truth)
└── policies/
    ├── ibm_leave_policy.md
    └── contractco_leave_policy.md
```

---

# 13. Email Account Setup

Two demo email accounts are required:

| Role | Address | Used for |
|---|---|---|
| Employee (Wei Ling) | (team to create) | Receives confirmation / rejection emails |
| Manager (Marcus) | (team to create) | Receives approval request email with action links |

Configure credentials in a `.env` file (never committed):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...    # Gmail app password
EMAIL_FROM=...
APP_BASE_URL=https://your-vercel-app.vercel.app
```

The `APP_BASE_URL` is used to construct the Approve/Reject token links.

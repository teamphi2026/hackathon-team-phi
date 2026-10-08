You have 10 core features and 4 stretch features. Below they're broken into user stories with acceptance criteria. The examples use your seeded data, so each story doubles as a demo or test case. Where a decision is still open, I've used my recommended default and marked it with *(assumed)*.

## Personas

| Persona | Example from data |
|---|---|
| IBM employee | Wei Ling Chua (E005), in 2 teams |
| Contractor | To be added (ContractCo) |
| Supervisor | Marcus Lim (E004), Engineering Manager |
| Contract HR | `contract_hr_email` from the `Companies` tab |

## Features at a glance

| # | Feature | Priority |
|---|---|---|
| F1 | Personalised leave summary | Must |
| F2 | Company-specific policy Q&A | Must |
| F3 | Natural-language leave request + validation | Must |
| F4 | Team conflict detection | Must |
| F5 | Smart date suggestions | Must |
| F6 | Team absences view | Should |
| F7 | Submit + approval email | Must |
| F8 | Approve/reject + fulfilment (every system updated) | Must |
| F9 | Contractor routing | Should |
| F10 | Proactive dependent-update guidance | Should |
| F11 | Privacy guardrails + audit | Must (cross-cutting) |
| S1–S4 | Cancel request, request history, out-of-office, handover reminder | Stretch |

## F1: Personalised leave summary

**US-1.1** As an employee, I want to ask "what leave can I take?" so that I can see every leave type I'm eligible for and my balance for each.
- Shows each eligible type with available days, pending days and expiring OIL credits.
- Includes profile-based types, e.g. childcare when I have an eligible child, calculated from `Dependents` and `Entitlement_Rules`.
- The numbers come from tools, never from the LLM. E005 shows AL: 5 available, 5 pending.
- Children's names and birthdates never appear in the reply. Only the derived entitlement does.

**US-1.2** As an employee, I want to ask "why do I have 12.5 days?" so that I trust the number.
- Explains the balance from ledger postings: accruals minus bookings.

## F2: Company-specific policy Q&A

**US-2.1** As an employee, I want to ask policy questions in plain English so that I don't have to read the PDF.
- Answers only from my employer's `.md` file and cites the section, e.g. "(Section 4.1)."
- If the policy doesn't cover the question, it says so and points me to HR.

**US-2.2** As a contractor, I want answers based on my own company's policy, not IBM's.
- An IBM employee and a contractor asking the same question get different, correctly cited answers.
- Asking "what does IBM's policy say?" as a contractor is declined.
- Contractors also get IBM site rules, such as holidays and blackouts *(assumed)*.

## F3: Natural-language leave request + validation

**US-3.1** As an employee, I want to type "I need 27–28 Oct off" so that I don't fill in forms.
- Extracts dates and leave type. Asks one clarifying question if either is missing.
- Shows a summary (type, dates, working days, approver) and asks me to confirm before submitting.

**US-3.2** As an employee, I want accurate working-day counts so that I'm not charged for holidays or weekends.
- R012's dates (9–13 Nov) count as 4 days, because the Deepavali in-lieu holiday is excluded.
- Half days are allowed only for single-day requests.

**US-3.3** As an employee, I want to be told immediately if my request is invalid.
- Rejects: dates in the past, not enough balance, overlap with my own Pending or Approved requests, and leave types I'm not eligible for.
- SL and HL are flagged as needing documentation and are auto-approved.

## F4: Team conflict detection

**US-4.1** As an employee, I want to know if my leave leaves my team short-staffed so that I can choose considerately.
- Checks every team I belong to. E005's request is checked against both T02 and T04.
- Pending and Approved requests both count as absent.
- If 27–28 Oct puts T02 at 2 of 5 on duty (minimum 3), the reply shows a warning with dates and teammates' names. Teammates appear only as "Out of office."
- A clash warns but doesn't block. The supervisor decides.

## F5: Smart date suggestions

**US-5.1** As an employee with flexible dates, I want "4 days off sometime in November" to suggest the best windows.
- Returns up to 3 windows that meet the hard constraints: balance, cover, no self-overlap, within the current year.
- Ranked by closeness to my preferred dates, leave efficiency and cover margin *(assumed weighting)*.
- Each window comes with a reason, e.g. "10–13 Nov: 4 AL days gives 9 days off thanks to Deepavali in-lieu; cover OK."
- Results are anonymised: counts only, no teammate names.

**US-5.2** As an employee whose dates clash, I want alternatives offered automatically so that I don't have to start over.

## F6: Team absences view

**US-6.1** As an employee, I want to ask "who's off next week?" so that I can plan handovers.
- Covers only my own teams, with a maximum window of about 2 months.
- Shows name, dates and "Out of office" or "Out of office (tentative)" *(assumed)*.
- Never shows leave type, reason or balance.

## F7: Submit + approval email

**US-7.1** As an employee, I want one confirmation to submit my request and notify my supervisor.
- Validation runs again at submit time.
- Writes a Pending row to the HR Database and a tentative row to the Shared sheet.
- Emails my `manager_id` and returns a reference number such as R019.

**US-7.2** As a supervisor, I want an email with everything I need to decide.
- Includes employee, dates, type, working days, balance after approval, and the team cover summary for my team.
- Has Approve and Reject buttons with single-use, expiring tokens. Rejecting lets me add an optional reason.

**US-7.3** As the MD (E001, no manager), I want my requests routed sensibly.
- They go to the HR Manager (E002) *(assumed)*.

## F8: Approve/reject + fulfilment

**US-8.1** As a supervisor, I want one click on Approve to update every system.
- In order:
  1. HR Database status set to Approved, with a ledger debit row.
  2. Shared sheet row confirmed.
  3. Calendar event created.
  4. Employee emailed a confirmation with the reference number.
- No LLM is involved. Clicking twice doesn't create duplicates.

**US-8.2** As a supervisor, I want Reject to notify the employee with my reason.
- Status set to Rejected, the Shared row removed, the employee emailed, no ledger posting.

**US-8.3** As an employee, I want to see the result in chat if I ask "what's the status of R019?"

## F9: Contractor routing

**US-9.1** As a contractor, I want my request approved by my IBM supervisor while my agency's HR is kept informed.
- The supervisor gets the approval email. Contract HR gets an FYI with no action links.
- The contractor's entitlements and policy come from their company, using the `SG_CONTRACT` profile.

## F10: Proactive dependent-update guidance

**US-10.1** As an employee who has just added a child in SuccessFactors, I want to be told what's changed for me.
- A simulated "dependent added" event recalculates my entitlements.
- I get a message in ask.hr, e.g. "You're now eligible for childcare leave: X days per `Entitlement_Rules`."
- It links to the relevant policy section.

## F11: Privacy guardrails + audit (cross-cutting)

**US-11.1** As an employee, I want my personal data kept private from colleagues.
- "What's Wei Ling's balance?" is refused.
- Identity comes from the session. No tool or MCP call accepts a `user_id` from the LLM.

**US-11.2** As HR, I want an audit trail of what the agent accessed and changed.
- Every tool call is logged with timestamp, user, tool and fields returned. Every write records the request ID.

**US-11.3** As a security reviewer, I want leaks blocked even if a tool misbehaves.
- An output filter blocks any email address or employee ID that isn't the user's or their manager's.
- Free text from other users, such as reasons and notes, never goes into a prompt.

## Stretch

| ID | Story |
|---|---|
| S1 | As an employee, I want to cancel a request so that it's reversed everywhere (reversal ledger row, Shared row removed, calendar event deleted). |
| S2 | As an employee, I want to see my request history with status. |
| S3 | As an employee, I want out-of-office set automatically for my approved dates. |
| S4 | As an employee, I want a handover reminder the day before my leave starts. |

## Suggested demo storyline

The stories chain into one five-minute demo:
1. Wei Ling asks for her balance (US-1.1).
2. She requests 27–28 Oct and gets a clash warning (US-4.1).
3. She accepts a suggested date in November (US-5.2).
4. She submits (US-7.1).
5. Marcus approves from his email (US-8.1), and the Sheet, calendar and confirmation email all update on screen.
6. A contractor asks the same policy question and gets a different, cited answer (US-2.2).
7. A simulated dependent event triggers new guidance (US-10.1).

[1]: Are the priorities right? In particular, are F6 (team view), F9 (contractors) and F10 (dependent event) "Should" rather than "Must"?
a. **Yes, as listed.**
b. **Promote F10 to Must.** It's the pitch's core differentiator.
c. **Other changes.**

[2]: Who on the team owns which feature? If you share names and skills, I'll map the stories to people and time slots in the implementation plan.

[3]: Are you ready for me to write the full task-by-task implementation plan? I'd use these stories and my recommended defaults for the open decisions (stack, Google bot account, links, Fulfilment as code, Scheduling as orchestrator tools, a single MCP server or none).

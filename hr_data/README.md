# HR Orchestrator AI Agent — workbook index

Sheets 1–16 are converted from `HR Orchestrator AI Agent.xlsx`. Each sheet is exported as a UTF-8 CSV in this folder (first row = column headers). Files 17–21 are not in the workbook; they were added for the orchestrator backend (childcare leave, project-aware planning, multi-company policies and login). Small reference sheets are also inlined below.

| # | Sheet | File | Data rows | Columns |
|---|---|---|---|---|
| 1 | SF_Mapping | [01_SF_Mapping.csv](01_SF_Mapping.csv) | 22 | tab, match_level, sf_equivalent, whats_the_same, whats_different_or_extra, sf_field_names_used, source |
| 2 | Job_Information | [02_Job_Information.csv](02_Job_Information.csv) | 15 | user_id, full_name, email, home_team_id, job_title, manager_id, join_date, years_of_service, employment_status, annual_leave_entitlement, all_teams, team_count, time_profile_code, work_schedule_code, holiday_calendar_code, project_id |
| 3 | Teams | [03_Teams.csv](03_Teams.csv) | 5 | team_id, team_name, head_employee_id, headcount, min_staff_on_duty, notes |
| 4 | Team_Members | [04_Team_Members.csv](04_Team_Members.csv) | 18 | membership_id, user_id, team_id, is_primary, role_in_team |
| 5 | Time_Type | [05_Time_Type.csv](05_Time_Type.csv) | 5 | time_type_code, time_type_name, time_unit, time_account_type_code, requires_approval, requires_medical_cert, duration_display, notes |
| 6 | Time_Account_Type | [06_Time_Account_Type.csv](06_Time_Account_Type.csv) | 5 | time_account_type_code, time_account_type_name, account_creation_type, entitlement_method, accrual_rule_code, annual_quota_days, account_valid_from, account_valid_until, carry_over_allowed, expiry_rule, notes |
| 7 | Accrual_Rule | [07_Accrual_Rule.csv](07_Accrual_Rule.csv) | 5 | accrual_rule_code, tier_id, min_years_service, max_years_service, annual_days, posting_frequency, first_posting_rule, description |
| 8 | Time_Profile | [08_Time_Profile.csv](08_Time_Profile.csv) | 7 | time_profile_code, time_type_code, available_to_employee, favorite, main_absence_time_type |
| 9 | Work_Schedule | [09_Work_Schedule.csv](09_Work_Schedule.csv) | 2 | work_schedule_code, work_schedule_name, mon_hours, tue_hours, wed_hours, thu_hours, fri_hours, sat_hours, sun_hours, weekend_mask |
| 10 | Holiday_Calendar | [10_Holiday_Calendar.csv](10_Holiday_Calendar.csv) | 26 | date, holiday_name, day_of_week, is_in_lieu, notes, holiday_calendar_code |
| 11 | Time_Account | [11_Time_Account.csv](11_Time_Account.csv) | 61 | time_account_id, user_id, time_account_type_code, account_valid_from, account_valid_until, account_closed, balance_today, planned_bookings, pending_requests, available, projected_year_end |
| 12 | Time_Account_Detail | [12_Time_Account_Detail.csv](12_Time_Account_Detail.csv) | 199 | detail_id, time_account_id, booking_date, posting_type, booking_amount, booking_unit, employee_time_id, comment, expiry_date, consumes_detail_id, remaining_credit, credit_status |
| 13 | Employee_Time | [13_Employee_Time.csv](13_Employee_Time.csv) | 18 | employee_time_id, user_id, time_type_code, start_date, end_date, half_day, quantity_in_days, reason, approval_status, approver_id, submitted_at, decided_at, decision_note |
| 14 | Day_Calculator | [14_Day_Calculator.csv](14_Day_Calculator.csv) | 6 | field, value, notes |
| 15 | Leave_Calendar | [15_Leave_Calendar.csv](15_Leave_Calendar.csv) | 38 | Month (type any date in it):, 2026-10-01, , , , , , , team, short_days, at_min_days, verdict |
| 16 | Agent_Guide | [16_Agent_Guide.csv](16_Agent_Guide.csv) | 30 | item_type, name, description, reads, writes, logic |
| 17 | Dependents | [17_Dependents.csv](17_Dependents.csv) | 1 | dependent_id, user_id, name, date_of_birth, relationship |
| 18 | Entitlement_Rules | [18_Entitlement_Rules.csv](18_Entitlement_Rules.csv) | 2 | rule_id, time_type_code, condition_field, condition_operator, condition_value, annual_quota_days, notes |
| 19 | Project_Events | [19_Project_Events.csv](19_Project_Events.csv) | 2 | event_id, project_id, event_type, start_date, end_date, description |
| 20 | Companies | [20_Companies.csv](20_Companies.csv) | 3 | company_id, company_name, contract_hr_email, time_profile_code, policy_file |
| 21 | Users | [21_Users.csv](21_Users.csv) | 3 | username, salt, password_hash, user_id, display_name |

## SF_Mapping

File: `01_SF_Mapping.csv`

| tab | match_level | sf_equivalent | whats_the_same | whats_different_or_extra | sf_field_names_used | source |
|---|---|---|---|---|---|---|
| Job_Information | Superset | Employee Central Job Information (Employment/Job Info) | user_id, manager, job title, hire date, one row per employee | Adds computed columns (years_of_service, entitlement, all_teams, team_count); flattens person, email and job data that SF holds in separate objects | userId, managerId, jobTitle, hireDate, timeProfile, workScheduleCode, holidayCalendarCode | https://help.sap.com/docs/successfactors-employee-central |
| Time_Type | Equivalent | Time Type (Time Off) | Code, name, unit, linked account type, approval flag | Adds requires_medical_cert and duration_display as simple helper columns | externalCode, unit, timeAccountType, approvalRequired | https://help.sap.com/docs/successfactors-time-off |
| Time_Account_Type | Partial | Time Account Type | Recurring/Permanent/Ad Hoc idea, accrual or entitlement method, validity | Simplified: one row per type, quota and expiry rule stored as plain columns; SF uses more configuration (e.g. account creation, period, accrual rule objects) | externalCode, accountCreationType, timeAccountCategory | https://help.sap.com/docs/successfactors-time-off |
| Accrual_Rule | Partial | Accrual/Accumulation rule (Time Account Type configuration) | Service-based tiers, posting frequency, first posting rule | Flattened into one table; SF models these with rule and eligibility objects. Inference: SF details are simplified here | accrualRule, seniority tiers | https://help.sap.com/docs/successfactors-time-off |
| Time_Profile | Equivalent | Time Profile | Assigns the time types an employee may use | Adds favorite and main_absence_time_type flags only as columns | timeProfile, timeType | https://help.sap.com/docs/successfactors-time-off |
| Work_Schedule | Partial | Work Schedule + Day Model | Hours per weekday decide working days | SF builds schedules from Day Models and a repeating pattern; here hours are one row per weekday set. Adds weekend_mask helper for NETWORKDAYS.INTL | workScheduleCode, dayModel | https://help.sap.com/docs/successfactors-time-off |
| Holiday_Calendar | Partial | Holiday Calendar / Holiday | Calendar code with dated holidays | SF has separate Holiday Calendar and Holiday objects; here combined in one table. Adds is_in_lieu note | holidayCalendar, holiday, date | https://help.sap.com/docs/successfactors-time-off |
| Time_Account | Superset | Time Account | One account per employee per time account type per validity period | Adds computed balance_today, planned_bookings, pending_requests, available, projected_year_end as live formulas; SF computes balances in the system and reports them separately | timeAccountType, user, bookingStartDate, bookingEndDate | https://help.sap.com/docs/successfactors-time-off |
| Time_Account_Detail | Superset | Time Account Detail | Ledger of postings (booking date, amount, unit, posting type, link to employee time); balance is the sum | Extra columns expiry_date, consumes_detail_id, remaining_credit, credit_status and a custom Expiry posting type for OIL; these are custom, not SF fields | bookingDate, bookingAmount, bookingUnit, employeeTime, comment, postingType | https://help.sap.com/docs/successfactors-time-off |
| Employee_Time | Partial | Employee Time (absence request) | Employee, time type, start/end date, quantity in days, approval status | No Pending Cancellation status and no separate workflow object; adds half_day, decision_note and approver columns inline | userId, timeType, startDate, endDate, quantityInDays, approvalStatus | https://help.sap.com/docs/successfactors-time-off |
| Teams | Custom | None (nearest: Foundation Object Department/Division) | Org-unit concept | Not an SF Time Off object. Adds head, headcount and min_staff_on_duty for clash checks | n/a | n/a |
| Team_Members | Custom | None (nearest: matrix manager relationship, a different concept) | Person-to-group link | Supports one person in many teams; SF matrix manager models additional managers, not teams | n/a | n/a |
| Leave_Calendar | Custom | Team Absences view (UI feature) | Shows who is absent when | Built with formulas, with per-team minimum cover and SHORT flags that SF does not have by default | n/a | n/a |
| Day_Calculator | Custom | None | n/a | Helper for the agent to count working days; not an SF object | n/a | n/a |
| Agent_Guide | Custom | None | n/a | Instructions for the AI agent; not an SF object | n/a | n/a |
| SF_Mapping | Custom | None | n/a | This tab | n/a | n/a |
| LEGEND |  |  |  |  |  |  |
| Equivalent |  | Same concept and similar fields as SF |  |  |  |  |
| Partial |  | Same concept but simplified or flattened vs SF |  |  |  |  |
| Superset |  | Does what SF does and more (extra columns or formulas) |  |  |  |  |
| Custom |  | Not an SF concept; added for the hackathon agent |  |  |  |  |
| CAVEAT |  | Based on public SAP Help Portal docs, not a live SuccessFactors tenant. Field names are approximate. Where the sheet notes an inference, it is my reading, not confirmed against SAP. |  |  |  |  |

## Job_Information

File: `02_Job_Information.csv`

| user_id | full_name | email | home_team_id | job_title | manager_id | join_date | years_of_service | employment_status | annual_leave_entitlement | all_teams | team_count | time_profile_code | work_schedule_code | holiday_calendar_code | project_id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E001 | Priya Nair | priya.nair@i-be-yam.com | T01 | Managing Director |  | 2015-03-02 | 11 | Active | 21 | Man Age Men-T | 1 | SG_STD | SG_STD | SG |  |
| E002 | Daniel Tan | daniel.tan@i-be-yam.com | T05 | HR Manager | E001 | 2017-06-12 | 9 | Active | 21 | Meow Woof Arf | 1 | SG_STD | SG_STD | SG |  |
| E003 | Aisha Rahman | aisha.rahman@i-be-yam.com | T05 | HR Executive | E002 | 2023-02-01 | 3 | Active | 15 | Meow Woof Arf | 1 | SG_STD | SG_STD | SG |  |
| E004 | Marcus Lim | marcuslim94@proton.me | T02 | Engineering Manager | E001 | 2018-09-03 | 8 | Active | 21 | Empty'em | 1 | SG_STD | SG_STD | SG | PROJ_ENG |
| E005 | Wei Ling Chua | chuaweiling@proton.me | T02 | Senior Software Engineer | E004 | 2020-01-06 | 6 | Active | 18 | Empty'em, Apple Computer Science | 2 | SG_STD | SG_STD | SG | PROJ_ENG |
| E006 | Rahul Menon | rahul.menon@i-be-yam.com | T02 | Software Engineer | E004 | 2022-07-04 | 4 | Active | 18 | Empty'em | 1 | SG_STD | SG_STD | SG | PROJ_ENG |
| E007 | Sarah Koh | sarah.koh@i-be-yam.com | T02 | Software Engineer | E004 | 2025-03-17 | 1 | Active | 15 | Empty'em | 1 | SG_STD | SG_STD | SG | PROJ_ENG |
| E008 | Jun Wei Ong | junwei.ong@i-be-yam.com | T02 | QA Engineer | E004 | 2024-11-04 | 1 | Active | 15 | Empty'em | 1 | SG_STD | SG_STD | SG | PROJ_ENG |
| E009 | Fatimah Yusof | fatimah.yusof@i-be-yam.com | T03 | Sales Manager | E001 | 2019-04-15 | 7 | Active | 18 | Diva Counter Strike | 1 | SG_STD | SG_STD | SG |  |
| E010 | Kevin Teo | kevin.teo@i-be-yam.com | T03 | Account Executive | E009 | 2021-08-02 | 5 | Active | 18 | Diva Counter Strike | 1 | SG_STD | SG_STD | SG |  |
| E011 | Michelle Goh | michelle.goh@i-be-yam.com | T03 | Account Executive | E009 | 2023-10-09 | 2 | Active | 15 | Diva Counter Strike, Meow Woof Arf | 2 | SG_STD | SG_STD | SG |  |
| E012 | Arjun Pillai | arjun.pillai@i-be-yam.com | T03 | Sales Associate | E009 | 2026-01-12 | 0 | Active | 15 | Diva Counter Strike | 1 | SG_STD | SG_STD | SG |  |
| E013 | Grace Lee | grace.lee@i-be-yam.com | T04 | Operations Manager | E001 | 2014-05-19 | 12 | Active | 21 | Apple Computer Science | 1 | SG_STD | SG_STD | SG |  |
| E014 | Ismail Hassan | ismail.hassan@i-be-yam.com | T04 | Operations Executive | E013 | 2022-02-14 | 4 | Active | 18 | Apple Computer Science, Diva Counter Strike | 2 | SG_STD | SG_STD | SG |  |
| E015 | Cheryl Wong | cheryl.wong@i-be-yam.com | T04 | Operations Coordinator | E013 | 2025-09-01 | 1 | Active | 15 | Apple Computer Science | 1 | SG_STD | SG_STD | SG |  |

## Teams

File: `03_Teams.csv`

| team_id | team_name | head_employee_id | headcount | min_staff_on_duty | notes |
|---|---|---|---|---|---|
| T01 | Man Age Men-T | E001 | 1 | 1 | Leadership |
| T02 | Empty'em | E004 | 5 | 3 | At least 3 engineers must be on duty each working day |
| T03 | Diva Counter Strike | E009 | 5 | 2 | At least 2 sales staff must be on duty each working day |
| T04 | Apple Computer Science | E013 | 4 | 2 | At least 2 operations staff must be on duty each working day |
| T05 | Meow Woof Arf | E002 | 3 | 1 | At least 1 HR staff must be on duty each working day |

## Team_Members

File: `04_Team_Members.csv`

| membership_id | user_id | team_id | is_primary | role_in_team |
|---|---|---|---|---|
| M001 | E001 | T01 | Y | Managing Director |
| M002 | E002 | T05 | Y | HR Manager |
| M003 | E003 | T05 | Y | HR Executive |
| M004 | E004 | T02 | Y | Team lead |
| M005 | E005 | T02 | Y | Senior Software Engineer |
| M006 | E006 | T02 | Y | Software Engineer |
| M007 | E007 | T02 | Y | Software Engineer |
| M008 | E008 | T02 | Y | QA Engineer |
| M009 | E009 | T03 | Y | Team lead |
| M010 | E010 | T03 | Y | Account Executive |
| M011 | E011 | T03 | Y | Account Executive |
| M012 | E012 | T03 | Y | Sales Associate |
| M013 | E013 | T04 | Y | Team lead |
| M014 | E014 | T04 | Y | Operations Executive |
| M015 | E015 | T04 | Y | Operations Coordinator |
| M016 | E005 | T04 | N | Systems liaison |
| M017 | E014 | T03 | N | Sales operations support |
| M018 | E011 | T05 | N | Recruitment interviewer |

## Time_Type

File: `05_Time_Type.csv`

| time_type_code | time_type_name | time_unit | time_account_type_code | requires_approval | requires_medical_cert | duration_display | notes |
|---|---|---|---|---|---|---|---|
| AL | Annual Leave | Days | ACC_AL | Yes | No | Work schedule | Entitlement accrues monthly; see Accrual_Rule |
| OIL | Off-in-Lieu | Days | ACC_OIL | Yes | No | Work schedule | Earned for work on rest days or public holidays; each credit expires 3 months after the earned date (assumption) |
| SL | Sick Leave (outpatient) | Days | ACC_SL | No | Yes | Work schedule | Notify manager; medical certificate required |
| HL | Hospitalisation Leave | Days | ACC_HL | No | Yes | Work schedule | 46 days on top of 14 days SL (60 combined); hospital discharge documentation required |
| CL | Childcare Leave | Days | ACC_CL | Yes | No | Work schedule | Singapore Childcare Leave; eligibility derived from Dependents + Entitlement_Rules |

## Time_Account_Type

File: `06_Time_Account_Type.csv`

| time_account_type_code | time_account_type_name | account_creation_type | entitlement_method | accrual_rule_code | annual_quota_days | account_valid_from | account_valid_until | carry_over_allowed | expiry_rule | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| ACC_AL | Annual Leave Account | Recurring | Accrued | AL_ACCRUAL | Tiered by years of service | 2026-01-01 | 2026-12-31 | No | Unused balance expires on 31 Dec; period-end processing posts an Expiry | Monthly accrual posted on the 1st; none in the hire month |
| ACC_OIL | Off-in-Lieu Account | Recurring | Earned (ad hoc postings) |  | Earned | 2026-01-01 | 2026-12-31 | No | Each credit expires 3 months after its earned date (assumption); an unused credit gets an Expiry posting | Credits are posted as Ad Hoc Entitlement with an expiry_date |
| ACC_SL | Sick Leave Account | Recurring | Entitled | SL_ENTITLE | 14 | 2026-01-01 | 2026-12-31 | No | Resets 1 Jan; unused days expire 31 Dec | First-year proration not modelled |
| ACC_HL | Hospitalisation Leave Account | Recurring | Entitled | HL_ENTITLE | 46 | 2026-01-01 | 2026-12-31 | No | Resets 1 Jan; unused days expire 31 Dec | On top of SL; 60 days combined |
| ACC_CL | Childcare Leave Account | Recurring | Entitled |  | Annual quota from Entitlement_Rules | 2026-01-01 | 2026-12-31 | No | Resets 1 Jan; unused days expire 31 Dec | Quota determined by child age at 1 Jan; 6 days if child aged 7 or under |

## Accrual_Rule

File: `07_Accrual_Rule.csv`

| accrual_rule_code | tier_id | min_years_service | max_years_service | annual_days | posting_frequency | first_posting_rule | description |
|---|---|---|---|---|---|---|---|
| AL_ACCRUAL | P1 | 0 | 3 | 15 | Monthly | No accrual in the hire month | 0 to 3 completed years of service |
| AL_ACCRUAL | P2 | 4 | 7 | 18 | Monthly | No accrual in the hire month | 4 to 7 completed years of service |
| AL_ACCRUAL | P3 | 8 | 99 | 21 | Monthly | No accrual in the hire month | 8 or more completed years of service |
| SL_ENTITLE | P1 | 0 | 99 | 14 | Annual | Posted on 1 Jan, or on hire date in the hire year | Outpatient sick leave |
| HL_ENTITLE | P1 | 0 | 99 | 46 | Annual | Posted on 1 Jan, or on hire date in the hire year | Hospitalisation leave on top of sick leave (60 days combined) |

## Time_Profile

File: `08_Time_Profile.csv`

| time_profile_code | time_type_code | available_to_employee | favorite | main_absence_time_type |
|---|---|---|---|---|
| SG_STD | AL | Y | Y | Y |
| SG_STD | OIL | Y | N | N |
| SG_STD | SL | Y | Y | N |
| SG_STD | HL | Y | N | N |
| SG_STD | CL | Y | N | N |
| SG_CONTRACT | AL | Y | Y | Y |
| SG_CONTRACT | SL | Y | Y | N |

## Work_Schedule

File: `09_Work_Schedule.csv`

| work_schedule_code | work_schedule_name | mon_hours | tue_hours | wed_hours | thu_hours | fri_hours | sat_hours | sun_hours | weekend_mask |
|---|---|---|---|---|---|---|---|---|---|
| SG_STD | Singapore standard Mon-Fri | 8 | 8 | 8 | 8 | 8 | 0 | 0 | 0000011 |
| SG_MON_THU | 4-day week Mon-Thu (example, not assigned) | 8 | 8 | 8 | 8 | 0 | 0 | 0 | 0000111 |

## Holiday_Calendar

File: `10_Holiday_Calendar.csv`

| date | holiday_name | day_of_week | is_in_lieu | notes | holiday_calendar_code |
|---|---|---|---|---|---|
| 2026-01-01 | New Year's Day | Thursday | N |  | SG |
| 2026-02-17 | Chinese New Year (Day 1) | Tuesday | N |  | SG |
| 2026-02-18 | Chinese New Year (Day 2) | Wednesday | N |  | SG |
| 2026-03-21 | Hari Raya Puasa | Saturday | N | Falls on a Saturday; no day in lieu | SG |
| 2026-04-03 | Good Friday | Friday | N |  | SG |
| 2026-05-01 | Labour Day | Friday | N |  | SG |
| 2026-05-27 | Hari Raya Haji | Wednesday | N |  | SG |
| 2026-05-31 | Vesak Day | Sunday | N | Falls on a Sunday; Monday 1 Jun is the day in lieu for staff whose rest day is Sunday | SG |
| 2026-06-01 | Vesak Day (in lieu) | Monday | Y | Applies to Mon-Fri staff | SG |
| 2026-08-09 | National Day | Sunday | N | Falls on a Sunday; Monday 10 Aug is the day in lieu for staff whose rest day is Sunday | SG |
| 2026-08-10 | National Day (in lieu) | Monday | Y | Applies to Mon-Fri staff | SG |
| 2026-11-08 | Deepavali | Sunday | N | Falls on a Sunday; Monday 9 Nov is the day in lieu for staff whose rest day is Sunday | SG |
| 2026-11-09 | Deepavali (in lieu) | Monday | Y | Applies to Mon-Fri staff | SG |
| 2026-12-25 | Christmas Day | Friday | N |  | SG |
| 2027-01-01 | New Year's Day | Friday | N |  | SG |
| 2027-02-06 | Chinese New Year (Day 1) | Saturday | N | Falls on a Saturday | SG |
| 2027-02-07 | Chinese New Year (Day 2) | Sunday | N | Falls on a Sunday; Monday 8 Feb is the day in lieu for staff whose rest day is Sunday | SG |
| 2027-02-08 | Chinese New Year (in lieu) | Monday | Y | Applies to Mon-Fri staff | SG |
| 2027-03-10 | Hari Raya Puasa | Wednesday | N |  | SG |
| 2027-03-26 | Good Friday | Friday | N |  | SG |
| 2027-05-01 | Labour Day | Saturday | N | Falls on a Saturday | SG |
| 2027-05-17 | Hari Raya Haji | Monday | N |  | SG |
| 2027-05-20 | Vesak Day | Thursday | N |  | SG |
| 2027-08-09 | National Day | Monday | N |  | SG |
| 2027-10-28 | Deepavali | Thursday | N |  | SG |
| 2027-12-25 | Christmas Day | Saturday | N | Falls on a Saturday | SG |

## Time_Account

File: `11_Time_Account.csv`

61 data rows (four accounts per employee, plus TA061 for E005's Childcare Leave); see the CSV. Columns: time_account_id, user_id, time_account_type_code, account_valid_from, account_valid_until, account_closed, balance_today, planned_bookings, pending_requests, available, projected_year_end

Sample (first 3 rows):

| time_account_id | user_id | time_account_type_code | account_valid_from | account_valid_until | account_closed | balance_today | planned_bookings | pending_requests | available | projected_year_end |
|---|---|---|---|---|---|---|---|---|---|---|
| TA001 | E001 | ACC_AL | 2026-01-01 | 2026-12-31 | N | 17.5 | 0 | 0 | 17.5 | 21 |
| TA002 | E001 | ACC_OIL | 2026-01-01 | 2026-12-31 | N | 0 | 0 | 0 | 0 | 0 |
| TA003 | E001 | ACC_SL | 2026-01-01 | 2026-12-31 | N | 14 | 0 | 0 | 14 | 14 |

## Time_Account_Detail

File: `12_Time_Account_Detail.csv`

199 data rows; see the CSV. Columns: detail_id, time_account_id, booking_date, posting_type, booking_amount, booking_unit, employee_time_id, comment, expiry_date, consumes_detail_id, remaining_credit, credit_status

Sample (first 3 rows):

| detail_id | time_account_id | booking_date | posting_type | booking_amount | booking_unit | employee_time_id | comment | expiry_date | consumes_detail_id | remaining_credit | credit_status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D001 | TA003 | 2026-01-01 | Entitlement | 14 | DAYS |  | Annual sick leave entitlement |  |  |  |  |
| D002 | TA004 | 2026-01-01 | Entitlement | 46 | DAYS |  | Annual hospitalisation leave entitlement |  |  |  |  |
| D003 | TA007 | 2026-01-01 | Entitlement | 14 | DAYS |  | Annual sick leave entitlement |  |  |  |  |

## Employee_Time

File: `13_Employee_Time.csv`

| employee_time_id | user_id | time_type_code | start_date | end_date | half_day | quantity_in_days | reason | approval_status | approver_id | submitted_at | decided_at | decision_note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R001 | E005 | AL | 2026-03-09 | 2026-03-13 | None | 5 | Family trip | Approved | E004 | 2026-02-20 10:12 | 2026-02-21 09:30 |  |
| R002 | E006 | AL | 2026-04-20 | 2026-04-22 | None | 3 | Personal errands | Approved | E004 | 2026-04-01 14:05 | 2026-04-02 08:50 |  |
| R003 | E007 | AL | 2026-05-04 | 2026-05-08 | None | 5 | Holiday | Approved | E004 | 2026-04-10 11:20 | 2026-04-10 16:45 |  |
| R004 | E010 | AL | 2026-07-13 | 2026-07-17 | None | 5 | Travel | Approved | E009 | 2026-06-15 09:00 | 2026-06-16 10:10 |  |
| R005 | E003 | SL | 2026-08-17 | 2026-08-17 | None | 1 | Fever | Approved | E002 | 2026-08-17 07:45 | 2026-08-17 08:20 | MC submitted |
| R006 | E011 | HL | 2026-06-22 | 2026-06-26 | None | 5 | Hospital stay (minor surgery) | Approved | E009 | 2026-06-22 08:05 | 2026-06-22 09:00 | Discharge summary on file |
| R007 | E004 | AL | 2026-08-24 | 2026-08-28 | None | 5 | Rest break | Approved | E001 | 2026-07-27 15:30 | 2026-07-28 09:15 |  |
| R008 | E013 | AL | 2026-01-19 | 2026-01-23 | None | 5 | Travel | Approved | E001 | 2025-12-10 10:00 | 2025-12-11 11:00 |  |
| R009 | E005 | AL | 2026-10-26 | 2026-10-30 | None | 5 | Short getaway | Pending | E004 | 2026-10-02 16:20 |  |  |
| R010 | E006 | AL | 2026-10-26 | 2026-10-28 | None | 3 | Moving house | Pending | E004 | 2026-10-03 09:40 |  |  |
| R011 | E007 | AL | 2026-10-27 | 2026-10-28 | None | 2 | Personal | Pending | E004 | 2026-10-04 19:05 |  |  |
| R012 | E012 | AL | 2026-11-09 | 2026-11-13 | None | 4 | Family visit | Pending | E009 | 2026-10-01 12:30 |  |  |
| R013 | E014 | AL | 2026-12-21 | 2026-12-24 | None | 4 | Year-end break | Approved | E013 | 2026-09-15 10:45 | 2026-09-16 09:00 |  |
| R014 | E015 | AL | 2026-11-02 | 2026-11-02 | AM | 0.5 | Appointment | Rejected | E013 | 2026-10-01 08:10 | 2026-10-02 10:00 | Insufficient operations coverage that morning |
| R015 | E006 | OIL | 2026-10-02 | 2026-10-02 | None | 1 | OIL for weekend on-call | Approved | E004 | 2026-09-28 13:00 | 2026-09-28 15:20 |  |
| R016 | E011 | OIL | 2026-09-28 | 2026-09-28 | None | 1 | OIL for weekend roadshow | Approved | E009 | 2026-09-22 09:30 | 2026-09-22 11:00 |  |
| R017 | E009 | AL | 2026-10-12 | 2026-10-13 | None | 2 | Personal | Cancelled | E001 | 2026-09-25 10:00 | 2026-10-01 09:00 | Cancelled by employee |
| R018 | E012 | SL | 2026-09-30 | 2026-09-30 | None | 1 | Migraine | Approved | E009 | 2026-09-30 07:30 | 2026-09-30 08:00 | MC submitted |

## Day_Calculator

File: `14_Day_Calculator.csv`

| field | value | notes |
|---|---|---|
| user_id | E005 | INPUT: the employee the leave is for; their work schedule and holiday calendar are looked up in Job_Information |
| start_date | 2026-10-26 | INPUT: first day of leave (yyyy-mm-dd) |
| end_date | 2026-10-30 | INPUT: last day of leave (yyyy-mm-dd) |
| half_day | None | INPUT: None, AM or PM. Only counts when start_date equals end_date |
| quantity_in_days | 5 | OUTPUT (formula): days on the employee's work schedule minus holidays on their holiday calendar, minus 0.5 for a half day. Do not overwrite |
| holidays_in_range | 0 | OUTPUT (formula): holidays that fall on the employee's working days in the range. Do not overwrite |

## Leave_Calendar

File: `15_Leave_Calendar.csv`

| Month (type any date in it): | 2026-10-01 |  |  |  |  |  |  | team | short_days | at_min_days | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Showing: | 2026-10-01 |  |  |  |  |  |  | Man Age Men-T | 0 | 0 | ✓ Enough |
| Legend: | ✓ OK (enough cover) | ▲ AT MIN (exactly minimum) | ⚠ SHORT (below minimum) | Weekend | Public holiday | (P) = pending approval |  | Empty'em | 2 | 1 | ⚠ Lacking manpower |
|  |  |  |  |  |  |  |  | Diva Counter Strike | 0 | 0 | ✓ Enough |
| T01 | Man Age Men-T | Min on duty: | 1 | Headcount: | 1 |  |  | Apple Computer Science | 0 | 0 | ✓ Enough |
| Mon | Tue | Wed | Thu | Fri | Sat | Sun |  | Meow Woof Arf | 0 | 0 | ✓ Enough |
|  |  |  | 1<br>✓ OK 1/1 | 2<br>✓ OK 1/1 | 3 | 4 |  |  |  |  |  |
| 5<br>✓ OK 1/1 | 6<br>✓ OK 1/1 | 7<br>✓ OK 1/1 | 8<br>✓ OK 1/1 | 9<br>✓ OK 1/1 | 10 | 11 |  |  |  |  |  |
| 12<br>✓ OK 1/1 | 13<br>✓ OK 1/1 | 14<br>✓ OK 1/1 | 15<br>✓ OK 1/1 | 16<br>✓ OK 1/1 | 17 | 18 |  |  |  |  |  |
| 19<br>✓ OK 1/1 | 20<br>✓ OK 1/1 | 21<br>✓ OK 1/1 | 22<br>✓ OK 1/1 | 23<br>✓ OK 1/1 | 24 | 25 |  |  |  |  |  |
| 26<br>✓ OK 1/1 | 27<br>✓ OK 1/1 | 28<br>✓ OK 1/1 | 29<br>✓ OK 1/1 | 30<br>✓ OK 1/1 | 31 |  |  |  |  |  |  |
| T02 | Empty'em | Min on duty: | 3 | Headcount: | 5 |  |  |  |  |  |  |
| Mon | Tue | Wed | Thu | Fri | Sat | Sun |  |  |  |  |  |
|  |  |  | 1<br>✓ OK 5/5 | 2<br>Rahul OIL<br>✓ OK 4/5 | 3 | 4 |  |  |  |  |  |
| 5<br>✓ OK 5/5 | 6<br>✓ OK 5/5 | 7<br>✓ OK 5/5 | 8<br>✓ OK 5/5 | 9<br>✓ OK 5/5 | 10 | 11 |  |  |  |  |  |
| 12<br>✓ OK 5/5 | 13<br>✓ OK 5/5 | 14<br>✓ OK 5/5 | 15<br>✓ OK 5/5 | 16<br>✓ OK 5/5 | 17 | 18 |  |  |  |  |  |
| 19<br>✓ OK 5/5 | 20<br>✓ OK 5/5 | 21<br>✓ OK 5/5 | 22<br>✓ OK 5/5 | 23<br>✓ OK 5/5 | 24 | 25 |  |  |  |  |  |
| 26<br>Wei AL (P)<br>Rahul AL (P)<br>▲ AT MIN 3/5 | 27<br>Wei AL (P)<br>Rahul AL (P)<br>Sarah AL (P)<br>⚠ SHORT 2/5 | 28<br>Wei AL (P)<br>Rahul AL (P)<br>Sarah AL (P)<br>⚠ SHORT 2/5 | 29<br>Wei AL (P)<br>✓ OK 4/5 | 30<br>Wei AL (P)<br>✓ OK 4/5 | 31 |  |  |  |  |  |  |
| T03 | Diva Counter Strike | Min on duty: | 2 | Headcount: | 5 |  |  |  |  |  |  |
| Mon | Tue | Wed | Thu | Fri | Sat | Sun |  |  |  |  |  |
|  |  |  | 1<br>✓ OK 5/5 | 2<br>✓ OK 5/5 | 3 | 4 |  |  |  |  |  |
| 5<br>✓ OK 5/5 | 6<br>✓ OK 5/5 | 7<br>✓ OK 5/5 | 8<br>✓ OK 5/5 | 9<br>✓ OK 5/5 | 10 | 11 |  |  |  |  |  |
| 12<br>✓ OK 5/5 | 13<br>✓ OK 5/5 | 14<br>✓ OK 5/5 | 15<br>✓ OK 5/5 | 16<br>✓ OK 5/5 | 17 | 18 |  |  |  |  |  |
| 19<br>✓ OK 5/5 | 20<br>✓ OK 5/5 | 21<br>✓ OK 5/5 | 22<br>✓ OK 5/5 | 23<br>✓ OK 5/5 | 24 | 25 |  |  |  |  |  |
| 26<br>✓ OK 5/5 | 27<br>✓ OK 5/5 | 28<br>✓ OK 5/5 | 29<br>✓ OK 5/5 | 30<br>✓ OK 5/5 | 31 |  |  |  |  |  |  |
| T04 | Apple Computer Science | Min on duty: | 2 | Headcount: | 4 |  |  |  |  |  |  |
| Mon | Tue | Wed | Thu | Fri | Sat | Sun |  |  |  |  |  |
|  |  |  | 1<br>✓ OK 4/4 | 2<br>✓ OK 4/4 | 3 | 4 |  |  |  |  |  |
| 5<br>✓ OK 4/4 | 6<br>✓ OK 4/4 | 7<br>✓ OK 4/4 | 8<br>✓ OK 4/4 | 9<br>✓ OK 4/4 | 10 | 11 |  |  |  |  |  |
| 12<br>✓ OK 4/4 | 13<br>✓ OK 4/4 | 14<br>✓ OK 4/4 | 15<br>✓ OK 4/4 | 16<br>✓ OK 4/4 | 17 | 18 |  |  |  |  |  |
| 19<br>✓ OK 4/4 | 20<br>✓ OK 4/4 | 21<br>✓ OK 4/4 | 22<br>✓ OK 4/4 | 23<br>✓ OK 4/4 | 24 | 25 |  |  |  |  |  |
| 26<br>Wei AL (P)<br>✓ OK 3/4 | 27<br>Wei AL (P)<br>✓ OK 3/4 | 28<br>Wei AL (P)<br>✓ OK 3/4 | 29<br>Wei AL (P)<br>✓ OK 3/4 | 30<br>Wei AL (P)<br>✓ OK 3/4 | 31 |  |  |  |  |  |  |
| T05 | Meow Woof Arf | Min on duty: | 1 | Headcount: | 3 |  |  |  |  |  |  |
| Mon | Tue | Wed | Thu | Fri | Sat | Sun |  |  |  |  |  |
|  |  |  | 1<br>✓ OK 3/3 | 2<br>✓ OK 3/3 | 3 | 4 |  |  |  |  |  |
| 5<br>✓ OK 3/3 | 6<br>✓ OK 3/3 | 7<br>✓ OK 3/3 | 8<br>✓ OK 3/3 | 9<br>✓ OK 3/3 | 10 | 11 |  |  |  |  |  |
| 12<br>✓ OK 3/3 | 13<br>✓ OK 3/3 | 14<br>✓ OK 3/3 | 15<br>✓ OK 3/3 | 16<br>✓ OK 3/3 | 17 | 18 |  |  |  |  |  |
| 19<br>✓ OK 3/3 | 20<br>✓ OK 3/3 | 21<br>✓ OK 3/3 | 22<br>✓ OK 3/3 | 23<br>✓ OK 3/3 | 24 | 25 |  |  |  |  |  |
| 26<br>✓ OK 3/3 | 27<br>✓ OK 3/3 | 28<br>✓ OK 3/3 | 29<br>✓ OK 3/3 | 30<br>✓ OK 3/3 | 31 |  |  |  |  |  |  |

## Agent_Guide

File: `16_Agent_Guide.csv`

| item_type | name | description | reads | writes | logic |
|---|---|---|---|---|---|
| FUNCTION | get_employee | READ Job_Information by user_id: profile, manager_id, home_team_id, all_teams, join_date, years_of_service, time_profile_code, work_schedule_code, holiday_calendar_code. | Employees, Teams, Team_Members |  | Match on employee_id, email or full_name. manager_id points to another row in Employees. List every team the person belongs to from Team_Members (is_primary = Y is the home team). |
| FUNCTION | get_time_account_balances | READ Time_Account rows for a user_id. Use 'available' (balance_today + planned_bookings - pending_requests) to answer 'how many days can I take'. 'projected_year_end' includes remaining monthly AL accruals. | Leave_Balances |  | Filter by employee_id and leave_year. available = entitlement - used - pending. For OIL, also call get_oil_grants for per-grant expiry. |
| FUNCTION | get_time_account_details | READ Time_Account_Detail rows for a time_account_id (the ledger). Use to explain how a balance was reached. | OIL_Grants |  | Filter by employee_id. status is Active, Fully used or Expired. Flag Active grants expiring within 14 days. Never use Expired grants. |
| FUNCTION | get_oil_credits | READ Time_Account_Detail where the account is ACC_OIL and posting_type = 'Ad Hoc Entitlement'. credit_status Active with remaining_credit > 0 is usable; flag expiry_date within 30 days. | Public_Holidays, Day_Calculator | Day_Calculator!B2:B4 | Write start_date, end_date and half_day to B2:B4, then read B5 (working_days). Half day = 0.5 and is only valid for a single-day request. |
| FUNCTION | get_available_time_types | READ Time_Profile for the employee's time_profile_code, then Time_Type for rules (approval, medical cert). | Public_Holidays |  | Filter by date. Rows with is_in_lieu = Y apply to Mon-Fri staff. Weekend dates do not reduce working days. |
| FUNCTION | calculate_working_days | WRITE Day_Calculator B2:B5 (user_id, start_date, end_date, half_day), then READ B6 (quantity_in_days) and B7 (holidays_in_range). Uses the employee's Work_Schedule and Holiday_Calendar. Do not overwrite B6:B7. | Employees, Teams, Team_Members, Leave_Requests |  | Find every team_id the requester belongs to in Team_Members, then check each team separately. For each working day in the range: members = Team_Members rows for that team whose employee is Active; on_leave = members with a Pending or Approved request covering that date, plus the requester; on_duty = members - on_leave. Clash if on_duty < Teams.min_staff_on_duty. Report each affected team, date and names. |
| FUNCTION | check_public_holidays | READ Holiday_Calendar filtered by holiday_calendar_code (SG). | Employees, Leave_Balances, Leave_Requests, Public_Holidays, Teams, Leave_Types | Leave_Requests | 1) Check employee is Active and leave_type exists. 2) Compute working_days. 3) Check available >= working_days. 4) Check no overlap with the employee's own Pending/Approved requests. 5) Run check_team_clash and warn (do not block). 6) Write a new row: next request_id (R###), status Pending, approver_id = employee's manager_id, submitted_at = now. SL and HL need no approval: set status Approved, decided_at = now, decision_note = Auto-approved. |
| FUNCTION | check_team_clash | For each team the employee belongs to (Team_Members), READ Leave_Calendar or count Approved+Pending Employee_Time overlapping the dates; compare headcount minus absent to Teams.min_staff_on_duty. Report every team that would be short. | Leave_Requests, Leave_Balances, OIL_Grants | Leave_Requests, OIL_Grants | Request must be Pending and the decider must be approver_id or in HR (T05). Re-check balance. Set status Approved or Rejected, decided_at = now, decision_note. On approving an OIL request, add working_days to days_used on the employee's non-expired grants, earliest expiry first. |
| FUNCTION | submit_time_off_request | 1) calculate_working_days 2) AL: compare quantity to Time_Account.projected_year_end for the start month (or 'available' if unsure); OIL: needs an Active credit with enough remaining_credit 3) check_team_clash and warn 4) WRITE new Employee_Time row (next R###, approval_status Pending, submitted_at now). SL: auto-Approved, post debit. HL: Approved with medical cert, post debit. | Leave_Requests, OIL_Grants | Leave_Requests, OIL_Grants | Not allowed once start_date has passed. Set status = Cancelled, decided_at = now, decision_note. If an Approved OIL request is cancelled, reduce days_used on the grants it consumed. Balances recalculate automatically. |
| FUNCTION | approve_or_reject_request | WRITE Employee_Time approval_status, approver_id, decided_at, decision_note. On Approve also WRITE a Time_Account_Detail row: posting_type 'Employee Time', booking_amount = -quantity_in_days, booking_date = start_date, employee_time_id = request id. For OIL set consumes_detail_id to the earliest-expiring Active credit. On Reject post nothing. | Leave_Requests, Employees |  | Filter status = Pending and approver_id = the manager's employee_id. Join Employees for names. |
| FUNCTION | cancel_request | Pending: set approval_status Cancelled, no posting. Approved: set Cancelled and WRITE a positive reversal row (posting_type 'Employee Time', comment 'Reversal of R###', same consumes_detail_id). Pending_Cancellation is not modelled. | Leave_Requests, Team_Members, Employees |  | Get the team's members from Team_Members (not Employees.team_id), join Leave_Requests on employee_id, filter by date overlap, include Pending and Approved, label each by status. |
| FUNCTION | get_pending_approvals | READ Employee_Time where approval_status = Pending and approver_id = manager's user_id. | Employees, OIL_Grants | OIL_Grants | Write A:G of the next empty row: next grant_id (G###), employee_id, earned_date, reason, days_granted, expiry_date = earned_date + 3 months, days_used = 0. Columns H:I are formulas, do not write them. |
| FUNCTION | get_team_calendar | READ Leave_Calendar (set B1 to the month first) or filter Employee_Time by Team_Members. |  |  | AL, SL and HL balances reset on 1 Jan. Unused AL expires on 31 Dec with no carry-over. |
| FUNCTION | grant_oil | WRITE Time_Account_Detail on the employee's ACC_OIL account: posting_type 'Ad Hoc Entitlement', booking_amount > 0, booking_date = earned date, expiry_date = earned date + 3 months (mock assumption). | Leave_Policy |  | 0-3 years = 15 days, 4-7 years = 18 days, 8+ years = 21 days. Employees.annual_leave_entitlement is derived from years_of_service as at today. Leave_Policy is the source of truth. |
| FUNCTION | run_accrual | On the 1st of each month WRITE one 'Accrual' row per ACC_AL account: amount = annual_leave_entitlement / 12. Skip the hire month (Accrual_Rule first_posting_rule). | OIL_Grants |  | Each grant expires 3 months after earned_date (assumption). Use the earliest-expiring grant first. |
| FUNCTION | run_period_end_processing | Post 'Expiry' rows (negative, consumes_detail_id = credit id) for OIL credits past expiry_date with remaining_credit > 0. On 31 Dec AL expires with no carry-over; on 1 Jan create new Time_Account rows for the new year. | Leave_Types |  | SL 14 days outpatient. HL 46 days on top, 60 days combined. Both need medical documentation and need no approval. |
| RULE | ledger_is_source_of_truth | Balances are never typed. Every change to a balance is a new Time_Account_Detail row. Do not edit or delete existing ledger rows; correct with a new row. | Public_Holidays |  | Mon-Fri only, minus rows in Public_Holidays. A half day counts as 0.5. |
| RULE | posting_types | Entitlement, Accrual, Ad Hoc Entitlement, Employee Time (SF-style) and Expiry (custom, not in SF). |  |  | Pending, Approved, Rejected, Cancelled. Only Approved counts as used; Pending counts as pending; Rejected and Cancelled count as nothing. |
| RULE | id_conventions | E### employee, T## team, R### employee_time_id, D### ledger detail_id, TA### time_account_id. Use the next unused number. |  |  | IDs: E### employees, T## teams, R### requests, G### OIL grants, B### balances. Dates yyyy-mm-dd. Timestamps yyyy-mm-dd hh:mm in Asia/Singapore time. |
| RULE | formula_columns_do_not_overwrite | Job_Information H,J,K,L; Teams D; Time_Account G:K; Time_Account_Detail K:L; Work_Schedule J; Day_Calculator B6:B7; Holiday_Calendar C; Leave_Calendar everything except B1. |  |  | Employees H, J, K and L, Teams D, Leave_Balances E:I, OIL_Grants H:I, Public_Holidays C, Day_Calculator B5:B6, and all of Leave_Calendar except B1. Add new rows with update_values on the next empty row rather than append. Employees.team_id is the home team only; Employees.all_teams and team_count are derived from Team_Members. |
| RULE | writing_rows | Write new rows with update_values at the next empty row. Do not use append (it can land in the wrong place beside formula columns). |  |  | All people are fictional. Public holidays follow the MOM list (updated 19 Jun 2026). First-year leave proration is not modelled. |
| RULE | multi_team | A person can be in several teams via Team_Members. home_team_id is the primary. A clash check must cover all of the person's teams. |  |  | R009-R011 create an Engineering clash on 27-28 Oct (min cover 3). R012 spans the 9 Nov Deepavali in-lieu holiday. G006 expires 11 Oct. G004 is already expired. E005, E014 and E011 each sit in two teams, so their leave counts against both teams' cover. |
| RULE | half_day | Half day only applies when start_date = end_date (AM or PM, 0.5 days). | Team_Members, Teams |  | Team_Members has one row per person per team. is_primary = Y marks the home team and must match Employees.team_id. Headcount and cover checks use Team_Members, not Employees.team_id. Approval always routes to Employees.manager_id regardless of team. To add a membership, write a new row (M###) with update_values on the next empty row. |
| RULE | expiry | AL expires 31 Dec, no carry-over. OIL expires on the credit's expiry_date. SL 14 and HL 46 days per year. | Leave_Requests, Team_Members, Teams, Public_Holidays | Leave_Calendar!B1 (month selector only) | Leave_Calendar is formula-driven and read-only apart from B1. Do not write to it. Its summary table (I1:L6) shows short_days and at_min_days for the selected month and can be read for a quick team verdict; for per-request clash checks use check_team_clash. |
| DEMO | clash_team_T02 | R009-R011 overlap 26-30 Oct in T02 (Empty Em, min on duty 3 of 5): 27-28 Oct goes SHORT (2/5). Check Leave_Calendar October. |  |  |  |
| DEMO | holiday_span | R012 (E012) spans the 9 Nov public holiday: 5 weekdays minus 1 holiday = 4 days. |  |  |  |
| DEMO | oil_expiry | D141 (E008 OIL credit) expires 11 Oct. D124 (E013) already expired and was closed by Expiry row D177. |  |  |  |
| DEMO | multi_team_people | E005 (also T04), E014 (also T03), E011 (also T05). |  |  |  |
| DEMO | hire_month | E012 joined in January 2026 mid-month; no accrual in the hire month, first accrual is Feb. |  |  |  |
| CAVEAT | mock_data | Mock data only. Accrual uses today's service tier for all months. OIL 3-month expiry is an assumption. Schema is modelled on public SAP SuccessFactors Time Off docs, not a live tenant. See SF_Mapping. |  |  |  |

## Dependents

File: `17_Dependents.csv`. Read by `check_childcare_eligibility` (`backend/tools/hr.py`) to compute each child's age at 1 Jan.

| dependent_id | user_id | name | date_of_birth | relationship |
|---|---|---|---|---|
| DEP001 | E005 | Ethan Chua | 2020-03-15 | Child |

## Entitlement_Rules

File: `18_Entitlement_Rules.csv`. Childcare Leave quota tiers, matched against the child's age at 1 Jan.

| rule_id | time_type_code | condition_field | condition_operator | condition_value | annual_quota_days | notes |
|---|---|---|---|---|---|---|
| ER001 | CL | child_age_at_jan1 | <= | 7 | 6 | Singapore Childcare Leave — child aged 7 or under at 1 Jan; 6 days per year |
| ER002 | CL | child_age_at_jan1 | <= | 12 | 2 | Extended Childcare Leave — child aged 8 to 12 at 1 Jan; 2 days per year |

## Project_Events

File: `19_Project_Events.csv`. Read by `get_project_events` (`backend/tools/team_project.py`); employees are linked to a project through `Job_Information.project_id`.

| event_id | project_id | event_type | start_date | end_date | description |
|---|---|---|---|---|---|
| PE001 | PROJ_ENG | CHANGE_WINDOW | 2026-10-27 | 2026-10-28 | System change freeze — no engineering leave; release stabilisation |
| PE002 | PROJ_ENG | DEPLOYMENT | 2026-11-03 | 2026-11-03 | Production release v2.1 |

## Companies

File: `20_Companies.csv`. Used by `backend/tools/policy_rag.py` to pick which policy document in `policies/` applies to an employee. The employee's `employer` (in `02_Job_Information.csv`) is matched to `company_name`; an employer with no `policy_file` has no policy on file and the assistant says so rather than using another employer's policy.
| company_id | company_name | contract_hr_email | time_profile_code | policy_file |
|---|---|---|---|---|
| I_BE_YAM | I Be Yam | hr@i-be-yam.com | SG_STD | i_be_yam_leave_policy.md |
| HE_BE_TOMATO | He Be Tomato | | SG_CONTRACT | he_be_tomato_leave_policy.md |
| SHE_BE_A_PEAR | She Be A Pear | | | |

## Users

File: `21_Users.csv`. Login accounts for the web UI, read by `backend/auth.py`. Each username maps to an existing employee `user_id`; passwords are stored as salted SHA-256 hashes (salt and hash values are not reproduced here).

| username | user_id | display_name |
|---|---|---|
| weiling | E005 | Wei Ling Chua |
| marcus | E004 | Marcus Lim |
| fatimah | E009 | Fatimah Yusof |

## Demo scenarios added with files 17–21

- Childcare Leave: E005 has one child (DEP001, aged 5 at 1 Jan 2026), so ER001 applies and TA061 holds 6 CL days.
- Project conflict: PE001 freezes engineering leave on 27–28 Oct, the same dates the T02 coverage clash (R009–R011) goes SHORT. PROJ_ENG covers E004–E008.

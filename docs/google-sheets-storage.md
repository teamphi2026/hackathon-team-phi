# Persistent storage in Google Sheets

The backend supports `DATA_BACKEND=csv` for local development and
`DATA_BACKEND=google_sheets` for this single-instance hackathon deployment.
Sheets mode reads and writes the configured workbook; failures never fall back
to ephemeral CSV files. No Google credentials are exposed to the browser or LLM.

## Connect the existing workbook

1. Enable the **Google Sheets API** in the service account's Google Cloud project.
2. Share the workbook with the service account's `client_email` as **Editor**.
   Keep access restricted: the workbook contains HR data and password hashes.
3. In Render, add a **Secret File** named `google-service-account.json` containing
   the service account JSON. Set:

   ```text
   GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/google-service-account.json
   GOOGLE_SHEETS_SPREADSHEET_ID=1ItLM27vcTfpyeuZBQeuhFTvz86ERTqpSG4zpOOapysk
   ```

   Alternatively, put the JSON in the private environment variable
   `GOOGLE_SERVICE_ACCOUNT_JSON`. Do not put it in Git, `config.js`, or chat.
4. Install the updated requirements and run the read-only check from a machine
   with those credentials (or a Render shell/job):

   ```sh
   python -m backend.storage_check
   ```

   `gid=17` identifies one tab, not the database. The app uses multiple tabs in
   the workbook. Names such as `Employee_Time`, `Employee Time`, and
   `13_Employee_Time` match `13_Employee_Time.csv` automatically. Row 1 must contain
   the CSV's column names. Extra named columns are allowed and preserved.
   If a tab has a different name, set an explicit mapping, for example:

   ```text
   GOOGLE_SHEETS_TAB_MAP={"13_Employee_Time.csv":"Leave Requests"}
   ```

   Resolve mappings before creating missing tabs. The check lists matches and
   missing tables without printing employee records, passwords or tokens.
5. If required tabs really are missing, initialise **only those tabs**:

   ```sh
   python -m backend.storage_check --seed-missing
   ```

   This creates missing tables from the repository CSVs, including user accounts,
   and an empty `22_Approval_Tokens` table. It never replaces an existing tab,
   fixes an existing schema, or copies CSV data over existing Sheets records.
   If Render currently has newer CSV records, export/back up those before a
   redeploy and reconcile them with the workbook; repository CSVs are not a
   backup of runtime data. Default demo login records should only be seeded for
   the demo environment.
6. After the schema check passes, set `DATA_BACKEND=google_sheets` and deploy.
   Keep Uvicorn at `--workers 1` and Render at **one instance**. Startup checks
   access and required schemas and fails visibly if they are unavailable.

## Behaviour and limits

- Employees, teams, policies' company mappings, entitlements, calendar data,
  requests, ledger transactions and registered accounts come from Sheets.
  Policy document text remains in the repository.
- Each operation uses a fresh batched snapshot, shared by that operation's
  tools. There is no cross-request cache of Google request statuses.
- Only request, ledger, user-account and approval-token tabs are writable by
  runtime code. It updates changed cells and appends rows, preserving unrelated
  cells, formulas and formatting. Free text is written as literal values.
- A decision, its debit and email-token consumption are saved in one atomic
  `spreadsheets.batchUpdate` call. Notification emails are sent only after the
  mutation returns successfully. Failed or uncertain writes return an error;
  uncertain writes are not automatically replayed. Refresh status before retrying.
- Email approval tokens are stored as SHA-256 digests in Sheets, with their
  action, expiry and consumed status. Newly issued links survive process
  restarts and cannot be reused after a decision. Old links issued before the
  migration are in-memory links and do not survive a restart.
- Browser login tokens, chat history and activity are still in memory. Users
  sign in again after a restart; their stored accounts and leave records remain.
- Sheets has no compare-and-swap database transaction covering a preceding
  read. The process lock protects this app's one writer, not another deployment
  or human editor. Do not run two backend writers or edit/sort the writable data
  tabs during app mutations. Avoid overlapping old/new deployments during writes.
  Use a transactional database if multiple independent writers are required.
- This is for low-volume demo use; polling and chats consume API quota. The
  existing approval panel polls every 10 seconds. Quota/access errors surface
  as HTTP 503 rather than being treated as an empty approval queue.

## Verify after deployment

1. Check `/api/health` reports `"data_backend": "google_sheets"`. Sign in and compare the balance/history and manager queue to the workbook.
2. Submit a test request; confirm its row appears in `Employee_Time`.
3. Restart the backend and sign in again. The request must still appear.
4. Approve via the UI or a newly issued email link. Check the request status,
   one debit in `Time_Account_Detail`, and that the approval queue clears it.
5. Restart again; status and balance must remain, and the same link must not
   approve or debit again.

Automated tests use a fake Sheets transport and temporary tables, not the live
workbook. A passing unit test is not verification of your credentials or tabs.

API references: [batch updates](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate),
[batch reads](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchGet),
[quotas](https://developers.google.com/workspace/sheets/api/limits).

## Optional approval forecast

The monthly forecast is a separate display updated after an approval commits.
Set `GOOGLE_SHEET_ID` to its workbook ID and `GOOGLE_SHEET_TAB` to its tab name.
Both features share `GOOGLE_APPLICATION_CREDENTIALS` (or the JSON/legacy
`GOOGLE_SERVICE_ACCOUNT_FILE` alternatives). The forecast can use the same
workbook as persistence, but must use a separate tab with its monthly layout.
Leave `GOOGLE_SHEET_ID` empty to disable forecast updates. `LEAVE_FORECAST_CSV`
is an optional local-development override.

Forecast failures are reported in activity logs and do not undo an approval or
prevent the notification email. The request and ledger tables remain authoritative;
the forecast is not part of their atomic transaction.

## Reuse the forecast service account on Render

No second service account is needed. Both adapters use the same
`GOOGLE_SERVICE_ACCOUNT_JSON` environment variable; when populated it takes
precedence over credential file settings. Upload the original downloaded JSON
as a private Render environment value, preserving its JSON escaping.

Keep the existing forecast settings:

```text
GOOGLE_SHEET_ID=1Cuo-5q-mWsdGeVMVOMYp3RqAOYbDTStQAOz_aTz1j-c
GOOGLE_SHEET_TAB=Leave Tracker
```

For persistent records, separately set:

```text
GOOGLE_SHEETS_SPREADSHEET_ID=1ItLM27vcTfpyeuZBQeuhFTvz86ERTqpSG4zpOOapysk
```

Share that persistence workbook with the `client_email` from the downloaded
service-account JSON as Editor. Keep the forecast workbook's existing sharing.
Run the schema check and missing-tab setup described above before switching
`DATA_BACKEND` to `google_sheets`. The monthly `Leave Tracker` layout alone does
not provide the request, balance, account and approval-token tables.

If a private key has been pasted into chat or another shared location, replace
it in Render and revoke the exposed key in Google Cloud. The service account
itself and its workbook permissions can stay the same. Never copy the key into
this document or any tracked file.

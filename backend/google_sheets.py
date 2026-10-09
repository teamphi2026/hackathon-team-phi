"""Google Sheets REST adapter. Writes are cell deltas in one atomic batch.

Never clear/replace existing worksheets: untouched formulas, formatting, and
extra columns are preserved. Runtime never creates or seeds worksheets.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import re

from . import config
from .storage import StorageError, TABLES, TOKEN_FILE, Table, schema

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WRITABLE = {"12_Time_Account_Detail.csv", "13_Employee_Time.csv", "21_Users.csv", TOKEN_FILE}
DATE_COLUMNS = {"start_date", "end_date", "date", "booking_date", "expiry_date",
                "account_valid_from", "account_valid_until", "join_date", "date_of_birth"}
NUMERIC_COLUMNS = {"quantity_in_days", "booking_amount", "remaining_credit", "balance_today",
                   "planned_bookings", "pending_requests", "available", "projected_year_end",
                   "headcount", "min_staff_on_duty", "years_of_service", "annual_leave_entitlement"}
EPOCH = date(1899, 12, 30)


def _normal(name: str) -> str:
    name = re.sub(r"^\d+[\s_.-]*", "", Path(name).stem)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _text(value, column: str) -> str:
    if value is None:
        return ""
    if column in DATE_COLUMNS and isinstance(value, (int, float)) and not isinstance(value, bool):
        return (EPOCH + timedelta(days=int(value))).isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _cell(value: str, column: str) -> dict:
    if column in DATE_COLUMNS and value:
        try:
            day = date.fromisoformat(value)
        except ValueError:
            raise StorageError(f"Date in {column} must be YYYY-MM-DD.") from None
        return {"userEnteredValue": {"numberValue": (day - EPOCH).days},
                "userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}}
    if column in NUMERIC_COLUMNS and value:
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError()
        except ValueError:
            raise StorageError(f"Invalid numeric value in {column}.") from None
        return {"userEnteredValue": {"numberValue": number}}
    # Explicit stringValue prevents spreadsheet formula injection from free text.
    return {"userEnteredValue": {"stringValue": str(value)}}


class SheetsStore:
    def __init__(self, spreadsheet_id: str, session, tab_map: dict | None = None):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
            raise StorageError("Set GOOGLE_SHEETS_SPREADSHEET_ID to the spreadsheet ID, not its URL.")
        self.base = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        self.session = session
        self.tab_map = tab_map or {}
        self.metadata = None

    @classmethod
    def from_config(cls):
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2.service_account import Credentials
            raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
            if raw:
                credentials = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
            else:
                credentials, _ = google.auth.default(scopes=SCOPES)
        except Exception:
            raise StorageError("Google credentials unavailable. Install google-auth and set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON on the server.") from None
        try:
            mapping = json.loads(config.GOOGLE_SHEETS_TAB_MAP)
            if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
                raise ValueError()
        except (ValueError, TypeError):
            raise StorageError("GOOGLE_SHEETS_TAB_MAP must be a JSON object of filename-to-tab-name mappings.") from None
        return cls(config.GOOGLE_SHEETS_SPREADSHEET_ID, AuthorizedSession(credentials), mapping)

    def _request(self, method: str, suffix: str = "", **kwargs) -> dict:
        try:
            response = self.session.request(method, self.base + suffix, timeout=30, **kwargs)
        except Exception:
            # Never retry an uncertain write: it may already have committed.
            raise StorageError("Google Sheets could not confirm the operation. Refresh request status before retrying.") from None
        if response.status_code >= 400:
            raise StorageError(f"Google Sheets returned HTTP {response.status_code}. Check API access, sharing and quota; no CSV fallback was used.")
        try:
            return response.json()
        except ValueError:
            raise StorageError("Google Sheets returned an invalid response.") from None

    def resolve(self, require_all: bool = True) -> dict[str, dict]:
        if self.metadata is None:
            self.metadata = self._request("GET", params={"fields": "sheets.properties"}).get("sheets", [])
        properties = [s["properties"] for s in self.metadata]
        resolved = {}
        for name in TABLES:
            matches = [p for p in properties if p["title"] == self.tab_map[name]] if name in self.tab_map else [
                p for p in properties if _normal(p["title"]) == _normal(name)]
            if len(matches) > 1:
                raise StorageError(f"Ambiguous worksheet for {name}; set GOOGLE_SHEETS_TAB_MAP.")
            if not matches:
                if require_all:
                    raise StorageError(f"Missing worksheet for {name}. Run the read-only storage check and initialise missing tables before enabling Sheets.")
                continue
            resolved[name] = matches[0]
        if len({p["sheetId"] for p in resolved.values()}) != len(resolved):
            raise StorageError("Each app table must map to a different worksheet.")
        return resolved

    def read_all(self) -> dict[str, Table]:
        resolved = self.resolve()
        ranges = ["'" + p["title"].replace("'", "''") + "'" for p in resolved.values()]
        response = self._request("GET", "/values:batchGet", params={
            "ranges": ranges, "valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"})
        values = response.get("valueRanges", [])
        if len(values) != len(resolved):
            raise StorageError("Google Sheets returned an incomplete table snapshot.")
        result = {}
        for (name, prop), value_range in zip(resolved.items(), values):
            values = value_range.get("values", [])
            header = [str(h).strip() for h in values[0]] if values else []
            if not header or len(set(header)) != len(header) or "" in header:
                raise StorageError(f"Worksheet {prop['title']} needs unique column headers in row 1.")
            missing = set(schema(name)) - set(header)
            if missing:
                raise StorageError(f"Worksheet {prop['title']} is missing columns: {', '.join(sorted(missing))}")
            rows = []
            for cells in values[1:]:
                if len(cells) > len(header):
                    raise StorageError(f"Worksheet {prop['title']} has data outside its headers.")
                row = {h: _text(cells[i] if i < len(cells) else "", h) for i, h in enumerate(header)}
                if any(v.startswith(("#REF!", "#VALUE!", "#ERROR!", "#DIV/0!", "#N/A")) for v in row.values()):
                    raise StorageError(f"Worksheet {prop['title']} contains a spreadsheet formula error.")
                for column in DATE_COLUMNS - {"join_date"}:
                    if row.get(column):
                        try:
                            date.fromisoformat(row[column])
                        except ValueError:
                            raise StorageError(f"Worksheet {prop['title']} needs native dates or YYYY-MM-DD text in {column}.") from None
                # Preserve blank rows so physical row coordinates remain correct.
                rows.append(row)
            result[name] = (header, rows)
        return result

    def commit(self, before: dict[str, Table], changes: dict[str, Table]) -> None:
        resolved = self.resolve()
        requests = []
        for name, (header, rows) in changes.items():
            if name not in WRITABLE:
                raise StorageError(f"The application cannot write reference table {name}.")
            old_header, old_rows = before[name]
            if header != old_header or len(rows) < len(old_rows):
                raise StorageError("Runtime table replacement, column changes and row deletion are not supported.")
            sheet_id = resolved[name]["sheetId"]
            for row_index, old in enumerate(old_rows):
                new = rows[row_index]
                if new.get(header[0], "") != old.get(header[0], ""):
                    raise StorageError("Runtime row reordering or primary-key changes are not supported.")
                for column_index, column in enumerate(header):
                    value = str(new.get(column, ""))
                    if value == old.get(column, ""):
                        continue
                    cell = _cell(value, column)
                    fields = "userEnteredValue"
                    if "userEnteredFormat" in cell:
                        fields += ",userEnteredFormat.numberFormat"
                    requests.append({"updateCells": {
                        "start": {"sheetId": sheet_id, "rowIndex": row_index + 1, "columnIndex": column_index},
                        "rows": [{"values": [cell]}], "fields": fields}})
            added = rows[len(old_rows):]
            if added:
                requests.append({"appendCells": {"sheetId": sheet_id,
                    "rows": [{"values": [_cell(str(r.get(h, "")), h) for h in header]} for r in added],
                    "fields": "userEnteredValue,userEnteredFormat.numberFormat"}})
        if requests:
            self._request("POST", ":batchUpdate", json={"requests": requests})

    def seed_missing(self) -> list[str]:
        """Explicit setup only: create missing tabs without overwriting any existing tab."""
        existing = self.resolve(require_all=False)
        next_id = max((s["properties"]["sheetId"] for s in self.metadata), default=0) + 1
        requests, created = [], []
        for name in TABLES:
            if name in existing:
                continue
            title = self.tab_map.get(name, Path(name).stem)
            header = schema(name)
            rows = []
            if name != TOKEN_FILE:
                with open(config.data_file(name), newline="", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
            values = [{"values": [{"userEnteredValue": {"stringValue": h}} for h in header]}]
            for row in rows:
                cells = []
                for h in header:
                    # Preserve legacy join-date strings exactly as imported.
                    cells.append(_cell(row.get(h, ""), "" if h == "join_date" else h))
                values.append({"values": cells})
            requests.extend([
                {"addSheet": {"properties": {"sheetId": next_id, "title": title}}},
                {"appendCells": {"sheetId": next_id, "rows": values,
                    "fields": "userEnteredValue,userEnteredFormat.numberFormat"}},
            ])
            next_id += 1
            created.append(title)
        if requests:
            self._request("POST", ":batchUpdate", json={"requests": requests})
            self.metadata = None
        return created

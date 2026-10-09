"""Table storage with request-scoped reads and atomic Sheets mutations.

One process/worker only: the lock serializes app writes and session identity.
Google Sheets is not a transactional database for multiple independent writers.
"""
from __future__ import annotations

import copy
import csv
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from threading import RLock

from . import config

Table = tuple[list[str], list[dict[str, str]]]
TOKEN_FILE = "22_Approval_Tokens.csv"
TOKEN_HEADER = ["token_hash", "employee_time_id", "action", "expiry", "used"]
TABLES = [
    "02_Job_Information.csv", "03_Teams.csv", "04_Team_Members.csv", "05_Time_Type.csv",
    "06_Time_Account_Type.csv", "08_Time_Profile.csv", "09_Work_Schedule.csv",
    "10_Holiday_Calendar.csv", "11_Time_Account.csv", "12_Time_Account_Detail.csv",
    "13_Employee_Time.csv", "17_Dependents.csv", "18_Entitlement_Rules.csv",
    "19_Project_Events.csv", "20_Companies.csv", "21_Users.csv", TOKEN_FILE,
]


class StorageError(RuntimeError):
    """Safe-to-display storage error; never contains credentials or raw HTTP bodies."""


def schema(name: str) -> list[str]:
    if name == TOKEN_FILE:
        return list(TOKEN_HEADER)
    with open(config.data_file(name), newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh))


class CsvStore:
    def read(self, name: str) -> Table:
        with open(config.data_file(name), newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            return reader.fieldnames or [], list(reader)

    def commit(self, before: dict[str, Table], changes: dict[str, Table]) -> None:
        for name, (header, rows) in changes.items():
            # Replace one complete local file; CSV mode is for local development.
            path = config.data_file(name)
            temp = path.with_suffix(".tmp")
            with open(temp, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=header)
                writer.writeheader()
                writer.writerows({k: r.get(k, "") for k in header} for r in rows)
            temp.replace(path)


_sheets = None
_sheets_key = None
_LOCK = RLock()


def using_sheets() -> bool:
    return config.DATA_BACKEND == "google_sheets"


def provider():
    global _sheets, _sheets_key
    if config.DATA_BACKEND == "csv":
        return CsvStore()
    if not using_sheets():
        raise StorageError("DATA_BACKEND must be csv or google_sheets.")
    key = (config.GOOGLE_SHEETS_SPREADSHEET_ID, config.GOOGLE_SHEETS_TAB_MAP)
    if _sheets is None or key != _sheets_key:
        from .google_sheets import SheetsStore
        _sheets = SheetsStore.from_config()
        _sheets_key = key
    return _sheets


@dataclass
class Unit:
    tables: dict[str, Table] = field(default_factory=dict)
    before: dict[str, Table] = field(default_factory=dict)
    dirty: set[str] = field(default_factory=set)
    depth: int = 0


_UNIT: ContextVar[Unit | None] = ContextVar("leave_storage_unit", default=None)


@contextmanager
def operation():
    """One read snapshot per operation; no cross-request cache of Sheets data."""
    with _LOCK:
        if _UNIT.get() is not None:
            yield
            return
        token = _UNIT.set(Unit())
        try:
            yield
        finally:
            _UNIT.reset(token)


def scoped(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with operation():
            return fn(*args, **kwargs)
    # FastAPI must resolve postponed endpoint annotations in the original module.
    wrapped.__signature__ = inspect.signature(fn, eval_str=True)
    return wrapped


@contextmanager
def transaction():
    """Stage all table changes, then commit one Sheets batch before returning."""
    with operation():
        unit = _UNIT.get()
        if unit.depth:
            yield
            return
        checkpoint = copy.deepcopy(unit)
        unit.depth = 1
        try:
            yield
            if unit.dirty:
                provider().commit(unit.before, {name: unit.tables[name] for name in sorted(unit.dirty)})
                # Derived/formula cells may have recalculated remotely. Refetch on
                # the next tool read rather than retaining the pre-write snapshot.
                unit.tables.clear()
                unit.before.clear()
                unit.dirty.clear()
        except Exception:
            unit.tables = checkpoint.tables
            unit.before = checkpoint.before
            unit.dirty = checkpoint.dirty
            # A network timeout may have committed. Do not retain stale snapshots.
            unit.tables.clear()
            unit.before.clear()
            raise
        finally:
            unit.depth = 0


def mutation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        from .state import get_session
        with operation():
            session = get_session()
            before = copy.deepcopy(session.__dict__)
            try:
                with transaction():
                    return fn(*args, **kwargs)
            except Exception:
                session.__dict__.clear()
                session.__dict__.update(before)
                raise
            finally:
                from .tools.actions import _invalidate_caches
                _invalidate_caches()
    return wrapped


def read_rows(name: str) -> Table:
    unit = _UNIT.get()
    if unit is None:
        with operation():
            return read_rows(name)
    if name not in unit.tables:
        store = provider()
        if using_sheets():
            # One batchGet for all app tables, even when several tools read them.
            tables = store.read_all()
            for key, table in tables.items():
                if key not in unit.tables:
                    unit.tables[key] = copy.deepcopy(table)
                    unit.before[key] = copy.deepcopy(table)
        else:
            unit.tables[name] = store.read(name)
            unit.before[name] = copy.deepcopy(unit.tables[name])
    if name not in unit.tables:
        raise StorageError(f"Missing storage table: {name}")
    return copy.deepcopy(unit.tables[name])


def write_rows(name: str, header: list[str], rows: list[dict[str, str]]) -> None:
    with transaction():
        unit = _UNIT.get()
        if name not in unit.tables:
            try:
                read_rows(name)
            except FileNotFoundError:
                if using_sheets():
                    raise
                unit.before[name] = (header, [])
        unit.tables[name] = copy.deepcopy((header, rows))
        unit.dirty.add(name)


def dataframe(name: str):
    import pandas as pd
    header, rows = read_rows(name)
    return pd.DataFrame(rows, columns=header).fillna("")

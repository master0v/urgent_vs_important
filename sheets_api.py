#!/usr/bin/env python3
"""
Google Sheets helper for the Pairwise Ranker.

Columns (updated):
  A: Status (dropdown: not started / in progress / done)  [with color rules]
  B: Rank        (only on root rows)
  C: Title
  D: Parent Title   (blank for roots)
  E: Description
  F: Link

Key capabilities:
- read_full_state(): parse the existing sheet into:
    * roots_in_order: list of dicts (title, notes, _link) in the existing top-level order
    * children_by_parent_title: { parent_title: [child dicts in current order] }
  This allows resuming without rewriting on start.
- write_full_state(): rewrite the entire tab using the current in-memory state,
  **preserving Status values** by matching rows on (Parent Title, Title).
- ensure_status_dropdown_and_colors(): installs the data validation + color rules.

Additional behaviors:
- If Description and Link are identical (trimmed), Description is written blank so only Link remains.
"""

import os
import datetime
from typing import List, Dict, Any, Optional, Tuple

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# UPDATED HEADER ORDER: Title moved before Parent Title
HEADER = ["Status", "Rank", "Title", "Parent Title", "Description", "Link"]
STATUS_VALUES = ["not started", "in progress", "done"]

# subtle readable backgrounds
COLOR_RED    = {"red": 0.96, "green": 0.80, "blue": 0.80}
COLOR_ORANGE = {"red": 1.00, "green": 0.90, "blue": 0.80}
COLOR_GREEN  = {"red": 0.85, "green": 0.94, "blue": 0.83}

class SheetsClient:
    def __init__(self, credentials_dir: Optional[str] = None):
        here = os.path.dirname(os.path.abspath(__file__))
        self._dir = credentials_dir or here
        self._creds = self._auth()
        self.service = build("sheets", "v4", credentials=self._creds)

    # ---------- auth ----------

    def _auth(self):
        creds_path = os.path.join(self._dir, "credentials.json")
        token_path = os.path.join(self._dir, "token_sheets.json")
        creds = None

        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SHEETS_SCOPES)
            except Exception:
                creds = None

        if not creds or not getattr(creds, "valid", False):
            if creds and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None

            if not creds:
                if not os.path.exists(creds_path):
                    raise FileNotFoundError(
                        "credentials.json not found for Sheets. "
                        "Download a Desktop App OAuth client and place it next to sheets_api.py."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SHEETS_SCOPES)
                try:
                    creds = flow.run_local_server(port=0)
                except Exception:
                    print("Sheets auth: falling back to console auth...")
                    creds = flow.run_console()

            try:
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
            except Exception:
                pass

        return creds

    # ---------- spreadsheet / tab ----------

    def create_spreadsheet(self, title: str) -> str:
        body = {"properties": {"title": title}}
        created = self.service.spreadsheets().create(body=body, fields="spreadsheetId").execute()
        return created["spreadsheetId"]

    def ensure_tab(self, spreadsheet_id: str, sheet_title: str) -> str:
        meta = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if sheet_title in existing_titles:
            return sheet_title
        try:
            reqs = [{"addSheet": {"properties": {"title": sheet_title}}}]
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": reqs}
            ).execute()
            return sheet_title
        except Exception:
            suffix = datetime.datetime.now().strftime("%Y-%m-%d %H.%M.%S")
            adjusted = f"{sheet_title} ({suffix})"
            reqs = [{"addSheet": {"properties": {"title": adjusted}}}]
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": reqs}
            ).execute()
            return adjusted

    def _get_sheet_id(self, spreadsheet_id: str, sheet_title: str) -> int:
        meta = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        for s in meta.get("sheets", []):
            if s["properties"]["title"] == sheet_title:
                return int(s["properties"]["sheetId"])
        raise RuntimeError(f"Sheet '{sheet_title}' not found in spreadsheet.")

    # ---------- validation & colors ----------

    def ensure_status_dropdown_and_colors(self, spreadsheet_id: str, sheet_title: str):
        sheet_id = self._get_sheet_id(spreadsheet_id, sheet_title)

        status_range = {
            "sheetId": sheet_id,
            "startRowIndex": 1,  # skip header
            "startColumnIndex": 0,
            "endColumnIndex": 1
        }

        requests = [
            {
                "setDataValidation": {
                    "range": status_range,
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": v} for v in STATUS_VALUES]
                        },
                        "strict": True,
                        "showCustomUi": True
                    }
                }
            },
            # Conditional formats for each status
            self._cf_eq("not started", COLOR_RED, status_range, 0),
            self._cf_eq("in progress", COLOR_ORANGE, status_range, 1),
            self._cf_eq("done", COLOR_GREEN, status_range, 2),
        ]

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def _cf_eq(self, val: str, color: Dict[str, float], rng: Dict[str, int], index: int):
        return {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [rng],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": val}]},
                        "format": {"backgroundColor": color}
                    }
                },
                "index": index
            }
        }

    # ---------- reads & writes ----------

    def read_full_state(
        self,
        spreadsheet_id: str,
        sheet_title: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        Parse the existing sheet (if any) into roots + children-by-parent (keyed by Parent Title).
        We intentionally do NOT write anything here—this enables truly non-destructive resume.

        Returns:
          roots_in_order: list of dicts with keys: title, notes, _link
          children_by_parent_title: { parent_title: [ {title, notes, _link}, ... ] }
        """
        rng = f"{sheet_title}!A1:F1000000"
        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=rng
            ).execute()
        except Exception:
            return [], {}

        rows = resp.get("values", [])
        if not rows:
            return [], {}

        # Normalize rows to 6 columns
        norm = [(r + [""] * 6)[:6] for r in rows]
        # Header sanity
        if norm[0][:len(HEADER)] != HEADER[:len(norm[0])]:
            # If header is missing or unexpected, treat as empty and let later writes normalize it.
            return [], {}

        roots: List[Dict[str, Any]] = []
        children_by_parent: Dict[str, List[Dict[str, Any]]] = {}

        current_parent_title: Optional[str] = None
        for i, row in enumerate(norm[1:], start=2):
            # A,B,C,D,E,F = Status, Rank, Title, Parent Title, Description, Link
            status, rank, title, parent_title, desc, link = row
            title = (title or "").strip()
            parent_title = (parent_title or "").strip()
            if not title:
                continue

            task_row = {
                "title": title,
                "notes": desc or "",
                "_link": link or "",
                # No IDs here (by design)—this is a sheet snapshot.
            }

            if (rank or "").strip():  # a root row (B has a value)
                roots.append(task_row)
                current_parent_title = title
            else:
                # child row: parent is explicit in col D; if blank, fall back to last seen root
                ptitle = parent_title or (current_parent_title or "")
                if ptitle:
                    children_by_parent.setdefault(ptitle, []).append(task_row)

        return roots, children_by_parent

    def _read_existing_status_map(self, spreadsheet_id: str, sheet_title: str) -> Dict[Tuple[str, str], str]:
        """
        Mapping (Parent Title, Title) -> Status for preserving the Status on rewrite.
        """
        rng = f"{sheet_title}!A1:F1000000"
        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=rng
            ).execute()
        except Exception:
            return {}
        rows = resp.get("values", [])
        if not rows:
            return {}

        m: Dict[Tuple[str, str], str] = {}
        for i, row in enumerate(rows):
            if i == 0:
                continue  # header
            row = (row + [""] * 6)[:6]
            # A,B,C,D,E,F = Status, Rank, Title, Parent Title, Description, Link
            status, _rank, title, parent_title, _desc, _link = row
            key = ((parent_title or "").strip(), (title or "").strip())
            if key[1]:
                m[key] = (status or "").strip()
        return m

    def clear_values(self, spreadsheet_id: str, sheet_title: str):
        self.service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=f"{sheet_title}!A:Z"
        ).execute()

    def write_full_state(
        self,
        spreadsheet_id: str,
        sheet_title: str,
        roots_in_order: List[Dict[str, Any]],
        children_by_parent: Dict[Any, List[Dict[str, Any]]],
    ):
        """
        Rewrite the sheet with header + all rows, preserving Status per (Parent Title, Title).
        children_by_parent can be keyed by:
          - parent task id (when available), OR
          - parent title (string), allowing us to carry forward existing child rows from a prior session.
        """
        status_map = self._read_existing_status_map(spreadsheet_id, sheet_title)

        def _dedupe_desc_link(desc: str, link: str) -> Tuple[str, str]:
            d = (desc or "").strip()
            l = (link or "").strip()
            return ("" if d and l and d == l else d, l)

        def row_for(task: Dict[str, Any], rank_str: str, parent_title: str) -> List[str]:
            title = (task.get("title") or "").strip()
            desc  = (task.get("notes") or "").strip()
            link  = (task.get("_link") or "").strip()
            # If Description and Link are the same, keep only the link
            desc, link = _dedupe_desc_link(desc, link)
            status = status_map.get(((parent_title or "").strip(), title), "")
            # Order: Status, Rank, Title, Parent Title, Description, Link
            return [status, rank_str, title, parent_title, desc, link]

        rows: List[List[str]] = [list(HEADER)]

        # Build lookups for children keyed by both id and title for convenience
        by_id_or_title = {}
        for k, lst in (children_by_parent or {}).items():
            by_id_or_title[k] = lst

        for idx, root in enumerate(roots_in_order, start=1):
            root_title = (root.get("title") or "").strip()
            rows.append(row_for(root, str(idx), ""))

            # Attempt to pull children by id first, then by title
            pid = root.get("id")
            child_list = None
            if pid is not None and pid in by_id_or_title:
                child_list = by_id_or_title.get(pid, [])
            if child_list is None or len(child_list) == 0:
                child_list = by_id_or_title.get(root_title, [])

            for ch in (child_list or []):
                rows.append(row_for(ch, "", root_title))

        # Final write
        self.clear_values(spreadsheet_id, sheet_title)
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_title}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

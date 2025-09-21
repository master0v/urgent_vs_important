#!/usr/bin/env python3
"""
Google Sheets helper for the Pairwise Ranker.

Columns (updated):
  A: Status (dropdown: not started / in progress / done)
  B: Rank        (only on root rows)
  C: Category    (editable dropdown from a separate tab)
  D: Title
  E: Parent Title   (blank for roots)
  F: Description
  G: Link

Behaviors:
- read_full_state(): parse the existing sheet into roots + children (with 'category' carried along).
- write_full_state(): rewrite the entire tab; preserves Status and Category by matching (Parent Title, Title).
- ensure_status_dropdown_and_colors(): installs status validation + color rules.
- ensure_category_dropdown(): installs editable dropdown for Category from a configurable tab.
- read_categories(): returns the Category list from the configured tab (first column A).
- If Description and Link are identical, Description is written blank so only Link remains.
"""

import os
import datetime
from typing import List, Dict, Any, Optional, Tuple

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# UPDATED HEADER ORDER: Category added after Rank; Title still before Parent Title.
HEADER = ["Status", "Rank", "Category", "Title", "Parent Title", "Description", "Link"]
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
            "startColumnIndex": 0,  # Status col A
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

    def ensure_category_dropdown(self, spreadsheet_id: str, data_sheet_title: str, categories_tab: str):
        """
        Install an editable dropdown for the Category column (col C) that points to 'categories_tab'!A:A.
        The dropdown is not strict, so users can type new values too.
        """
        data_sheet_id = self._get_sheet_id(spreadsheet_id, data_sheet_title)
        categories_sheet_id = self._get_sheet_id(spreadsheet_id, categories_tab)

        category_col_range = {
            "sheetId": data_sheet_id,
            "startRowIndex": 1,     # skip header
            "startColumnIndex": 2,  # Column C (Category)
            "endColumnIndex": 3
        }

        requests = [
            {
                "setDataValidation": {
                    "range": category_col_range,
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_RANGE",
                            "values": [{
                                "userEnteredValue": f"='{categories_tab}'!A:A"
                            }]
                        },
                        "strict": False,   # allow typing new categories
                        "showCustomUi": True
                    }
                }
            }
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

    def read_categories(self, spreadsheet_id: str, categories_tab: str) -> List[str]:
        """
        Read categories from the given tab (first column A, ignoring header blanks).
        """
        rng = f"{categories_tab}!A1:A1000"
        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=rng
            ).execute()
        except Exception:
            return []
        rows = resp.get("values", []) or []
        cats = []
        for r in rows:
            if not r:
                continue
            v = (r[0] or "").strip()
            if v:
                cats.append(v)
        return cats

    def read_full_state(
        self,
        spreadsheet_id: str,
        sheet_title: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        Parse the existing sheet (if any) into roots + children-by-parent (keyed by Parent Title).
        Returns:
          roots_in_order: list of dicts with keys: title, notes, _link, category
          children_by_parent_title: { parent_title: [ {title, notes, _link, category}, ... ] }
        """
        rng = f"{sheet_title}!A1:G1000000"
        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=rng
            ).execute()
        except Exception:
            return [], {}

        rows = resp.get("values", [])
        if not rows:
            return [], {}

        # Normalize rows to 7 columns
        norm = [(r + [""] * 7)[:7] for r in rows]
        if norm[0][:len(HEADER)] != HEADER[:len(norm[0])]:
            return [], {}

        roots: List[Dict[str, Any]] = []
        children_by_parent: Dict[str, List[Dict[str, Any]]] = {}

        current_parent_title: Optional[str] = None
        for i, row in enumerate(norm[1:], start=2):
            # A..G = Status, Rank, Category, Title, Parent Title, Description, Link
            status, rank, category, title, parent_title, desc, link = row
            title = (title or "").strip()
            parent_title = (parent_title or "").strip()
            if not title:
                continue

            task_row = {
                "title": title,
                "notes": desc or "",
                "_link": link or "",
                "category": (category or "").strip(),
            }

            if (rank or "").strip():  # root row (B has a value)
                roots.append(task_row)
                current_parent_title = title
            else:
                ptitle = parent_title or (current_parent_title or "")
                if ptitle:
                    children_by_parent.setdefault(ptitle, []).append(task_row)

        return roots, children_by_parent

    def _read_existing_status_and_category_map(self, spreadsheet_id: str, sheet_title: str) -> Dict[Tuple[str, str], Tuple[str, str]]:
        """
        Mapping (Parent Title, Title) -> (Status, Category) for preserving on rewrite.
        """
        rng = f"{sheet_title}!A1:G1000000"
        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=rng
            ).execute()
        except Exception:
            return {}
        rows = resp.get("values", [])
        if not rows:
            return {}

        m: Dict[Tuple[str, str], Tuple[str, str]] = {}
        for i, row in enumerate(rows):
            if i == 0:
                continue  # header
            row = (row + [""] * 7)[:7]
            # A..G = Status, Rank, Category, Title, Parent Title, Description, Link
            status, _rank, category, title, parent_title, _desc, _link = row
            key = ((parent_title or "").strip(), (title or "").strip())
            if key[1]:
                m[key] = ((status or "").strip(), (category or "").strip())
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
        Rewrite the sheet with header + all rows, preserving Status & Category per (Parent Title, Title).
        children_by_parent can be keyed by parent id (new session placements) **or** parent title (baseline).
        """
        sc_map = self._read_existing_status_and_category_map(spreadsheet_id, sheet_title)

        def _dedupe_desc_link(desc: str, link: str):
            d = (desc or "").strip()
            l = (link or "").strip()
            return ("" if d and l and d == l else d, l)

        def row_for(task: Dict[str, Any], rank_str: str, parent_title: str) -> List[str]:
            title = (task.get("title") or "").strip()
            desc  = (task.get("notes") or "").strip()
            link  = (task.get("_link") or "").strip()
            category = (task.get("category") or "").strip()
            # If Description and Link are the same, keep only the link
            desc, link = _dedupe_desc_link(desc, link)
            # preserve Status & Category if missing from task dict
            prev_status, prev_cat = sc_map.get(((parent_title or "").strip(), title), ("", ""))
            status = prev_status
            if not category:
                category = prev_cat
            # Order: Status, Rank, Category, Title, Parent Title, Description, Link
            return [status, rank_str, category, title, parent_title, desc, link]

        rows: List[List[str]] = [list(HEADER)]

        by_id_or_title = {}
        for k, lst in (children_by_parent or {}).items():
            by_id_or_title[k] = lst

        for idx, root in enumerate(roots_in_order, start=1):
            root_title = (root.get("title") or "").strip()
            rows.append(row_for(root, str(idx), ""))

            pid = root.get("id")
            child_list = None
            if pid is not None and pid in by_id_or_title:
                child_list = by_id_or_title.get(pid, [])
            if not child_list:
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

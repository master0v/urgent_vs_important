#!/usr/bin/env python3
"""
Google Sheets helper for the Pairwise Ranker.

Strict canonical header (no Rank; Effort/Joy present between Description and Link):
  A: Status
  B: Category
  C: Title
  D: Parent Title
  E: Description
  F: Effort
  G: Joy
  H: Link

Behavior:
- On read: require exact header match. If incorrect, raise a clear ValueError and stop.
- On write: always write the canonical 8-col header, then rows.
- Safety merge: before writing, read the existing sheet and append any pre-existing rows
  (keyed by (Parent Title, Title)) that are not in the new write set — so row count never decreases.
  This happens only if the existing header is correct; otherwise we abort with an error.
- Preserves Status, Category, Effort, Joy for existing (Parent Title, Title) when the app doesn't supply them.
- If Description == Link, we blank Description to reduce clutter.
"""

import os
import datetime
from typing import List, Dict, Any, Optional, Tuple

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADER = ["Status", "Category", "Title", "Parent Title", "Description", "Effort", "Joy", "Link"]
STATUS_VALUES = ["not started", "in progress", "done"]

COLOR_RED    = {"red": 0.96, "green": 0.80, "blue": 0.80}
COLOR_ORANGE = {"red": 1.00, "green": 0.90, "blue": 0.80}
COLOR_GREEN  = {"red": 0.85, "green": 0.94, "blue": 0.83}

def _s(x: Any) -> str:
    return (x or "").strip()

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
            "startColumnIndex": 0,  # Column A (Status)
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
            self._cf_eq("not started", COLOR_RED, status_range, 0),
            self._cf_eq("in progress", COLOR_ORANGE, status_range, 1),
            self._cf_eq("done", COLOR_GREEN, status_range, 2),
        ]

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def ensure_category_dropdown(self, spreadsheet_id: str, data_sheet_title: str, categories_tab: str):
        """
        Editable dropdown for Category (Column B) referencing 'categories_tab'!A:A.
        """
        data_sheet_id = self._get_sheet_id(spreadsheet_id, data_sheet_title)
        _ = self._get_sheet_id(spreadsheet_id, categories_tab)  # ensure exists

        category_col_range = {
            "sheetId": data_sheet_id,
            "startRowIndex": 1,
            "startColumnIndex": 1,  # Column B
            "endColumnIndex": 2
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
                        "strict": False,
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

    def _require_header_or_fail(self, spreadsheet_id: str, sheet_title: str) -> List[List[str]]:
        """Fetch values and ensure header matches exactly; otherwise raise ValueError."""
        resp = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{sheet_title}!A1:H1"
        ).execute()
        row0 = (resp.get("values") or [[]])[0] if resp.get("values") else []
        if row0 != HEADER:
            found = ", ".join(row0) if row0 else "(none)"
            expected = ", ".join(HEADER)
            raise ValueError(
                f"Unexpected header in sheet '{sheet_title}'.\n"
                f"Expected: [{expected}]\nFound:    [{found}]\n\n"
                f"Fix the header row exactly as above (A1..H1), or create a new tab and let the app write it."
            )
        # fetch full sheet once header validated
        resp_full = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{sheet_title}!A1:H1000000"
        ).execute()
        return resp_full.get("values", []) or []

    def read_categories(self, spreadsheet_id: str, categories_tab: str) -> List[str]:
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
        Read the sheet strictly using the canonical header.
        Root rows: blank 'Parent Title'.
        """
        rows = self._require_header_or_fail(spreadsheet_id, sheet_title)
        if not rows:
            return [], {}

        body = rows[1:]
        roots: List[Dict[str, Any]] = []
        children_by_parent: Dict[str, List[Dict[str, Any]]] = {}

        for r in body:
            r = (r + [""] * 8)[:8]
            status, category, title, parent_title, desc, effort, joy, link = r
            title = _s(title)
            parent_title = _s(parent_title)
            if not title:
                continue

            task = {
                "title": title,
                "notes": desc or "",
                "_link": _s(link),
                "category": _s(category),
                "effort": _s(effort),
                "joy": _s(joy),
            }

            if parent_title:
                children_by_parent.setdefault(parent_title, []).append(task)
            else:
                roots.append(task)

        return roots, children_by_parent

    def _read_existing_preserve_map(
        self, spreadsheet_id: str, sheet_title: str
    ) -> Dict[Tuple[str, str], Tuple[str, str, str, str]]:
        """
        (Parent Title, Title) -> (Status, Category, Effort, Joy)
        """
        rows = self._require_header_or_fail(spreadsheet_id, sheet_title)
        m: Dict[Tuple[str, str], Tuple[str, str, str, str]] = {}
        for r in rows[1:]:
            r = (r + [""] * 8)[:8]
            status, category, title, parent_title, _desc, effort, joy, _link = r
            key = (_s(parent_title), _s(title))
            if key[1]:
                m[key] = (_s(status), _s(category), _s(effort), _s(joy))
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
        Write canonical header + rows. Never reduce row count:
        we merge in any existing rows not present in the new set (by (Parent Title, Title)).
        If the existing header is wrong, we abort with a clear error (no write).
        """
        # Validate header first (abort on mismatch)
        existing_rows = self._require_header_or_fail(spreadsheet_id, sheet_title)

        preserve_map = self._read_existing_preserve_map(spreadsheet_id, sheet_title)

        def _dedupe_desc_link(desc: str, link: str):
            d = _s(desc)
            l = _s(link)
            return ("" if d and l and d == l else d, l)

        def row_for(task: Dict[str, Any], parent_title: str) -> List[str]:
            title    = _s(task.get("title"))
            desc     = _s(task.get("notes"))
            link     = _s(task.get("_link"))
            category = _s(task.get("category"))
            effort   = _s(task.get("effort"))
            joy      = _s(task.get("joy"))

            desc, link = _dedupe_desc_link(desc, link)

            prev_status, prev_cat, prev_eff, prev_joy = preserve_map.get(
                (_s(parent_title), title), ("", "", "", "")
            )
            status = prev_status
            if not category: category = prev_cat
            if not effort:   effort   = prev_eff
            if not joy:      joy      = prev_joy

            return [status, category, title, parent_title, desc, effort, joy, link]

        rows: List[List[str]] = [list(HEADER)]

        by_id_or_title = dict(children_by_parent or {})

        for root in (roots_in_order or []):
            root_title = _s(root.get("title"))
            if not root_title:
                continue
            rows.append(row_for(root, ""))

            pid = root.get("id")
            child_list = by_id_or_title.get(pid) if pid is not None else None
            if not child_list:
                child_list = by_id_or_title.get(root_title, [])
            for ch in (child_list or []):
                rows.append(row_for(ch, root_title))

        # SAFETY MERGE (with strict header)
        existing_body = existing_rows[1:] if len(existing_rows) > 1 else []
        existing_rows_by_key = {}
        for r in existing_body:
            r = (r + [""] * 8)[:8]
            _status, _cat, title, parent_title, _desc, _eff, _joy, _lnk = r
            key = (_s(parent_title), _s(title))
            if key[1]:
                existing_rows_by_key[key] = r

        new_keys = set()
        for r in rows[1:]:
            _status, _cat, title, parent_title, _desc, _eff, _joy, _lnk = (r + [""] * 8)[:8]
            key = (_s(parent_title), _s(title))
            if key[1]:
                new_keys.add(key)

        missing = [v for k, v in existing_rows_by_key.items() if k not in new_keys]
        if missing:
            rows.extend(missing)

        # Final write
        self.clear_values(spreadsheet_id, sheet_title)
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_title}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

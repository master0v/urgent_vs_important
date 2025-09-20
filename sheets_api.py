#!/usr/bin/env python3
"""
Minimal Google Sheets helper for the Pairwise Ranker.

Capabilities:
- Auth (separate token file from Google Tasks)
- Create spreadsheet, create/ensure tab
- Read current rank (by Task ID column)
- Write full ranked table (rewrites the sheet each time for simplicity + correctness)
"""

import os
import datetime
from typing import List, Dict, Any, Optional

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADER = ["Rank", "Title", "List", "Notes (first line)", "Task ID"]

class SheetsClient:
    def __init__(self, credentials_dir: Optional[str] = None):
        """
        credentials_dir: folder with credentials.json (default = script folder).
        Tokens are stored as token_sheets.json in the same folder.
        """
        here = os.path.dirname(os.path.abspath(__file__))
        self._dir = credentials_dir or here
        self._creds = self._auth()
        self.service = build("sheets", "v4", credentials=self._creds)

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

    # ---- Spreadsheet / Tab management ----

    def create_spreadsheet(self, title: str) -> str:
        body = {"properties": {"title": title}}
        created = self.service.spreadsheets().create(body=body, fields="spreadsheetId").execute()
        return created["spreadsheetId"]

    def ensure_tab(self, spreadsheet_id: str, sheet_title: str) -> str:
        """
        Ensures a tab with the given title exists; if the title is taken, creates a timestamped one.
        Returns the (possibly adjusted) tab title you should write to.
        """
        meta = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if sheet_title in existing_titles:
            return sheet_title

        # try to add with requested title, and if it fails, add with a suffix
        try:
            reqs = [{"addSheet": {"properties": {"title": sheet_title}}}]
            self.service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": reqs}).execute()
            return sheet_title
        except Exception:
            suffix = datetime.datetime.now().strftime("%Y-%m-%d %H.%M.%S")
            adjusted = f"{sheet_title} ({suffix})"
            reqs = [{"addSheet": {"properties": {"title": adjusted}}}]
            self.service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": reqs}).execute()
            return adjusted

    # ---- Read / Write ----

    def read_current_rank_ids(self, spreadsheet_id: str, sheet_title: str) -> List[str]:
        """
        Reads the Task ID column from the sheet (skips header).
        Returns IDs in order (top to bottom).
        If the sheet is empty or missing, returns [].
        """
        rng = f"{sheet_title}!A1:E1000000"  # wide range; we’ll just read what’s there
        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=rng
            ).execute()
        except Exception:
            return []

        values = resp.get("values", [])
        if not values:
            return []

        # Expect header in row 1. Task ID is column E (index 4).
        ids = []
        for i, row in enumerate(values):
            if i == 0:
                # Verify header or just skip first row
                continue
            if len(row) >= 5:
                tid = (row[4] or "").strip()
                if tid:
                    ids.append(tid)
        return ids

    def write_full_rank(
        self,
        spreadsheet_id: str,
        sheet_title: str,
        ranked_tasks: List[Dict[str, Any]],
    ):
        """
        Rewrites the sheet with HEADER + ranked rows (Rank, Title, List, Notes, Task ID).
        """
        rows: List[List[str]] = [list(HEADER)]
        for idx, t in enumerate(ranked_tasks, start=1):
            title = (t.get("title") or "").strip()
            notes = (t.get("notes") or "").strip().splitlines()[0] if t.get("notes") else ""
            rows.append([str(idx), title, t.get("list_title") or "", notes, t.get("id") or ""])

        rng = f"{sheet_title}!A1"
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheets_id_or_raise(spreadsheet_id),
            range=rng,
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

def spreadsheets_id_or_raise(spreadsheet_id: Optional[str]) -> str:
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required.")
    return spreadsheet_id

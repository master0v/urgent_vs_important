#!/usr/bin/env python3
"""
Pairwise stack-ranker (Tkinter) for Google Tasks -> Google Sheets (streaming writes).

Key behavior:
- After EVERY comparison (or tie/undo that changes order), the sheet is updated.
- If you pass --spreadsheet-id and --sheet-tab from a prior run, we read the
  Task ID column and preload the current sorted portion to resume exactly where you left off.

Usage:
  python3 pairwise_ranker.py \
      --task-list "My Tasks" \
      --spreadsheet-id <YOUR_SHEET_ID> \
      --sheet-tab "Ranking"

If you omit --spreadsheet-id, we create a brand-new spreadsheet and print the ID.
"""

import argparse
import datetime
import tkinter as tk
from tkinter import messagebox
from typing import List, Dict, Any, Optional, Tuple

from tasks_api import GoogleTasks, SEPARATOR_TITLE
from sheets_api import SheetsClient

# ------------- Task loading -------------

def load_active_tasks(task_list_title: Optional[str]) -> List[Dict[str, Any]]:
    gt = GoogleTasks()
    data = gt.getTasks(taskList=task_list_title)  # {list_title:{position:task}}
    items = []
    for list_title, by_pos in data.items():
        for _pos, task in by_pos.items():
            if task.get("title") == SEPARATOR_TITLE:
                continue
            title = (task.get("title") or "").strip()
            if not title:
                continue
            t = dict(task)
            t["list_title"] = list_title
            items.append(t)
    return items

# ------------- Sorter -------------

class PairwiseBinarySorter:
    """
    Binary insertion with a sorted prefix preloaded from the sheet.
    - 'sorted' holds items already placed (in final order, best at index 0).
    - 'remaining' are candidates yet to place.
    """
    def __init__(self, already_sorted: List[Dict[str, Any]], remaining: List[Dict[str, Any]]):
        self.sorted = list(already_sorted)
        self.remaining = list(remaining)
        self.frames: List[Tuple[int, int, int, Dict[str, Any]]] = []
        # frame: (low, high, mid, candidate)

    def has_work(self) -> bool:
        return bool(self.remaining) or bool(self.frames)

    def start_next(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        if not self.frames:
            if not self.remaining:
                return None
            cand = self.remaining.pop(0)
            if not self.sorted:
                self.sorted.append(cand)
                return self.start_next()
            low, high = 0, len(self.sorted)
            mid = (low + high) // 2
            self.frames.append((low, high, mid, cand))
        low, high, mid, cand = self.frames[-1]
        return cand, self.sorted[mid]

    def decide(self, prefer_left: Optional[bool], tie: bool = False) -> bool:
        """Return True if the overall 'sorted' changed (used to trigger sheet write)."""
        if not self.frames:
            return False
        low, high, mid, cand = self.frames.pop()

        if tie:
            self.sorted.insert(mid + 1, cand)
            return True

        if prefer_left is True:
            # cand better than mid -> search upper half [low, mid)
            high = mid
        else:
            # cand worse than mid -> search lower half (mid+1, high]
            low = mid + 1

        if low >= high:
            self.sorted.insert(low, cand)
            return True

        mid = (low + high) // 2
        self.frames.append((low, high, mid, cand))
        return False

    def undo(self) -> bool:
        """
        Heuristic undo:
          - If in the middle of a search, drop the frame (one step back).
          - Else remove the last inserted item (if any) and put it back at
            the front of remaining.
        Returns True if state changed.
        """
        if self.frames:
            self.frames.pop()
            return True
        if self.sorted:
            moved = self.sorted.pop()
            self.remaining.insert(0, moved)
            return True
        return False

# ------------- UI -------------

class RankerUI:
    def __init__(self, root, sorter: PairwiseBinarySorter, on_change):
        self.root = root
        self.sorter = sorter
        self.on_change = on_change  # callback to persist sheet after order changes
        self.root.title("Pairwise Task Ranker")

        self.progress = tk.Label(root, text="", font=("Arial", 12))
        self.progress.pack(pady=(8, 4))

        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=12, pady=8)

        self.left_btn = tk.Button(frame, text="", font=("Arial", 14), wraplength=380,
                                  command=lambda: self._choose(True))
        self.left_btn.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.right_btn = tk.Button(frame, text="", font=("Arial", 14), wraplength=380,
                                   command=lambda: self._choose(False))
        self.right_btn.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        ctrl = tk.Frame(root)
        ctrl.pack(fill="x", padx=12, pady=(4, 10))
        tk.Button(ctrl, text="Tie", command=self._tie).pack(side="left")
        tk.Button(ctrl, text="Undo", command=self._undo).pack(side="left", padx=6)
        tk.Button(ctrl, text="Finish", command=self._finish).pack(side="right")

        # shortcuts
        self.root.bind("<Left>", lambda e: self._choose(True))
        self.root.bind("<Right>", lambda e: self._choose(False))
        self.root.bind("<space>", lambda e: self._tie())
        self.root.bind("<BackSpace>", lambda e: self._undo())
        self.root.bind("<Escape>", lambda e: self._finish())

        self._refresh()

    @staticmethod
    def _label(t: Dict[str, Any]) -> str:
        title = (t.get("title") or "").strip()
        notes = (t.get("notes") or "").strip().splitlines()[0] if t.get("notes") else ""
        where = t.get("list_title") or ""
        return f"{title}\n\n{notes}\n\n({where})" if notes else f"{title}\n\n({where})"

    def _refresh_progress(self):
        total = len(self.sorter.sorted) + len(self.sorter.remaining)
        placed = len(self.sorter.sorted)
        self.progress.config(text=f"Placed {placed}/{total} • Remaining {len(self.sorter.remaining)}")

    def _refresh(self):
        self._refresh_progress()
        pair = self.sorter.start_next()
        if not pair:
            self.left_btn.config(text="(done)", state="disabled")
            self.right_btn.config(text="(done)", state="disabled")
            return
        a, b = pair
        self.left_btn.config(text=self._label(a), state="normal")
        self.right_btn.config(text=self._label(b), state="normal")

    def _choose(self, left: bool):
        changed = self.sorter.decide(prefer_left=left, tie=False)
        if changed:
            self.on_change(self.sorter.sorted)  # persist immediately
        self._refresh()

    def _tie(self):
        changed = self.sorter.decide(prefer_left=None, tie=True)
        if changed:
            self.on_change(self.sorter.sorted)
        self._refresh()

    def _undo(self):
        if self.sorter.undo():
            self.on_change(self.sorter.sorted)  # persist current order after undo
            self._refresh()

    def _finish(self):
        if not self.sorter.sorted:
            if not messagebox.askyesno("Finish", "No items ranked yet. Exit anyway?"):
                return
        self.on_change(self.sorter.sorted)  # one last write
        self.root.quit()

# ------------- Glue / Resume logic -------------

def build_resume_state(all_tasks: List[Dict[str, Any]], existing_ids: List[str]):
    by_id = {t.get("id"): t for t in all_tasks if t.get("id")}
    already_sorted = []
    for tid in existing_ids:
        t = by_id.get(tid)
        if t:
            already_sorted.append(t)
    # anything not already placed goes into remaining
    placed_ids = {t.get("id") for t in already_sorted}
    remaining = [t for t in all_tasks if t.get("id") not in placed_ids]
    return already_sorted, remaining

# ------------- Main -------------

def main():
    parser = argparse.ArgumentParser(description="Pairwise Tk ranker with streaming writes to Sheets")
    parser.add_argument("--task-list", default=None, help="Filter to a specific Google Task list title.")
    parser.add_argument("--spreadsheet-id", default=None, help="Write to this spreadsheet. If omitted, a new one is created.")
    parser.add_argument("--sheet-tab", default="Ranking", help="Worksheet tab title (default: Ranking).")
    parser.add_argument("--sheet-title", default=None, help="Only used when creating a new spreadsheet.")
    args = parser.parse_args()

    # Load tasks
    tasks = load_active_tasks(args.task_list)
    if not tasks:
        print("No active tasks found. Nothing to rank.")
        return

    # Sheets client
    sheets = SheetsClient()

    # Create or use provided spreadsheet
    if args.spreadsheet_id:
        spreadsheet_id = args.spreadsheet_id
        tab_title = sheets.ensure_tab(spreadsheet_id, args.sheet_tab)
    else:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H.%M")
        spreadsheet_title = args.sheet_title or f"Task Stack Rank ({ts})"
        spreadsheet_id = sheets.create_spreadsheet(spreadsheet_title)
        tab_title = sheets.ensure_tab(spreadsheet_id, args.sheet_tab)
        print(f"[Created spreadsheet] ID: {spreadsheet_id}  •  Tab: {tab_title}")

    # Resume: read current ranked order (Task ID column), preload sorter
    existing_ids = sheets.read_current_rank_ids(spreadsheet_id, tab_title)
    already_sorted, remaining = build_resume_state(tasks, existing_ids)
    sorter = PairwiseBinarySorter(already_sorted, remaining)

    # Define persistence callback
    def persist(sorted_list: List[Dict[str, Any]]):
        sheets.write_full_rank(spreadsheet_id, tab_title, sorted_list)
        # (optional) print a tiny heartbeat
        # print(f"Wrote {len(sorted_list)} rows to Sheets.")

    # Initial write (in case we resumed with existing rows or start empty)
    persist(sorter.sorted)

    # Fire up the UI
    root = tk.Tk()
    ui = RankerUI(root, sorter, persist)
    root.mainloop()

    # Final pointer for convenience
    print("\nDone.")
    print(f"Spreadsheet ID: {spreadsheet_id}")
    print(f"Tab: {tab_title}")

if __name__ == "__main__":
    main()

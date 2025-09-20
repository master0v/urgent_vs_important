#!/usr/bin/env python3
"""
Pairwise ranker (Tkinter):

- Resumes without rewriting on start:
    Reads the current sheet and uses it as the already-sorted baseline.
    No write occurs until the first new placement happens.
- Injects new Google Tasks into the existing list and sorts them via binary insertion (O(n log n)).
- Subtasks are only compared against siblings of the same parent (if >1).
- After every placement:
    * Full state is written to the sheet (Status preserved),
    * The placed Google Task is deleted (children immediately; parents when their children are done).
- UI shows Title (button), Description, Parent (for subtasks), Link; bottom shows "Remaining N".
- Window position/size persisted to disk across runs.
"""

import json
import os
import re
import datetime
import tkinter as tk
from typing import List, Dict, Any, Optional, Tuple, Any as AnyType

from tasks_api import GoogleTasks, SEPARATOR_TITLE
from sheets_api import SheetsClient

# --------- Config ---------

def load_config() -> Dict[str, Any]:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "ranker_config.json")
    with open(path, "r") as f:
        return json.load(f)

# --------- Link extraction ---------

URL_RE = re.compile(r"(https?://\S+|mailto:[^\s>]+)", re.IGNORECASE)

def extract_first_link(t: Dict[str, Any]) -> str:
    for link_obj in (t.get("links") or []):
        url = (link_obj.get("link") or "").strip()
        if url:
            return url
    txt = " ".join([(t.get("notes") or ""), (t.get("title") or "")])
    m = URL_RE.search(txt)
    return m.group(0) if m else ""

# --------- Task loading & grouping ---------

def fetch_active_tasks(task_list_title: Optional[str]) -> Tuple[
    List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]
]:
    """
    Snapshot the Google Tasks list (active tasks only) and split into roots vs children.
    Returns:
      roots: list of top-level tasks (dicts with id, title, notes, _link, parent=None, etc.)
      children_by_parent_id: { parent_id: [child task dicts] }
      by_id: map of **all** tasks by id
    """
    gt = GoogleTasks()
    raw = gt.getTasks(taskList=task_list_title)  # {list_title:{position:task}}

    by_id: Dict[str, Dict[str, Any]] = {}
    roots: List[Dict[str, Any]] = []
    children_by_parent: Dict[str, List[Dict[str, Any]]] = {}

    for list_title, by_pos in raw.items():
        for _pos, t in by_pos.items():
            if t.get("title") == SEPARATOR_TITLE:
                continue
            title = (t.get("title") or "").strip()
            if not title:
                continue
            t = dict(t)
            t["list_title"] = list_title
            t["_link"] = extract_first_link(t)
            tid = t.get("id")
            if tid:
                by_id[tid] = t

    for t in by_id.values():
        if t.get("parent"):
            children_by_parent.setdefault(t["parent"], []).append(t)
        else:
            roots.append(t)

    # Keep API "position" order as a stable baseline for first comparisons
    roots.sort(key=lambda x: x.get("position", ""))
    for lst in children_by_parent.values():
        lst.sort(key=lambda x: x.get("position", ""))

    # Add readable parent titles on children for UI
    parent_title_by_id = {r.get("id"): (r.get("title") or "") for r in roots}
    for pid, lst in children_by_parent.items():
        ptitle = parent_title_by_id.get(pid, "")
        for c in lst:
            c["_parent_title"] = ptitle

    return roots, children_by_parent, by_id

# --------- Binary sorter (O(n log n)) ---------

class PairwiseBinarySorter:
    """
    For each new item, binary-search the insertion position in the existing 'sorted' list.
    Comparisons are pairwise (candidate vs mid). Complexity: O(k log m) for k new items and current length m.
    """
    def __init__(self, already_sorted: List[Dict[str, Any]], remaining: List[Dict[str, Any]]):
        self.sorted = list(already_sorted)
        self.remaining = list(remaining)
        self.frames: List[Tuple[int, int, int, Dict[str, Any]]] = []  # (low, high, mid, candidate)

    def has_work(self) -> bool:
        return bool(self.remaining) or bool(self.frames)

    def current_pair(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        if not self.frames:
            if not self.remaining:
                return None
            candidate = self.remaining[0]  # peek
            if not self.sorted:
                self.sorted.append(self.remaining.pop(0))
                return self.current_pair()
            low, high = 0, len(self.sorted)
            mid = (low + high) // 2
            self.frames.append((low, high, mid, candidate))
        low, high, mid, cand = self.frames[-1]
        return cand, self.sorted[mid]

    def decide(self, choose_left: bool) -> bool:
        """
        choose_left=True -> candidate outranks mid (search upper half).
        Returns True once the candidate is **placed** (i.e., list changed).
        """
        if not self.frames:
            return False
        low, high, mid, cand = self.frames.pop()

        # Consume the candidate the first time we move
        if self.remaining and self.remaining[0].get("id") == cand.get("id"):
            self.remaining.pop(0)

        if choose_left:
            high = mid
        else:
            low = mid + 1

        if low >= high:
            self.sorted.insert(low, cand)
            return True

        mid = (low + high) // 2
        self.frames.append((low, high, mid, cand))
        return False

# --------- Controller (roots first, then per-parent children) ---------

class RankingController:
    """
    Orchestrates ranking across two phases:
      1) Roots: global order across top-level tasks (binary insertion).
      2) Children: for each root (with >=2 children), rank its subtasks (binary insertion).
    It merges an existing sheet snapshot (already-sorted roots/children-by-title)
    with newly fetched Google Tasks (remaining roots/children-by-id).
    """
    def __init__(
        self,
        gt: GoogleTasks,
        sheets: SheetsClient,
        spreadsheet_id: str,
        sheet_tab: str,
        # From Sheets (existing baseline; NO ids)
        roots_from_sheet: List[Dict[str, Any]],
        children_from_sheet_by_title: Dict[str, List[Dict[str, Any]]],
        # From Google Tasks (new items to inject; WITH ids)
        roots_from_gt: List[Dict[str, Any]],
        children_from_gt_by_id: Dict[str, List[Dict[str, Any]]],
    ):
        self.gt = gt
        self.sheets = sheets
        self.spreadsheet_id = spreadsheet_id
        self.sheet_tab = sheet_tab

        # Existing baseline (read-only snapshot of the sheet)
        self.baseline_roots = list(roots_from_sheet)  # dicts without ids
        self.baseline_children_by_title = {k: list(v) for k, v in (children_from_sheet_by_title or {}).items()}

        # New items to insert (with ids) – binary insertion against the existing baseline
        self.roots_sorter = PairwiseBinarySorter(already_sorted=self.baseline_roots, remaining=roots_from_gt)

        # Newly placed children during this session (by parent id)
        self.children_sorted_by_parent_id: Dict[str, List[Dict[str, Any]]] = {}
        self.children_remaining_by_parent_id = {pid: list(lst) for pid, lst in (children_from_gt_by_id or {}).items()}

        # Active child ranker
        self.parent_order_ids: List[str] = []  # filled after root phase completes
        self.current_parent_id: Optional[str] = None
        self.child_sorter: Optional[PairwiseBinarySorter] = None

        # Deletion bookkeeping
        self.deleted_ids: set[str] = set()

        # IMPORTANT: no write here — that avoids any rewrite on restart.

    # ---- UI-facing methods ----

    def remaining_count(self) -> int:
        n_roots = len(self.roots_sorter.remaining)
        # Count children not yet processed
        n_children = sum(len(v) for v in self.children_remaining_by_parent_id.values())
        if self.child_sorter and self.child_sorter.has_work():
            n_children += len(self.child_sorter.remaining)
        return n_roots + n_children

    def current_pair(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        if self.roots_sorter.has_work():
            return self.roots_sorter.current_pair()

        if not self.parent_order_ids:
            # Build parent id order using the final order of roots that actually have ids (live parents)
            for r in self.roots_sorter.sorted:
                if r.get("id"):
                    self.parent_order_ids.append(r["id"])
            self._auto_place_trivial_children()
            # still no write until something changes (first placement or auto-placed child)

        # Activate next parent with >= 2 children
        if not self.child_sorter or not self.child_sorter.has_work():
            if not self._activate_next_parent_group():
                return None

        return self.child_sorter.current_pair()

    def choose_left(self):
        self._decide(True)

    def choose_right(self):
        self._decide(False)

    # ---- Internals ----

    def _decide(self, left: bool):
        if self.roots_sorter.has_work():
            placed = self.roots_sorter.decide(left)
            if placed:
                # If the placed root exists in Google Tasks, we'll delete it later (after its children are handled).
                self._persist()  # first write occurs only after the first placement
            return

        if not (self.child_sorter and self.current_parent_id):
            return

        placed = self.child_sorter.decide(left)
        if placed:
            pid = self.current_parent_id
            self.children_sorted_by_parent_id.setdefault(pid, list(self.child_sorter.sorted))
            self._persist()
            self._delete_newly_placed_children(pid)

            if not self.child_sorter.has_work():
                self._delete_parent_if_done(pid)
                self.current_parent_id = None
                self.child_sorter = None

    def _persist(self):
        """
        Write a full, consistent snapshot:
          - Roots = baseline roots + newly inserted roots (kept in self.roots_sorter.sorted)
          - Children = union of:
              a) preexisting child rows from the sheet (keyed by parent title)
              b) newly placed children this session (keyed by parent id)
        Status values are preserved by the writer.
        """
        # Build the children map including both 'by id' (new) and 'by title' (existing)
        children_union: Dict[AnyType, List[Dict[str, Any]]] = {}

        # Include newly placed children by parent id
        for pid, lst in self.children_sorted_by_parent_id.items():
            children_union[pid] = list(lst)

        # Include baseline children groups by parent **title**
        for ptitle, lst in self.baseline_children_by_title.items():
            # If we also have newly placed children for the same parent, append them after existing:
            # We'll find that parent's id by looking for a root with matching title.
            children_union.setdefault(ptitle, [])
            children_union[ptitle].extend(lst)

        self.sheets.write_full_state(
            self.spreadsheet_id,
            self.sheet_tab,
            self.roots_sorter.sorted,
            children_union
        )

    # -- Child group orchestration --

    def _auto_place_trivial_children(self):
        """
        For any parent id with 0 children: attempt to delete the parent now (it is already ranked).
        For any parent id with exactly 1 child remaining: place that child immediately, write, and delete it.
        NOTE: This will cause the **first write** if any auto-placement occurs; otherwise we remain read-only.
        """
        wrote_any = False
        for pid in list(self.children_remaining_by_parent_id.keys()):
            rem = self.children_remaining_by_parent_id.get(pid, [])
            if len(rem) == 0:
                self._delete_parent_if_done(pid)
                continue
            if len(rem) == 1:
                child = rem.pop(0)
                self.children_sorted_by_parent_id.setdefault(pid, []).append(child)
                self._persist()
                wrote_any = True
                self._delete_task(child)
                self._delete_parent_if_done(pid)
        # If we auto-placed none, we still have not written anything yet (respecting "no rewrite on restart").

    def _activate_next_parent_group(self) -> bool:
        while self.parent_order_ids:
            pid = self.parent_order_ids[0]
            rem = self.children_remaining_by_parent_id.get(pid, [])
            placed = self.children_sorted_by_parent_id.get(pid, [])
            total = len(rem) + len(placed)
            if total <= 1:
                # trivial group handled elsewhere; advance + ensure deletion
                if rem:
                    # single child left -> auto place then delete
                    child = rem.pop(0)
                    self.children_sorted_by_parent_id.setdefault(pid, []).append(child)
                    self._persist()
                    self._delete_task(child)
                self._delete_parent_if_done(pid)
                self.parent_order_ids.pop(0)
                continue

            # Start interactive ranking for this parent's children
            self.current_parent_id = pid
            self.child_sorter = PairwiseBinarySorter(already_sorted=placed, remaining=rem)
            # Clear remaining list in dict so we don't double-count
            self.children_remaining_by_parent_id[pid] = []
            return True

        return False

    # -- Deletions --

    def _delete_task(self, task: Dict[str, Any]):
        tid = task.get("id")
        if not tid or tid in self.deleted_ids:
            return
        tlist = task.get("task_list_id")
        if not tlist:
            return
        try:
            self.gt.service.tasks().delete(tasklist=tlist, task=tid).execute()
        except Exception:
            pass
        self.deleted_ids.add(tid)

    def _delete_newly_placed_children(self, pid: Optional[str]):
        if not pid or not self.child_sorter:
            return
        for t in self.child_sorter.sorted:
            tid = t.get("id")
            if tid and tid not in self.deleted_ids:
                self._delete_task(t)

    def _delete_parent_if_done(self, pid: Optional[str]):
        if not pid:
            return
        # Parent can be deleted after all its children are placed/cleared
        any_remaining = self.children_remaining_by_parent_id.get(pid)
        if any_remaining:
            return
        parent = next((r for r in self.roots_sorter.sorted if r.get("id") == pid), None)
        if parent:
            self._delete_task(parent)

# --------- UI (unchanged behavior: minimal info + geometry persistence) ---------

class UIState:
    def __init__(self, path: str):
        self.path = path
        self.geometry = None
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    self.geometry = (json.load(f) or {}).get("geometry")
            except Exception:
                self.geometry = None

    def save(self, geometry: str):
        try:
            with open(self.path, "w") as f:
                json.dump({"geometry": geometry}, f)
        except Exception:
            pass

class TaskPane:
    def __init__(self, parent_frame: tk.Frame, on_pick):
        self.frame = tk.Frame(parent_frame, bd=1, relief="groove")
        self.frame.pack_propagate(False)

        self.title_btn = tk.Button(self.frame, text="", font=("Arial", 16, "bold"), wraplength=420, command=on_pick)
        self.title_btn.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(self.frame, text="Description:", anchor="w").pack(fill="x", padx=10)
        self.desc = tk.Text(self.frame, height=12, wrap="word")
        self.desc.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.desc.configure(state="disabled")

        self.parent_row = tk.Frame(self.frame)
        self.parent_row.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(self.parent_row, text="Parent:", anchor="w").pack(side="left")
        self.parent_val = tk.Entry(self.parent_row)
        self.parent_val.pack(side="left", fill="x", expand=True)
        self.parent_val.configure(state="readonly")

        link_row = tk.Frame(self.frame)
        link_row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(link_row, text="Link:", anchor="w").pack(side="left")
        self.link_val = tk.Entry(link_row)
        self.link_val.pack(side="left", fill="x", expand=True)
        self.link_val.configure(state="readonly")

    def set_task(self, t: Optional[Dict[str, Any]]):
        if not t:
            self.title_btn.config(text="(no task)", state="disabled")
            self._set_desc("")
            self._set_entry(self.parent_val, "")
            self._set_entry(self.link_val, "")
            self.parent_row.forget()
            return

        self.title_btn.config(text=(t.get("title") or "").strip(), state="normal")
        self._set_desc((t.get("notes") or "").strip())

        parent_title = (t.get("_parent_title") or "").strip()
        if parent_title:
            self.parent_row.pack(fill="x", padx=10, pady=(0, 4))
            self._set_entry(self.parent_val, parent_title)
        else:
            self.parent_row.forget()

        self._set_entry(self.link_val, (t.get("_link") or "").strip())

    def _set_desc(self, text: str):
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        self.desc.insert("1.0", text)
        self.desc.configure(state="disabled")

    def _set_entry(self, ent: tk.Entry, value: str):
        ent.configure(state="normal")
        ent.delete(0, "end")
        ent.insert(0, value)
        ent.configure(state="readonly")

class RankerUI:
    def __init__(self, controller: RankingController, state_path: str):
        self.controller = controller
        self.state = UIState(state_path)

        self.root = tk.Tk()
        self.root.title("Pairwise Task Ranker")

        if self.state.geometry:
            self.root.geometry(self.state.geometry)

        self._geom_after = None
        def on_conf(_e):
            if self._geom_after:
                self.root.after_cancel(self._geom_after)
            self._geom_after = self.root.after(250, self._save_geometry)
        self.root.bind("<Configure>", on_conf)

        def on_close():
            self._save_geometry()
            self.root.destroy()
        self.root.protocol("WM_DELETE_WINDOW", on_close)

        tk.Label(
            self.root,
            text="Which of the following two tasks is more important for you?",
            font=("Arial", 14)
        ).pack(fill="x", padx=12, pady=(10, 6))

        mid = tk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=12, pady=6)

        self.left = TaskPane(mid, on_pick=self._pick_left)
        self.left.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.right = TaskPane(mid, on_pick=self._pick_right)
        self.right.frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        mid.grid_columnconfigure(0, weight=1, uniform="col")
        mid.grid_columnconfigure(1, weight=1, uniform="col")
        mid.grid_rowconfigure(0, weight=1)

        self.remaining = tk.Label(self.root, text="Remaining 0", font=("Arial", 12))
        self.remaining.pack(fill="x", padx=12, pady=(6, 12))

        self.root.bind("<Left>",  lambda e: self._pick_left())
        self.root.bind("<Right>", lambda e: self._pick_right())

        self._refresh()

    def _save_geometry(self):
        try:
            self.state.save(self.root.wm_geometry())
        except Exception:
            pass

    def _refresh(self):
        pair = self.controller.current_pair()
        if not pair:
            self.left.set_task(None)
            self.right.set_task(None)
            self.remaining.config(text="Remaining 0")
            self.root.after(600, self.root.destroy)
            return
        a, b = pair
        self.left.set_task(a)
        self.right.set_task(b)
        self.remaining.config(text=f"Remaining {self.controller.remaining_count()}")

    def _pick_left(self):
        self.controller.choose_left()
        self._refresh()

    def _pick_right(self):
        self.controller.choose_right()
        self._refresh()

    def run(self):
        self.root.mainloop()

# --------- Main ---------

def main():
    cfg = load_config()
    task_list_name = (cfg.get("task_list") or "").strip() or None
    spreadsheet_id = (cfg.get("spreadsheet_id") or "").strip()
    sheet_tab = (cfg.get("sheet_tab") or "Ranking").strip()
    sheet_title = (cfg.get("sheet_title") or f"Task Stack Rank ({datetime.datetime.now().strftime('%Y-%m-%d %H.%M')})").strip()
    credentials_dir = (cfg.get("credentials_dir") or "").strip() or None
    ui_state_path = (cfg.get("ui_state_path") or "").strip() or os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_state.json")

    sheets = SheetsClient(credentials_dir=credentials_dir)
    if not spreadsheet_id:
        spreadsheet_id = sheets.create_spreadsheet(sheet_title)
        sheet_tab = sheets.ensure_tab(spreadsheet_id, sheet_tab)
        print(f"[Created spreadsheet] ID: {spreadsheet_id} • Tab: {sheet_tab}")
    else:
        sheet_tab = sheets.ensure_tab(spreadsheet_id, sheet_tab)

    # Always ensure the dropdown + colors exist; this is idempotent.
    sheets.ensure_status_dropdown_and_colors(spreadsheet_id, sheet_tab)

    # 1) Read the existing sheet (NO WRITES HERE).
    roots_from_sheet, children_from_sheet_by_title = sheets.read_full_state(spreadsheet_id, sheet_tab)

    # 2) Fetch current Google Tasks snapshot (new items to inject).
    gt = GoogleTasks()
    roots_from_gt, children_from_gt_by_id, _by_id = fetch_active_tasks(task_list_name)

    # 3) Build the controller using the sheet as the 'already_sorted' baseline.
    controller = RankingController(
        gt=gt,
        sheets=sheets,
        spreadsheet_id=spreadsheet_id,
        sheet_tab=sheet_tab,
        roots_from_sheet=roots_from_sheet,
        children_from_sheet_by_title=children_from_sheet_by_title,
        roots_from_gt=roots_from_gt,
        children_from_gt_by_id=children_from_gt_by_id,
    )

    # 4) Run the UI (still O(n log n) thanks to PairwiseBinarySorter).
    ui = RankerUI(controller, state_path=ui_state_path)
    ui.run()

if __name__ == "__main__":
    main()

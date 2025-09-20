#!/usr/bin/env python3
"""
Pairwise ranker (Tkinter) — robust restart + correct deletions.

Fixes:
- Startup reconciliation: attach Google Task IDs to sheet rows by matching Title (case/space-normalized),
  so we never compare a task with itself after restart.
- Parent deletion: delete once there are NO unprocessed children left (ignoring already-written ones).
- Children are deleted immediately after being written (unchanged).
- Optional: set DELETE_PARENTS_IMMEDIATELY = True to delete parents as soon as they’re inserted into the sheet.

Safe default:
- DELETE_PARENTS_IMMEDIATELY = False  (prevents losing subtasks if you quit mid-session)
"""

import json
import os
import re
import datetime
import tkinter as tk
from typing import List, Dict, Any, Optional, Tuple, Any as AnyType

from tasks_api import GoogleTasks, SEPARATOR_TITLE
from sheets_api import SheetsClient

# ---- behavior switches ----
DELETE_PARENTS_IMMEDIATELY = False  # set to True only if you accept that deleting a parent may erase its subtasks in Google Tasks

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

# --------- Binary sorter ---------

class PairwiseBinarySorter:
    def __init__(self, already_sorted: List[Dict[str, Any]], remaining: List[Dict[str, Any]]):
        self.sorted = list(already_sorted)
        self.remaining = list(remaining)
        self.frames: List[Tuple[int, int, int, Dict[str, Any]]] = []

    def has_work(self) -> bool:
        return bool(self.remaining) or bool(self.frames)

    def current_pair(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        if not self.frames:
            if not self.remaining:
                return None
            candidate = self.remaining[0]
            if not self.sorted:
                self.sorted.append(self.remaining.pop(0))
                return self.current_pair()
            low, high = 0, len(self.sorted)
            mid = (low + high) // 2
            self.frames.append((low, high, mid, candidate))
        low, high, mid, cand = self.frames[-1]
        return cand, self.sorted[mid]

    def decide(self, choose_left: bool) -> Optional[Dict[str, Any]]:
        """
        choose_left=True -> candidate outranks mid (search upper half).
        Returns the placed candidate dict when it is finally inserted; otherwise None.
        """
        if not self.frames:
            return None
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
            return cand  # placed!
        mid = (low + high) // 2
        self.frames.append((low, high, mid, cand))
        return None

# --------- Controller ---------

class RankingController:
    """
    - Reconciles Sheet rows with Google Tasks by Title on startup (attaches IDs, filters duplicates).
    - Roots ranked first, then children per parent.
    - Writes after every decision.
    - Children deleted immediately after writing; parents deleted when no unprocessed children remain
      (or immediately if DELETE_PARENTS_IMMEDIATELY=True).
    - Final cleanup on flush/exit.
    """
    def __init__(
        self,
        gt: GoogleTasks,
        sheets: SheetsClient,
        spreadsheet_id: str,
        sheet_tab: str,
        roots_from_sheet: List[Dict[str, Any]],
        children_from_sheet_by_title: Dict[str, List[Dict[str, Any]]],
        roots_from_gt: List[Dict[str, Any]],
        children_from_gt_by_id: Dict[str, List[Dict[str, Any]]],
    ):
        self.gt = gt
        self.sheets = sheets
        self.spreadsheet_id = spreadsheet_id
        self.sheet_tab = sheet_tab

        # Baseline from the sheet (no ids initially)
        self.baseline_roots = list(roots_from_sheet)
        self.baseline_children_by_title = {k: list(v) for k, v in (children_from_sheet_by_title or {}).items()}

        # Reconcile sheet vs Google Tasks by Title (case/space normalized)
        remaining_roots_from_gt, remaining_children_by_id = \
            self._reconcile_sheet_with_google(roots_from_gt, children_from_gt_by_id)

        # Sorters & state
        self.roots_sorter = PairwiseBinarySorter(already_sorted=self.baseline_roots, remaining=remaining_roots_from_gt)
        self.children_sorted_by_parent_id: Dict[str, List[Dict[str, Any]]] = {}
        self.children_remaining_by_parent_id = {pid: list(lst) for pid, lst in (remaining_children_by_id or {}).items()}

        # Ensure zero-child parents are tracked (for cleanup)
        self._seed_empty_child_groups_for_all_parents()

        # Parent ordering (for child phase)
        self.parent_order_ids: List[str] = []
        self.current_parent_id: Optional[str] = None
        self.child_sorter: Optional[PairwiseBinarySorter] = None

        # Deletion bookkeeping
        self.deleted_ids: set[str] = set()

    # ---- normalization & reconciliation ----

    @staticmethod
    def _norm(s: Optional[str]) -> str:
        s = (s or "").strip()
        # collapse inner whitespace and lowercase
        return " ".join(s.split()).lower()

    def _reconcile_sheet_with_google(
        self,
        roots_from_gt: List[Dict[str, Any]],
        children_from_gt_by_id: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """
        Attach Google Task IDs to sheet rows (roots + children) where titles match,
        and remove those items from the "remaining to-rank" lists so we don't compare against ourselves.
        """
        # --- roots ---
        title_to_sheet_root: Dict[str, Dict[str, Any]] = {}
        for r in self.baseline_roots:
            t = self._norm(r.get("title"))
            if t:
                title_to_sheet_root[t] = r

        remaining_roots: List[Dict[str, Any]] = []
        # Also build a parent-title map by id as we go
        parent_title_by_id: Dict[str, str] = {}

        for gr in roots_from_gt:
            nt = self._norm(gr.get("title"))
            if not nt:
                continue
            sheet_root = title_to_sheet_root.get(nt)
            if sheet_root:
                # Attach identifiers/metadata onto the sheet row
                for k in ("id", "task_list_id", "position", "list_title"):
                    if gr.get(k) is not None:
                        sheet_root[k] = gr.get(k)
                # Prefer existing Description/Link from sheet; fill blanks from GT snapshot
                if not (sheet_root.get("_link") or "").strip():
                    sheet_root["_link"] = (gr.get("_link") or "").strip()
                if not (sheet_root.get("notes") or "").strip():
                    sheet_root["notes"] = (gr.get("notes") or "").strip()
                if gr.get("id"):
                    parent_title_by_id[gr["id"]] = sheet_root.get("title") or ""
            else:
                remaining_roots.append(gr)
                if gr.get("id"):
                    parent_title_by_id[gr["id"]] = gr.get("title") or ""

        # --- children ---
        # Build child title index from the sheet per parent title
        children_index_by_parent_title: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for ptitle, lst in self.baseline_children_by_title.items():
            idx = {self._norm(c.get("title")): c for c in lst if (c.get("title") or "").strip()}
            children_index_by_parent_title[ptitle] = idx

        remaining_children: Dict[str, List[Dict[str, Any]]] = {}
        for pid, glist in (children_from_gt_by_id or {}).items():
            ptitle = parent_title_by_id.get(pid, "")
            idx = children_index_by_parent_title.get(ptitle, {})
            for gc in glist:
                nt = self._norm(gc.get("title"))
                if nt and nt in idx:
                    # Attach identifiers/metadata to the sheet child row
                    sc = idx[nt]
                    for k in ("id", "task_list_id", "position", "list_title", "parent"):
                        if gc.get(k) is not None:
                            sc[k] = gc.get(k)
                    if not (sc.get("_link") or "").strip():
                        sc["_link"] = (gc.get("_link") or "").strip()
                    if not (sc.get("notes") or "").strip():
                        sc["notes"] = (gc.get("notes") or "").strip()
                else:
                    remaining_children.setdefault(pid, []).append(gc)

        return remaining_roots, remaining_children

    def _seed_empty_child_groups_for_all_parents(self):
        # Ensure every root with an ID has a bucket, even if no children
        for r in self.baseline_roots + self.roots_sorter.remaining:
            pid = r.get("id")
            if pid and pid not in self.children_remaining_by_parent_id:
                self.children_remaining_by_parent_id[pid] = []

    # ---- UI-facing API ----

    def remaining_count(self) -> int:
        n_roots = len(self.roots_sorter.remaining)
        # Only count children not yet processed (remaining + in-progress sorter)
        n_children = sum(len(v) for v in self.children_remaining_by_parent_id.values())
        if self.child_sorter and self.child_sorter.has_work():
            n_children += len(self.child_sorter.remaining)
        return n_roots + n_children

    def current_pair(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        if self.roots_sorter.has_work():
            return self.roots_sorter.current_pair()

        if not self.parent_order_ids:
            # Build parent order from final root order
            for r in self.roots_sorter.sorted:
                if r.get("id"):
                    self.parent_order_ids.append(r["id"])
            self._auto_place_trivial_children()

        if not self.child_sorter or not self.child_sorter.has_work():
            if not self._activate_next_parent_group():
                return None

        return self.child_sorter.current_pair()

    def choose_left(self):
        self._decide(True)

    def choose_right(self):
        self._decide(False)

    def flush(self):
        """Write a snapshot and perform cleanup for any deletable parents."""
        self._persist()
        self._final_cleanup_for_parents()

    # ---- internal decision logic ----

    def _decide(self, left: bool):
        # Root phase
        if self.roots_sorter.has_work():
            placed_root = self.roots_sorter.decide(left)
            if placed_root:
                self._persist()

                # Delete parent now if requested OR if it has no unprocessed children
                pid = placed_root.get("id")
                if pid:
                    if DELETE_PARENTS_IMMEDIATELY:
                        self._delete_task(placed_root)
                    else:
                        self._delete_parent_if_ready(pid)
            return

        # Child phase
        if not (self.child_sorter and self.current_parent_id):
            return

        placed_child = self.child_sorter.decide(left)
        if placed_child:
            pid = self.current_parent_id
            self.children_sorted_by_parent_id.setdefault(pid, list(self.child_sorter.sorted))

            self._persist()

            # Delete the placed child immediately (idempotent)
            self._delete_task(placed_child)

            # If the group is finished, consider deleting the parent now.
            if not self.child_sorter.has_work():
                self._delete_parent_if_ready(pid)
                self.current_parent_id = None
                self.child_sorter = None

    # ---- persistence & activation ----

    def _persist(self):
        children_union: Dict[AnyType, List[Dict[str, Any]]] = {}
        for pid, lst in self.children_sorted_by_parent_id.items():
            children_union[pid] = list(lst)
        for ptitle, lst in self.baseline_children_by_title.items():
            children_union.setdefault(ptitle, [])
            children_union[ptitle].extend(lst)

        self.sheets.write_full_state(
            self.spreadsheet_id,
            self.sheet_tab,
            self.roots_sorter.sorted,
            children_union
        )

    def _auto_place_trivial_children(self):
        """Auto-handle parents with 0 or 1 remaining child."""
        for pid in list(self.children_remaining_by_parent_id.keys()):
            rem = self.children_remaining_by_parent_id.get(pid, [])
            if len(rem) == 0:
                self._delete_parent_if_ready(pid)
                continue
            if len(rem) == 1:
                child = rem.pop(0)
                self.children_sorted_by_parent_id.setdefault(pid, []).append(child)
                self._persist()
                self._delete_task(child)
                self._delete_parent_if_ready(pid)

    def _activate_next_parent_group(self) -> bool:
        while self.parent_order_ids:
            pid = self.parent_order_ids[0]
            rem = self.children_remaining_by_parent_id.get(pid, [])
            placed = self.children_sorted_by_parent_id.get(pid, [])

            total_to_process = len(rem)
            # If nothing remains to process for this parent, possibly delete and advance
            if total_to_process == 0:
                self._delete_parent_if_ready(pid)
                self.parent_order_ids.pop(0)
                continue

            # Start interactive ranking for this parent's children
            self.current_parent_id = pid
            self.child_sorter = PairwiseBinarySorter(already_sorted=placed, remaining=rem)
            # Clear remaining list in dict so we don't double-count
            self.children_remaining_by_parent_id[pid] = []
            return True

        return False

    # ---- deletions ----

    def _parent_has_unprocessed_children(self, pid: str) -> bool:
        if len(self.children_remaining_by_parent_id.get(pid, [])) > 0:
            return True
        # Also consider the active sorter for this parent
        if self.current_parent_id == pid and self.child_sorter and self.child_sorter.has_work():
            return True
        return False

    def _delete_parent_if_ready(self, pid: Optional[str]):
        if not pid:
            return
        if self._parent_has_unprocessed_children(pid):
            return
        parent = next((r for r in self.roots_sorter.sorted if r.get("id") == pid), None)
        if parent:
            self._delete_task(parent)

    def _final_cleanup_for_parents(self):
        """Run at flush/exit: delete any parents with no remaining children to process."""
        for pid in list(self.children_remaining_by_parent_id.keys()):
            self._delete_parent_if_ready(pid)

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
            # Parent might already be gone (or children cascaded) — safe to ignore.
            pass
        self.deleted_ids.add(tid)

# --------- UI ---------

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
            try:
                self.controller.flush()
            except Exception:
                pass
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

    # Idempotent
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

    # 4) Run the UI (pairwise O(n log n)).
    ui = RankerUI(controller, state_path=ui_state_path)
    ui.run()

if __name__ == "__main__":
    main()

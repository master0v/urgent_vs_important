#!/usr/bin/env python3
"""
Pairwise ranker (Tkinter) — inline Effort/Joy row.

Key behaviors (kept):
- Subtasks only get written to the sheet when their parent’s subtask ranking is FINISHED,
  and are placed directly under the parent (indent with two leading spaces; handled in sheets_api).
- Category validation mirrors colors from "Categories".
- Link is editable and saved.
- Remaining label shows "Remaining <N> tasks in '<list name>'".
- No Rank column; row order in the sheet is the rank.
- Config write-back: when creating a new spreadsheet, persist spreadsheet_id in ranker_config.json.
- Print details on delete for BOTH tasks and subtasks.
- Single-root scenario handled: parent is written first, then subtasks ranked; exit only when done.
- “Subtask” wording for child ranking and title shows “— subtask of <parent>”.
- sheets_api writes are authoritative but preserve non-finalized children from the existing sheet.

NEW (safety fix):
- Subtasks are **NOT** deleted from Google Tasks during ranking anymore. They are queued.
- When a parent’s child sorter finishes, we:
  1) finalize the child order,
  2) PERSIST that to the sheet,
  3) **ONLY THEN** delete the queued subtasks (and finally the parent if ready).
- If persisting fails, we **do not delete** anything — so state can’t be lost.
"""

import json
import os
import re
import datetime
import tkinter as tk
import tkinter.ttk as ttk
from typing import List, Dict, Any, Optional, Tuple, Any as AnyType

from tasks_api import GoogleTasks, SEPARATOR_TITLE
from sheets_api import SheetsClient, HEADER

# ---- behavior switches ----
DELETE_PARENTS_IMMEDIATELY = False  # keep false; parent deletion happens after children are finished

# --------- Config helpers ---------

def _config_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "ranker_config.json")

def load_config() -> Dict[str, Any]:
    with open(_config_path(), "r") as f:
        return json.load(f)

def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(_config_path(), "w") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
        print("[Config] Saved updates to ranker_config.json.")
    except Exception as e:
        print(f"[Config] Warning: failed to write config: {e}")

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

    roots.sort(key=lambda x: x.get("position", ""))
    for lst in children_by_parent.values():
        lst.sort(key=lambda x: x.get("position", ""))

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
        if not self.frames:
            return None
        low, high, mid, cand = self.frames.pop()
        if self.remaining and self.remaining[0].get("id") == cand.get("id"):
            self.remaining.pop(0)
        if choose_left:
            high = mid
        else:
            low = mid + 1
        if low >= high:
            self.sorted.insert(low, cand)
            return cand
        mid = (low + high) // 2
        self.frames.append((low, high, mid, cand))
        return None

# --------- Controller ---------

class RankingController:
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

        self.baseline_roots = list(roots_from_sheet)
        self.baseline_children_by_title = {k: list(v) for k, v in (children_from_sheet_by_title or {}).items()}

        remaining_roots_from_gt, remaining_children_by_id = \
            self._reconcile_sheet_with_google(roots_from_gt, children_from_gt_by_id)

        self.roots_sorter = PairwiseBinarySorter(already_sorted=self.baseline_roots, remaining=remaining_roots_from_gt)

        # children_sorted_by_parent_id holds ONLY finalized child orders for parents already finished.
        self.children_sorted_by_parent_id: Dict[str, List[Dict[str, Any]]] = {}

        # Pending (not-yet-ranked) children per parent id:
        self.children_remaining_by_parent_id = {pid: list(lst) for pid, lst in (remaining_children_by_id or {}).items()}

        # Queue of subtasks to delete AFTER successful persist per parent id:
        self._pending_child_deletes_by_parent: Dict[str, List[Dict[str, Any]]] = {}

        self._seed_empty_child_groups_for_all_parents()

        self.parent_order_ids: List[str] = []
        self.current_parent_id: Optional[str] = None
        self.child_sorter: Optional[PairwiseBinarySorter] = None

        self._persisted_after_auto_root = False
        self.deleted_ids: set[str] = set()

    # ---- normalization & reconciliation ----

    @staticmethod
    def _norm(s: Optional[str]) -> str:
        s = (s or "").strip()
        return " ".join(s.split()).lower()

    def _reconcile_sheet_with_google(
        self,
        roots_from_gt: List[Dict[str, Any]],
        children_from_gt_by_id: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        title_to_sheet_root: Dict[str, Dict[str, Any]] = {}
        for r in self.baseline_roots:
            t = self._norm(r.get("title"))
            if t:
                title_to_sheet_root[t] = r

        remaining_roots: List[Dict[str, Any]] = []
        parent_title_by_id: Dict[str, str] = {}

        for gr in roots_from_gt:
            nt = self._norm(gr.get("title"))
            if not nt:
                continue
            sheet_root = title_to_sheet_root.get(nt)
            if sheet_root:
                for k in ("id", "task_list_id", "position", "list_title"):
                    if gr.get(k) is not None:
                        sheet_root[k] = gr.get(k)
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
        for r in self.baseline_roots + self.roots_sorter.remaining:
            pid = r.get("id")
            if pid and pid not in self.children_remaining_by_parent_id:
                self.children_remaining_by_parent_id[pid] = []

    # ---- UI-facing API ----

    def remaining_count(self) -> int:
        n_roots = len(self.roots_sorter.remaining)
        n_children = sum(len(v) for v in self.children_remaining_by_parent_id.values())
        if self.child_sorter and self.child_sorter.has_work():
            n_children += len(self.child_sorter.remaining)
        return n_roots + n_children

    def is_ranking_subtasks(self) -> bool:
        return bool(self.child_sorter and (self.child_sorter.has_work()))

    def current_pair(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        # 1) Try root-level pair
        if self.roots_sorter.has_work():
            pair = self.roots_sorter.current_pair()
            if pair is not None:
                return pair

        # 2) Ensure placed roots are persisted (handles single-root auto-place)
        if not self._persisted_after_auto_root and self.roots_sorter.sorted:
            self._persist()  # writes ONLY roots + any finalized child groups
            self._persisted_after_auto_root = True

        # 3) Prep parents & auto-handle trivial children
        if not self.parent_order_ids:
            for r in self.roots_sorter.sorted:
                if r.get("id"):
                    self.parent_order_ids.append(r["id"])
            self._auto_place_trivial_children()

        # 4) Activate next parent
        if not self.child_sorter or not self.child_sorter.has_work():
            if not self._activate_next_parent_group():
                return None

        return self.child_sorter.current_pair()

    def choose_left(self, left_task: Dict[str, Any], right_task: Dict[str, Any]):
        self._decide(True)

    def choose_right(self, left_task: Dict[str, Any], right_task: Dict[str, Any]):
        self._decide(False)

    def flush(self):
        # Persist roots and any finalized children. Do NOT delete anything new here.
        self._persist()
        self._final_cleanup_for_parents()

    # ---- internal decision logic ----

    def _decide(self, left: bool):
        if self.roots_sorter.has_work():
            placed_root = self.roots_sorter.decide(left)
            if placed_root:
                # For roots we persist as we go (like before).
                self._persist()
                pid = placed_root.get("id")
                if pid:
                    if DELETE_PARENTS_IMMEDIATELY:
                        self._delete_task(placed_root)
                    else:
                        self._delete_parent_if_ready(pid)
            return

        if not (self.child_sorter and self.current_parent_id):
            return

        placed_child = self.child_sorter.decide(left)
        if placed_child:
            pid = self.current_parent_id
            # Queue the subtask for deletion LATER (after a successful persist).
            self._pending_child_deletes_by_parent.setdefault(pid, []).append(placed_child)

            # When the child sorter finishes:
            if not self.child_sorter.has_work():
                # 1) finalize order for this parent
                self.children_sorted_by_parent_id[pid] = list(self.child_sorter.sorted)

                # 2) persist FIRST; if it fails, do NOT delete
                persist_ok = False
                try:
                    self._persist()
                    persist_ok = True
                except Exception as e:
                    print(f"[WARN] Persist failed; not deleting children for parent id={pid}: {e}")

                # 3) only after a successful persist, delete queued subtasks (and then parent)
                if persist_ok:
                    for ch in self._pending_child_deletes_by_parent.get(pid, []):
                        self._delete_task(ch)
                    self._pending_child_deletes_by_parent[pid] = []
                    self._delete_parent_if_ready(pid)

                # reset active child sorter
                self.current_parent_id = None
                self.child_sorter = None

    # ---- persistence & activation ----

    def _persist(self):
        """
        Write current state to the sheet:
          - Roots (always in current order).
          - Subtasks ONLY for parents whose ranking is FINISHED (children_sorted_by_parent_id).
        No pending subtasks are written here; sheets_api preserves existing children for unfinished parents.
        """
        children_union: Dict[AnyType, List[Dict[str, Any]]] = {}

        for pid, lst in self.children_sorted_by_parent_id.items():
            children_union[pid] = list(lst)

        self.sheets.write_full_state(
            self.spreadsheet_id,
            self.sheet_tab,
            self.roots_sorter.sorted,
            children_union
        )

    def _auto_place_trivial_children(self):
        # If a parent has exactly 1 child, finalize immediately (no comparisons needed).
        for pid in list(self.children_remaining_by_parent_id.keys()):
            rem = self.children_remaining_by_parent_id.get(pid, [])
            if len(rem) == 0:
                self._delete_parent_if_ready(pid)
                continue
            if len(rem) == 1:
                child = rem.pop(0)
                self.children_sorted_by_parent_id.setdefault(pid, []).append(child)
                # Persist first; if OK, delete child and possibly parent
                persist_ok = False
                try:
                    self._persist()
                    persist_ok = True
                except Exception as e:
                    print(f"[WARN] Persist failed in trivial child path; not deleting child for parent id={pid}: {e}")
                if persist_ok:
                    self._delete_task(child)
                    self._delete_parent_if_ready(pid)

    def _activate_next_parent_group(self) -> bool:
        while self.parent_order_ids:
            pid = self.parent_order_ids[0]
            rem = self.children_remaining_by_parent_id.get(pid, [])
            placed_final = self.children_sorted_by_parent_id.get(pid)
            if placed_final is not None:
                self._delete_parent_if_ready(pid)
                self.parent_order_ids.pop(0)
                continue
            if len(rem) == 0:
                self._delete_parent_if_ready(pid)
                self.parent_order_ids.pop(0)
                continue
            self.current_parent_id = pid
            self.child_sorter = PairwiseBinarySorter(already_sorted=[], remaining=rem)
            self.children_remaining_by_parent_id[pid] = []
            return True
        return False

    # ---- deletions ----

    def _parent_has_unprocessed_children(self, pid: str) -> bool:
        if len(self.children_remaining_by_parent_id.get(pid, [])) > 0:
            return True
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
        for pid in list(self.children_remaining_by_parent_id.keys()):
            self._delete_parent_if_ready(pid)

    def _delete_task(self, task: Dict[str, Any]):
        """
        Delete a task. Print details for BOTH tasks and subtasks.
        """
        tid = task.get("id")
        if not tid or tid in self.deleted_ids:
            return
        tlist = task.get("task_list_id")
        if not tlist:
            return

        is_sub = bool(task.get("parent"))
        kind = "subtask" if is_sub else "task"

        print(f"\n[Deleting {kind}]")
        print(f"  Title:        {task.get('title') or ''}")
        if is_sub:
            print(f"  Parent Title: {task.get('_parent_title') or ''}")
        print(f"  Notes:        {task.get('notes') or ''}")
        print(f"  Category:     {task.get('category') or ''}")
        print(f"  Effort:       {task.get('effort') or ''}")
        print(f"  Joy:          {task.get('joy') or ''}")
        print(f"  Link:         {task.get('_link') or ''}")
        print(f"  TaskList ID:  {task.get('task_list_id') or ''}")
        print(f"  Task ID:      {task.get('id') or ''}")
        print(f"  List Title:   {task.get('list_title') or ''}")
        print(f"[/Deleting {kind}]\n")

        try:
            self.gt.service.tasks().delete(tasklist=tlist, task=tid).execute()
        except Exception:
            pass
        self.deleted_ids.add(tid)

# --------- UI ---------

class TaskPane:
    def __init__(self, parent_frame: tk.Frame, on_pick, category_values: List[str]):
        self.frame = tk.Frame(parent_frame, bd=1, relief="groove")
        self.frame.pack_propagate(False)

        self.title_btn = tk.Button(self.frame, text="", font=("Arial", 16, "bold"), wraplength=420, command=on_pick)
        self.title_btn.pack(fill="x", padx=10, pady=(10, 6))

        # Category row (editable dropdown)
        cat_row = tk.Frame(self.frame)
        cat_row.pack(fill="x", padx=10, pady=(0, 6))
        tk.Label(cat_row, text="Category:", anchor="w").pack(side="left")
        self.category_combo = ttk.Combobox(cat_row, values=category_values)
        self.category_combo.pack(side="left", fill="x", expand=True)
        self.category_combo.configure(state="normal")  # allow typing

        tk.Label(self.frame, text="Description:", anchor="w").pack(fill="x", padx=10)
        self.desc = tk.Text(self.frame, height=12, wrap="word")
        self.desc.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # Effort/Joy row — single line
        ej_row = tk.Frame(self.frame)
        ej_row.pack(fill="x", padx=10, pady=(0, 10))
        for col in range(4):
            ej_row.grid_columnconfigure(col, weight=0)
        ej_row.grid_columnconfigure(1, weight=1, uniform="ej")
        ej_row.grid_columnconfigure(3, weight=1, uniform="ej")

        tk.Label(ej_row, text="Effort (hours)", anchor="w").grid(row=0, column=0, sticky="w", padx=(0,6))
        self.effort_val = tk.Entry(ej_row)
        self.effort_val.grid(row=0, column=1, sticky="ew", padx=(0,12))

        tk.Label(ej_row, text="Joy (1-5)", anchor="w").grid(row=0, column=2, sticky="w", padx=(0,6))
        self.joy_val = tk.Entry(ej_row)
        self.joy_val.grid(row=0, column=3, sticky="ew")

        # Parent (readonly)
        self.parent_row = tk.Frame(self.frame)
        self.parent_row.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(self.parent_row, text="Parent:", anchor="w").pack(side="left")
        self.parent_val = tk.Entry(self.parent_row)
        self.parent_val.pack(side="left", fill="x", expand=True)
        self.parent_val.configure(state="readonly")

        # Link (editable)
        link_row = tk.Frame(self.frame)
        link_row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(link_row, text="Link:", anchor="w").pack(side="left")
        self.link_val = tk.Entry(link_row)
        self.link_val.pack(side="left", fill="x", expand=True)

        self._task_ref = None  # bound task dict

    def set_task(self, t: Optional[Dict[str, Any]]):
        self._task_ref = t
        if not t:
            self.title_btn.config(text="(no task)", state="disabled")
            self._set_desc("")
            self._set_ro_entry(self.parent_val, "")
            self._set_entry(self.link_val, "")
            self.category_combo.set("")
            self._set_entry(self.effort_val, "")
            self._set_entry(self.joy_val, "")
            self.parent_row.forget()
            return

        parent_title = (t.get("_parent_title") or "").strip()
        base_title = (t.get("title") or "").strip()
        self.title_btn.config(text=base_title, state="normal")

        self._set_desc((t.get("notes") or "").strip())
        self.category_combo.set((t.get("category") or "").strip())

        if parent_title:
            self.parent_row.pack(fill="x", padx=10, pady=(0, 4))
            self._set_ro_entry(self.parent_val, parent_title)
        else:
            self.parent_row.forget()

        self._set_entry(self.link_val, (t.get("_link") or "").strip())
        self._set_entry(self.effort_val, (t.get("effort") or "").strip())
        self._set_entry(self.joy_val, (t.get("joy") or "").strip())

    def apply_edits_to_task(self):
        if not self._task_ref:
            return
        notes = self.desc.get("1.0", "end").strip()
        category = self.category_combo.get().strip()
        link = self.link_val.get().strip()
        effort = self.effort_val.get().strip()
        joy = self.joy_val.get().strip()
        self._task_ref["notes"] = notes
        self._task_ref["category"] = category
        self._task_ref["_link"] = link
        self._task_ref["effort"] = effort
        self._task_ref["joy"] = joy

    def _set_desc(self, text: str):
        self.desc.delete("1.0", "end")
        self.desc.insert("1.0", text)

    def _set_entry(self, ent: tk.Entry, value: str):
        ent.delete(0, "end")
        ent.insert(0, value)

    def _set_ro_entry(self, ent: tk.Entry, value: str):
        ent.configure(state="normal")
        ent.delete(0, "end")
        ent.insert(0, value)
        ent.configure(state="readonly")

class UIStatePersist:
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

class RankerUI:
    def __init__(self, controller, state_path: str, category_values: List[str], list_name: Optional[str] = None):
        self.controller = controller
        self.state = UIStatePersist(state_path)
        self.list_name = list_name or "All tasks"

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
                self.left.apply_edits_to_task()
                self.right.apply_edits_to_task()
                self.controller.flush()
            except Exception:
                pass
            self.root.destroy()
        self.root.protocol("WM_DELETE_WINDOW", on_close)

        # Dynamic question (task vs subtask) — updated AFTER pair fetch
        self.question = tk.Label(self.root, text="", font=("Arial", 14))
        self.question.pack(fill="x", padx=12, pady=(10, 6))

        mid = tk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=12, pady=6)

        self.left = TaskPane(mid, on_pick=self._pick_left, category_values=category_values)
        self.left.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.right = TaskPane(mid, on_pick=self._pick_right, category_values=category_values)
        self.right.frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        mid.grid_columnconfigure(0, weight=1, uniform="col")
        mid.grid_columnconfigure(1, weight=1, uniform="col")
        mid.grid_rowconfigure(0, weight=1)

        self.remaining = tk.Label(self.root, text=f"Remaining 0 tasks in '{self.list_name}'", font=("Arial", 12))
        self.remaining.pack(fill="x", padx=12, pady=(6, 12))

        self.root.bind("<Left>",  lambda e: self._pick_left())
        self.root.bind("<Right>", lambda e: self._pick_right())

        self._current_pair: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
        self._refresh()

    def _save_geometry(self):
        try:
            self.state.save(self.root.wm_geometry())
        except Exception:
            pass

    def _update_question_label(self):
        if self.controller.is_ranking_subtasks():
            # Look up the current parent title
            parent_id = self.controller.current_parent_id
            parent_task = None
            if parent_id:
                parent_task = next((r for r in self.controller.roots_sorter.sorted if r.get("id") == parent_id), None)
            parent_title = (parent_task.get("title") or "") if parent_task else ""
            if parent_title:
                txt = f"Which of the following two subtasks of '{parent_title}' is more important for you?"
            else:
                txt = "Which of the following two subtasks is more important for you?"
        else:
            txt = "Which of the following two tasks is more important for you?"
        self.question.config(text=txt)
    
    def _refresh(self):
        # Fetch next pair first (this may activate child ranking), then update wording.
        pair = self.controller.current_pair()
        self._current_pair = pair
        self._update_question_label()

        if not pair:
            self.left.set_task(None)
            self.right.set_task(None)
            self.remaining.config(text=f"Remaining 0 tasks in '{self.list_name}'")
            self.root.after(600, self.root.destroy)
            return

        a, b = pair
        self.left.set_task(a)
        self.right.set_task(b)
        self.remaining.config(text=f"Remaining {self.controller.remaining_count()} tasks in '{self.list_name}'")

    def _pick_left(self):
        if self._current_pair:
            self.left.apply_edits_to_task()
            self.right.apply_edits_to_task()
            a, b = self._current_pair
            self.controller.choose_left(a, b)
        self._refresh()

    def _pick_right(self):
        if self._current_pair:
            self.left.apply_edits_to_task()
            self.right.apply_edits_to_task()
            a, b = self._current_pair
            self.controller.choose_right(a, b)
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
    categories_tab = (cfg.get("categories_tab") or "Categories").strip()

    sheets = SheetsClient(credentials_dir=credentials_dir)

    # If no spreadsheet specified, create one AND persist the id back to config immediately.
    if not spreadsheet_id:
        spreadsheet_id = sheets.create_spreadsheet(sheet_title)
        cfg["spreadsheet_id"] = spreadsheet_id
        save_config(cfg)
        print(f"[Created spreadsheet] ID: {spreadsheet_id} • Title: {sheet_title}")

    # Ensure tabs exist
    sheet_tab = sheets.ensure_tab(spreadsheet_id, sheet_tab)
    sheets.ensure_tab(spreadsheet_id, categories_tab)

    # Prime header if missing/wrong
    try:
        sheets._require_header_or_fail(spreadsheet_id, sheet_tab)  # private but safe here
    except Exception:
        sheets.clear_values(spreadsheet_id, sheet_tab)
        sheets.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_tab}!A1",
            valueInputOption="RAW",
            body={"values": [list(HEADER)]},
        ).execute()

    # Install validations (idempotent)
    sheets.ensure_status_dropdown_and_colors(spreadsheet_id, sheet_tab)
    sheets.ensure_category_dropdown(spreadsheet_id, sheet_tab, categories_tab)

    # Load categories for UI
    category_values = sheets.read_categories(spreadsheet_id, categories_tab)

    # Read sheet baseline
    roots_from_sheet, children_from_sheet_by_title = sheets.read_full_state(spreadsheet_id, sheet_tab)

    # Fetch Google Tasks
    gt = GoogleTasks()
    roots_from_gt, children_from_gt_by_id, _by_id = fetch_active_tasks(task_list_name)

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

    ui = RankerUI(controller, state_path=ui_state_path, category_values=category_values, list_name=task_list_name or "All tasks")
    ui.run()

if __name__ == "__main__":
    main()

#! /usr/bin/env python
#  -*- coding: utf-8 -*-

import sys, time, os, json
from pathlib import Path

try:
    import tkinter as tk
except ImportError:
    import Tkinter as tk  # pragma: no cover

try:
    import tkinter.ttk as ttk
    py3 = True
except ImportError:
    import ttk  # pragma: no cover
    py3 = False

import urgent_vs_important_support
from tasks_api import GoogleTasks

colors = [
    'blue','orange','green','red','purple',
    'brown','pink','gray','olive','cyan'
]

SETTINGS_FILE = os.path.join(Path.home(), ".prioritize_settings.json")

def vp_start_gui():
    global val, w, root
    root = tk.Tk()
    top = Toplevel1(root)
    urgent_vs_important_support.init(root, top)
    root.mainloop()

w = None
def create_Toplevel1(rt, *args, **kwargs):
    global w, w_win, root
    root = rt
    w = tk.Toplevel(root)
    top = Toplevel1(w)
    urgent_vs_important_support.init(w, top, *args, **kwargs)
    return (w, top)

def destroy_Toplevel1():
    global w
    w.destroy()
    w = None

class Toplevel1:

    def __init__(self, top=None):
        self.top = top  # keep handle to real window

        _bgcolor = '#d9d9d9'
        _fgcolor = '#000000'
        _compcolor = '#d9d9d9'
        _ana1color = '#d9d9d9'
        _ana2color = '#ececec'
        self.style = ttk.Style()
        if sys.platform == "win32":
            self.style.theme_use('winnative')
        self.style.configure('.', background=_bgcolor, foreground=_fgcolor, font="TkDefaultFont")
        self.style.map('.', background=[('selected', _compcolor), ('active', _ana2color)])

        # fullscreen state
        self._fullscreen = False

        # Default geometry (overridden by saved settings if present)
        top.geometry("900x700+200+100")
        top.resizable(True, True)
        top.title("Prioritize!")
        top.configure(background=_bgcolor)
        top.configure(highlightbackground=_bgcolor, highlightcolor="black")

        # Fullscreen helpers
        top.bind("<F11>", lambda e: self.toggle_fullscreen())
        top.bind("<FocusIn>", self._enforce_fullscreen)
        top.bind("<Map>", self._enforce_fullscreen)
        top.bind("<Visibility>", self._enforce_fullscreen)

        # --- Layout: resizable left pane via Panedwindow ---
        self.paned = ttk.Panedwindow(top, orient=tk.HORIZONTAL)
        self.paned.place(relx=0.0, rely=0.0, relheight=1.0, relwidth=1.0)

        self.left_frame = ttk.Frame(self.paned)
        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.left_frame, weight=1)
        self.paned.add(self.right_frame, weight=3)

        # Sizegrip
        self.style.configure('TSizegrip', background=_bgcolor)
        self.TSizegrip1 = ttk.Sizegrip(top)
        self.TSizegrip1.place(anchor='se', relx=1.0, rely=1.0)

        # Canvas inside right frame
        self.Canvas1 = tk.Canvas(self.right_frame)
        self.Canvas1.pack(fill="both", expand=True, padx=4, pady=4)
        self.Canvas1.configure(background=_bgcolor, borderwidth="2",
                               highlightbackground=_bgcolor, highlightcolor="black",
                               insertbackground="black", relief="ridge",
                               selectbackground="blue", selectforeground="white")

        # Redraw axis labels on resize and initial placement
        self.Canvas1.bind("<Configure>", self._on_canvas_resize)
        self.Canvas1.bind("<Configure>", self._maybe_place_pending_tokens, add="+")

        self.TSeparator1 = ttk.Separator(self.Canvas1)
        self.TSeparator1.place(relx=0.02, rely=0.514, relwidth=0.958)

        self.TSeparator2 = ttk.Separator(self.Canvas1)
        self.TSeparator2.place(relx=0.508, rely=0.016, relheight=0.981)
        self.TSeparator2.configure(orient="vertical")

        self.style.configure('Treeview', font="TkDefaultFont")

        # Left tree view
        self.Scrolledtreeview1 = ScrolledTreeView(self.left_frame)
        self.Scrolledtreeview1.pack(fill="both", expand=True, padx=4, pady=4)
        self.Scrolledtreeview1.heading("#0", text="Unprioritized", anchor="center")
        self.Scrolledtreeview1.column("#0", width="220", minwidth="120", stretch=True, anchor="w")

        # Load tasks
        print("loading tasks from your google account")
        self.gt = GoogleTasks()
        self.myTasks = self.gt.getTasks()  # active only

        self.list_to_task = {}
        # group-based dragging data
        self._drag_data = {"x": 0, "y": 0, "group": None, "rect_id": None, "moved": False}

        # Queue tokens for later placement
        self._pending_tokens = []     # [(x,y,color,task)]
        self._initial_tokens_placed = False
        self._placing_tokens = False  # re-entrancy guard

        # subtasks: cache and per-token panel state
        self._subtasks_by_parent = {}  # { parent_task_id: [titles...] }
        # { rect_id: {"expanded": bool, "ids": (panel_rect, panel_text) or None,
        #             "icon": (icon_bg, icon_text) or None } }
        self._subtask_panels = {}

        # === Build UI: tasks WITH coords -> canvas (deferred); WITHOUT -> tree ===
        color_index = 0
        list_index = 0

        for key in self.myTasks.keys():
            tasks_map = self.myTasks[key]
            print(f"{key} has {len(tasks_map)} active tasks")

            # list header
            self.Scrolledtreeview1.insert(
                '', tk.END, text=key, iid=list_index, open=True, tags=(colors[color_index], 'list_name')
            )
            list_header_iid = list_index
            list_index += 1

            # tasks with coordinates -> queue for exact placement
            canvas_parent_ids = set()
            for pos in sorted(tasks_map.keys()):  # preserve API order
                t = tasks_map[pos]
                coords = t.get('coordinates')
                if coords:
                    x, y = coords
                    self._pending_tokens.append((x, y, colors[color_index], t))
                    if t.get('id'):
                        canvas_parent_ids.add(t['id'])

            # parents (no coordinates)
            id_to_iid = {}
            for pos in sorted(tasks_map.keys()):
                t = tasks_map[pos]
                if t.get('coordinates'):
                    continue
                if not t.get('parent'):
                    txt = t.get('title', '')
                    tags = (colors[color_index], 'task')
                    self.Scrolledtreeview1.insert('', tk.END, text=txt, iid=list_index, open=False, tags=tags)
                    self.Scrolledtreeview1.move(list_index, list_header_iid, list_index)
                    id_to_iid[t['id']] = list_index
                    self.list_to_task[list_index] = t
                    list_index += 1

            # subtasks (hide those whose parent is on canvas; cache for panel)
            for pos in sorted(tasks_map.keys()):
                t = tasks_map[pos]
                if t.get('coordinates'):
                    continue
                parent_id = t.get('parent')
                if parent_id:
                    if parent_id in canvas_parent_ids:
                        self._subtasks_by_parent.setdefault(parent_id, []).append(t.get('title', ''))
                        continue
                    parent_iid = id_to_iid.get(parent_id)
                    txt = t.get('title', '')
                    tags = (colors[color_index], 'task', 'subtask')
                    if parent_iid:
                        self.Scrolledtreeview1.insert(parent_iid, tk.END, text=txt, iid=list_index, open=False, tags=tags)
                    else:
                        self.Scrolledtreeview1.insert('', tk.END, text=txt, iid=list_index, open=False, tags=tags)
                        self.Scrolledtreeview1.move(list_index, list_header_iid, list_index)
                    id_to_iid[t['id']] = list_index
                    self.list_to_task[list_index] = t
                    list_index += 1

            self.Scrolledtreeview1.tag_configure(colors[color_index], foreground=colors[color_index])
            color_index = (color_index + 1) % len(colors)

        # Initial placement
        self.Canvas1.after(0, self._maybe_place_pending_tokens)

        # Drag bindings (only for items tagged "token")
        self.Canvas1.tag_bind("token", "<ButtonPress-1>", self.drag_start)
        self.Canvas1.tag_bind("token", "<ButtonRelease-1>", self.drag_stop)
        self.Canvas1.tag_bind("token", "<B1-Motion>", self.drag)

        self.Scrolledtreeview1.bind("<ButtonPress-1>", self.tree_drag_start)
        self.Scrolledtreeview1.bind("<ButtonRelease-1>", self.tree_drag_stop)
        self.Scrolledtreeview1.bind("<B1-Motion>", self.tree_drag)

        # Axis labels
        self.draw_axes_labels()

        # --- Settings load/restore (geometry + left panel width as ratio) ---
        self._settings = self._load_settings()
        self._restore_geometry(self.top)
        self.top.after(0, self._restore_paned_sash)

        # Save settings on close
        self.top.protocol("WM_DELETE_WINDOW", self._on_close)

    # === Settings persistence ===
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self):
        try:
            geom = self.top.winfo_geometry()
        except Exception:
            geom = None
        try:
            total = max(self.paned.winfo_width(), 1)
            leftw = self.paned.sashpos(0)
            ratio = max(0.15, min(0.7, leftw / total))  # clamp to reasonable range
        except Exception:
            ratio = None

        data = dict(self._settings)
        if geom:
            data["window_geometry"] = geom
        if ratio is not None:
            data["left_panel_ratio"] = ratio

        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _restore_geometry(self, top):
        geom = self._settings.get("window_geometry")
        if geom:
            try:
                top.geometry(geom)
            except Exception:
                pass

    def _restore_paned_sash(self):
        width = self.paned.winfo_width()
        if width < 50:
            self.top.after(25, self._restore_paned_sash)
            return
        ratio = self._settings.get("left_panel_ratio", 0.30)
        ratio = max(0.15, min(0.7, float(ratio)))
        px = int(ratio * width)
        px = max(120, min(width - 240, px))  # at least 120px left; leave ~240px for right
        try:
            self.paned.sashpos(0, px)
        except Exception:
            pass

    def _on_close(self):
        self._save_settings()
        self.top.destroy()

    # ===== Fullscreen =====
    def toggle_fullscreen(self, event=None):
        self._fullscreen = not self._fullscreen
        try:
            self.top.attributes("-fullscreen", self._fullscreen)
        except Exception:
            pass

    def _enforce_fullscreen(self, event=None):
        if self._fullscreen:
            try:
                self.top.attributes("-fullscreen", True)
            except Exception:
                pass

    # ===== Initial token placement (deferred until canvas has real size) =====
    def _maybe_place_pending_tokens(self, event=None):
        # Guard against double calls from <Configure> + after(0)
        if self._initial_tokens_placed or self._placing_tokens:
            return
        w = self.Canvas1.winfo_width()
        h = self.Canvas1.winfo_height()
        if w < 50 or h < 50:
            self.Canvas1.after(50, self._maybe_place_pending_tokens)
            return
        self._placing_tokens = True
        for x, y, color, task in self._pending_tokens:
            self.create_token(x, y, color, task)
        self._pending_tokens.clear()
        self._initial_tokens_placed = True
        self._placing_tokens = False

    # ===== Axis labels =====
    def draw_axes_labels(self):
        self.Canvas1.delete('axis_label')
        w = self.Canvas1.winfo_width()
        h = self.Canvas1.winfo_height()
        self.Canvas1.create_text(w/2, h-12, text="Urgency →", tags=('axis_label',), anchor='s')
        self.Canvas1.create_text(10, 12, text="Importance ↑", tags=('axis_label',), anchor='nw')

    def _on_canvas_resize(self, event):
        self.draw_axes_labels()

    # ===== Tokens on canvas (auto-sized, wrapped text, rounded-ish rect) =====
    def create_token(self, x, y, color, task):
        title = task.get('title', '')
        # main pill text (measure)
        max_text_width = min(220, max(140, int(self.Canvas1.winfo_width() * 0.25)))
        temp_text_id = self.Canvas1.create_text(
            x, y, text=title, width=max_text_width, anchor="center", tags=("token_temp_text",)
        )
        self.Canvas1.update_idletasks()
        bbox = self.Canvas1.bbox(temp_text_id)  # (x1,y1,x2,y2)
        if not bbox:
            bbox = (x-40, y-15, x+40, y+15)
        pad_x, pad_y = 12, 8
        rx1, ry1, rx2, ry2 = bbox[0]-pad_x, bbox[1]-pad_y, bbox[2]+pad_x, bbox[3]+pad_y
        # Rounded-ish rectangle via smoothed polygon
        points = [
            rx1+10, ry1,  rx2-10, ry1,  rx2, ry1,  rx2, ry1+10,
            rx2, ry2-10,  rx2, ry2,  rx2-10, ry2,  rx1+10, ry2,
            rx1, ry2,  rx1, ry2-10,  rx1, ry1+10,  rx1, ry1,
        ]
        rect_id = self.Canvas1.create_polygon(
            points, smooth=True, splinesteps=12, outline=color, fill=color, tags=("token",)
        )
        self.Canvas1.delete(temp_text_id)
        text_id = self.Canvas1.create_text(
            (rx1+rx2)//2, (ry1+ry2)//2, text=title, width=max_text_width,
            anchor="center", fill="white", tags=("token",)
        )

        # group rect + text so they move together
        group_tag = f"token_group_{rect_id}"
        self.Canvas1.addtag_withtag(group_tag, rect_id)
        self.Canvas1.addtag_withtag(group_tag, text_id)

        # Subtask panel state: collapsed by default
        self._subtask_panels[rect_id] = {"expanded": False, "ids": None, "icon": None}

        # If this task has subtasks, draw a + icon (BOTTOM-RIGHT) and bind click
        parent_id = task.get('id')
        if parent_id:
            titles = self._gather_subtasks_titles(parent_id)
            if titles:
                icon_ids = self._render_toggle_icon_bottom_right(rect_id, rx1, ry1, rx2, ry2, expanded=False)
                self._subtask_panels[rect_id]["icon"] = icon_ids

        # Register this token id with backend (single id is enough)
        try:
            self.gt.setTokenId(rect_id, task)
        except Exception:
            pass

        # Keep a quick lookup to its task id for toggling
        self.Canvas1.itemconfig(rect_id, tags=self.Canvas1.gettags(rect_id) + (f"taskid_{task.get('id','')}",))

        return rect_id

    def _render_toggle_icon_bottom_right(self, rect_id, rx1, ry1, rx2, ry2, expanded: bool):
        """
        Render a small circular + / - icon at the pill's BOTTOM-RIGHT corner.
        Returns (icon_bg_id, icon_text_id) and binds click to toggle panel.
        IMPORTANT: No "token" tag on icon to avoid drag bindings.
        """
        group_tag = f"token_group_{rect_id}"
        size = 16  # diameter
        margin = 6
        cx = rx2 - margin - size // 2
        cy = ry2 - margin - size // 2

        icon_bg_id = self.Canvas1.create_oval(
            cx - size//2, cy - size//2, cx + size//2, cy + size//2,
            fill="#f7f7f7", outline="#b7b7b7",  # NOTE: no "token" tag
        )
        icon_text_id = self.Canvas1.create_text(
            cx, cy, text=("-" if expanded else "+"), fill="black",
            font=("TkDefaultFont", 10, "bold"),  # NOTE: no "token" tag
        )

        # bind both bg and text to same handler
        toggle_tag = f"subtoggle_{rect_id}"
        self.Canvas1.addtag_withtag(toggle_tag, icon_bg_id)
        self.Canvas1.addtag_withtag(toggle_tag, icon_text_id)
        # make them move with the pill (group tag), but still not draggable themselves
        self.Canvas1.addtag_withtag(group_tag, icon_bg_id)
        self.Canvas1.addtag_withtag(group_tag, icon_text_id)

        # Clicking the icon should ONLY toggle; avoid drag handlers by not using "token" tag
        self.Canvas1.tag_bind(toggle_tag, "<Button-1>", lambda e, rid=rect_id: self.toggle_subtasks_panel(rid))

        return (icon_bg_id, icon_text_id)

    def _set_toggle_icon(self, rect_id, expanded: bool):
        state = self._subtask_panels.get(rect_id)
        if not state or not state.get("icon"):
            return
        _, icon_text_id = state["icon"]
        try:
            self.Canvas1.itemconfig(icon_text_id, text=("-" if expanded else "+"))
        except Exception:
            pass

    def _taskid_for_rect(self, rect_id):
        # extract Google Task id from polygon tags
        for t in self.Canvas1.gettags(rect_id):
            if t.startswith("taskid_"):
                return t[len("taskid_"):] or None
        return None

    def _gather_subtasks_titles(self, parent_id):
        """Return cached subtasks for parent_id; if missing, compute once from self.myTasks and cache."""
        titles = self._subtasks_by_parent.get(parent_id)
        if titles is not None:
            return titles

        titles = []
        for _list_title, tasks_map in self.myTasks.items():
            for _pos_key, t in tasks_map.items():
                if t.get('parent') == parent_id:
                    title = t.get('title', '')
                    if title:
                        titles.append(title)
        self._subtasks_by_parent[parent_id] = titles
        return titles

    def toggle_subtasks_panel(self, rect_id):
        """Expand/collapse the inline subtask rectangle under the pill."""
        state = self._subtask_panels.get(rect_id)
        if not state:
            return

        if state["expanded"]:
            # collapse: remove items
            ids = state["ids"]
            if ids:
                for cid in ids:
                    try:
                        self.Canvas1.delete(cid)
                    except Exception:
                        pass
            state["ids"] = None
            state["expanded"] = False
            self._set_toggle_icon(rect_id, expanded=False)
            return

        # expand: compute titles and render panel
        parent_id = self._taskid_for_rect(rect_id)
        if not parent_id:
            return
        titles = self._gather_subtasks_titles(parent_id)
        if not titles:
            return

        pill_bbox = self.Canvas1.bbox(rect_id)
        if not pill_bbox:
            return
        rx1, ry1, rx2, ry2 = pill_bbox

        ids = self._render_subtasks_panel(rect_id, rx1, ry1, rx2, ry2, titles)
        state["ids"] = ids
        state["expanded"] = True
        self._set_toggle_icon(rect_id, expanded=True)

    def _render_subtasks_panel(self, rect_id, rx1, ry1, rx2, ry2, titles):
        """
        Create a rounded rectangle panel with bullet list of titles, under the main pill.
        - Panel width sized to fit text WITHOUT wrapping.
        - Slightly shifted a bit to the right.
        - Text is black.
        - Attached to the same group as the pill.
        Returns: (panel_rect_id, panel_text_id)
        """
        group_tag = f"token_group_{rect_id}"

        # Build the text (no width => no wrapping)
        text = "• " + "\n• ".join(titles)

        # Measure natural size (no wrapping) using a temporary text item
        shift_right = 8
        pad_x = 10
        pad_y = 8
        gap = 6
        pill_cx = (rx1 + rx2) // 2 + shift_right

        temp = self.Canvas1.create_text(
            pill_cx, ry2 + gap + pad_y,
            text=text, anchor="n", justify="left",  # NO width -> no wrapping
            fill="black", tags=("token_temp_text",)
        )
        self.Canvas1.update_idletasks()
        tb = self.Canvas1.bbox(temp)  # (x1,y1,x2,y2) of text alone
        if not tb:
            tb = (pill_cx - 50, ry2 + gap + pad_y, pill_cx + 50, ry2 + gap + pad_y + 20)
        text_w = tb[2] - tb[0]
        text_h = tb[3] - tb[1]

        panel_x1 = pill_cx - text_w//2 - pad_x
        panel_x2 = pill_cx + text_w//2 + pad_x
        panel_y1 = ry2 + gap
        panel_y2 = panel_y1 + pad_y + text_h + pad_y

        # Rounded-ish rectangle panel
        r = 8
        pts = [
            panel_x1+r, panel_y1, panel_x2-r, panel_y1, panel_x2, panel_y1, panel_x2, panel_y1+r,
            panel_x2, panel_y2-r, panel_x2, panel_y2, panel_x2-r, panel_y2, panel_x1+r, panel_y2,
            panel_x1, panel_y2, panel_x1, panel_y2-r, panel_x1, panel_y1+r, panel_x1, panel_y1,
        ]
        panel_rect_id = self.Canvas1.create_polygon(
            pts, smooth=True, splinesteps=12, outline="#b7b7b7", fill="#f7f7f7",
            tags=("token",)  # keep draggable with the pill
        )
        # Recreate text as the final (non-temp) item at same spot (no width)
        self.Canvas1.delete(temp)
        panel_text_id = self.Canvas1.create_text(
            pill_cx, panel_y1 + pad_y,
            text=text, anchor="n", justify="left",
            fill="black", tags=("token",)  # keep draggable with the pill
        )

        # bind to same group so everything moves as a unit
        self.Canvas1.addtag_withtag(group_tag, panel_rect_id)
        self.Canvas1.addtag_withtag(group_tag, panel_text_id)

        return (panel_rect_id, panel_text_id)

    # ===== Canvas dragging (group-based) =====
    def _pick_group_for_item(self, item_id):
        tags = self.Canvas1.gettags(item_id)
        group = next((t for t in tags if t.startswith("token_group_")), None)
        rect_id = None
        if group:
            try:
                rect_id = int(group.split("_")[-1])
            except Exception:
                rect_id = None
        return group, rect_id

    def drag_start(self, event):
        item = self.Canvas1.find_closest(event.x, event.y)[0]
        group, rect_id = self._pick_group_for_item(item)
        if not group:
            return
        self._drag_data["group"] = group
        self._drag_data["rect_id"] = rect_id
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self._drag_data["moved"] = False
        self.Scrolledtreeview1.configure(cursor="hand")
        self.Canvas1.configure(cursor="hand")

    def drag_stop(self, event):
        # Only persist if the item actually moved
        if self._drag_data["rect_id"] is not None and self._drag_data.get("moved"):
            task = self.gt.getTaskByTokenId(self._drag_data["rect_id"])
            if task:
                self.gt.updateTaskCoodinates(task, event.x, event.y)
        self._drag_data = {"x": 0, "y": 0, "group": None, "rect_id": None, "moved": False}
        self.Scrolledtreeview1.configure(cursor="arrow")
        self.Canvas1.configure(cursor="arrow")

    def drag(self, event):
        if not self._drag_data["group"]:
            return
        # keep token inside canvas while dragging
        if event.x > self.Canvas1.winfo_width() or event.x < 0 or \
           event.y > self.Canvas1.winfo_height() or event.y < 0:
            return
        delta_x = event.x - self._drag_data["x"]
        delta_y = event.y - self._drag_data["y"]
        if delta_x != 0 or delta_y != 0:
            self._drag_data["moved"] = True
        self.Canvas1.move(self._drag_data["group"], delta_x, delta_y)
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    # ===== Tree drag to canvas =====
    def tree_drag_start(self, event):
        self._drag_data = {"x": event.x, "y": event.y, "group": None, "rect_id": None, "moved": False}
        self.Scrolledtreeview1.configure(cursor="hand")
        self.Canvas1.configure(cursor="hand")

    def tree_drag_stop(self, event):
        tree_width = self.Scrolledtreeview1.winfo_width()
        if self._drag_data['rect_id'] is not None:
            task = self.gt.getTaskByTokenId(self._drag_data['rect_id'])
            if task:
                self.gt.updateTaskCoodinates(task, event.x - tree_width, event.y)
        self._drag_data = {"x": 0, "y": 0, "group": None, "rect_id": None, "moved": False}
        self.Scrolledtreeview1.configure(cursor="arrow")
        self.Canvas1.configure(cursor="arrow")

    def tree_drag(self, event):
        tree_width = self.Scrolledtreeview1.winfo_width()
        # Crossed into the canvas? Create token (once) and remove from tree
        if event.x > tree_width and not self._drag_data["group"]:
            focused = self.Scrolledtreeview1.focus()
            if focused:
                selected = self.Scrolledtreeview1.item(focused)
                tags = selected.get('tags', [])
                if len(tags) >= 2 and tags[1] == 'task':
                    task = self.list_to_task.get(int(focused))
                    if task:
                        # Collect this task's subtasks from the tree and remove them (cache them)
                        self._collect_and_remove_subtasks_for(task_id=task.get('id'))
                        # Create token near left edge of canvas
                        rect_id = self.create_token(4, event.y, tags[0], task)
                        group = f"token_group_{rect_id}"
                        self._drag_data["group"] = group
                        self._drag_data["rect_id"] = rect_id
                        self.Scrolledtreeview1.delete(self.Scrolledtreeview1.selection()[0])

        # Move token while inside canvas bounds
        if self._drag_data["group"] and \
           event.x > tree_width and \
           event.x < self.Canvas1.winfo_width() + tree_width and \
           event.y < self.Canvas1.winfo_height() and event.y > 0:
            delta_x = event.x - self._drag_data["x"]
            delta_y = event.y - self._drag_data["y"]
            self.Canvas1.move(self._drag_data["group"], delta_x, delta_y)

        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _collect_and_remove_subtasks_for(self, task_id):
        """
        When a parent task is moved to canvas from the tree, gather its subtasks,
        remove them from the left pane, and store for inline panel.
        """
        if not task_id:
            return
        titles = []
        to_delete_iids = []
        for iid, t in list(self.list_to_task.items()):
            if not isinstance(iid, int):
                continue
            if t.get('parent') == task_id:
                title = t.get('title', '')
                if title:
                    titles.append(title)
                to_delete_iids.append(iid)
        for iid in to_delete_iids:
            try:
                self.Scrolledtreeview1.delete(iid)
            except Exception:
                pass
            self.list_to_task.pop(iid, None)
        if titles:
            self._subtasks_by_parent.setdefault(task_id, []).extend(titles)

# ===== Scrolled TreeView helper =====
class AutoScroll(object):
    def __init__(self, master):
        try:
            vsb = ttk.Scrollbar(master, orient='vertical', command=self.yview)
        except Exception:
            vsb = None
        hsb = ttk.Scrollbar(master, orient='horizontal', command=self.xview)
        try:
            self.configure(yscrollcommand=self._autoscroll(vsb))
        except Exception:
            pass
        self.configure(xscrollcommand=self._autoscroll(hsb))
        self.grid(column=0, row=0, sticky='nsew')
        if vsb:
            vsb.grid(column=1, row=0, sticky='ns')
        hsb.grid(column=0, row=1, sticky='ew')
        master.grid_columnconfigure(0, weight=1)
        master.grid_rowconfigure(0, weight=1)
        if py3:
            methods = tk.Pack.__dict__.keys() | tk.Grid.__dict__.keys() | tk.Place.__dict__.keys()
        else:
            methods = tk.Pack.__dict__.keys() + tk.Grid.__dict__.keys() + tk.Place.__dict__.keys()
        for meth in methods:
            if meth[0] != '_' and meth not in ('config', 'configure'):
                setattr(self, meth, getattr(master, meth))

    @staticmethod
    def _autoscroll(sbar):
        def wrapped(first, last):
            first, last = float(first), float(last)
            if sbar is not None:
                if first <= 0 and last >= 1:
                    sbar.grid_remove()
                else:
                    sbar.grid()
                sbar.set(first, last)
        return wrapped

    def __str__(self):
        return str(self.master)

def _create_container(func):
    def wrapped(cls, master, **kw):
        container = ttk.Frame(master)
        container.bind('<Enter>', lambda e: _bound_to_mousewheel(e, container))
        container.bind('<Leave>', lambda e: _unbound_to_mousewheel(e, container))
        return func(cls, container, **kw)
    return wrapped

class ScrolledTreeView(AutoScroll, ttk.Treeview):
    @_create_container
    def __init__(self, master, **kw):
        ttk.Treeview.__init__(self, master, **kw)
        AutoScroll.__init__(self, master)

import platform
def _bound_to_mousewheel(event, widget):
    child = widget.winfo_children()[0]
    if platform.system() in ('Windows', 'Darwin'):
        child.bind_all('<MouseWheel>', lambda e: _on_mousewheel(e, child))
        child.bind_all('<Shift-MouseWheel>', lambda e: _on_shiftmouse(e, child))
    else:
        child.bind_all('<Button-4>', lambda e: _on_mousewheel(e, child))
        child.bind_all('<Button-5>', lambda e: _on_mousewheel(e, child))
        child.bind_all('<Shift-Button-4>', lambda e: _on_shiftmouse(e, child))
        child.bind_all('<Shift-Button-5>', lambda e: _on_shiftmouse(e, child))

def _unbound_to_mousewheel(event, widget):
    if platform.system() in ('Windows', 'Darwin'):
        widget.unbind_all('<MouseWheel>')
        widget.unbind_all('<Shift-MouseWheel>')
    else:
        widget.unbind_all('<Button-4>')
        widget.unbind_all('<Button-5>')
        widget.unbind_all('<Shift-Button-4>')
        widget.unbind_all('<Shift-Button-5>')

def _on_mousewheel(event, widget):
    if platform.system() == 'Windows':
        widget.yview_scroll(-1 * int(event.delta / 120), 'units')
    elif platform.system() == 'Darwin':
        widget.yview_scroll(-1 * int(event.delta), 'units')
    else:
        if event.num == 4:
            widget.yview_scroll(-1, 'units')
        elif event.num == 5:
            widget.yview_scroll(1, 'units')

def _on_shiftmouse(event, widget):
    if platform.system() == 'Windows':
        widget.xview_scroll(-1 * int(event.delta / 120), 'units')
    elif platform.system() == 'Darwin':
        widget.xview_scroll(-1 * int(event.delta), 'units')
    else:
        if event.num == 4:
            widget.xview_scroll(-1, 'units')
        elif event.num == 5:
            widget.xview_scroll(1, 'units')

if __name__ == '__main__':
    vp_start_gui()

#! /usr/bin/env python
#  -*- coding: utf-8 -*-

import sys, os, json
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
        self.top = top
        _bgcolor = '#d9d9d9'
        _fgcolor = '#000000'
        _ana2color = '#ececec'
        self.style = ttk.Style()
        if sys.platform == "win32":
            self.style.theme_use('winnative')
        self.style.configure('.', background=_bgcolor, foreground=_fgcolor, font="TkDefaultFont")
        self.style.map('.', background=[('selected', _bgcolor), ('active', _ana2color)])

        self._fullscreen = False
        top.geometry("900x700+200+100")
        top.resizable(True, True)
        top.title("Prioritize!")
        top.configure(background=_bgcolor)

        top.bind("<F11>", lambda e: self.toggle_fullscreen())
        top.bind("<FocusIn>", self._enforce_fullscreen)

        # ---- Layout: left tree + right canvas-with-scrollbars ----
        self.paned = ttk.Panedwindow(top, orient=tk.HORIZONTAL)
        self.paned.place(relx=0.0, rely=0.0, relheight=1.0, relwidth=1.0)

        self.left_frame = ttk.Frame(self.paned)
        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.left_frame, weight=1)
        self.paned.add(self.right_frame, weight=3)

        # Right side: container grid for canvas + scrollbars
        self.canvas_container = ttk.Frame(self.right_frame)
        self.canvas_container.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas_container.grid_rowconfigure(0, weight=1)
        self.canvas_container.grid_columnconfigure(0, weight=1)

        self.Canvas1 = tk.Canvas(
            self.canvas_container,
            background=_bgcolor, borderwidth=2,
            highlightbackground=_bgcolor, relief="ridge"
        )

        # Scrollbars wired directly to canvas (axes are drawn in canvas coords, so they scroll naturally)
        self.hscroll = ttk.Scrollbar(self.canvas_container, orient='horizontal', command=self.Canvas1.xview)
        self.vscroll = ttk.Scrollbar(self.canvas_container, orient='vertical', command=self.Canvas1.yview)
        self.Canvas1.configure(xscrollcommand=self.hscroll.set, yscrollcommand=self.vscroll.set)

        self.Canvas1.grid(row=0, column=0, sticky="nsew")
        self.vscroll.grid(row=0, column=1, sticky="ns")
        self.hscroll.grid(row=1, column=0, sticky="ew")

        # Redraw axes when the visible size changes (center-of-canvas may need recompute if canvas grew)
        self.Canvas1.bind("<Configure>", self._on_canvas_resize)

        self.style.configure('Treeview', font="TkDefaultFont")
        self.Scrolledtreeview1 = ScrolledTreeView(self.left_frame)
        self.Scrolledtreeview1.pack(fill="both", expand=True, padx=4, pady=4)
        self.Scrolledtreeview1.heading("#0", text="Unprioritized", anchor="center")
        self.Scrolledtreeview1.column("#0", width="220", minwidth="120", stretch=True, anchor="w")

        print("loading tasks from your google account")
        self.gt = GoogleTasks()
        self.myTasks = self.gt.getTasks()

        self.list_to_task = {}
        self._drag_data = {"x": 0, "y": 0, "group": None, "rect_id": None, "moved": False}

        self._pending_tokens = []
        self._initial_tokens_placed = False
        self._placing_tokens = False

        self._subtasks_by_parent = {}
        self._subtask_panels = {}
        self._token_widgets = {}

        # Scrollregion content bounds [x0,y0,x1,y1]; x0=y0=0 in this app
        self._content_bounds = None

        # ===== Populate left + queue canvas tokens =====
        color_index = 0
        list_index = 0

        for key in self.myTasks.keys():
            tasks_map = self.myTasks[key]
            print(f"{key} has {len(tasks_map)} active tasks")

            self.Scrolledtreeview1.insert(
                '', tk.END, text=key, iid=list_index, open=True, tags=(colors[color_index], 'list_name')
            )
            list_header_iid = list_index
            list_index += 1

            canvas_parent_ids = set()
            for pos in sorted(tasks_map.keys()):
                t = tasks_map[pos]
                coords = t.get('coordinates')
                if coords:
                    x, y = coords
                    self._pending_tokens.append((x, y, colors[color_index], t))
                    if t.get('id'):
                        canvas_parent_ids.add(t['id'])

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

        # Initial placement (after Canvas has size)
        self.Canvas1.after(0, self._maybe_place_pending_tokens)

        # Drag bindings (only for "token" items)
        self.Canvas1.tag_bind("token", "<ButtonPress-1>", self.drag_start)
        self.Canvas1.tag_bind("token", "<ButtonRelease-1>", self.drag_stop)
        self.Canvas1.tag_bind("token", "<B1-Motion>", self.drag)

        self.Scrolledtreeview1.bind("<ButtonPress-1>", self.tree_drag_start)
        self.Scrolledtreeview1.bind("<ButtonRelease-1>", self.tree_drag_stop)
        self.Scrolledtreeview1.bind("<B1-Motion>", self.tree_drag)

        # Settings (window + left pane split)
        self._settings = self._load_settings()
        self._restore_geometry(self.top)
        self.top.after(0, self._restore_paned_sash)

        self.top.protocol("WM_DELETE_WINDOW", self._on_close)

    # ===== Settings =====
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
            ratio = max(0.15, min(0.7, leftw / total))
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
        px = max(120, min(width - 240, px))
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

    # ===== Scroll region & axes =====
    def _init_content_bounds(self):
        if self._content_bounds is None:
            w = max(1, self.Canvas1.winfo_width())
            h = max(1, self.Canvas1.winfo_height())
            self._content_bounds = [0, 0, w, h]
            self.Canvas1.config(scrollregion=tuple(self._content_bounds))
            self.draw_axes()

    def _expand_content_bounds(self, bbox, margin=40):
        if not bbox:
            return
        self._init_content_bounds()
        x1, y1, x2, y2 = bbox
        changed = False
        if x2 + margin > self._content_bounds[2]:
            self._content_bounds[2] = int(x2 + margin)
            changed = True
        if y2 + margin > self._content_bounds[3]:
            self._content_bounds[3] = int(y2 + margin)
            changed = True
        if changed:
            self.Canvas1.config(scrollregion=tuple(self._content_bounds))
            self.draw_axes()

    def _canvas_center(self):
        self._init_content_bounds()
        x0, y0, x1, y1 = self._content_bounds
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    def draw_axes(self):
        """Cartesian-like axes centered in the canvas (not the viewport) with absolute pixel labels."""
        self.Canvas1.delete('axes')
        self._init_content_bounds()
        x0, y0, xmax, ymax = self._content_bounds
        cx, cy = self._canvas_center()  # fixed relative to the canvas extent

        # Main axes
        self.Canvas1.create_line(x0, cy, xmax, cy, fill='#666666', width=1, tags=('axes',))
        self.Canvas1.create_line(cx, y0, cx, ymax, fill='#666666', width=1, tags=('axes',))

        # Tick spacing and label spacing (in pixels)
        tick = 200
        label_every = 400

        # Helper: start on a multiple of 'tick'
        def start_multiple(a, step):
            if a % step == 0:
                return int(a)
            return int(a + (step - (a % step)))

        # Horizontal axis ticks (absolute x labels)
        x = start_multiple(int(x0), tick)
        while x <= int(xmax):
            self.Canvas1.create_line(x, cy - 5, x, cy + 5, fill='#777777', tags=('axes',))
            if (x % label_every) == 0:
                self.Canvas1.create_text(x, cy + 12, text=str(x), anchor='n', fill='#333333', tags=('axes',))
            x += tick

        # Vertical axis ticks (absolute y labels; note: canvas y grows downward)
        y = start_multiple(int(y0), tick)
        while y <= int(ymax):
            self.Canvas1.create_line(cx - 5, y, cx + 5, y, fill='#777777', tags=('axes',))
            if (y % label_every) == 0:
                self.Canvas1.create_text(cx + 10, y, text=str(y), anchor='w', fill='#333333', tags=('axes',))
            y += tick

        # Axis titles
        self.Canvas1.create_text(min(xmax - 80, cx + 100), cy - 12, text="x", anchor='w',
                                 fill='#222222', tags=('axes',))
        self.Canvas1.create_text(cx + 10, max(y0 + 10, cy - 100), text="y", anchor='w',
                                 fill='#222222', tags=('axes',))

    def _on_canvas_resize(self, event):
        # Ensure content bounds at least as large as visible area
        self._init_content_bounds()
        changed = False
        if event.width > self._content_bounds[2]:
            self._content_bounds[2] = int(event.width)
            changed = True
        if event.height > self._content_bounds[3]:
            self._content_bounds[3] = int(event.height)
            changed = True
        if changed:
            self.Canvas1.config(scrollregion=tuple(self._content_bounds))
        # Recenter axes to the canvas center (not viewport)
        self.draw_axes()

    # ===== Initial token placement =====
    def _maybe_place_pending_tokens(self):
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

    # ===== Tokens (pill + compact inline controls) =====
    def create_token(self, x, y, color, task):
        title = task.get('title', '')
        max_text_width = min(220, max(140, int(self.Canvas1.winfo_width() * 0.25)))
        temp_text_id = self.Canvas1.create_text(
            x, y, text=title, width=max_text_width, anchor="center", tags=("token_temp_text",)
        )
        self.Canvas1.update_idletasks()
        bbox = self.Canvas1.bbox(temp_text_id)
        if not bbox:
            bbox = (x-40, y-15, x+40, y+15)
        pad_x, pad_y = 12, 8

        extra_h = 24  # compact controls strip inside pill
        rx1, ry1, rx2, ry2 = bbox[0]-pad_x, bbox[1]-pad_y, bbox[2]+pad_x, bbox[3]+pad_y + extra_h

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
            (rx1+rx2)//2, (ry1+ry2 - extra_h)//2,
            text=title, width=max_text_width,
            anchor="center", fill="white", tags=("token",)
        )

        # group rect + text so they move together
        group_tag = f"token_group_{rect_id}"
        self.Canvas1.addtag_withtag(group_tag, rect_id)
        self.Canvas1.addtag_withtag(group_tag, text_id)

        # Subtask panel state: collapsed by default
        self._subtask_panels[rect_id] = {"expanded": False, "ids": None, "icon": None}

        # Compact controls INSIDE the pill
        self._create_compact_controls_inside_pill(rect_id, rx1, ry1, rx2, ry2, extra_h, color, task, group_tag)

        # If this task has subtasks, draw a + icon (BOTTOM-RIGHT)
        parent_id = task.get('id')
        if parent_id:
            titles = self._gather_subtasks_titles(parent_id)
            if titles:
                icon_ids = self._render_toggle_icon_bottom_right(rect_id, rx1, ry1, rx2, ry2, expanded=False)
                self._subtask_panels[rect_id]["icon"] = icon_ids

        # Register this token id with backend
        try:
            self.gt.setTokenId(rect_id, task)
        except Exception:
            pass
        self.Canvas1.itemconfig(rect_id, tags=self.Canvas1.gettags(rect_id) + (f"taskid_{task.get('id','')}",))

        # Expand scrollregion to include the whole token group
        gbb = self.Canvas1.bbox(group_tag)
        self._expand_content_bounds(gbb, margin=60)
        return rect_id

    def _create_compact_controls_inside_pill(self, rect_id, rx1, ry1, rx2, ry2, extra_h, pill_color, task, group_tag):
        row_y = ry2 - (extra_h // 2)
        row_w = max(80, (rx2 - rx1) - 24)

        frame = tk.Frame(self.Canvas1, bg=pill_color, bd=0, highlightthickness=0)

        var_est = tk.StringVar()
        if task.get('time_estimate') is not None:
            var_est.set(f"{float(task['time_estimate']):g}")
        entry = tk.Entry(
            frame, width=3, textvariable=var_est,
            bd=0, highlightthickness=0, relief="flat", justify="right"
        )
        lbl_h = tk.Label(frame, text="h", bg=pill_color, fg="white")

        var_prog = tk.IntVar(value=int(task.get('progress', 0)))
        scale = ttk.Scale(frame, from_=0, to=100, orient=tk.HORIZONTAL, length=max(60, row_w - 50), variable=var_prog)

        entry.pack(side="left", padx=(6,2), pady=0)
        lbl_h.pack(side="left", padx=(0,6), pady=0)
        scale.pack(side="left", padx=(0,6), pady=0)

        cx = (rx1 + rx2) // 2
        win_id = self.Canvas1.create_window(cx, row_y, window=frame, anchor="center")
        self.Canvas1.addtag_withtag(group_tag, win_id)

        def persist_estimate(event=None, token_rect_id=rect_id, entry_widget=entry):
            task_obj = self.gt.getTaskByTokenId(token_rect_id)
            if not task_obj:
                return
            val = entry_widget.get().strip()
            if val == "":
                # leave absent
                return
            try:
                hours = max(0.0, float(val))
                self.gt.updateTask(task_obj, t_hours=hours, resort=False)
            except Exception:
                if task_obj.get('time_estimate') is not None:
                    entry_widget.delete(0, tk.END)
                    entry_widget.insert(0, f"{float(task_obj['time_estimate']):g}")

        def persist_progress(event=None, token_rect_id=rect_id, var=var_prog):
            task_obj = self.gt.getTaskByTokenId(token_rect_id)
            if not task_obj:
                return
            try:
                p = max(0, min(100, int(float(var.get()))))
                self.gt.updateTask(task_obj, progress=p, resort=False)
            except Exception:
                pass

        entry.bind("<FocusOut>", persist_estimate)
        entry.bind("<Return>", persist_estimate)
        scale.bind("<ButtonRelease-1>", persist_progress)

        self._token_widgets[rect_id] = {
            "frame": frame, "window_id": win_id,
            "entry": entry, "scale": scale, "vars": (var_est, var_prog)
        }

    def _render_toggle_icon_bottom_right(self, rect_id, rx1, ry1, rx2, ry2, expanded: bool):
        group_tag = f"token_group_{rect_id}"
        size = 16
        margin = 6
        cx = rx2 - margin - size // 2
        cy = ry2 - margin - size // 2

        icon_bg_id = self.Canvas1.create_oval(
            cx - size//2, cy - size//2, cx + size//2, cy + size//2,
            fill="#f7f7f7", outline="#b7b7b7",
        )
        icon_text_id = self.Canvas1.create_text(
            cx, cy, text=("-" if expanded else "+"), fill="black",
            font=("TkDefaultFont", 10, "bold"),
        )
        toggle_tag = f"subtoggle_{rect_id}"
        self.Canvas1.addtag_withtag(toggle_tag, icon_bg_id)
        self.Canvas1.addtag_withtag(toggle_tag, icon_text_id)
        self.Canvas1.addtag_withtag(group_tag, icon_bg_id)
        self.Canvas1.addtag_withtag(group_tag, icon_text_id)
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
        for t in self.Canvas1.gettags(rect_id):
            if t.startswith("taskid_"):
                return t[len("taskid_"):] or None
        return None

    def _gather_subtasks_titles(self, parent_id):
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
        state = self._subtask_panels.get(rect_id)
        if not state:
            return
        if state["expanded"]:
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

        # Expand scrollregion to include the panel
        if ids and len(ids) >= 1:
            pb = self.Canvas1.bbox(ids[0])  # panel rect bbox
            self._expand_content_bounds(pb, margin=40)

    def _render_subtasks_panel(self, rect_id, rx1, ry1, rx2, ry2, titles):
        group_tag = f"token_group_{rect_id}"
        text = "• " + "\n• ".join(titles)

        shift_right = 8
        pad_x = 10
        pad_y = 8
        gap = 6
        pill_cx = (rx1 + rx2) // 2 + shift_right

        temp = self.Canvas1.create_text(
            pill_cx, ry2 + gap + pad_y,
            text=text, anchor="n", justify="left",
            fill="black", tags=("token_temp_text",)
        )
        self.Canvas1.update_idletasks()
        tb = self.Canvas1.bbox(temp)
        if not tb:
            tb = (pill_cx - 50, ry2 + gap + pad_y, pill_cx + 50, ry2 + gap + pad_y + 20)
        text_w = tb[2] - tb[0]
        text_h = tb[3] - tb[1]

        panel_x1 = pill_cx - text_w//2 - pad_x
        panel_x2 = pill_cx + text_w//2 + pad_x
        panel_y1 = ry2 + gap
        panel_y2 = panel_y1 + pad_y + text_h + pad_y

        r = 8
        pts = [
            panel_x1+r, panel_y1, panel_x2-r, panel_y1, panel_x2, panel_y1, panel_x2, panel_y1+r,
            panel_x2, panel_y2-r, panel_x2, panel_y2, panel_x2-r, panel_y2, panel_x1+r, panel_y2,
            panel_x1, panel_y2, panel_x1, panel_y2-r, panel_x1, panel_y1+r, panel_x1, panel_y1,
        ]
        panel_rect_id = self.Canvas1.create_polygon(
            pts, smooth=True, splinesteps=12, outline="#b7b7b7", fill="#f7f7f7",
            tags=("token",)
        )
        self.Canvas1.delete(temp)
        panel_text_id = self.Canvas1.create_text(
            pill_cx, panel_y1 + pad_y,
            text=text, anchor="n", justify="left",
            fill="black", tags=("token",)
        )

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

    def _persist_group_center(self):
        """Persist using the group's visual center; correct even when scrolled."""
        if not self._drag_data["group"]:
            return None
        gbb = self.Canvas1.bbox(self._drag_data["group"])
        if not gbb:
            return None
        cx = (gbb[0] + gbb[2]) // 2
        cy = (gbb[1] + gbb[3]) // 2
        return (cx, cy)

    def drag_stop(self, event):
        if self._drag_data["rect_id"] is not None and self._drag_data.get("moved"):
            task = self.gt.getTaskByTokenId(self._drag_data["rect_id"])
            if task:
                center = self._persist_group_center()
                if center:
                    self.gt.updateTaskCoodinates(task, center[0], center[1])
            # expand scrollregion to include final position
            gbb = self.Canvas1.bbox(self._drag_data["group"])
            self._expand_content_bounds(gbb, margin=60)
        self._drag_data = {"x": 0, "y": 0, "group": None, "rect_id": None, "moved": False}
        self.Scrolledtreeview1.configure(cursor="arrow")
        self.Canvas1.configure(cursor="arrow")

    def drag(self, event):
        if not self._drag_data["group"]:
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
        if self._drag_data['rect_id'] is not None:
            task = self.gt.getTaskByTokenId(self._drag_data['rect_id'])
            if task:
                center = self._persist_group_center()
                if center:
                    self.gt.updateTaskCoodinates(task, center[0], center[1])
            gbb = self.Canvas1.bbox(self._drag_data["group"])
            self._expand_content_bounds(gbb, margin=60)
        self._drag_data = {"x": 0, "y": 0, "group": None, "rect_id": None, "moved": False}
        self.Scrolledtreeview1.configure(cursor="arrow")
        self.Canvas1.configure(cursor="arrow")

    def tree_drag(self, event):
        tree_width = self.Scrolledtreeview1.winfo_width()
        if event.x > tree_width and not self._drag_data["group"]:
            focused = self.Scrolledtreeview1.focus()
            if focused:
                selected = self.Scrolledtreeview1.item(focused)
                tags = selected.get('tags', [])
                if len(tags) >= 2 and tags[1] == 'task':
                    task = self.list_to_task.get(int(focused))
                    if task:
                        self._collect_and_remove_subtasks_for(task_id=task.get('id'))
                        rect_id = self.create_token(4, event.y, tags[0], task)
                        group = f"token_group_{rect_id}"
                        self._drag_data["group"] = group
                        self._drag_data["rect_id"] = rect_id
                        self.Scrolledtreeview1.delete(self.Scrolledtreeview1.selection()[0])

        if self._drag_data["group"] and event.x > tree_width:
            delta_x = event.x - self._drag_data["x"]
            delta_y = event.y - self._drag_data["y"]
            self.Canvas1.move(self._drag_data["group"], delta_x, delta_y)

        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _collect_and_remove_subtasks_for(self, task_id):
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
        return func(cls, container, **kw)
    return wrapped

class ScrolledTreeView(AutoScroll, ttk.Treeview):
    @_create_container
    def __init__(self, master, **kw):
        ttk.Treeview.__init__(self, master, **kw)
        AutoScroll.__init__(self, master)

if __name__ == '__main__':
    vp_start_gui()

#!/usr/local/bin/python3
#  -*- coding: utf-8 -*-

import sys, time

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

        # No size caps
        top.geometry("900x700+200+100")
        top.resizable(True, True)
        top.title("Prioritize!")
        top.configure(background=_bgcolor)
        top.configure(highlightbackground=_bgcolor, highlightcolor="black")

        # Fullscreen helpers: re-assert when returning to Space
        top.bind("<F11>", lambda e: self.toggle_fullscreen())
        top.bind("<FocusIn>", self._enforce_fullscreen)
        top.bind("<Map>", self._enforce_fullscreen)
        top.bind("<Visibility>", self._enforce_fullscreen)

        self.style.configure('TSizegrip', background=_bgcolor)
        self.TSizegrip1 = ttk.Sizegrip(top)
        self.TSizegrip1.place(anchor='se', relx=1.0, rely=1.0)

        self.Canvas1 = tk.Canvas(top)
        self.Canvas1.place(relx=0.299, rely=0.006, relheight=0.983, relwidth=0.693)
        self.Canvas1.configure(background=_bgcolor, borderwidth="2",
                               highlightbackground=_bgcolor, highlightcolor="black",
                               insertbackground="black", relief="ridge",
                               selectbackground="blue", selectforeground="white")

        # Redraw axis labels on resize and try initial token placement when size is ready
        self.Canvas1.bind("<Configure>", self._on_canvas_resize)
        self.Canvas1.bind("<Configure>", self._maybe_place_pending_tokens, add="+")  # add, don't replace

        self.TSeparator1 = ttk.Separator(self.Canvas1)
        self.TSeparator1.place(relx=0.02, rely=0.514, relwidth=0.958)

        self.TSeparator2 = ttk.Separator(self.Canvas1)
        self.TSeparator2.place(relx=0.508, rely=0.016, relheight=0.981)
        self.TSeparator2.configure(orient="vertical")

        self.style.configure('Treeview', font="TkDefaultFont")

        # Left tree view
        self.Scrolledtreeview1 = ScrolledTreeView(top)
        self.Scrolledtreeview1.place(relx=0.008, rely=0.006, relheight=0.98, relwidth=0.289)
        self.Scrolledtreeview1.heading("#0", text="Unprioritized", anchor="center")
        self.Scrolledtreeview1.column("#0", width="220", minwidth="120", stretch=True, anchor="w")

        # Load active tasks
        print("loading tasks from your google account")
        self.gt = GoogleTasks()
        self.myTasks = self.gt.getTasks()  # active only

        self.list_to_task = {}
        self._drag_data = {"x": 0, "y": 0, "item": None}

        # --- NEW: we'll queue tokens to place after canvas has a real size ---
        self._pending_tokens = []     # list of (x, y, color, task)
        self._initial_tokens_placed = False

        # === Build UI: tasks WITH coordinates -> canvas (deferred); WITHOUT -> tree ===
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

            # queue all tasks with coordinates for later placement (exact coords)
            for pos in sorted(tasks_map.keys()):  # keep API order (lexicographic)
                t = tasks_map[pos]
                coords = t.get('coordinates')
                if coords:
                    x, y = coords  # already ints from tasks_api
                    self._pending_tokens.append((x, y, colors[color_index], t))

            # build tree for tasks WITHOUT coordinates
            id_to_iid = {}
            # parents
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

            # subtasks
            for pos in sorted(tasks_map.keys()):
                t = tasks_map[pos]
                if t.get('coordinates'):
                    continue
                parent_id = t.get('parent')
                if parent_id:
                    parent_iid = id_to_iid.get(parent_id)
                    txt = t.get('title', '')
                    tags = (colors[color_index], 'task', 'subtask')
                    if parent_iid:
                        self.Scrolledtreeview1.insert(parent_iid, tk.END, text=txt, iid=list_index, open=False, tags=tags)
                    else:
                        # parent might be on canvas or filtered → attach under list header
                        self.Scrolledtreeview1.insert('', tk.END, text=txt, iid=list_index, open=False, tags=tags)
                        self.Scrolledtreeview1.move(list_index, list_header_iid, list_index)
                    id_to_iid[t['id']] = list_index
                    self.list_to_task[list_index] = t
                    list_index += 1

            self.Scrolledtreeview1.tag_configure(colors[color_index], foreground=colors[color_index])
            color_index = (color_index + 1) % len(colors)

        # kick an initial attempt shortly after layout starts
        self.Canvas1.after(0, self._maybe_place_pending_tokens)

        # Canvas drag bindings
        self.Canvas1.tag_bind("token", "<ButtonPress-1>", self.drag_start)
        self.Canvas1.tag_bind("token", "<ButtonRelease-1>", self.drag_stop)
        self.Canvas1.tag_bind("token", "<B1-Motion>", self.drag)

        # Tree drag bindings
        self.Scrolledtreeview1.bind("<ButtonPress-1>", self.tree_drag_start)
        self.Scrolledtreeview1.bind("<ButtonRelease-1>", self.tree_drag_stop)
        self.Scrolledtreeview1.bind("<B1-Motion>", self.tree_drag)

        # Initial axis labels
        self.draw_axes_labels()

    # ===== Fullscreen helpers =====
    def toggle_fullscreen(self, event=None):
        self._fullscreen = not self._fullscreen
        self.winfo_toplevel().attributes("-fullscreen", self._fullscreen)

    def _enforce_fullscreen(self, event=None):
        if self._fullscreen:
            try:
                self.winfo_toplevel().attributes("-fullscreen", True)
            except Exception:
                pass

    # ===== Initial token placement (deferred until canvas has real size) =====
    def _maybe_place_pending_tokens(self, event=None):
        if self._initial_tokens_placed:
            return
        w = self.Canvas1.winfo_width()
        h = self.Canvas1.winfo_height()
        if w < 50 or h < 50:
            # try again shortly until canvas is laid out
            self.Canvas1.after(50, self._maybe_place_pending_tokens)
            return
        # Place exactly where saved (no clamping on initial restore)
        for x, y, color, task in self._pending_tokens:
            self.create_token(x, y, color, task)
        self._pending_tokens.clear()
        self._initial_tokens_placed = True

    # ===== Axis labels =====
    def draw_axes_labels(self):
        self.Canvas1.delete('axis_label')
        w = self.Canvas1.winfo_width()
        h = self.Canvas1.winfo_height()
        self.Canvas1.create_text(w/2, h-12, text="Urgency →", tags=('axis_label',), anchor='s')
        self.Canvas1.create_text(10, 12, text="Importance ↑", tags=('axis_label',), anchor='nw')

    def _on_canvas_resize(self, event):
        self.draw_axes_labels()

    # ===== Tokens on canvas =====
    def create_token(self, x, y, color, task):
        token_id = self.Canvas1.create_oval(
            x - 35, y - 15, x + 35, y + 15, outline=color, fill=color, tags=("token",),
        )
        self.gt.setTokenId(token_id, task)
        self.Canvas1.create_text(x, y, text=task['title'], tags=("token",))

    def drag_start(self, event):
        self._drag_data["item"] = self.Canvas1.find_closest(event.x, event.y)[0]
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self.Scrolledtreeview1.configure(cursor="hand")
        self.Canvas1.configure(cursor="hand")

    def drag_stop(self, event):
        task = self.gt.getTaskByTokenId(self._drag_data['item'])
        if task:
            self.gt.updateTaskCoodinates(task, event.x, event.y)
        self._drag_data["item"] = None
        self._drag_data["x"] = 0
        self._drag_data["y"] = 0
        self.Scrolledtreeview1.configure(cursor="arrow")
        self.Canvas1.configure(cursor="arrow")

    def drag(self, event):
        # keep token inside canvas while dragging
        if event.x > self.Canvas1.winfo_width() or event.x < 0 or \
           event.y > self.Canvas1.winfo_height() or event.y < 0:
            return
        delta_x = event.x - self._drag_data["x"]
        delta_y = event.y - self._drag_data["y"]
        self.move_token(self._drag_data["item"], delta_x, delta_y)
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def move_token(self, token_item, delta_x, delta_y):
        if (token_item % 2) == 0:
            token_item -= 1
        self.Canvas1.move(token_item, delta_x, delta_y)
        self.Canvas1.move(token_item + 1, delta_x, delta_y)

    # ===== Tree drag to canvas =====
    def tree_drag_start(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self.Scrolledtreeview1.configure(cursor="hand")
        self.Canvas1.configure(cursor="hand")

    def tree_drag_stop(self, event):
        tree_width = self.Scrolledtreeview1.winfo_width()
        if self._drag_data['item']:
            task = self.gt.getTaskByTokenId(self._drag_data['item'])
            if task:
                self.gt.updateTaskCoodinates(task, event.x - tree_width, event.y)
        self._drag_data["item"] = None
        self._drag_data["x"] = 0
        self._drag_data["y"] = 0
        self.Scrolledtreeview1.configure(cursor="arrow")
        self.Canvas1.configure(cursor="arrow")

    def tree_drag(self, event):
        tree_width = self.Scrolledtreeview1.winfo_width()
        # Crossed into the canvas? Create token (once) and remove from tree
        if event.x > tree_width and not self._drag_data["item"]:
            focused = self.Scrolledtreeview1.focus()
            if focused:
                selected = self.Scrolledtreeview1.item(focused)
                tags = selected.get('tags', [])
                if len(tags) >= 2 and tags[1] == 'task':
                    task = self.list_to_task.get(int(focused))
                    if task:
                        self.create_token(1, event.y, tags[0], task)
                        self._drag_data["item"] = self.Canvas1.find_closest(0, event.y)[0] - 1
                        self.Scrolledtreeview1.delete(self.Scrolledtreeview1.selection()[0])

        # Move token while inside canvas bounds
        if event.x > tree_width and self._drag_data["item"] and \
           event.x < self.Canvas1.winfo_width() + tree_width and \
           event.y < self.Canvas1.winfo_height() and event.y > 0:
            delta_x = event.x - self._drag_data["x"]
            delta_y = event.y - self._drag_data["y"]
            self.move_token(self._drag_data["item"], delta_x, delta_y)

        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

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

# working sample from https://developers.google.com/tasks/quickstart/python
# reference https://developers.google.com/tasks/reference/rest/v1/tasks/update
#   pip3 install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

from __future__ import print_function
import os
import re
import logging

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logging.basicConfig(format='%(name)-8s: %(asctime)-10s %(levelname)-6s %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SEPARATOR_TITLE = "----- above ^^^ prioritized -----"

# Single compact token, e.g. [x=788,y=191,est=0.5,progress=69]
RE_BLOCK = re.compile(r'\[([^\]]*)\]')

def _parse_notes_map(notes: str):
    """
    Parse the first [key=value,...] block into a dict.
    Returns ({k:v as strings}, start_idx, end_idx). If not found, returns ({}, -1, -1).
    """
    if not notes:
        return {}, -1, -1
    m = RE_BLOCK.search(notes)
    if not m:
        return {}, -1, -1
    body = m.group(1)
    kvs = {}
    for part in body.split(','):
        part = part.strip()
        if not part or '=' not in part:
            continue
        k, v = part.split('=', 1)
        kvs[k.strip()] = v.strip()
    return kvs, m.start(), m.end()

def _to_notes_block(kvs: dict):
    # keep order x,y,est,progress if present
    order = ['x', 'y', 'est', 'progress']
    parts = []
    for k in order:
        if k in kvs:
            parts.append(f"{k}={kvs[k]}")
    # include any other keys that may be present
    for k in kvs:
        if k not in order:
            parts.append(f"{k}={kvs[k]}")
    return "[" + ",".join(parts) + "]"

def _read_xy_est_progress(notes: str):
    """
    Return ((x,y) or None, est or None, progress or None) parsed from first bracket block.
    """
    kvs, _, _ = _parse_notes_map(notes or "")
    x = kvs.get('x'); y = kvs.get('y')
    est = kvs.get('est'); prog = kvs.get('progress')
    coords = None
    if x is not None and y is not None:
        try:
            coords = (int(float(x)), int(float(y)))
        except Exception:
            coords = None
    est_val = None
    if est is not None:
        try:
            est_val = float(est)
        except Exception:
            est_val = None
    prog_val = None
    if prog is not None:
        try:
            prog_i = int(float(prog))
            prog_val = max(0, min(100, prog_i))
        except Exception:
            prog_val = None
    return coords, est_val, prog_val

def _write_xy_est_progress(notes: str, x=None, y=None, est=None, progress=None):
    """
    Insert or update the single bracket block with any provided values.
    Unspecified fields remain as-is if present.
    """
    kvs, s, e = _parse_notes_map(notes or "")
    if s == -1:
        kvs = {}
        prefix = (notes or "")
        if prefix and not prefix.endswith("\n"):
            prefix = prefix + "\n\n"
    else:
        prefix = (notes or "")[:s]
        suffix = (notes or "")[e:]
        # we’ll rebuild block and keep prefix+suffix
        if prefix and not prefix.endswith("\n"):
            prefix = prefix + "\n\n"
        # (no need to include suffix; we’ll append it back below)

    if x is not None:
        kvs['x'] = str(int(x))
    if y is not None:
        kvs['y'] = str(int(y))
    if est is not None:
        kvs['est'] = f"{float(est):g}"
    if progress is not None:
        kvs['progress'] = str(int(progress))

    block = _to_notes_block(kvs)
    if s == -1:
        return (prefix + block).strip()
    else:
        return (prefix + block + suffix).strip()

class GoogleTasks:

    def __init__(self):
        SCOPES = ['https://www.googleapis.com/auth/tasks']

        creds = None
        here = os.path.dirname(os.path.abspath(__file__))
        creds_path = os.path.join(here, 'credentials.json')
        token_path  = os.path.join(here, 'token.json')

        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
                logger.debug(f"Loaded token.json. Valid? {getattr(creds, 'valid', False)}")
            except Exception as e:
                logger.warning(f"Failed to load token.json: {e}")
                creds = None

        if not creds or not getattr(creds, 'valid', False):
            logger.debug(f"Token expired? {getattr(creds, 'expired', 'n/a (no creds)')}")
            if creds and getattr(creds, 'expired', False) and getattr(creds, 'refresh_token', None):
                try:
                    creds.refresh(Request())
                    logger.info("Refreshed access token.")
                except Exception as e:
                    logger.warning(f"Refresh token failed: {e}")
                    creds = None

            if not creds:
                if not os.path.exists(creds_path):
                    raise FileNotFoundError(
                        "credentials.json not found. Download a Desktop App OAuth client from "
                        "Google Cloud Console and place it next to tasks_api.py."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                try:
                    creds = flow.run_local_server(port=0)
                except Exception:
                    print("Falling back to console auth...")
                    creds = flow.run_console()

            try:
                with open(token_path, 'w') as token_file:
                    token_file.write(creds.to_json())
            except Exception as e:
                logger.warning(f"Could not write token.json: {e}")

        self.service = build('tasks', 'v1', credentials=creds)
        self.token_list = {}
        self.separators = {}
        self.user_tasks = {}

    def getTasks(self, taskList=None):
        """
        Active tasks only, lexicographic 'position' order.
        Returns: { list_title: { position_str: task_obj } }
        """
        self.user_tasks = {}
        results = self.service.tasklists().list(maxResults=100).execute()
        task_lists = results.get('items', [])

        for task_list in task_lists:
            if taskList and task_list['title'] != taskList:
                print(f"Skipping task list {task_list['title']}")
                continue

            self.user_tasks[task_list['title']] = {}

            nextPageToken = ""
            while True:
                result = self.service.tasks().list(
                    tasklist=task_list['id'],
                    maxResults=100,
                    pageToken=nextPageToken,
                    showCompleted=False,
                    showHidden=False,
                    showDeleted=False,
                ).execute()

                tasks = result.get('items', [])
                for task in tasks:
                    task['task_list_id'] = task_list['id']

                    if task.get('title') == SEPARATOR_TITLE:
                        self.separators[task_list['id']] = task
                        continue

                    coords, est, prog = _read_xy_est_progress(task.get('notes') or "")
                    if coords:
                        task['coordinates'] = coords
                    if est is not None:
                        task['time_estimate'] = est
                    if prog is not None:
                        task['progress'] = prog

                    pos_key = task.get('position', '')
                    while pos_key in self.user_tasks[task_list['title']]:
                        pos_key += "_"
                    self.user_tasks[task_list['title']][pos_key] = task

                nextPageToken = result.get('nextPageToken', [])
                if not nextPageToken:
                    break

        return self.user_tasks

    def setTokenId(self, token_id, task):
        self.token_list[token_id] = task

    def getTaskByTokenId(self, token_id: int):
        t = self.token_list.get(token_id)
        if t:
            return t
        t = self.token_list.get(token_id - 1)
        if t:
            return t
        return self.token_list.get(token_id + 1)

    def weightBasedOnCoordinates(self, e):
        y = e.get('coordinates', (0, 5000))[1]
        x = e.get('coordinates', (0, 0))[0]
        importance = 5000 - int(y)
        urgency = int(x)
        return importance * 10 + urgency

    def moveTaskToTheTop(self, task):
        return self.service.tasks().move(
            tasklist=task['task_list_id'], task=task['id']
        ).execute()

    def insertNewTaskAtTheTop(self, list_id, task):
        return self.service.tasks().insert(tasklist=list_id, body=task).execute()

    def sortPrioritizedTasks(self, list_id):
        unique_by_id = {}
        for t in self.token_list.values():
            if t.get('task_list_id') == list_id and t.get('coordinates'):
                unique_by_id[t['id']] = t

        prioritized_tasks = sorted(unique_by_id.values(), key=self.weightBasedOnCoordinates)

        separator_task = self.separators.get(list_id)
        if separator_task:
            self.moveTaskToTheTop(separator_task)
        else:
            new_task = {
                'kind': 'tasks#task',
                'title': SEPARATOR_TITLE,
                'status': 'needsAction',
            }
            rv = self.insertNewTaskAtTheTop(list_id, new_task)
            rv['task_list_id'] = list_id
            self.separators[list_id] = rv

        for task in prioritized_tasks:
            print(f"Moving '{task['title']}' to the top")
            self.moveTaskToTheTop(task)

    def _persist(self, task):
        self.service.tasks().update(
            tasklist=task['task_list_id'], task=task['id'], body=task
        ).execute()

    # NEW: unified updater used by the UI
    def updateTask(self, task, x=None, y=None, t_hours=None, progress=None, resort=True):
        """
        Update any subset of (x,y,time_estimate,progress) and persist to API.
        Stores as a SINGLE bracket: [x=..,y=..,est=..,progress=..]
        """
        notes = task.get('notes') or ""
        coords = task.get('coordinates', (None, None))
        cur_x, cur_y = coords

        if x is not None:
            cur_x = max(0, int(x))
        if y is not None:
            cur_y = max(0, int(y))
        if cur_x is not None and cur_y is not None:
            task['coordinates'] = (cur_x, cur_y)

        if t_hours is not None:
            try:
                task['time_estimate'] = float(t_hours)
            except Exception:
                pass

        if progress is not None:
            try:
                task['progress'] = max(0, min(100, int(progress)))
            except Exception:
                pass

        notes = _write_xy_est_progress(
            notes,
            x=cur_x if cur_x is not None else None,
            y=cur_y if cur_y is not None else None,
            est=task.get('time_estimate', None) if t_hours is not None else None,
            progress=task.get('progress', None) if progress is not None else None
        )
        task['notes'] = notes

        self._persist(task)

        if resort and (x is not None or y is not None):
            self.sortPrioritizedTasks(task['task_list_id'])

    # Back-compat alias for coords-only updates
    def updateTaskCoodinates(self, task, x, y):
        print(f"Updating list {task['task_list_id']}, task {task['id']} with x={x}, y={y}")
        self.updateTask(task, x=x, y=y, resort=True)

# ========
# block that walks all your task lists and prints every task (including completed & hidden) with useful details
# This includes completed and hidden tasks (showCompleted=True, showHidden=True).
# If you want only active tasks, set those to False.


if __name__ == "__main__":
    import sys
    from datetime import datetime

    gt = GoogleTasks()
    svc = gt.service

    def iter_tasklists():
        """Yield all task lists (handles pagination)."""
        token = None
        while True:
            resp = svc.tasklists().list(maxResults=100, pageToken=token).execute()
            for tl in resp.get("items", []):
                yield tl
            token = resp.get("nextPageToken")
            if not token:
                break

    def iter_tasks(list_id):
        """Yield all tasks in a list (handles pagination). Includes completed & hidden."""
        token = None
        while True:
            resp = svc.tasks().list(
                tasklist=list_id,
                maxResults=100,
                pageToken=token,
                showCompleted=True, #
                showHidden=True, #
                showDeleted=False,
            ).execute()
            for t in resp.get("items", []):
                yield t
            token = resp.get("nextPageToken")
            if not token:
                break

    total = 0
    for tl in iter_tasklists():
        list_title = tl.get("title", "<untitled>")
        list_id = tl.get("id")
        print(f"\n=== Task list: {list_title} ({list_id}) ===")

        for t in iter_tasks(list_id):
            total += 1
            title = t.get("title", "<no title>")
            notes = (t.get("notes") or "").strip()

            # Parse your compact notes block to expose coordinates/est/progress if present
            coords, est, prog = _read_xy_est_progress(notes)

            print(f"- {title}")
            # Core metadata
            for k in ("status", "due", "completed", "updated", "position", "parent"):
                v = t.get(k)
                if v:
                    print(f"    {k}: {v}")

            # Parsed fields from the notes block
            if coords:
                print(f"    coordinates: x={coords[0]}, y={coords[1]}")
            if est is not None:
                print(f"    time_estimate(h): {est}")
            if prog is not None:
                print(f"    progress(%): {prog}")

            # Raw notes (kept last for readability)
            if notes:
                print("    notes:")
                # indent multi-line notes nicely
                for line in notes.splitlines():
                    print(f"        {line}")

            # Any attached links
            links = t.get("links") or []
            for link in links:
                desc = link.get("description") or ""
                href = link.get("link") or ""
                typ  = link.get("type") or ""
                print(f"    link: {desc} [{typ}] -> {href}")

            # Show the task's id last (handy for scripting)
            print(f"    id: {t.get('id')}")

    print(f"\nTotal tasks listed: {total}")

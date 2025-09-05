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

                    # parse coordinates (store as ints)
                    task_notes = task.get('notes')
                    if task_notes:
                        coords = re.findall(
                            r'.*\[x=([0-9]+),y=([0-9]+)\].*',
                            task_notes,
                            re.MULTILINE | re.DOTALL
                        )
                        if coords:
                            try:
                                task['coordinates'] = (int(coords[0][0]), int(coords[0][1]))
                            except Exception:
                                pass

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
        """
        Be tolerant to different canvas item ids:
        - Return by exact key if present.
        - Otherwise try neighbors (old odd/even pairing logic).
        """
        t = self.token_list.get(token_id)
        if t:
            return t
        t = self.token_list.get(token_id - 1)
        if t:
            return t
        return self.token_list.get(token_id + 1)


    def weightBasedOnCoordinates(self, e):
        importance = 5000 - int(e['coordinates'][1])
        urgency = int(e['coordinates'][0])
        return importance * 10 + urgency


    def moveTaskToTheTop(self, task):
        return self.service.tasks().move(
            tasklist=task['task_list_id'], task=task['id']
        ).execute()

    def insertNewTaskAtTheTop(self, list_id, task):
        return self.service.tasks().insert(tasklist=list_id, body=task).execute()


    def sortPrioritizedTasks(self, list_id):
        # Deduplicate tasks by their Google Tasks id first, then sort
        unique_by_id = {}
        for t in self.token_list.values():
            # Only keep tasks for this list
            if t.get('task_list_id') == list_id:
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
            return_value = self.insertNewTaskAtTheTop(list_id, new_task)
            return_value['task_list_id'] = list_id
            self.separators[list_id] = return_value

        for task in prioritized_tasks:
            print(f"Moving '{task['title']}' to the top")
            self.moveTaskToTheTop(task)


    def updateTaskCoodinates(self, task, x, y):
        if x < 0: x = 0
        if y < 0: y = 0
        print(f"Updating list {task['task_list_id']}, task {task['id']} with x={x}, y={y}")
        task['coordinates'] = (int(x), int(y))
        notes = task.get('notes')
        new_coords = f"[x={int(x)},y={int(y)}]"
        if notes:
            coords = re.findall(
                r'.*\[x=([0-9]+),y=([0-9]+)\].*',
                task['notes'],
                re.MULTILINE | re.DOTALL
            )
            if coords:
                current_coords = f"[x={coords[0][0]},y={coords[0][1]}]"
                new_notes = notes.replace(current_coords, new_coords)
            else:
                new_notes = f"{notes}\n\n{new_coords}"
        else:
            new_notes = f"\n\n{new_coords}"
        task['notes'] = new_notes

        # persist to API
        self.service.tasks().update(
            tasklist=task['task_list_id'], task=task['id'], body=task
        ).execute()

        # resort within list
        self.sortPrioritizedTasks(task['task_list_id'])


if __name__ == '__main__':
    gt = GoogleTasks()
    tasks = gt.getTasks()
    for k in tasks.keys():
        print(f"{k} has {len(tasks[k])} tasks (active only)")

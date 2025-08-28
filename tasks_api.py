# working sample from https://developers.google.com/tasks/quickstart/python
# reference https://developers.google.com/tasks/reference/rest/v1/tasks/update
#   pip3 install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

from __future__ import print_function
import os.path
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
        # If modifying these scopes, delete the file token.json.
        SCOPES = ['https://www.googleapis.com/auth/tasks']  # use tasks.readonly for read-only

        creds = None

        # Try to load existing token
        if os.path.exists('token.json'):
            try:
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
                logger.debug(f"Loaded token.json. Valid? {getattr(creds, 'valid', False)}")
            except Exception as e:
                logger.warning(f"Failed to load token.json: {e}")
                creds = None

        # If missing/invalid, refresh or re-auth
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
                if not os.path.exists('credentials.json'):
                    raise FileNotFoundError(
                        "credentials.json not found. Download a Desktop App OAuth client from "
                        "Google Cloud Console and place it next to tasks_api.py."
                    )
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                # Opens a browser window for consent and returns creds
                creds = flow.run_local_server(port=0)

            # Save the (new or refreshed) credentials
            try:
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                logger.warning(f"Could not write token.json: {e}")

        self.service = build('tasks', 'v1', credentials=creds)
        self.token_list = {}
        self.separators = {}
        self.user_tasks = {}

    # === get all users google tasks, add additional fields to them, and return the pointer ===

    def getTasks(self, taskList=None):
        self.user_tasks = {}
        results = self.service.tasklists().list(maxResults=100).execute()
        task_lists = results.get('items', [])
        for task_list in task_lists:
            # if task list name is passed, skip all the others
            if taskList and task_list['title'] != taskList:
                print(f"Skipping task list {task_list['title']}")
                continue

            self.user_tasks[task_list['title']] = {}

            # get tasks from the list using paging
            nextPageToken = ""
            while True:
                result = self.service.tasks().list(
                    tasklist=task_list['id'], maxResults=100, pageToken=nextPageToken
                ).execute()

                tasks = result.get('items', [])
                for task in tasks:
                    # only ingest the tasks that are active
                    if task.get('status') == 'needsAction':
                        task['task_list_id'] = task_list['id']
                        # check if the task is a separator
                        if task.get('title') == SEPARATOR_TITLE:
                            # assign it to a separate list
                            self.separators[task_list['id']] = task
                        else:  # normal task
                            # check if the notes field exists
                            task_notes = task.get('notes')
                            if task_notes:
                                # extract coordinates if present: [x=...,y=...]
                                coords = re.findall(
                                    r'.*\[x=([0-9]+),y=([0-9]+)\].*',
                                    task_notes,
                                    re.MULTILINE | re.DOTALL
                                )
                                if coords:
                                    task['coordinates'] = coords[0]
                            # position is a string; we sort by it as int
                            self.user_tasks[task_list['title']][int(task['position'])] = task

                # check if we've reached the end of results
                nextPageToken = result.get('nextPageToken', [])
                if not nextPageToken:
                    break

        return self.user_tasks

    # ===

    def setTokenId(self, token_id, task):
        # map Canvas token id to a task object
        self.token_list[token_id] = task

    def getTaskByTokenId(self, token_id: int):
        # each token consists of two items (oval + text). Normalize to the oval id.
        if (token_id % 2) == 0:
            token_id -= 1
        return self.token_list.get(token_id)

    def weightBasedOnCoordinates(self, e):
        # TODO: Replace 5000 with the actual canvas height if available dynamically
        importance = 5000 - int(e['coordinates'][1])
        urgency = int(e['coordinates'][0])
        # importance is given an order of magnitude higher weight than urgency
        return importance * 10 + urgency

    # ===

    def moveTaskToTheTop(self, task):
        return self.service.tasks().move(
            tasklist=task['task_list_id'], task=task['id']
        ).execute()
        # previous=previous_task_id could be used to put it under a specific task

    # ===

    def insertNewTaskAtTheTop(self, list_id, task):
        return self.service.tasks().insert(tasklist=list_id, body=task).execute()

    # ===

    def sortPrioritizedTasks(self, list_id):
        # self.token_list contains all tasks on the Canvas
        # sort them according to their coordinates (importance/urgency)
        prioritized_tasks = sorted(self.token_list.values(), key=self.weightBasedOnCoordinates)

        # for a given list_id add prioritized/unprioritized separator at the bottom
        separator_task = self.separators.get(list_id)
        if separator_task:
            self.moveTaskToTheTop(separator_task)
        else:  # create a new separator at the top
            new_task = {
                'kind': 'tasks#task',
                'title': SEPARATOR_TITLE,
                'status': 'needsAction',
            }
            return_value = self.insertNewTaskAtTheTop(list_id, new_task)
            return_value['task_list_id'] = list_id
            # remember it in the separator list for future refreshes
            self.separators[list_id] = return_value

        # move tasks (for this list) to the top in order
        for task in prioritized_tasks:
            if task['task_list_id'] == list_id:
                print(f"Moving '{task['title']}' to the top")
                self.moveTaskToTheTop(task)

    # === update task with new coordinates ===

    def updateTaskCoodinates(self, task, x, y):
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        print(f"Updating list {task['task_list_id']}, task {task['id']} with x={x}, y={y}")
        # update coordinates in the data structure
        task['coordinates'] = (str(x), str(y))
        # insert them in the notes, so that they are saved between reloads
        notes = task.get('notes')
        new_coords = f"[x={x},y={y}]"
        if notes:  # task already has notes
            coords = re.findall(
                r'.*\[x=([0-9]+),y=([0-9]+)\].*',
                task['notes'],
                re.MULTILINE | re.DOTALL
            )
            if coords:  # task already has coordinates
                current_coords = f"[x={coords[0][0]},y={coords[0][1]}]"
                new_notes = notes.replace(current_coords, new_coords)
            else:  # task didn't have coordinates, add them at the end
                new_notes = f"{notes}\n\n{new_coords}"
        else:  # task didn't have notes, add new notes with coordinates
            new_notes = f"\n\n{new_coords}"
        task['notes'] = new_notes

        # persist update
        self.service.tasks().update(
            tasklist=task['task_list_id'], task=task['id'], body=task
        ).execute()

        # re-order all the prioritized tasks according to the urgent/important algorithm
        self.sortPrioritizedTasks(task['task_list_id'])


if __name__ == '__main__':
    # Optional: quick smoke test for auth (lists tasklist titles)
    gt = GoogleTasks()
    tasks = gt.getTasks()
    for k in tasks.keys():
        print(f"{k} has {len(tasks[k])} tasks (active)")



# working sample from https://developers.google.com/tasks/quickstart/python
# referenc https://developers.google.com/tasks/reference/rest/v1/tasks/update
#   pip3 install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

from __future__ import print_function
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import re


class GoogleTasks:
  
  def __init__(self):
    # If modifying these scopes, delete the file token.json.
    SCOPES = ['https://www.googleapis.com/auth/tasks'] # tasks.readonly

    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
      creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
      if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
      else:
        flow = InstalledAppFlow.from_client_secrets_file(
          'credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
      with open('token.json', 'w') as token:
        token.write(creds.to_json())

    self.service = build('tasks', 'v1', credentials=creds)
    self.token_list = {}

  # === get all users google tasks, add additional fields to them, and return the pointer ==

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
        result = self.service.tasks().list(tasklist=task_list['id'], maxResults=100,
          pageToken=nextPageToken).execute()
      
        tasks = result.get('items', [])
        for task in tasks:
          # if the "notes" field contains coordinates, then extract them an populate the field
          coords=re.findall('.*\[x=([0-9]+),y=([0-9]+)\].*', task['notes'], re.MULTILINE|re.DOTALL)
          if coords:
            task['coordinates'] = coords[0]
          task['task_list_id'] = task_list['id']
          self.user_tasks[task_list['title']][int(task['position'])] = task

        # check if we've reached the end of results
        nextPageToken = result.get('nextPageToken', [])
        if not nextPageToken:
          break
        
    return self.user_tasks
    
    
  # ===
  def setTokenId(self, token_id, task):
    #print(f"Settings token {token_id}={task}")
    self.token_list[token_id] = task
  
  def getTaskByTokenId(self, token_id:int):
    if (token_id % 2) == 0:
      token_id -= 1
    return self.token_list.get(token_id)
  # === update task with new coordinates ==

  def updateTaskCoodinates(self, task, x, y):
    if x < 0:
      x = 0
    if y < 0:
      y = 0
    print(f"Updating list {task['task_list_id']}, task {task['id']} with x={x}, y={y}") # ['id']
    notes = task.get('notes')
    new_coords=f"[x={x},y={y}]"
    if notes: # task already has notes
      print("task already has notes")
      coords = re.findall('.*\[x=([0-9]+),y=([0-9]+)\].*', task['notes'], re.MULTILINE|re.DOTALL)
      if (coords): # task already has coordinates
        print("task already has coordinates {coords}")
        current_coords = f"[x={coords[0][0]},y={coords[0][1]}]"
        new_notes = notes.replace(current_coords, new_coords)
      else: # task didn't have coordinates, add them at the end
        print("task didn't have coordinates, adding them at the end")
        new_notes = f"{notes}\n\n{new_coords}"
    else: # task didn't have notes, add new notes with coordinates
      print("task didn't have notes, adding new notes with coordinates")
      new_notes = f"\n\n{new_coords}"
    
    task['notes'] = new_notes
    return self.service.tasks().update(tasklist=task['task_list_id'], task=task['id'], body=task).execute()
    
  # ===
  
    #result = service.tasks().move(tasklist='@default', task='taskID', parent='parentTaskID', previous='previousTaskID').execute()

    # Print the new values.
    #print result['parent']
    #print result['position']
    #tasks = 
    
  

if __name__ == '__main__':
  myTasks = getGoogleTasks()
  for key in myTasks.keys() :
    print (f"{key} has {len(myTasks[key])} tasks")

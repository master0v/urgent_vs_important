

# working sample from https://developers.google.com/tasks/quickstart/python
#   pip3 install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

from __future__ import print_function
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/tasks.readonly']

def getGoogleTasks(taskList=None):

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

  service = build('tasks', 'v1', credentials=creds)
  results = service.tasklists().list(maxResults=100).execute()
  
  user_tasks = {}
  
  task_lists = results.get('items', [])
  for task_list in task_lists:
    # if task list name is passed, skip all the others
    if taskList and task_list['title'] != taskList:
      print(f"Skipping task list {task_list['title']}")
      continue
      
    user_tasks[task_list['title']] = {}
    #print(task_list)
    #input("\n")
    
    # get tasks from the list using paging
    nextPageToken = ""
    while True:
      result = service.tasks().list(tasklist=task_list['id'], maxResults=100,
        pageToken=nextPageToken).execute()
      
      tasks = result.get('items', [])
      for task in tasks:
        user_tasks[task_list['title']][int(task['position'])] = task
        task_status = '📦' if (task['status'] == 'needsAction') else '✅'
        #print(f" {int(task['position'])}: {task['title']} {task_status}")
        #print(task)
        #input("\n")
      
      # check if we've reached the end of results
      nextPageToken = result.get('nextPageToken', [])
      if not nextPageToken:
        break
        
  return user_tasks


def updateGoogleTask(taskID, updatedValues):
      
  #result = service.tasks().move(tasklist='@default', task='taskID', parent='parentTaskID', previous='previousTaskID').execute()

  # Print the new values.
  #print result['parent']
  #print result['position']
  #tasks = 
  return
  

if __name__ == '__main__':
  myTasks = getGoogleTasks()
  for key in myTasks.keys() :
    print (f"{key} has {len(myTasks[key])} tasks")

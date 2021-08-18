# working sample from https://developers.google.com/tasks/quickstart/python

from __future__ import print_function
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/tasks.readonly']

def main():
  """Shows basic usage of the Tasks API.
  Prints the title and ID of the first 10 task lists.
  """
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

  # Call the Tasks API
  results = service.tasklists().list(maxResults=10).execute()
  task_lists = results.get('items', [])

  if not task_lists:
    print('No task lists found.')
  else:
    #print('Task lists:')
    for task_list in task_lists:
      print("")
      #print(task_list)
      #input("Press Enter to continue...")
      
      result = service.tasks().list(tasklist=task_list['id'], maxResults=1000).execute()
      tasks = result.get('items', [])
      if not tasks:
        print(' No tasks found in this list')
      else:
        print(f"{task_list['title']}, {len(tasks)}")
        print("=================")
        for task in tasks:
          task_status = '📦' if (task['status'] == 'needsAction') else '✅'
          print(f"{int(task['position'])}: {task['title']} {task_status}")
          #print(task)
          #input("\nPress Enter to continue...\n")
      
      
      #result = service.tasks().move(tasklist='@default', task='taskID', parent='parentTaskID', previous='previousTaskID').execute()

      # Print the new values.
      #print result['parent']
      #print result['position']
      #tasks = 

if __name__ == '__main__':
  main()
# urgent_vs_important
For users of Google Tasks: visualize all your tasks on the Urgent vs Important plot

in order to run on a mac ensure that python is installed using homebrew and has tkinter

```
brew info python
echo 'export PATH=/opt/homebrew/opt/python@3.12/libexec/bin:$PATH' >> ~/.zprofile
```

pip install -r requirements.txt

to get OAuth token:

1. go to
https://console.cloud.google.com/auth/clients/
2. under "Client Secrets" click "Download JSON"
3. rename/move to credentials.json in the application folder
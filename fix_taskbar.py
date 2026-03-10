import os, subprocess, sys
from pathlib import Path

appdata = os.environ['APPDATA']
taskbar_dir = Path(appdata) / 'Microsoft' / 'Internet Explorer' / 'Quick Launch' / 'User Pinned' / 'TaskBar'

print(f"Taskbar dir: {taskbar_dir}")
print(f"Exists: {taskbar_dir.exists()}")

if taskbar_dir.exists():
    print("\nTaskbar shortcuts:")
    for f in taskbar_dir.iterdir():
        print(f"  {f.name}")

    # Update any Zoom Transcriber shortcut
    python_exe = sys.executable
    lnk_args   = r'"C:\Users\kansal vibhor\zoom_transcriber\zoom_transcriber.py" --model medium --chunk 30'
    work_dir   = r'C:\Users\kansal vibhor\zoom_transcriber'
    icon       = r'C:\Users\kansal vibhor\zoom_transcriber\zoom_transcriber.ico'

    for lnk in taskbar_dir.glob("*Zoom*"):
        ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('{lnk}')
$s.TargetPath       = '{python_exe}'
$s.Arguments        = '{lnk_args}'
$s.WorkingDirectory = '{work_dir}'
$s.IconLocation     = '{icon},0'
$s.Save()
Write-Output 'OK'
"""
        r = subprocess.run(['powershell.exe', '-NoProfile', '-Command', ps],
                           capture_output=True, text=True)
        print(f"\n[{'OK' if 'OK' in r.stdout else 'ERR'}] Updated taskbar: {lnk.name}")
else:
    print("\nTaskbar shortcut folder not found.")
    print("Check if you're launching from run.bat or the desktop shortcut.")

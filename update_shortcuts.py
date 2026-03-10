import os, subprocess, sys
from pathlib import Path

python_w   = str(Path(sys.executable).parent / "pythonw.exe")
lnk_args   = r'"C:\Users\kansal vibhor\zoom_transcriber\tray_app.py" --model medium --chunk 30'
work_dir   = r'C:\Users\kansal vibhor\zoom_transcriber'
icon       = r'C:\Users\kansal vibhor\zoom_transcriber\zoom_transcriber.ico'

appdata = os.environ['APPDATA']
shortcuts = [
    rf'{appdata}\Microsoft\Windows\Start Menu\Programs\Startup\Zoom Transcriber.lnk',
    rf'{appdata}\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Zoom Transcriber.lnk',
    r'C:\Users\kansal vibhor\OneDrive - The Boston Consulting Group, Inc\Desktop\Zoom Transcriber.lnk',
]

for lnk in shortcuts:
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('{lnk}')
$s.TargetPath       = '{python_w}'
$s.Arguments        = '{lnk_args}'
$s.WorkingDirectory = '{work_dir}'
$s.IconLocation     = '{icon},0'
$s.Save()
Write-Output 'OK'
"""
    r = subprocess.run(['powershell.exe', '-NoProfile', '-Command', ps],
                       capture_output=True, text=True)
    label = Path(lnk).parent.name
    print(f"[{'OK' if 'OK' in r.stdout else 'ERR'}] {label} — {Path(lnk).name}")
    if 'ERR' in r.stdout or r.returncode != 0:
        print("   ", r.stderr.strip()[:150])

print("\nDone. Launch from taskbar or desktop icon — no terminal window.")

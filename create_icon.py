"""
Creates a desktop shortcut + taskbar pin for Zoom Transcriber.
Run once: python create_icon.py
"""

import os
import sys
import struct
import subprocess
import zlib
from pathlib import Path

APP_DIR    = Path(__file__).parent.resolve()
APP_SCRIPT = APP_DIR / "zoom_transcriber.py"
ICON_FILE  = APP_DIR / "zoom_transcriber.ico"
PYTHON_EXE = Path(sys.executable)
# Use pythonw.exe so no console flashes, but we want output — use python.exe
# Actually keep python.exe so user sees live transcription in terminal
PYTHON_W   = PYTHON_EXE.parent / "python.exe"


# ── Build a simple microphone-themed .ico file in pure Python ─────────────────
def make_ico():
    """Write a 32x32 + 16x16 ICO with a simple mic icon (no Pillow needed)."""

    def rgba_to_bmp(pixels_rgba, size):
        """Convert RGBA pixel list to a BITMAPINFOHEADER + pixel data for ICO."""
        w, h = size, size
        # BITMAPINFOHEADER (40 bytes)
        bi_size       = 40
        bi_width      = w
        bi_height     = h * 2   # ICO BMP height = pixels + mask, doubled
        bi_planes     = 1
        bi_bit_count  = 32
        bi_compression = 0
        bi_size_image  = w * h * 4
        header = struct.pack(
            "<IiiHHIIiiII",
            bi_size, bi_width, bi_height, bi_planes, bi_bit_count,
            bi_compression, bi_size_image, 0, 0, 0, 0,
        )
        # Pixel data: BGRA, bottom-up
        rows = [pixels_rgba[y * w:(y + 1) * w] for y in range(h)]
        rows.reverse()
        pixel_bytes = b"".join(
            struct.pack("BBBB", r, g, b, a)
            for row in rows
            for (r, g, b, a) in row
        )
        # AND mask (all transparent = 0), 4-byte aligned rows
        mask_row_bytes = ((w + 31) // 32) * 4
        and_mask = b"\x00" * (mask_row_bytes * h)
        return header + pixel_bytes + and_mask

    def draw_icon(size):
        """Draw a simple mic circle icon at given size."""
        px = [[(0, 0, 0, 0)] * size for _ in range(size)]

        BG   = (30, 120, 200, 255)   # blue background
        MIC  = (255, 255, 255, 255)  # white mic body
        RING = (255, 255, 255, 200)

        cx, cy = size // 2, size // 2
        r_bg = size // 2 - 1

        for y in range(size):
            for x in range(size):
                dx, dy = x - cx, y - cy
                dist = (dx * dx + dy * dy) ** 0.5

                # Blue circle background
                if dist <= r_bg:
                    px[y][x] = BG

                # Mic body — rounded rectangle
                mw = max(2, size // 6)
                mh = max(3, size // 4)
                mx1, mx2 = cx - mw, cx + mw
                my1, my2 = cy - mh, cy + mh // 3
                if mx1 <= x <= mx2 and my1 <= y <= my2 and dist <= r_bg:
                    corner = mw // 2
                    # Round top corners
                    if y <= my1 + corner:
                        if x <= mx1 + corner:
                            if (x - (mx1 + corner)) ** 2 + (y - (my1 + corner)) ** 2 > corner ** 2:
                                continue
                        elif x >= mx2 - corner:
                            if (x - (mx2 - corner)) ** 2 + (y - (my1 + corner)) ** 2 > corner ** 2:
                                continue
                    px[y][x] = MIC

                # Arc / stand below mic
                r_out = size // 3
                r_in  = r_out - max(1, size // 12)
                if dist <= r_bg:
                    arc_y = cy + max(1, size // 12)
                    if y >= cy and y <= arc_y + r_out // 2:
                        if r_in <= dist <= r_out and x >= cx - r_out and x <= cx + r_out:
                            px[y][x] = RING

                # Stem at bottom
                stem_w = max(1, size // 16)
                stem_y1 = cy + r_out // 2
                stem_y2 = stem_y1 + max(1, size // 8)
                if stem_y1 <= y <= stem_y2 and abs(x - cx) <= stem_w and dist <= r_bg:
                    px[y][x] = RING

                # Base line
                base_w = size // 5
                base_y = stem_y2
                if y == base_y and abs(x - cx) <= base_w and dist <= r_bg:
                    px[y][x] = RING

        flat = [pix for row in px for pix in row]
        return flat

    images = []
    for sz in (32, 16):
        pixels = draw_icon(sz)
        bmp    = rgba_to_bmp(pixels, sz)
        images.append((sz, bmp))

    # ICO file layout
    # Header: 6 bytes
    # Directory entries: 16 bytes each
    # Image data
    num = len(images)
    header = struct.pack("<HHH", 0, 1, num)   # reserved, type=1 (ICO), count
    dir_offset = 6 + num * 16
    entries = b""
    data    = b""
    for (sz, bmp) in images:
        entries += struct.pack(
            "<BBBBHHII",
            sz, sz,          # width, height
            0, 0,            # color count, reserved
            1, 32,           # planes, bit count
            len(bmp),        # size of image data
            dir_offset + len(data),  # offset
        )
        data += bmp

    ico_bytes = header + entries + data
    ICON_FILE.write_bytes(ico_bytes)
    print(f"[OK] Icon created: {ICON_FILE}")


# ── Create desktop shortcut (.lnk) via PowerShell ─────────────────────────────
def create_shortcut():
    import subprocess as _sp
    _r = _sp.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True,
    )
    desktop = Path(_r.stdout.strip())
    lnk_path   = desktop / "Zoom Transcriber.lnk"
    icon_path  = str(ICON_FILE).replace("\\", "\\\\")
    # Use pythonw.exe (no console window) pointing to tray_app.py
    tray_script = str(APP_DIR / "tray_app.py").replace("\\", "\\\\")
    pythonw     = str(PYTHON_W.parent / "pythonw.exe").replace("\\", "\\\\")
    work_dir    = str(APP_DIR).replace("\\", "\\\\")
    lnk_str     = str(lnk_path).replace("\\", "\\\\")

    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut("{lnk_str}")
$s.TargetPath       = "{pythonw}"
$s.Arguments        = '"{tray_script}" --model medium --chunk 30'
$s.WorkingDirectory = "{work_dir}"
$s.IconLocation     = "{icon_path},0"
$s.Description      = "Auto-transcribe Zoom and Teams meetings with Whisper"
$s.WindowStyle      = 1
$s.Save()
Write-Host "Shortcut created: {lnk_str}"
"""

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"[OK] Desktop shortcut created: {lnk_path}")
    else:
        print(f"[ERR] Shortcut creation failed:\n{result.stderr}")
    return lnk_path


# ── Try to pin shortcut to taskbar ────────────────────────────────────────────
def pin_to_taskbar(lnk_path: Path):
    lnk_str = str(lnk_path).replace("\\", "\\\\")
    ps = f"""
$path   = "{lnk_str}"
$shell  = New-Object -ComObject Shell.Application
$folder = $shell.Namespace((Split-Path $path))
$item   = $folder.ParseName((Split-Path $path -Leaf))
$verb   = $item.Verbs() | Where-Object {{ $_.Name -match 'pin.*task|taskbar' }}
if ($verb) {{
    $verb.DoIt()
    Write-Host "Pinned to taskbar."
}} else {{
    Write-Host "SKIP: Pin-to-taskbar verb not available on this Windows version."
}}
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    msg = (result.stdout + result.stderr).strip()
    if "Pinned" in msg:
        print("[OK] Pinned to taskbar!")
    elif "SKIP" in msg:
        print("[INFO] Windows 11 blocks automatic taskbar pinning.")
        print("       To pin manually: right-click the desktop shortcut -> 'Pin to taskbar'")
    else:
        print(f"[INFO] {msg}")


if __name__ == "__main__":
    print("Setting up Zoom Transcriber shortcut...\n")
    make_ico()
    lnk = create_shortcut()
    pin_to_taskbar(lnk)
    print("\nDone.")

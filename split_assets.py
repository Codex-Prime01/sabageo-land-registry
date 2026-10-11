"""
Run this in your project folder (next to index.html and main.py):

    python split_assets.py

It moves the CSS and JavaScript out of index.html into:
    static/style.css
    static/app.js
fixes the links in index.html, and tells main.py to serve the static folder.
Your original files are saved as index.before-split.html and main.before-split.py
"""
import re
import shutil
import sys
from pathlib import Path

html_path = Path("index.html")
main_path = Path("main.py")
if not html_path.exists():
    sys.exit("Cannot find index.html here. Run this from your project folder.")

s = html_path.read_text(encoding="utf-8")

style = re.search(r"<style>(.*?)</style>", s, re.S)
script = re.search(r"<script>(.*?)</script>", s, re.S)  # the one without src=
if not style or not script:
    sys.exit("No inline <style> or <script> found. Already split? Nothing changed.")

shutil.copy(html_path, "index.before-split.html")
Path("static").mkdir(exist_ok=True)
Path("static/style.css").write_text(style.group(1).strip() + "\n", encoding="utf-8")
Path("static/app.js").write_text(script.group(1).strip() + "\n", encoding="utf-8")

# remove any old, broken link to style.css
s = re.sub(r'\s*<link\s+rel="stylesheet"\s+href="style\.css"\s*/?>', "", s)
s = s.replace(style.group(0), '<link rel="stylesheet" href="/static/style.css" />', 1)
s = s.replace(script.group(0), '<script src="/static/app.js"></script>', 1)
html_path.write_text(s, encoding="utf-8")

MOUNT = 'app.mount("/static", StaticFiles(directory="static"), name="static")'
if main_path.exists():
    m = main_path.read_text(encoding="utf-8")
    if MOUNT in m:
        print("main.py already serves /static.")
    elif 'app.mount("/uploads"' in m and "StaticFiles" in m:
        shutil.copy(main_path, "main.before-split.py")
        lines = m.split("\n")
        for i, line in enumerate(lines):
            if 'app.mount("/uploads"' in line:
                lines.insert(i + 1, MOUNT)
                break
        main_path.write_text("\n".join(lines), encoding="utf-8")
        print("main.py updated.")
    else:
        print("\nAdd this line to main.py yourself, under the line that mounts /uploads:")
        print("    " + MOUNT)
        print("(and make sure it has: from fastapi.staticfiles import StaticFiles)")
else:
    print("main.py not found here. Add this line to it, under the /uploads mount:")
    print("    " + MOUNT)

print("\nDone. Restart the server, then refresh with Ctrl + F5.")
import os
import time
from flask import Flask, render_template, request, url_for, send_from_directory
from weasyprint import HTML
import json, re
import datetime

PDF_FOLDER = "pdf_cache"
PDF_LIFETIME = 6 * 60 * 60  # 6 hours in seconds

def cleanup_old_pdfs():
    folder = "pdf_cache"
    os.makedirs(folder, exist_ok=True)  # ✅ Make sure it exists
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(hours=6)

    for fname in os.listdir(folder):
        fpath = os.path.join(folder, fname)
        if os.path.isfile(fpath):
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)



app = Flask(__name__)

# Load JSON data
with open("spirits.json") as f:
    SECTIONS = json.load(f)

def extract_bar_num(backbar_label: str) -> int | None:
    m = re.search(r'(\d+)', backbar_label)
    return int(m.group(1)) if m else None

def is_au(spirit: str) -> bool:
    return spirit.startswith("AU ")

def get_par(section: str, backbar_label: str, spirit: str) -> int:
    """
    PAR rules from our earlier setup:
      • Absolut Vanilla = 2 on every backbar
      • Bottom Bar (Downstairs): default 4
          - On backbar 4: Corky's Raspberry/Cherry/Apple = 3
      • Top Bar:
          - Backbar 5: default 3
              exceptions = 5 for AU*, Smirnoff Raspberry, Smirnoff Mango and Passionfruit, Archers, Malibu
              exceptions = 10 for Captain Morgans Spiced, Smirnoff Red
          - Backbar 6A: default 5
    """
    if spirit == "Absolut Vanilla":
        return 2

    n = extract_bar_num(backbar_label)

    # Bottom bar defaults (Downstairs)
    if section in ("Bottom Bar", "Downstairs"):
        if n == 4 and spirit in ("Corky's Raspberry", "Corky's Cherry", "Corky's Apple"):
            return 3
        return 4

    # Top bar rules
    if section == "Top Bar":
        if n == 5:
            if spirit in ("Captain Morgans Spiced", "Smirnoff Red"):
                return 10
            if is_au(spirit) or spirit in ("Smirnoff Raspberry", "Smirnoff Mango and Passionfruit", "Archers", "Malibu"):
                return 5
            return 3
        if n == 6:
            return 5

    # Sensible fallback
    return 4

@app.route("/")
def index():
    return render_template("index.html", sections=SECTIONS.keys())

@app.route("/count/<section_name>")
def count(section_name):
    if section_name not in SECTIONS:
        return "Section not found", 404
    return render_template("countpage.html", section_name=section_name, items=SECTIONS[section_name])

@app.route("/process", methods=["POST"])
def process():
    form = request.form

    # --- Your NEED calculation logic here ---
    needed_per_bar = {}
    for key, value in form.items():
        if not value.strip():
            continue
        try:
            section, backbar_label, spirit = key.split("__")
        except ValueError:
            continue
        bar_num = extract_bar_num(backbar_label)
        if bar_num is None:
            continue
        have = int(value)
        par = get_par(section, backbar_label, spirit)
        need = max(par - have, 0)
        needed_per_bar.setdefault((section, bar_num), {})[spirit] = need

    # Pair results (1&2, 3&4, etc.)
    paired_needed = {}
    for (section, bar_num), spirits in needed_per_bar.items():
        pair_label = f"{bar_num} & {bar_num+1}" if bar_num % 2 == 1 else f"{bar_num-1} & {bar_num}"
        key = (section, pair_label)
        bucket = paired_needed.setdefault(key, {})
        for spirit, need in spirits.items():
            bucket[spirit] = bucket.get(spirit, 0) + need

    # Convert NEED totals into boxes & bottles
    paired_display = {}
    for key, spirits in paired_needed.items():
        paired_display[key] = {}
        for spirit, total_need in spirits.items():
            boxes = total_need // 6
            bottles = total_need % 6
            paired_display[key][spirit] = {
                "boxes": boxes,
                "bottles": bottles
            }

    # --- Cleanup old PDFs ---
    cleanup_old_pdfs()

    # Create folder if it doesn't exist
    os.makedirs("pdf_cache", exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_filename = f"cellar_run_{timestamp}.pdf"
    pdf_path = os.path.join("pdf_cache", pdf_filename)

    # First render HTML (so we can use it for both display & PDF)
    rendered_html = render_template(
        "results.html",
        results=needed_per_bar,
        pair_results=paired_display,
        pdf_url=None  # Prevents "View PDF" button in the PDF itself
    )

    # Create PDF from rendered HTML
    HTML(string=rendered_html).write_pdf(pdf_path)

    # Create URL for viewing PDF
    pdf_url = url_for('serve_pdf', filename=pdf_filename)

    # Render HTML for web with PDF link
    return render_template(
        "results.html",
        results=needed_per_bar,
        pair_results=paired_display,
        pdf_url=pdf_url
    )



@app.route("/pdf/<path:filename>")
def serve_pdf(filename):
    return send_from_directory("pdf_cache", filename)

if __name__ == "__main__":
    app.run(debug=True)

"""Use your own (AI-generated) pictures for the hidden gem cards.

1. Save each picture in  static/gems/ai/  and name it after the place (see the list the
   script prints, for example  wat-phumin.png  or  ko-tao.jpg).  JPG, PNG and WEBP work.
2. Run:   python add_ai_photos.py
   It makes a 1200 px wide JPG of each picture in static/gems/ (replacing a Wikipedia photo of the
   same place) and writes the caption "Illustration: AI-generated image" in credits.json.
   (Install Pillow first for small files:  pip install pillow)
You can run it again whenever you add or replace a picture.
"""
import json
import os
import shutil

from fetch_gem_photos import CREDITS, HTML, OUT, gems, slug

SRC = os.path.join(OUT, "ai")
CAPTION = "Illustration: AI-generated image"
EXTS = (".jpg", ".jpeg", ".png", ".webp")


def main():
    try:
        from PIL import Image
    except ImportError:
        Image = None
        print("Pillow is not installed, so the pictures are copied as they are (they may be large).")
        print("For smaller files run:  pip install pillow\n")
    with open(HTML, encoding="utf-8") as f:
        items = gems(f.read())
    os.makedirs(SRC, exist_ok=True)
    credits = {}
    if os.path.exists(CREDITS):
        with open(CREDITS, encoding="utf-8") as f:
            credits = json.load(f)
    done = 0
    print("File names for the pictures in static/gems/ai/ :")
    for name, _ in items:
        found = None
        for ext in EXTS:
            p = os.path.join(SRC, slug(name) + ext)
            if os.path.exists(p):
                found = p
                break
        if not found:
            print("  missing  ", slug(name) + ".jpg", "   (" + name + ")")
            continue
        if Image:
            out_name = slug(name) + ".jpg"
            im = Image.open(found).convert("RGB")
            w = min(1200, im.width)
            im.resize((w, round(im.height * w / im.width))).save(
                os.path.join(OUT, out_name), "JPEG", quality=82, optimize=True)
        else:
            out_name = os.path.basename(found)
            shutil.copy(found, os.path.join(OUT, out_name))
        old = credits.get(name)
        if old and old.get("file") != out_name and os.path.exists(os.path.join(OUT, old.get("file", ""))):
            os.remove(os.path.join(OUT, old["file"]))  # the old Wikipedia photo has another file name
        credits[name] = {"file": out_name, "caption": CAPTION}
        done += 1
        print("  ok       ", out_name)
    with open(CREDITS, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1)
    print(f"\n{done} pictures added to credits.json")


if __name__ == "__main__":
    main()

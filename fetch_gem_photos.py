"""Download free-licensed photos for the hidden gems of Sawasdee Guide.

Run this ONCE on your own computer (it needs internet). No extra packages are needed:

    python fetch_gem_photos.py

For every place in GEMS (static/index.html) it looks for a photo in this order:
  1. the lead photo of the matching Wikipedia article,
  2. a search in all photos of Wikimedia Commons.
It only keeps photos with a free licence (CC BY, CC BY-SA, CC0, public domain; non-commercial
and non-free photos are skipped), downloads an 800 px version to static/gems/ and writes
static/gems/credits.json with the photographer and licence.
The web app shows the photo with that credit line. A place without a photo gets a coloured
banner with its icon instead.

Photos that were already downloaded are kept, so you can run it again.
Read the printed list: if a place got the wrong photo, delete that file from static/gems/,
set the right Wikipedia title in OVERRIDES below and run the script again.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "static", "index.html")
OUT = os.path.join(HERE, "static", "gems")
CREDITS = os.path.join(OUT, "credits.json")
WIKI = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = "SawasdeeGuideSchoolProject/1.0 (student project; github.com/JustXR/thai-trip-buddy)"

# gem name -> exact English Wikipedia article title (use when the automatic search picks the wrong one)
OVERRIDES = {
    "Wat Phumin": "Wat Phumin",
    "Mon Bridge": "Uttamanusorn Bridge",
    "Wat Phra That Pha Sorn Kaew": "Wat Phra That Pha Son Kaeo",
    "Koh Kood": "Ko Kut",
    "Ko Kradan": "Ko Kradan",
    "Ko Yao Noi": "Ko Yao District",
    "Ko Lipe": "Ko Lipe",
    "Ko Tao": "Ko Tao",
    "Koh Surin": "Surin Islands",
    "Talat Noi": "Talat Noi",
    "Bang Kachao": "Bang Kachao",
    "Sampheng Market (Talat Sampheng)": "Sampheng Lane",
    "Banthat Thong Road": "Banthat Thong Road",
    "Phu Chi Fa": "Phu Chi Fa Forest Park",
    "Naka Cave": "Phu Langka National Park",
    "Koh Phayam": "Ko Phayam",
    "Kudee Chin": "Kudi Chin",
    "Khao Sok Ratchaprapha Dam (Cheow Lan Lake)": "Ratchaprapha Dam",
}

GOOD_LICENSE = re.compile(r"\b(CC|PD|public domain)", re.I)
BAD_LICENSE = re.compile(r"-NC|-ND|fair use|non-free", re.I)


def get(url):
    """Download a URL. When Wikimedia says 'too many requests' (429), wait and try again."""
    for attempt in range(6):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            wait = int(e.headers.get("Retry-After", "0") or 0) or 20 * (attempt + 1)
            print(f"  (rate limited, waiting {wait} s)")
            time.sleep(wait)


def api(endpoint=WIKI, **params):
    params.update({"format": "json", "formatversion": "2"})
    return json.loads(get(endpoint + "?" + urllib.parse.urlencode(params)))


def gems(html):
    """Return [(name, place)] from the GEMS array."""
    block = re.search(r"const GEMS = \[(.*?)\n\];", html, re.S)
    if not block:
        sys.exit("Could not find GEMS in index.html")
    out = []
    for m in re.finditer(r'"place": "((?:[^"\\]|\\.)*)", "name": "((?:[^"\\]|\\.)*)"', block.group(1)):
        out.append((json.loads('"' + m.group(2) + '"'), json.loads('"' + m.group(1) + '"')))
    return out


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def licence_from(info):
    """Return the credit dict for an imageinfo entry, or None when the licence is not free."""
    meta = info.get("extmetadata", {})
    lic = strip_tags(meta.get("LicenseShortName", {}).get("value", ""))
    if not lic or BAD_LICENSE.search(lic) or not GOOD_LICENSE.search(lic):
        return None
    return {
        "author": strip_tags(meta.get("Artist", {}).get("value", "")) or "Unknown",
        "license": lic,
        "licenseUrl": strip_tags(meta.get("LicenseUrl", {}).get("value", "")),
        "source": info.get("descriptionurl", ""),
    }


def name_words(name):
    return [w.lower() for w in re.findall(r"[A-Za-z]{4,}", re.sub(r"\(.*?\)", "", name))]


def from_wikipedia(name, place):
    """Lead photo of the matching Wikipedia article: (label, thumbnail url, credit) or None."""
    if name in OVERRIDES:
        data = api(action="query", titles=OVERRIDES[name], redirects=1, prop="pageimages",
                   piprop="name|thumbnail", pithumbsize=800)
        pages = data.get("query", {}).get("pages", [])
    else:
        query = re.sub(r"\(.*?\)", "", name).strip() + " " + place + " Thailand"
        data = api(action="query", generator="search", gsrsearch=query, gsrlimit=3,
                   prop="pageimages", piprop="name|thumbnail", pithumbsize=800)
        words = name_words(name)  # only accept an article that shares a word with the place name
        pages = [p for p in sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
                 if any(w in p["title"].lower() for w in words)]
    for p in pages:
        if p.get("pageimage") and p.get("thumbnail"):
            time.sleep(1.5)
            info = api(action="query", titles="File:" + p["pageimage"], prop="imageinfo",
                       iiprop="extmetadata|url")
            ipages = info.get("query", {}).get("pages", [])
            if ipages and "imageinfo" in ipages[0]:
                lic = licence_from(ipages[0]["imageinfo"][0])
                if lic:
                    return "Wikipedia: " + p["title"], p["thumbnail"]["source"], lic
    return None


def from_commons(name, place):
    """Search all photos on Wikimedia Commons: (label, thumbnail url, credit) or None."""
    words = name_words(name)
    base = re.sub(r"\(.*?\)", "", name).strip()
    for query in (base, base + " " + place.replace("Province", "").strip()):
        data = api(COMMONS, action="query", generator="search", gsrnamespace=6, gsrsearch=query,
                   gsrlimit=10, prop="imageinfo", iiprop="url|mime|extmetadata", iiurlwidth=800)
        pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
        for p in pages:
            infos = p.get("imageinfo") or []
            if not infos or infos[0].get("mime") not in ("image/jpeg", "image/png"):
                continue
            title = p["title"]
            if not any(w in title.lower() for w in words):
                continue
            if re.search(r"map|logo|flag|diagram|poster", title, re.I):
                continue
            lic = licence_from(infos[0])
            if lic and infos[0].get("thumburl"):
                return "Commons: " + title, infos[0]["thumburl"], lic
        time.sleep(1.5)
    return None


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    with open(HTML, encoding="utf-8") as f:
        items = gems(f.read())
    print(f"{len(items)} places found")
    os.makedirs(OUT, exist_ok=True)
    credits = {}
    if os.path.exists(CREDITS):
        with open(CREDITS, encoding="utf-8") as f:
            credits = json.load(f)
    missing = []
    for name, place in items:
        old = credits.get(name)
        if old and os.path.exists(os.path.join(OUT, old["file"])):
            print("keep   ", name)
            continue
        try:
            found = from_wikipedia(name, place)
            if not found:
                time.sleep(1.5)
                found = from_commons(name, place)
            if not found:
                print("NO PHOTO", name, "(the card will show a banner with an icon)")
                missing.append(name)
                continue
            label, thumb, lic = found
            ext = os.path.splitext(urllib.parse.urlparse(thumb).path)[1].lower() or ".jpg"
            out_name = slug(name) + ext
            with open(os.path.join(OUT, out_name), "wb") as f:
                f.write(get(thumb))
            credits[name] = dict(lic, file=out_name, article=label)
            print("ok     ", name, "<-", label, "|", lic["license"])
        except Exception as e:  # network hiccup: skip, run again later
            print("ERROR  ", name, "|", e)
            missing.append(name)
        time.sleep(3)  # be polite to Wikimedia, it blocks fast requests
    with open(CREDITS, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1)
    print(f"Done: {len(credits)} photos, {len(missing)} without a photo")
    if missing:
        print("Run the script again to retry errors. Places without a photo get a banner with their icon.")


if __name__ == "__main__":
    main()

"""Generate Thai audio files for Sawasdee Guide.

Run this ONCE on your own computer (it needs internet):

    pip install edge-tts
    python generate_audio.py

It reads the phrases, spice phrases and dish names from static/index.html and
creates one .mp3 per spoken text in static/audio/, plus static/audio/manifest.json
which tells the web app which file belongs to which Thai text.

Voices (free Microsoft online voices):
  The script asks the service for its Thai voices and uses a female voice for
  "no ending" and "kha", and a male voice for "khrab" (if a male voice exists).

Files that already exist are kept, so you can simply run it again to finish any that failed.
After you add phrases or dishes, run it again to make the new files.
Use --dry-run to only count the files without generating anything.
"""
import asyncio
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "static", "index.html")
OUT = os.path.join(HERE, "static", "audio")

FEMALE = "F"  # replaced by a real Thai voice name at run time
MALE = "M"
RATE = "-10%"  # a little slower than normal so learners can follow


def collect(html):
    """Return {thai_text: voice} for every text the app can speak."""
    texts = {}

    def add(text, voice):
        texts.setdefault(text, voice)

    # Phrases: ["ไทย", "romanisation", "English", true?]  (true = it is a question)
    block = re.search(r"const PHRASES = \{(.*?)\n\};", html, re.S)
    if not block:
        sys.exit("Could not find PHRASES in index.html")
    phrases = re.findall(
        r'\[\s*"([^"]+)"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*(?:,\s*(true))?\s*\]', block.group(1)
    )
    # Spice phrases: th: "..."
    spice_block = re.search(r"const SPICE = \[(.*?)\];", html, re.S)
    spice = re.findall(r'th:\s*"([^"]+)"', spice_block.group(1)) if spice_block else []
    # Dishes: "th": "..."
    dish_block = re.search(r"const DISHES = \[(.*?)\n\];", html, re.S)
    dishes = re.findall(r'"th":\s*"([^"]+)"', dish_block.group(1)) if dish_block else []

    for th, is_q in phrases:
        add(th, FEMALE)
        add(th + "ครับ", MALE)
        add(th + ("คะ" if is_q else "ค่ะ"), FEMALE)
    for th in spice:
        add(th, FEMALE)
        add(th + "ครับ", MALE)
        add(th + "ค่ะ", FEMALE)
    for th in dishes:
        add(th, FEMALE)
    return texts


async def pick_voices(edge_tts):
    """Ask the service which Thai voices exist and choose a female and a male one."""
    voices = await edge_tts.list_voices()
    th = [v for v in voices if v.get("Locale", "").lower().startswith("th")]
    print("Thai voices found:", [v["ShortName"] + " (" + v["Gender"] + ")" for v in th])
    if not th:
        sys.exit("No Thai voices were returned by the service.")
    fem = next((v["ShortName"] for v in th if v["Gender"] == "Female"), th[0]["ShortName"])
    mal = next((v["ShortName"] for v in th if v["Gender"] == "Male"), fem)
    if mal == fem:
        print("Note: no male Thai voice found, the female voice is used for 'khrab' too.")
    return {FEMALE: fem, MALE: mal}


async def make(sem, edge_tts, text, voices, path):
    """voices = [preferred voice, other Thai voice]. Existing files are kept."""
    if os.path.exists(path) and os.path.getsize(path) > 500:
        return True
    async with sem:
        err = None
        # preferred voice (slower, then normal speed), then the other Thai voice
        plan = [(voices[0], True), (voices[0], False), (voices[1], True), (voices[1], False), (voices[1], False)]
        for voice, slow in plan:
            try:
                await edge_tts.Communicate(text, voice, **({"rate": RATE} if slow else {})).save(path)
                if os.path.exists(path) and os.path.getsize(path) > 500:
                    return True
            except Exception as e:  # network hiccup or text the voice cannot read: try the next option
                err = e
            await asyncio.sleep(1.5)
        print("FAILED:", text, "|", err)
        if os.path.exists(path):
            os.remove(path)
        return False


async def main():
    with open(HTML, encoding="utf-8") as f:
        texts = collect(f.read())
    print(f"{len(texts)} audio files needed")
    if "--dry-run" in sys.argv:
        return
    try:
        import edge_tts
    except ImportError:
        sys.exit("Please run first:  pip install edge-tts")

    voice_names = await pick_voices(edge_tts)
    os.makedirs(OUT, exist_ok=True)
    manifest = {}
    sem = asyncio.Semaphore(1)
    jobs = []
    for i, (text, voice) in enumerate(sorted(texts.items()), 1):
        name = f"t{i:03d}.mp3"
        manifest[text] = name
        path = os.path.join(OUT, name)
        spoken = text.replace(" / ", " ")  # "/" is not pronounced, leave it out of the speech
        other = voice_names[MALE if voice == FEMALE else FEMALE]
        jobs.append(make(sem, edge_tts, spoken, [voice_names[voice], other], path))
    results = await asyncio.gather(*jobs)
    failed = results.count(False)
    # drop manifest entries whose file failed
    manifest = {t: n for t, n in manifest.items() if os.path.exists(os.path.join(OUT, n))}
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=0)
    print(f"Done: {len(manifest)} files in static/audio/ ({failed} failed)")
    if failed:
        print("Some files failed. Run the script again, or tell Claude the FAILED lines above.")


if __name__ == "__main__":
    asyncio.run(main())

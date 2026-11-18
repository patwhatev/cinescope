"""Step through the watchlist one film at a time, opening an ok.ru search tab per film.

    python pipeline/okru_walk.py [--start N] [--csv profiles/<profile>/watchlist.csv]

Keys (in this terminal):  → next   ← previous   r reopen current   q quit
Tabs open in Chrome in the background so this terminal keeps keyboard focus --
put the two windows side by side.
"""
import argparse
import csv
import subprocess
import sys
import termios
import tty
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [(r["title"], r["year"]) for r in csv.DictReader(f)]


def open_tab(title, year):
    q = urllib.parse.quote_plus(f"{title} {year} ok.ru")
    subprocess.run(["open", "-g", "-a", "Google Chrome",
                    f"https://www.google.com/search?q={q}"], check=True)


def read_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch += sys.stdin.read(2)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="default: the active profile's watchlist.csv")
    ap.add_argument("--start", type=int, default=1, help="1-based position to start at")
    args = ap.parse_args()

    if args.csv is None:
        sys.path.insert(0, str(ROOT / "pipeline"))
        import common
        args.csv = common.paths().watchlist
    films = load(args.csv)
    i = max(0, min(args.start - 1, len(films) - 1))
    print("→ next   ← previous   r reopen   q quit\n")
    while True:
        title, year = films[i]
        print(f"[{i + 1}/{len(films)}] {title} ({year})")
        open_tab(title, year)
        while True:
            k = read_key()
            if k == "\x1b[C":
                if i + 1 >= len(films):
                    print("End of list.")
                    return
                i += 1
                break
            if k == "\x1b[D" and i > 0:
                i -= 1
                break
            if k == "r":
                break
            if k in ("q", "\x03"):
                print(f"Stopped at {i + 1}. Resume with --start {i + 1}")
                return


if __name__ == "__main__":
    main()

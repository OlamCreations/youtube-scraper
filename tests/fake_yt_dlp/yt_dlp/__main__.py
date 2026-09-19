"""Offline stand-in for yt-dlp, run as ``python -m yt_dlp`` by scripts/scrape.py.

The end-to-end test puts tests/fake_yt_dlp first on PYTHONPATH. scrape.py then
finds this package where it would find the real one after
``pip install -r requirements.txt``, and runs it the same way.

It answers the two calls scrape.py makes during a scrape, from the JSON file
named by the FAKE_YT_DLP_FIXTURE environment variable:

1. ``--flat-playlist --print id --print title --playlist-end N <channel url>``
   prints the listed videos. For a URL the fixture marks as failing, it fails
   in one of three ways: "404" exits 1 like yt-dlp on a 404, "silent" exits 0
   and prints nothing, and "cut short" prints the first video, then exits 1
   with an error.
2. ``--write-auto-sub --sub-lang L -o TEMPLATE <watch url>`` writes the caption
   file where yt-dlp would.

Each call is appended to the file named by FAKE_YT_DLP_LOG. Any other call
exits 2, so a new yt-dlp call in scrape.py cannot pass the test unnoticed.
Nothing here opens a network connection.
"""

import json
import os
import sys
from pathlib import Path

VALUE_OPTIONS = {"--print", "--playlist-end", "--sub-lang", "-o", "--encoding", "--cookies"}
FLAG_OPTIONS = {"--flat-playlist", "--write-auto-sub", "--skip-download", "--no-check-formats"}


def parse(argv):
    values, flags, positionals = {}, set(), []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in VALUE_OPTIONS and index + 1 < len(argv):
            values.setdefault(arg, []).append(argv[index + 1])
            index += 2
        elif arg in FLAG_OPTIONS:
            flags.add(arg)
            index += 1
        elif arg.startswith("-"):
            raise ValueError(f"option the fake does not know: {arg}")
        else:
            positionals.append(arg)
            index += 1
    if len(positionals) != 1:
        raise ValueError(f"expected one URL, got {positionals}")
    return values, flags, positionals[0]


def print_lines(lines, values, fixture):
    # The real yt-dlp encodes what it prints with --encoding when given, otherwise with
    # the output stream's encoding, and drops the characters that do not fit. Measured
    # with yt-dlp 2026.08.19 on a Windows pipe: cp1252, curly quotes as bytes 0x93 and
    # 0x94, emoji dropped. The fixture's pipe_encoding plays that stream on any system.
    encoding = values.get("--encoding", [None])[-1] or fixture["pipe_encoding"]
    sys.stdout.buffer.write("".join(line + "\n" for line in lines).encode(encoding, "ignore"))
    sys.stdout.flush()


def answer(argv, fixture):
    values, flags, url = parse(argv)
    if "--flat-playlist" in flags:
        failure = fixture["failing"].get(url)
        if failure == "404":
            sys.stderr.write(f"ERROR: [youtube:tab] {url}: HTTP Error 404: Not Found\n")
            return 1
        if failure == "silent":
            return 0
        if url not in fixture["listings"]:
            raise ValueError(f"listing for a URL the fixture does not have: {url}")
        limit = int(values["--playlist-end"][-1])
        fields = {"id": 0, "title": 1}
        lines = [entry[fields[name]] for entry in fixture["listings"][url][:limit] for name in values["--print"]]
        if failure == "cut short":
            print_lines(lines[:len(values["--print"])], values, fixture)
            sys.stderr.write(f"ERROR: [youtube:tab] {url}: fake listing cut short after one video\n")
            return 1
        if failure is not None:
            raise ValueError(f"failure the fake does not know: {failure}")
        print_lines(lines, values, fixture)
        return 0
    if "--write-auto-sub" in flags:
        video_id = url.split("watch?v=")[-1]
        if video_id not in fixture["captions"]:
            raise ValueError(f"captions for a video the fixture does not have: {video_id}")
        language = values["--sub-lang"][-1]
        target = Path(values["-o"][-1].replace("%(id)s", video_id) + f".{language}.vtt")
        target.write_text(fixture["captions"][video_id], encoding="utf-8")
        return 0
    raise ValueError("neither a listing nor a caption download")


def main():
    argv = sys.argv[1:]
    fixture = json.loads(Path(os.environ["FAKE_YT_DLP_FIXTURE"]).read_text(encoding="utf-8"))
    try:
        code = answer(argv, fixture)
        ok = True
    except ValueError as error:
        sys.stderr.write(f"fake yt-dlp: unrecognised call: {error}\n")
        code, ok = 2, False
    with open(os.environ["FAKE_YT_DLP_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"argv": argv, "ok": ok, "code": code}) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())

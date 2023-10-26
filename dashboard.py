import datetime
import glob
import itertools
import json
import os
import subprocess
import time
from pathlib import Path
from collections import Counter, defaultdict
from urllib.parse import quote

import fontbakery
import htmlmin
from packaging.version import parse as parse_version
from shaperglot.languages import Languages
from gflanguages import LoadScripts
import humanize
import tqdm
from gftools.push.servers import GFServers
from jinja2 import Environment, FileSystemLoader, select_autoescape

from googlefonts import GoogleFont

FONTBAKERY_BLACKLISTED = ["handjet", "adobeblank"]

BASE_URL = "https://simoncozens.github.io/gf-dashboard/"

TESTING = False

langs = Languages()
scripts = LoadScripts()
servers = GFServers.open(".gf_server_data.json")
servers.update()
gfpath = os.environ["GF_PATH"]
fonts = []
github_repo = os.environ.get("GITHUB_REPOSITORY", "")
repo_url = (
    os.environ.get("GITHUB_SERVER_URL", "https://github.com/") + "/" + github_repo
)

if os.path.exists("docs/versionhistory.json"):
    versionhistory = json.load(open("docs/versionhistory.json"))
else:
    versionhistory = {}

reports_this_session = 100


def fontbakery_needs_update(directory, last_update: datetime.datetime):
    global reports_this_session
    basedir = os.path.basename(directory)
    report_file = Path("docs/fontbakery-reports/" + basedir + "-report.json")
    if basedir in FONTBAKERY_BLACKLISTED:
        return False
    if report_file.exists():
        report = json.load(open(report_file))
        if "fontbakery_version" in report and parse_version(report["fontbakery_version"]) < parse_version(fontbakery.__version__):
            return True
    if report_file.exists() and report_file.stat().st_mtime > last_update.timestamp():
        return False
    reports_this_session -= 1
    return reports_this_session >= 0


def run_fontbakery(directory):
    inputs = glob.glob(directory + "/*")
    basedir = os.path.basename(directory)
    os.makedirs("docs/fontbakery-reports/" + basedir, exist_ok=True)
    json_file = Path(f"docs/fontbakery-reports/{basedir}-report.json")
    if json_file.exists():
        previous_json_time = json_file.stat().st_mtime
    else:
        previous_json_time = None
    args = [
        "fontbakery",
        f"check-googlefonts",
        "-F",
        "-l",
        "WARN",
        "--succinct",
        "--configuration",
        "fontbakery.yml",
        "--badges",
        f"docs/fontbakery-reports/{basedir}/",
        "--html",
        f"docs/fontbakery-reports/{basedir}-report.html",
        "--json",
        str(json_file),
        *inputs,
    ]
    args = " ".join(args)
    result = subprocess.run(args, shell=True, capture_output=True)
    if json_file.exists and (
        previous_json_time is None or json_file.stat().st_mtime > previous_json_time
    ):
        report = json.load(open(json_file))
        report["fontbakery_version"] = fontbakery.__version__
        json.dump(report, open(json_file, "w"))


def fontbakery_fails(basedir):
    fb_fails = []
    file = f"docs/fontbakery-reports/{basedir}-report.json"
    if not os.path.exists(file):
        return []
    report = json.load(open(file))
    failset = set()
    for section in report["sections"]:
        for check in section["checks"]:
            if check["result"] not in ["ERROR", "FAIL"]:
                continue
            if tuple(check["key"][0:2]) in failset:
                continue
            failset.add(tuple(check["key"][0:2]))
            fb_fails.append(
                {
                    "description": check["description"],
                    "result": check["result"],
                }
            )
    return fb_fails


def fontbakery_badges(basedir):
    fb_badges = []
    for badge in glob.glob(f"docs/fontbakery-reports/{basedir}/*.json"):
        if "Shaping" in badge:
            continue
        url = BASE_URL + "fontbakery-reports/" + basedir + "/" + os.path.basename(badge)
        fb_badges.append(f"https://img.shields.io/endpoint?url="+quote(url, safe=""))
    return fb_badges


def tidy_version(version):
    version = version.replace("Version ", "")
    version = version.split(";")[0].strip()
    return version


def rearrange_history(history):
    new_history = []
    for server, moves in history.items():
        # Ignore the first move
        for move in moves:
            if "1970-01-01" in move["date"]:
                continue
            new_history.append(
                {
                    "date": datetime.datetime.fromisoformat(move["date"]),
                    "version": move["version"],
                    "server": server,
                }
            )
    return sorted(new_history, key=lambda x: x["date"], reverse=True)


script_langs = defaultdict(set)
for lang in langs.keys():
    script_langs[langs[lang]["script"]].add(langs[lang]["name"])

def rearrange_languages(languages):
    supported_langs_by_script = defaultdict(set)
    report = []
    for lang in languages:
        lang = langs[lang]
        supported_langs_by_script[lang["script"]].add(lang["name"])
    for script, thislangs in supported_langs_by_script.items():
        expected = script_langs[script]
        percent = len(thislangs)/len(expected)*100
        result = ("%i%% (%i/%i) of languages using the %s script" %
            (percent, len(thislangs), len(expected), scripts[script].name))
        missing = expected - thislangs
        if len(missing) > 0 and len(missing) < 10:
            result += f" (Missing {'; '.join(missing)})"
        elif percent < 100 and len(thislangs) < 10:
            result += f" (Supports {'; '.join(thislangs)})"
        report.append(result)
    return report



for directory in tqdm.tqdm(glob.glob(gfpath + "/ofl/*")):
    if "noto" in directory:
        continue
    try:
        gf = GoogleFont(directory, gfpath)
    except Exception as e:
        print(e)
        continue

    if fontbakery_needs_update(directory, gf.last_updated):
        print("Running fontbakery on " + os.path.basename(directory))
        run_fontbakery(directory)

    gf.html_id = gf.directory.replace("/", "_")

    if gf.metadata.name not in versionhistory:
        versionhistory[gf.metadata.name] = {}

    for s in servers:
        if gf.metadata.name not in s.families:
            continue
        if s.name not in versionhistory[gf.metadata.name]:
            versionhistory[gf.metadata.name][s.name] = []
        current_version = s.families[gf.metadata.name].version
        versions = [x["version"] for x in versionhistory[gf.metadata.name][s.name]]
        if current_version not in versions:
            versionhistory[gf.metadata.name][s.name].append(
                {
                    "version": current_version,
                    "date": datetime.datetime.now().isoformat(),
                }
            )
    json.dump(versionhistory, open("docs/versionhistory.json", "w"), indent=2)

    gf.version_history = rearrange_history(versionhistory[gf.metadata.name])

    gf.server_versions = {
        s.name: s.families[gf.metadata.name].version
        for s in servers
        if s.families.get(gf.metadata.name)
    }
    if os.path.exists(
        "docs/fontbakery-reports/" + os.path.basename(directory) + "-report.html"
    ):
        gf.fontbakery_report = os.path.basename(directory) + "-report.html"
    gf.fb_badges = fontbakery_badges(os.path.basename(directory))
    gf.fb_fails = fontbakery_fails(os.path.basename(directory))
    gf.version_badges = [
        f"https://img.shields.io/badge/google/fonts-{tidy_version(gf.dev_version)}-green"
    ]
    color = "green"
    last_version = tidy_version(gf.dev_version)
    for s in servers:
        if gf.server_versions.get(s.name):
            version = tidy_version(gf.server_versions[s.name])
            if str(version) < str(last_version).strip():
                color = "orange"
            gf.version_badges.append(
                f"https://img.shields.io/badge/{s.name}-{version}-{color}"
            )
            last_version = version
    gf.build_badges = []
    if gf.seems_gfr:
        workflows = list(gf.upstream_gh.get_workflows())
        for workflow in workflows or []:
            runs = list(workflow.get_runs())
            if runs and len(runs) > 0:
                gf.build_badges.append(
                    f"https://img.shields.io/badge/{workflow.name}-{runs[0].conclusion}"
                )

    gf.languages = rearrange_languages(gf.supported_languages)
    # Prime the pump
    _ = gf.recent_commits
    _ = gf.recent_pulls
    _ = gf.releases

    classes = []
    if len(list(gf.open_pulls)):
        classes.append("openpr")
    if gf.new_releases_since_update:
        classes.append("newrelease")
    if "production" not in gf.server_versions or (
        gf.server_versions["production"] != gf.dev_version
        ):
        classes.append("inpipeline")
    gf.classes = " ".join(classes)
    # Downstream versions if noto
    fonts.append(gf)
    if TESTING and len(fonts) > 15:
        break
fonts = sorted(fonts, key=lambda x: x.metadata.name)


def ago(dt):
    return humanize.naturaldelta(
        datetime.datetime.now(datetime.timezone.utc)
        - dt.replace(tzinfo=datetime.timezone.utc)
    )


env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape())
env.filters["ago"] = ago
template = env.get_template("index.html")
html = template.render(fonts=fonts, BASE_URL=BASE_URL)
html = htmlmin.minify(html)
with open("docs/index.html", "w") as f:
    f.write(html)

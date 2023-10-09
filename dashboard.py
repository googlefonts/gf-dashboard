import sys
import os
import glob
import anybadge
import humanize
import json
import tqdm
import re
import github
import subprocess
from googlefonts import GoogleFont
from gftools.push.servers import GFServers
from jinja2 import Environment, FileSystemLoader, select_autoescape
import datetime
import itertools

TESTING = True

servers = GFServers.open(".gf_server_data.json")
servers.update()
gfpath = os.environ["GF_PATH"]
fonts = []
github_repo = os.environ.get("GITHUB_REPOSITORY", "")
repo_url = (
    os.environ.get("GITHUB_SERVER_URL", "https://github.com/") + "/" + github_repo
)

reports_this_session = 10


def fontbakery_needs_update(directory, last_update: datetime.datetime):
    global reports_this_session
    basedir = os.path.basename(directory)
    report_file = "docs/fontbakery-reports/" + basedir + "-report.html"
    if (
        os.path.exists(report_file)
        and os.path.getmtime(report_file) > last_update.timestamp()
    ):
        return False
    reports_this_session -= 1
    return reports_this_session >= 0


def run_fontbakery(directory):
    inputs = glob.glob(directory + "/*")
    basedir = os.path.basename(directory)
    os.makedirs("docs/fontbakery-reports/" + basedir, exist_ok=True)
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
        f"docs/fontbakery-reports/{basedir}-report.json",
        *inputs,
    ]
    args = " ".join(args)
    result = subprocess.run(args, shell=True, capture_output=True)


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
        result = json.load(open(badge))
        color = result["color"].replace("bright", "light")
        try:
            anybadge.Color[color.upper()]
        except KeyError:
            color = "lightgrey"
        badge = anybadge.Badge(result["label"], result["message"], default_color=color)
        fb_badges.append(badge)
    return fb_badges


def tidy_version(version):
    version = version.replace("Version ", "")
    version = version.split(";")[0].strip()
    return version


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
    gf.version_badges = [anybadge.Badge("google/fonts", tidy_version(gf.dev_version))]
    color = "green"
    for s in servers:
        if gf.server_versions.get(s.name):
            version = tidy_version(gf.server_versions[s.name])
            if str(version) < str(gf.version_badges[-1].value).strip():
                color = "orange"
            gf.version_badges.append(
                anybadge.Badge(s.name, version, default_color=color)
            )
    gf.build_badges = []
    if gf.seems_gfr:
        workflows = list(gf.upstream_gh.get_workflows())
        for workflow in workflows or []:
            runs = list(workflow.get_runs())
            if runs and len(runs) > 0:
                gf.build_badges.append(anybadge.Badge(workflow.name, run[0].conclusion))

    # Codepoints

    groups = (
        list(x)
        for _, x in itertools.groupby(
            gf.encoded_codepoints, lambda x, c=itertools.count(): x - next(c)
        )
    )
    gf.codepoints = ", ".join(
        "-".join(map(lambda c: "U+%04X" % c, (item[0], item[-1])[: len(item)]))
        for item in groups
    )

    # Downstream versions if noto
    # Version history
    fonts.append(gf)
    if TESTING and len(fonts) > 5:
        break
fonts = sorted(fonts, key=lambda x: x.metadata.name)


def ago(dt):
    return humanize.naturaldelta(datetime.datetime.now(datetime.timezone.utc) - dt)


env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape())
env.filters["ago"] = ago
template = env.get_template("index.html")
with open("docs/index.html", "w") as f:
    f.write(template.render(fonts=fonts))

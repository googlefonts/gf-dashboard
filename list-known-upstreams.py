from collections import Counter
import glob
import requests
import tqdm

from yaml import Loader
import yaml
from googlefonts import GoogleFont
from github import Github, Auth
import os
import json

GFDIR = "/Users/simon/others-repos/fonts"
# GITHUB = Github()
GITHUB = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"]))

if os.path.exists("cache.json"):
    with open("cache.json") as f:
        repos = json.load(f)
else:
    repos = {}

for directory in tqdm.tqdm(list(sorted(glob.glob(GFDIR+"/ofl/*")))):
    #if "noto" in directory:
    #    continue
    try:
        gf = GoogleFont(directory, GFDIR)
    except Exception as e:
        print(e)
        continue
    this_repo = {}
    base_directory = os.path.basename(directory)
    if base_directory in repos:
        continue
    repos[os.path.basename(directory)] = this_repo
    try:
        upstream = gf.upstream_gh
    except:
        print(f"Upstream {gf.github_owner_repo} not found")
        continue
    if not upstream:
        print("No upstream for "+base_directory)
        continue
    this_repo["has_upstream"] = True
    this_repo["last_updated"] = upstream.updated_at.isoformat()
    real_upstream = upstream.owner.login, upstream.name
    # progress.set_description(real_upstream[0]+"/"+real_upstream[1])
    upstream = this_repo["real_upstream"] = real_upstream[0]+"/"+real_upstream[1]
    if not gf.upstream.get("repository_url") and not gf.metadata.source.repository_url:
        print(f"{base_directory} should have upstream {upstream}")
    repo = GITHUB.get_repo(upstream)
    try:
        sources = repo.get_contents("sources")
    except:
        continue

    configs = [
        p for p in sources
        if p.path.startswith("sources/conf") and (p.path.endswith(".yaml") or p.path.endswith(".yml"))
    ]
    if configs:
        this_repo["is_gfr"] = True
        this_repo["source_files"]= []
        config = yaml.load(configs[0].decoded_content, Loader=Loader)
        if "sources" not in config:
            print(f"{base_directory} ({upstream}) has weird config file {configs[0]}")
            continue
        for source in config["sources"]:
            if source.endswith(".designspace"):
                this_repo["source_files"].append("designspace")
            elif source.endswith(".ufo"):
                this_repo["source_files"].append("ufo")
            elif source.endswith(".glyphs"):
                try:
                    glyphs_file = requests.get(repo.get_contents("sources/"+source).download_url).text
                    if ".formatVersion = 3" in glyphs_file:
                        this_repo["source_files"].append("Glyphs 3")
                    else:
                        this_repo["source_files"].append("Glyphs 2")
                except:
                    this_repo["source_files"].append("Missing Glyphs file")
            elif source.endswith(".glyphspackage"):
                glyphs_file = requests.get(repo.get_contents("sources/"+source+"/fontinfo.plist").download_url).text
                if ".formatVersion = 3" in glyphs_file:
                    this_repo["source_files"].append("Glyphs 3 package")
                else:
                    this_repo["source_files"].append("Glyphs 2 package")

    json.dump(repos, open("cache.json", "w"))

upstream_repos = len([r for r in repos.values() if r.get("has_upstream")])
gfr_repos = len([r for r in repos.values() if r.get("is_gfr")])
source_types = Counter()
for r in repos.values():
    sources = r.get("source_files", [])
    for s in sources:
        source_types[s] += 1

print(f"""
      
Out of {len(repos)} google font families:
    {upstream_repos} ({int(upstream_repos/len(repos)*100)}%) have known and accessible upstreams
    {gfr_repos} appear to be based on the GFR

Out of {source_types.total()} source files:
""")
for source_type, count in source_types.most_common():
    print(f"    {source_type}: {count} ({int(count/source_types.total()*100)}%)")


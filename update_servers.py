from gftools.push.servers import GFServers
from pathlib import Path
import json
import datetime
import glob
import os
import tqdm
from googlefonts import GoogleFont

gfpath = os.environ["GF_PATH"]

server_data = Path("docs/servers.json")

if not server_data.exists():
    print(f"{server_data} not found. Generating file. This may take a while")
    servers = GFServers()
else:
    servers = GFServers.open(server_data)

servers.update_all()
servers.save(server_data)


if os.path.exists("docs/versionhistory.json"):
    versionhistory = json.load(open("docs/versionhistory.json"))
else:
    versionhistory = {}


for directory in tqdm.tqdm(glob.glob(gfpath + "/ofl/*")):
    try:
        gf = GoogleFont(directory, gfpath)
    except Exception as e:
        print(e)
        continue

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

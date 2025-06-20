from gftools.push.servers import GFServers
from pathlib import Path

server_data = Path("docs/servers.json")

if not server_data.exists():
    print(f"{server_data} not found. Generating file. This may take a while")
    servers = GFServers()
else:
    servers = GFServers.open(server_data)

servers.update_all()
servers.save(server_data)

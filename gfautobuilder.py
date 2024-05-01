import glob
import json
import os
import re
import subprocess
import selectors

import git
from rich import progress
from rich.progress import Progress

from progress import GitRemoteProgress

repos = json.load(open("cache.json", "r"))

upstream_repos = len([r for r in repos.values() if r.get("has_upstream")])
gfr_repos = {k: v for k, v in repos.items() if v.get("is_gfr") or v.get("sources")}

failed = []
succeeded = []
with Progress(
            progress.TimeElapsedColumn(),
            progress.TextColumn("[progress.description]{task.description}"),
            progress.BarColumn(),
            progress.TextColumn("{task.completed}/{task.total}"),
            progress.TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            progress.TimeRemainingColumn(),
        ) as progress:
    buildall_task = progress.add_task("[green]Building Google Fonts", total=len(gfr_repos))
    clone_task = progress.add_task("[yellow]Clone", total=100, visible=False)
    if not os.path.isdir("build"):
        os.mkdir("build")
    for name, upstream in gfr_repos.items():
        builddir = "build/"+name
        project_url = "https://github.com/"+upstream["real_upstream"]
        if not os.path.isdir(builddir):
            progress.update(clone_task,description="[yellow] Cloning "+name+"...", completed=0, visible=True)
            git.Repo.clone_from(
                url=project_url,
                to_path=builddir,
                depth=1,
                progress=GitRemoteProgress(progress, clone_task, name),
            )
            progress.update(clone_task, visible=False)
        progress.update(buildall_task, advance=1)
        build_task = progress.add_task("[green]Build " + name, total=1)
        progress.console.print("[bright_black]Building " + name + "...")
        os.chdir(builddir)
        if upstream.get("sources"):
            sources = upstream["sources"]
        else:
            sources = glob.glob("sources/*.y*l")
            if not sources:
                progress.console.print(f"[red]{name} has no sources!")
                failed.append(name)
                continue
            sources = [sources[0]]
        buildcmd = ["gftools-builder"] + sources
        progress.console.print("[bright_black]Building " + " ".join(buildcmd) + "...")

        process = subprocess.Popen(
            buildcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        sel = selectors.DefaultSelector()
        sel.register(process.stdout, selectors.EVENT_READ)
        sel.register(process.stderr, selectors.EVENT_READ)
        ok = True
        stdoutlines = []
        stderrlines = []
        while ok:
            for key, val1 in sel.select():
                line = key.fileobj.readline()
                if not line:
                    ok = False
                    break
                if key.fileobj is process.stdout and (
                    m := re.match(r"^\[(\d+)/(\d+)\]", line.decode("utf8"))
                ):
                    progress.update(
                        build_task, completed=int(m.group(1)), total=int(m.group(2))
                    )
                elif key.fileobj is process.stderr:
                    stderrlines.append(line)
                else:
                    stdoutlines.append(line)
        rc = process.wait()
        if rc != 0:
            for line in stdoutlines:
                progress.console.print(line.decode("utf-8"), end="")
            for line in stderrlines:
                progress.console.print("[red]" + line.decode("utf8"), end="")

            failed.append(name)
            progress.console.print("[red]Error building " + name)
        else:
            progress.console.print("[green]Built " + name)
            succeeded.append(name)
        os.chdir("../..")
        progress.update(build_task, advance=1, visible=False)
        progress.console.print("")

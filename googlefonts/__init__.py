import os
import re
from functools import cached_property
from pathlib import Path

import yaml
from fontTools.misc.timeTools import epoch_diff
from fontTools.ttLib import TTFont
from gflanguages import LoadLanguages
from gftools.util.google_fonts import (GetExemplarFont, LanguageComments,
                                       Metadata, WriteProto)
from github3api import GitHubAPI
from github import Auth, Github


try:
    from yaml import CDumper as Dumper
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader, Dumper

from collections import defaultdict
from datetime import datetime,timedelta,timezone

import tqdm

GH_URL_RE = r"https?:\/\/.*?github\.com/(\S+)\/(\S+)(\/|$)"
# GITHUB = Github()
GITHUB = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"]))
LANGUAGE_COMMENTS = LanguageComments(LoadLanguages())

A_YEAR_AGO = datetime.now(timezone.utc) - timedelta(days=365)
GF_REPO = GITHUB.get_repo("google/fonts")

GRAPHQL_CLIENT = GitHubAPI(bearer_token= os.environ["GITHUB_TOKEN"])


RECENT_COMMITS_QUERY = """
query($path: String!) {
  repository(name: "fonts", owner: "google") {
    ref(qualifiedName: "main") {
      target {
        ... on Commit {
          history(first: 10, path: $path) {
            edges {
              node {
                url
                message
                committedDate
                author {
                  name
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

class GoogleFont:
    has_open_prs = None

    def __init__(self, directory: str, gfroot: str):
        self.metadata = Metadata(directory)
        self.directory = directory.replace(gfroot, "")
        if self.directory[0] == "/":
            self.directory = self.directory[1:]
        self.fullpath = Path(gfroot) / directory

    def root(self, path: str) -> Path:
        return self.fullpath / path
    
    @property
    def open_pulls(self):
        if GoogleFont.has_open_prs is None:
            GoogleFont.has_open_prs = defaultdict(list)
            OPEN_PRS = GITHUB.get_repo("google/fonts").get_pulls(state="open")
            for pr in tqdm.tqdm(OPEN_PRS, total=OPEN_PRS.totalCount):
                directories = {os.path.dirname(x.filename) for x in pr.get_files()}
                for directory in directories:
                    GoogleFont.has_open_prs[directory].append(pr)
        return GoogleFont.has_open_prs[self.directory]

    @cached_property
    def exemplar(self):
        return self.root(GetExemplarFont(self.metadata).filename)

    @cached_property
    def exemplar_tt(self):
        return TTFont(self.exemplar)

    @cached_property
    def encoded_codepoints(self):
        return sorted(list(self.exemplar_tt.getBestCmap().keys()))

    @cached_property
    def dev_head_version(self):
        return self.exemplar_tt["head"].fontRevision

    @cached_property
    def dev_name_version(self):
        return self.exemplar_tt["name"].getDebugName(5)

    @cached_property
    def dev_version(self):
        if self.dev_name_version:
            return self.dev_name_version
        return "%0.2f" % self.dev_head_version

    @cached_property
    def upstream(self):
        upstream_path = self.root("upstream.yaml")
        if upstream_path.exists():
            return yaml.load(upstream_path.open(), Loader=Loader)
        return {}

    @cached_property
    def github_owner_repo(self):
        POTENTIAL_REPOS = [
            self.metadata.source.repository_url,
            self.upstream.get("repository_url"),
            self.upstream.get("archive")
        ]

        copyright = re.search(r"\((.*)\)", self.metadata.fonts[0].copyright)
        if copyright:
            POTENTIAL_REPOS.append(copyright[1])

        for repo_url in POTENTIAL_REPOS:
            if not repo_url:
                continue
            m = re.match(GH_URL_RE, repo_url)
            if m:
                owner, repo = m[1], m[2]
                repo = repo.replace(".git", "")
                return owner, repo


    def save_metadata(self):
        WriteProto(self.metadata, self.root('METADATA.pb'), comments=LANGUAGE_COMMENTS)

    @cached_property
    def upstream_gh(self):
        if self.github_owner_repo:
            try:
                return GITHUB.get_repo("/".join(self.github_owner_repo))
            except Exception:
                return

    @cached_property
    def last_updated(self):
        return datetime.fromtimestamp(self.exemplar.stat().st_mtime)

    @cached_property
    def releases(self):
        if not self.upstream_gh:
            return []
        return self.upstream_gh.get_releases()

    @cached_property
    def new_releases_since_update(self):
        # XXX Check also version numbers
        return list(filter(lambda x: x.published_at, self.releases))
        # return list(filter(lambda x: x.published_at and x.published_at > self.last_updated, self.releases))

    @cached_property
    def seems_gfr(self):
        repo = self.upstream_gh
        if not repo:
            return
        try:
            sources = repo.get_contents("sources")
            configs = [
                p for p in sources
                if p.path.startswith("sources/conf") and (p.path.endswith(".yaml") or p.path.endswith(".yml"))
            ]
            if configs:
                return True
        except:
            return False

    @cached_property
    def recent_commits(self):
        try:
            result = GRAPHQL_CLIENT.graphql(RECENT_COMMITS_QUERY,
                {"path": self.directory}
            )
            import IPython;IPython.embed()
            result = result["data"]["repository"]["ref"]["target"]["history"]["edges"]
            result = [x["node"] for x in result]
            newresult = []
            for x in result:
                x["committedDate"] = datetime.fromisoformat(x["committedDate"])
                if x["committedDate"] > A_YEAR_AGO:
                    newresult.append(x)
            return newresult
        except Exception as e:
            raise e

            return None

    @cached_property
    def recent_pulls(self):
        try:
            result = GRAPHQL_CLIENT.graphql("""
{
  search(query: "is:pr repo:google/fonts %s/", type: ISSUE, first: 100) {
    edges {
      node {
        ... on PullRequest {
          number
          title
          url
          updatedAt
          author { login }
        }
      }
    }
  }
}
"""  % self.directory, {})
            import IPython;IPython.embed()
            result = result["data"]["search"]["edges"]
            result = [x["node"] for x in result]
            for x in result:
                x["updatedAt"] = datetime.fromisoformat(x["updatedAt"])
            return result
        except Exception as e:
            raise e
            return None

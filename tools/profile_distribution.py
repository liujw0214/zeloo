"""Profile Git Distribution System — distribute profiles from Git repositories."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROFILE_SOURCES_FILE = "profile_sources.json"
PROFILES_DIR = "profiles"


class ProfileMergeStrategy(Enum):
    LOCAL_FIRST = "local_first"
    REMOTE_FIRST = "remote_first"
    MERGE = "merge"
    ASK = "ask"


@dataclass
class ProfileRevision:
    name: str
    git_url: str
    branch: str
    commit_hash: str
    tag: str | None = None
    author: str = ""
    message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "git_url": self.git_url,
            "branch": self.branch,
            "commit_hash": self.commit_hash,
            "tag": self.tag,
            "author": self.author,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProfileRevision:
        ts = data["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return cls(
            name=data["name"],
            git_url=data["git_url"],
            branch=data["branch"],
            commit_hash=data["commit_hash"],
            tag=data.get("tag"),
            author=data.get("author", ""),
            message=data.get("message", ""),
            timestamp=ts,
            files=data.get("files", []),
        )


@dataclass
class ProfileDiff:
    name: str
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "added": self.added,
            "modified": self.modified,
            "removed": self.removed,
            "summary": self.summary,
        }


@dataclass
class ProfileSource:
    name: str
    git_url: str
    branch: str = "main"
    path_in_repo: str = ""
    last_pulled: str | None = None
    last_revision: str | None = None

    def to_dict(self) -> dict:
        return {
            "git_url": self.git_url,
            "branch": self.branch,
            "path_in_repo": self.path_in_repo,
            "last_pulled": self.last_pulled,
            "last_revision": self.last_revision,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> ProfileSource:
        return cls(
            name=name,
            git_url=data["git_url"],
            branch=data.get("branch", "main"),
            path_in_repo=data.get("path_in_repo", ""),
            last_pulled=data.get("last_pulled"),
            last_revision=data.get("last_revision"),
        )


class ProfileMerge:
    def merge(self, local: dict, remote: dict) -> dict:
        result = local.copy()
        for key, value in remote.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self.merge(result[key], value)
            else:
                result[key] = value
        return result

    def has_conflict(self, local: dict, remote: dict) -> bool:
        for key, value in remote.items():
            if key in local:
                local_val = local[key]
                if isinstance(local_val, dict) and isinstance(value, dict):
                    if self.has_conflict(local_val, value):
                        return True
                elif local_val != value:
                    return True
        return False

    def resolve_conflict(self, local: dict, remote: dict, strategy: ProfileMergeStrategy) -> dict:
        match strategy:
            case ProfileMergeStrategy.LOCAL_FIRST:
                return remote if not local else local
            case ProfileMergeStrategy.REMOTE_FIRST:
                return remote
            case ProfileMergeStrategy.MERGE | ProfileMergeStrategy.ASK:
                return self.merge(local, remote)
        return remote


class ProfileDistribution:
    def __init__(self, config_dir: Path | None = None):
        if config_dir is None:
            from agent.zeloo_constants import get_zeloo_home
            config_dir = get_zeloo_home()
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.sources_file = self.config_dir / PROFILE_SOURCES_FILE
        self.profiles_dir = self.config_dir / PROFILES_DIR
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._sources: dict[str, ProfileSource] = {}
        self._load_sources()

    def _load_sources(self) -> None:
        if self.sources_file.exists():
            try:
                with open(self.sources_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._sources = {
                    name: ProfileSource.from_dict(name, info)
                    for name, info in data.get("sources", {}).items()
                }
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load profile sources: %s", e)
                self._sources = {}

    def _save_sources(self) -> None:
        data = {"sources": {name: src.to_dict() for name, src in self._sources.items()}}
        with open(self.sources_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_source(self, name: str, git_url: str, branch: str = "main", path_in_repo: str = "") -> str:
        if name in self._sources:
            raise ValueError(f"Source '{name}' already exists")
        source = ProfileSource(name=name, git_url=git_url, branch=branch, path_in_repo=path_in_repo)
        self._sources[name] = source
        self._save_sources()
        return f"Added source '{name}' -> {git_url} (branch: {branch})"

    def remove_source(self, name: str) -> bool:
        if name not in self._sources:
            return False
        del self._sources[name]
        self._save_sources()
        profile_path = self.profiles_dir / name
        if profile_path.exists():
            shutil.rmtree(profile_path)
        return True

    def list_sources(self) -> list[dict]:
        return [
            {
                "name": src.name,
                "git_url": src.git_url,
                "branch": src.branch,
                "path_in_repo": src.path_in_repo,
                "last_pulled": src.last_pulled,
                "last_revision": src.last_revision,
            }
            for src in self._sources.values()
        ]

    def clone(self, url: str, branch: str, dest: Path, depth: int = 1) -> Path:
        logger.info("Cloning %s (branch: %s) to %s", url, branch, dest)
        try:
            subprocess.run(
                ["git", "clone", "--depth", str(depth), "--branch", branch, url, str(dest)],
                check=True, capture_output=True, text=True,
            )
            return dest
        except subprocess.CalledProcessError as e:
            logger.error("Git clone failed: %s", e.stderr)
            raise RuntimeError(f"Failed to clone {url}: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError("Git is not installed or not in PATH")

    def pull(self, name: str, revision: str | None = None) -> ProfileRevision:
        if name not in self._sources:
            raise KeyError(f"Source '{name}' not found")
        source = self._sources[name]
        profile_path = self.profiles_dir / name
        if profile_path.exists():
            self._git_pull(profile_path, source.branch)
        else:
            self.clone(source.git_url, source.branch, profile_path)
        if revision:
            self._git_checkout(profile_path, revision)
        commit_hash = self._git_get_current_commit(profile_path)
        commit_info = self._git_get_commit_info(profile_path, commit_hash)
        files = self._list_profile_files(profile_path, source.path_in_repo)
        revision_obj = ProfileRevision(
            name=name,
            git_url=source.git_url,
            branch=source.branch,
            commit_hash=commit_hash,
            tag=commit_info.get("tag"),
            author=commit_info.get("author", ""),
            message=commit_info.get("message", ""),
            timestamp=commit_info.get("timestamp", datetime.now(timezone.utc)),
            files=files,
        )
        source.last_pulled = datetime.now(timezone.utc).isoformat()
        source.last_revision = commit_hash
        self._save_sources()
        return revision_obj

    def pull_all(self, revision: str | None = None) -> list[ProfileRevision]:
        revisions = []
        for name in list(self._sources.keys()):
            try:
                rev = self.pull(name, revision)
                revisions.append(rev)
            except Exception as e:
                logger.error("Failed to pull from '%s': %s", name, e)
        return revisions

    def diff(self, name: str, local: str, remote: str) -> ProfileDiff:
        if name not in self._sources:
            raise KeyError(f"Source '{name}' not found")
        profile_path = self.profiles_dir / name
        if not profile_path.exists():
            raise RuntimeError(f"Profile '{name}' not cloned yet. Run pull() first.")
        try:
            result = subprocess.run(
                ["git", "diff", "--name-status", local, remote],
                cwd=profile_path, check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to diff: {e.stderr}")
        added, modified, removed = [], [], []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            status, filepath = line.split("\t", 1)
            match status:
                case "A" | "?":
                    added.append(filepath)
                case "M":
                    modified.append(filepath)
                case "D":
                    removed.append(filepath)
        return ProfileDiff(
            name=name,
            added=added,
            modified=modified,
            removed=removed,
            summary=f"+{len(added)} -{len(modified)} ~{len(removed)}",
        )

    def resolve(self, name: str) -> Path | None:
        profile_path = self.profiles_dir / name
        if profile_path.exists() and any(profile_path.iterdir()):
            return profile_path
        return None

    def get_current(self, name: str) -> ProfileRevision | None:
        if name not in self._sources:
            return None
        profile_path = self.profiles_dir / name
        if not profile_path.exists():
            return None
        try:
            commit_hash = self._git_get_current_commit(profile_path)
            commit_info = self._git_get_commit_info(profile_path, commit_hash)
            source = self._sources[name]
            return ProfileRevision(
                name=name,
                git_url=source.git_url,
                branch=source.branch,
                commit_hash=commit_hash,
                tag=commit_info.get("tag"),
                author=commit_info.get("author", ""),
                message=commit_info.get("message", ""),
                timestamp=commit_info.get("timestamp", datetime.now(timezone.utc)),
                files=self._list_profile_files(profile_path, source.path_in_repo),
            )
        except Exception as e:
            logger.warning("Failed to get current revision for '%s': %s", name, e)
            return None

    def _git_pull(self, repo_path: Path, branch: str) -> None:
        try:
            subprocess.run(["git", "fetch", "origin", branch], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], cwd=repo_path, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git pull failed: {e.stderr}")

    def _git_checkout(self, repo_path: Path, revision: str) -> None:
        try:
            subprocess.run(["git", "checkout", revision], cwd=repo_path, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git checkout failed: {e.stderr}")

    def _git_get_current_commit(self, repo_path: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo_path, check=True, capture_output=True, text=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get commit hash: {e.stderr}")

    def _git_get_commit_info(self, repo_path: Path, commit_hash: str) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%an|%ae|%s|%ai|%D", commit_hash],
                cwd=repo_path, check=True, capture_output=True, text=True,
            )
            parts = result.stdout.strip().split("|")
            info: dict[str, Any] = {"author": parts[0] if len(parts) > 0 else "", "tag": None}
            if len(parts) > 2:
                info["message"] = parts[2]
            if len(parts) > 4:
                ref_str = parts[4]
                if "tag:" in ref_str:
                    for ref in ref_str.split(","):
                        ref = ref.strip()
                        if ref.startswith("tag: "):
                            info["tag"] = ref[5:]
                            break
            if len(parts) > 3:
                try:
                    info["timestamp"] = datetime.fromisoformat(parts[3].replace("Z", "+00:00"))
                except ValueError:
                    info["timestamp"] = datetime.now(timezone.utc)
            return info
        except subprocess.CalledProcessError as e:
            logger.warning("Failed to get commit info: %s", e.stderr)
            return {}

    def _list_profile_files(self, repo_path: Path, path_in_repo: str) -> list[str]:
        profile_root = repo_path / path_in_repo if path_in_repo else repo_path
        if not profile_root.exists():
            return []
        return sorted(str(f.relative_to(profile_root)) for f in profile_root.rglob("*") if f.is_file())


def clone_profile_repo(url: str, branch: str = "main", dest: Path | None = None) -> Path:
    from agent.zeloo_constants import get_zeloo_home
    if dest is None:
        url_hash = str(abs(hash(url)))[:12]
        dest = get_zeloo_home() / PROFILES_DIR / f"clone_{url_hash}"
    dist = ProfileDistribution()
    return dist.clone(url, branch, dest)


def fetch_profile(url: str, revision: str = "HEAD") -> dict:
    import re
    if "github.com" in url:
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?", url)
        if match:
            owner, repo = match.groups()
            return {"api_url": f"https://api.github.com/repos/{owner}/{repo}/commits/{revision}", "platform": "github"}
    elif "gitlab.com" in url:
        match = re.match(r"https?://gitlab\.com/([^/]+)/([^/]+?)(?:\.git)?/?", url)
        if match:
            owner, repo = match.groups()
            return {"api_url": f"https://gitlab.com/api/v4/projects/{owner}%2F{repo}/commits/{revision}", "platform": "gitlab"}
    return {"url": url, "revision": revision, "platform": "unknown"}


def sync_profiles(sources: list[dict], strategy: ProfileMergeStrategy) -> list[ProfileRevision]:
    dist = ProfileDistribution()
    revisions = []
    for source_config in sources:
        name = source_config.get("name", "")
        git_url = source_config.get("git_url", "")
        branch = source_config.get("branch", "main")
        if not name or not git_url:
            logger.warning("Invalid source config: %s", source_config)
            continue
        if name not in dist._sources:
            dist.add_source(name, git_url, branch)
        try:
            revisions.append(dist.pull(name))
        except Exception as e:
            logger.error("Failed to sync '%s': %s", name, e)
    return revisions


def import_profile_from_git(git_url: str, profile_name: str, branch: str = "main") -> str:
    dist = ProfileDistribution()
    if profile_name in dist._sources:
        return f"Profile '{profile_name}' already exists. Use pull() to update."
    dist.add_source(profile_name, git_url, branch)
    rev = dist.pull(profile_name)
    profile_path = dist.resolve(profile_name)
    if profile_path:
        return str(profile_path)
    return f"Imported {profile_name} at revision {rev.commit_hash[:8]}"


def export_profile_to_git(profile_path: Path, git_url: str, branch: str = "main", message: str = "") -> str:
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile path does not exist: {profile_path}")
    temp_clone = profile_path.parent / f"export_{abs(hash(str(profile_path)))}"
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "--branch", branch, git_url, str(temp_clone)],
            check=True, capture_output=True,
        )
        for item in profile_path.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(profile_path)
                dest_file = temp_clone / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_file)
        if not message:
            message = f"Export profile from {profile_path.name}"
        subprocess.run(["git", "add", "."], cwd=temp_clone, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=Zeloo", "-c", "user.email=zeloo@local", "commit", "-m", message],
            cwd=temp_clone, check=True, capture_output=True,
        )
        subprocess.run(["git", "push", "origin", branch], cwd=temp_clone, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=temp_clone, check=True, capture_output=True, text=True,
        )
        return f"Exported to {git_url}@{branch} ({result.stdout.strip()[:8]})"
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Export failed: {e.stderr}")
    finally:
        if temp_clone.exists():
            shutil.rmtree(temp_clone)


def profile_add_source(name: str, git_url: str, branch: str = "main", path_in_repo: str = "") -> dict:
    try:
        dist = ProfileDistribution()
        return {"success": True, "message": dist.add_source(name, git_url, branch, path_in_repo)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def profile_remove_source(name: str) -> dict:
    try:
        dist = ProfileDistribution()
        if dist.remove_source(name):
            return {"success": True, "message": f"Removed source '{name}'"}
        return {"success": False, "error": f"Source '{name}' not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def profile_list_sources() -> dict:
    try:
        return {"success": True, "sources": ProfileDistribution().list_sources()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def profile_pull(name: str, revision: str | None = None) -> dict:
    try:
        dist = ProfileDistribution()
        rev = dist.pull(name, revision)
        return {
            "success": True,
            "revision": {
                "name": rev.name,
                "commit_hash": rev.commit_hash,
                "branch": rev.branch,
                "author": rev.author,
                "message": rev.message,
                "tag": rev.tag,
                "timestamp": rev.timestamp.isoformat(),
                "files": rev.files,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def profile_diff(name: str) -> dict:
    try:
        dist = ProfileDistribution()
        source = dist._sources.get(name)
        if not source:
            return {"success": False, "error": f"Source '{name}' not found"}
        profile_path = dist.resolve(name)
        if not profile_path:
            return {"success": False, "error": f"Profile '{name}' not cloned yet"}
        diff = dist.diff(name, "HEAD~1", "HEAD")
        return {
            "success": True,
            "diff": {
                "name": diff.name,
                "added": diff.added,
                "modified": diff.modified,
                "removed": diff.removed,
                "summary": diff.summary,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

import os
import json
import base64
import urllib.request
import urllib.error
import urllib.parse
try:
    from pyvcs.repo import Repository
except ImportError:
    from repo import Repository

DEFAULT_TOKEN = "pyvcs-secret-token"

class RemoteClient:
    """Handles HTTP operations for remote push, pull, fetch, clone, and GitHub sync."""

    def __init__(self, repo: Repository = None):
        self.repo = repo
        if repo:
            self.remote_config = os.path.join(repo.vcs_dir, "remote.json")

    def _load_remote(self) -> dict:
        if self.repo and os.path.exists(self.remote_config):
            with open(self.remote_config, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def add_remote(self, name: str, url: str):
        if not self.repo:
            raise SystemExit("Repository not initialized.")
        config = {"name": name, "url": url.rstrip("/")}
        with open(self.remote_config, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Added remote '{name}' -> {url}")

    def _http_request(self, url: str, method: str = "GET", data: dict = None, token: str = DEFAULT_TOKEN) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        encoded_data = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            raise SystemExit(f"HTTP Remote Error ({e.code}): {err_msg}")
        except Exception as e:
            raise SystemExit(f"Remote Network Error: {e}")

    def push(self, token: str = DEFAULT_TOKEN):
        config = self._load_remote()
        if not config:
            raise SystemExit("No remote configured. Run 'vcs remote add origin <url>' first.")

        url = config["url"]
        branch = self.repo._current_branch()
        head = self.repo._get_head_commit()

        if not head:
            print("No commits to push.")
            return

        reachable_shas = set()
        stack = [head]
        while stack:
            sha = stack.pop()
            if not sha or sha in reachable_shas:
                continue
            reachable_shas.add(sha)
            try:
                tree_entries = self.repo._get_tree_entries(sha)
                for blob_sha in tree_entries.values():
                    reachable_shas.add(blob_sha)
                _, body = self.repo.store.read_object(sha)
                c_data = json.loads(body.decode("utf-8"))
                tree_sha = c_data.get("tree")
                if tree_sha:
                    reachable_shas.add(tree_sha)
                if c_data.get("parent"):
                    stack.append(c_data["parent"])
            except Exception:
                pass

        objects_payload = {}
        for sha in reachable_shas:
            raw_bytes = self.repo.store.read_raw(sha)
            objects_payload[sha] = base64.b64encode(raw_bytes).decode("utf-8")

        push_data = {
            "branch": branch,
            "head": head,
            "objects": objects_payload
        }

        res = self._http_request(f"{url}/push", method="POST", data=push_data, token=token)
        print(f"Pushed branch '{branch}' -> {head[:8]} to remote ({res.get('status')})")

    def fetch(self, token: str = DEFAULT_TOKEN) -> dict:
        config = self._load_remote()
        if not config:
            raise SystemExit("No remote configured. Run 'vcs remote add origin <url>' first.")

        url = config["url"]
        res = self._http_request(f"{url}/fetch", method="POST", data={"have": []}, token=token)

        objects = res.get("objects", {})
        for sha, b64_data in objects.items():
            raw_bytes = base64.b64decode(b64_data)
            obj_type, body = raw_bytes.split(b"\n", 1)
            self.repo.store.write_raw(obj_type.decode("utf-8"), body)

        print(f"Fetched {len(objects)} object(s) from remote.")
        return res.get("refs", {})

    def pull(self, token: str = DEFAULT_TOKEN):
        refs = self.fetch(token=token)
        branch = self.repo._current_branch()
        remote_head = refs.get(branch)

        if not remote_head:
            print(f"Remote branch '{branch}' not found.")
            return

        our_head = self.repo._get_head_commit()
        if our_head == remote_head:
            print("Already up-to-date.")
            return

        self.repo.branch_mgr.create("FETCH_HEAD", switch_to=False)
        self.repo._update_branch_ref("FETCH_HEAD", remote_head)
        self.repo.branch_mgr.merge("FETCH_HEAD")
        self.repo.branch_mgr.delete("FETCH_HEAD")

    def github_sync(self, github_url: str, branch: str = "main", token: str = None):
        """Push pyvcs-tracked files straight to a GitHub repository over plain HTTP,
        using GitHub's REST 'contents' API — no local `git` binary involved at all.

        This is what makes pyvcs a genuinely independent VCS: it reads files
        straight out of its own object store (self.repo.store) and uploads
        them one by one via urllib, using a GitHub Personal Access Token.

        Only files that are part of the pyvcs HEAD commit tree are pushed —
        never files sitting in the folder that were never `vcs stage`d.
        """
        if not self.repo:
            raise SystemExit("Repository not initialized.")

        token = token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit(
                "No GitHub token found. Set the GITHUB_TOKEN environment variable to a "
                "GitHub Personal Access Token with 'repo' scope, then try again.\n"
                "  (See README.md -> 'Pushing to GitHub' for step-by-step instructions.)"
            )

        head = self.repo._get_head_commit()
        if not head:
            raise SystemExit(
                "No commits to sync. Run 'vcs stage <files>' and 'vcs save -m \"...\"' first."
            )

        tree_entries = self.repo._get_tree_entries(head)
        tracked_files = sorted(
            fp for fp in tree_entries.keys() if not self.repo.ignore.is_ignored(fp)
        )
        if not tracked_files:
            raise SystemExit("HEAD commit has no tracked files to push.")

        if len(tracked_files) > 300:
            print(
                f"Note: {len(tracked_files)} tracked files found — this pushes one file per "
                "HTTP request, so a large count can be slow and may hit GitHub's API rate "
                "limit (5000 requests/hour). Double-check your .vcsignore excludes "
                "node_modules, venv, build/dist, etc.\n"
            )

        owner, repo_name = self._parse_github_url(github_url)
        print(
            f"Pushing {len(tracked_files)} pyvcs-tracked file(s) to "
            f"github.com/{owner}/{repo_name} (branch: {branch}) via GitHub REST API..."
        )

        pushed, failed = 0, []
        for i, fp in enumerate(tracked_files, 1):
            blob_sha = tree_entries[fp]
            _, body = self.repo.store.read_object(blob_sha)
            content_b64 = base64.b64encode(body).decode("utf-8")
            api_path = "/".join(urllib.parse.quote(part) for part in fp.split("/"))

            # Look up the file's current sha on GitHub (needed to update vs create).
            status, existing = self._github_api_request(
                "GET", f"/repos/{owner}/{repo_name}/contents/{api_path}?ref={branch}", token
            )

            payload = {
                "message": f"vcs sync: {head[:8]} - update {fp}",
                "content": content_b64,
                "branch": branch,
            }
            if status == 200 and isinstance(existing, dict) and "sha" in existing:
                payload["sha"] = existing["sha"]

            put_status, result = self._github_api_request(
                "PUT", f"/repos/{owner}/{repo_name}/contents/{api_path}", token, data=payload
            )
            if put_status in (200, 201):
                pushed += 1
            else:
                failed.append((fp, result.get("message", f"HTTP {put_status}")))

            if i % 10 == 0 or i == len(tracked_files):
                print(f"  ...{i}/{len(tracked_files)} file(s) processed")

        print(f"Pushed {pushed}/{len(tracked_files)} file(s).")
        if failed:
            print("Failed:")
            for fp, msg in failed:
                print(f"  {fp}: {msg}")
        else:
            print(f"Successfully synced all pyvcs-tracked files to https://github.com/{owner}/{repo_name}")

    @staticmethod
    def _parse_github_url(url: str):
        url = url.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        parts = [p for p in url.split("/") if p]
        return parts[-2], parts[-1]

    @staticmethod
    def _github_api_request(method: str, path: str, token: str, data: dict = None):
        req = urllib.request.Request(
            f"https://api.github.com{path}",
            data=json.dumps(data).encode("utf-8") if data is not None else None,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "pyvcs",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read()
                return resp.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"message": body.decode("utf-8", errors="replace")}
            return e.code, parsed
        except Exception as e:
            return 0, {"message": str(e)}

    @staticmethod
    def clone(url: str, target_dir: str = None, token: str = DEFAULT_TOKEN):
        url = url.rstrip("/")
        repo_name = url.split("/")[-1]
        dest_dir = target_dir or repo_name

        Repository.init(dest_dir)
        repo = Repository(dest_dir)
        client = RemoteClient(repo)
        client.add_remote("origin", url)

        refs = client.fetch(token=token)
        main_head = refs.get("main") or (list(refs.values())[0] if refs else "")

        if main_head:
            repo._update_branch_ref("main", main_head)
            repo._checkout_commit_tree(main_head)
            print(f"Cloned repository '{repo_name}' successfully into '{dest_dir}' (HEAD: {main_head[:8]}).")
        else:
            print(f"Cloned empty repository into '{dest_dir}'.")

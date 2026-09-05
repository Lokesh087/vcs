import os
import json
import time

class Stash:
    """Shelves and restores uncommitted working directory state."""

    def __init__(self, repo):
        self.repo = repo
        self.stash_file = os.path.join(self.repo.vcs_dir, "stash.json")

    def _load(self) -> list:
        if os.path.exists(self.stash_file):
            with open(self.stash_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self, stashes: list):
        with open(self.stash_file, "w", encoding="utf-8") as f:
            json.dump(stashes, f, indent=2)

    def push(self):
        # Gather all modified / added tracked files
        staged = self.repo._load_index()
        modified, deleted, added, untracked = self.repo.get_status_lists()

        files_to_stash = set(staged.keys()) | set(modified) | set(deleted)
        if not files_to_stash:
            print("No local changes to stash.")
            return

        snapshot = {}
        for fp in files_to_stash:
            full_path = os.path.join(self.repo.root_dir, fp)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    snapshot[fp] = f.read()
            else:
                snapshot[fp] = None  # file was deleted

        stashes = self._load()
        stashes.insert(0, {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "branch": self.repo._current_branch(),
            "files": snapshot
        })
        self._save(stashes)

        # Clean working directory back to HEAD state
        self.repo.revert_all()
        print(f"Saved working directory state (stashed {len(snapshot)} file(s))")

    def pop(self):
        stashes = self._load()
        if not stashes:
            print("No stashed state found.")
            return

        entry = stashes.pop(0)
        self._save(stashes)

        restored_count = 0
        for fp, content in entry["files"].items():
            full_path = os.path.join(self.repo.root_dir, fp)
            if content is None:
                if os.path.exists(full_path):
                    os.remove(full_path)
            else:
                os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.repo.stage_file(fp)
            restored_count += 1

        print(f"Applied stashed changes from {entry['timestamp']} ({restored_count} file(s) restored)")

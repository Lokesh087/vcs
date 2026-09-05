import os
import json

class Tagger:
    """Manages lightweight and annotated tags pointing to commit SHAs."""

    def __init__(self, repo):
        self.repo = repo
        self.tags_file = os.path.join(self.repo.vcs_dir, "tags.json")

    def _load(self) -> dict:
        if os.path.exists(self.tags_file):
            with open(self.tags_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self, tags: dict):
        with open(self.tags_file, "w", encoding="utf-8") as f:
            json.dump(tags, f, indent=2)

    def create(self, name: str, message: str = ""):
        head_commit = self.repo._get_head_commit()
        if not head_commit:
            raise SystemExit("Cannot create tag: repository has no commits.")
        tags = self._load()
        tags[name] = {
            "commit": head_commit,
            "message": message
        }
        self._save(tags)
        print(f"Created tag '{name}' -> {head_commit[:8]}")

    def delete(self, name: str):
        tags = self._load()
        if name in tags:
            del tags[name]
            self._save(tags)
            print(f"Deleted tag '{name}'")
        else:
            print(f"Tag '{name}' not found.")

    def list_tags(self):
        tags = self._load()
        if not tags:
            print("No tags found.")
            return
        for name, info in sorted(tags.items()):
            msg_str = f" ({info['message']})" if info.get("message") else ""
            print(f"{name:<15} -> {info['commit'][:8]}{msg_str}")

    def resolve(self, ref: str) -> str:
        """Resolve a tag name to a commit SHA, or return ref as-is."""
        tags = self._load()
        if ref in tags:
            return tags[ref]["commit"]
        return ref

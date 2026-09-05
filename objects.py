import os
import json
import zlib
import hashlib
import time

class ObjectStore:
    """Content-addressed object store for pyvcs."""

    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        self.objects_dir = os.path.join(self.repo_path, ".vcs", "objects")
        os.makedirs(self.objects_dir, exist_ok=True)
        self._packer = None

    def set_packer(self, packer):
        self._packer = packer

    def _path(self, sha: str) -> str:
        return os.path.join(self.objects_dir, sha[:2], sha[2:])

    def write_raw(self, obj_type: str, content: bytes) -> str:
        """Store raw object (type header + content), return SHA-256 hash."""
        header = f"{obj_type}\n".encode("utf-8")
        full_data = header + content
        sha = hashlib.sha256(full_data).hexdigest()
        path = self._path(sha)

        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(zlib.compress(full_data))
        return sha

    def try_read_loose(self, sha: str):
        """Attempt to read loose object. Returns full_data bytes or None."""
        path = self._path(sha)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return zlib.decompress(f.read())
        return None

    def read_raw(self, sha: str) -> bytes:
        """Read object data. Checks loose objects first, then packfiles."""
        data = self.try_read_loose(sha)
        if data is not None:
            return data
        if self._packer is not None:
            return self._packer.read_object(sha)
        raise KeyError(f"Object {sha} not found in repository.")

    def read_object(self, sha: str):
        """Return tuple of (obj_type_str, body_bytes)."""
        raw = self.read_raw(sha)
        obj_type, body = raw.split(b"\n", 1)
        return obj_type.decode("utf-8"), body

    def remove_loose(self, sha: str) -> bool:
        """Remove a loose object once it has been packed."""
        path = self._path(sha)
        if os.path.exists(path):
            os.remove(path)
            # Remove parent directory if empty
            parent = os.path.dirname(path)
            if os.path.exists(parent) and not os.listdir(parent):
                os.rmdir(parent)
            return True
        return False

    # High-level helper methods

    def store_blob(self, file_path: str) -> str:
        with open(file_path, "rb") as f:
            content = f.read()
        return self.write_raw("blob", content)

    def store_blob_bytes(self, content: bytes) -> str:
        return self.write_raw("blob", content)

    def store_tree(self, entries: dict) -> str:
        """entries = {rel_path: blob_sha}"""
        sorted_entries = {k: entries[k] for k in sorted(entries.keys())}
        json_bytes = json.dumps(sorted_entries, indent=2).encode("utf-8")
        return self.write_raw("tree", json_bytes)

    def store_commit(self, tree_sha: str, parent_sha: str, message: str, author: str = "dev") -> str:
        commit_data = {
            "tree": tree_sha,
            "parent": parent_sha,
            "author": author,
            "message": message,
            "timestamp": time.time()
        }
        json_bytes = json.dumps(commit_data, indent=2).encode("utf-8")
        return self.write_raw("commit", json_bytes)

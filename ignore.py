import os
import fnmatch

VCS_DIR = ".vcs"

class IgnoreMatcher:
    """Handles .vcsignore pattern matching using fnmatch."""

    def __init__(self, root_dir="."):
        self.root_dir = os.path.abspath(root_dir)
        self.patterns = [VCS_DIR, f"{VCS_DIR}/*", ".git", ".git/*"]
        self._load_vcsignore()

    def _load_vcsignore(self):
        ignore_path = os.path.join(self.root_dir, ".vcsignore")
        if os.path.exists(ignore_path):
            with open(ignore_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Normalize pattern slashes
                        pattern = line.replace("\\", "/")
                        self.patterns.append(pattern)
                        # If pattern is a folder like 'node_modules/', also match contents
                        if pattern.endswith("/"):
                            self.patterns.append(pattern + "*")
                        else:
                            self.patterns.append(pattern + "/*")

    def is_ignored(self, file_path: str) -> bool:
        """Return True if relative or absolute file_path matches any ignore pattern."""
        # Convert path relative to root_dir
        abs_path = os.path.abspath(os.path.join(self.root_dir, file_path))
        try:
            rel_path = os.path.relpath(abs_path, self.root_dir).replace("\\", "/")
        except ValueError:
            rel_path = file_path.replace("\\", "/")

        if rel_path == "." or rel_path == "":
            return False

        # Always ignore .vcs directory
        parts = rel_path.split("/")
        if VCS_DIR in parts:
            return True

        for pat in self.patterns:
            if fnmatch.fnmatch(rel_path, pat):
                return True
            # Check matching against any path segment (e.g., node_modules)
            for part in parts:
                if fnmatch.fnmatch(part, pat.rstrip("/")):
                    return True
        return False

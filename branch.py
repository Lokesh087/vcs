import os
import json
try:
    from pyvcs.diff import three_way_merge
except ImportError:
    from diff import three_way_merge

class BranchManager:
    """Manages branches, branch switching, fast-forward and 3-way merges."""

    def __init__(self, repo):
        self.repo = repo
        self.store = repo.store
        self.heads_dir = os.path.join(repo.vcs_dir, "refs", "heads")
        os.makedirs(self.heads_dir, exist_ok=True)

    def create(self, name: str, switch_to: bool = False):
        ref_path = os.path.join(self.heads_dir, name)
        if os.path.exists(ref_path) and not switch_to:
            print(f"Branch '{name}' already exists.")
            return

        head_commit = self.repo._get_head_commit()
        if not os.path.exists(ref_path):
            with open(ref_path, "w", encoding="utf-8") as f:
                f.write(head_commit or "")
            print(f"Created branch '{name}'")

        if switch_to:
            self.switch(name)

    def list_branches(self):
        current = self.repo._current_branch()
        if not os.path.exists(self.heads_dir):
            print("* main")
            return

        branches = sorted(os.listdir(self.heads_dir))
        if not branches:
            print(f"* {current}")
            return

        for b in branches:
            prefix = "* " if b == current else "  "
            print(f"{prefix}{b}")

    def delete(self, name: str):
        current = self.repo._current_branch()
        if name == current:
            raise SystemExit(f"Cannot delete the currently active branch '{name}'.")
        ref_path = os.path.join(self.heads_dir, name)
        if os.path.exists(ref_path):
            os.remove(ref_path)
            print(f"Deleted branch '{name}'")
        else:
            print(f"Branch '{name}' does not exist.")

    def switch(self, name: str, create: bool = False):
        ref_path = os.path.join(self.heads_dir, name)
        if not os.path.exists(ref_path):
            if create:
                self.create(name, switch_to=False)
            else:
                raise SystemExit(f"Branch '{name}' does not exist. Use -c to create it.")

        modified, deleted, added, untracked = self.repo.get_status_lists()
        if modified or deleted:
            print(f"Warning: Local unsaved changes present. Switching to '{name}'.")

        target_commit = ""
        with open(ref_path, "r", encoding="utf-8") as f:
            target_commit = f.read().strip()

        if target_commit:
            self.repo._checkout_commit_tree(target_commit)

        with open(self.repo.head_file, "w", encoding="utf-8") as f:
            f.write(f"ref: refs/heads/{name}")
        print(f"Switched to branch '{name}'")

    def merge(self, target_branch: str):
        """Merge target_branch into current branch."""
        current_b = self.repo._current_branch()
        if current_b == target_branch:
            print("Cannot merge branch into itself.")
            return

        target_ref = os.path.join(self.heads_dir, target_branch)
        if not os.path.exists(target_ref):
            raise SystemExit(f"Target branch '{target_branch}' does not exist.")

        with open(target_ref, "r", encoding="utf-8") as f:
            their_commit = f.read().strip()
        our_commit = self.repo._get_head_commit()

        if not their_commit:
            print("Target branch has no commits.")
            return
        if not our_commit:
            self.repo._update_branch_ref(current_b, their_commit)
            self.repo._checkout_commit_tree(their_commit)
            print(f"Fast-forwarded '{current_b}' to {their_commit[:8]}")
            return

        base_commit = self._find_merge_base(our_commit, their_commit)

        if base_commit == their_commit:
            print("Already up-to-date.")
            return
        if base_commit == our_commit:
            self.repo._update_branch_ref(current_b, their_commit)
            self.repo._checkout_commit_tree(their_commit)
            print(f"Fast-forward merged '{target_branch}' into '{current_b}' ({their_commit[:8]})")
            return

        base_tree = self.repo._get_tree_entries(base_commit) if base_commit else {}
        our_tree = self.repo._get_tree_entries(our_commit)
        their_tree = self.repo._get_tree_entries(their_commit)

        all_files = set(base_tree.keys()) | set(our_tree.keys()) | set(their_tree.keys())
        conflict_files = []

        for fp in all_files:
            base_b = base_tree.get(fp)
            our_b = our_tree.get(fp)
            their_b = their_tree.get(fp)

            if our_b == their_b:
                continue
            elif base_b == our_b:
                if their_b is not None:
                    content = self.store.read_raw(their_b).split(b"\n", 1)[1]
                    self.repo._write_workspace_file(fp, content)
                    self.repo.stage_file(fp)
                else:
                    self.repo._remove_workspace_file(fp)
            elif base_b == their_b:
                continue
            else:
                base_txt = self.store.read_raw(base_b).split(b"\n", 1)[1].decode("utf-8", errors="replace") if base_b else ""
                our_txt = self.store.read_raw(our_b).split(b"\n", 1)[1].decode("utf-8", errors="replace") if our_b else ""
                their_txt = self.store.read_raw(their_b).split(b"\n", 1)[1].decode("utf-8", errors="replace") if their_b else ""

                merged_lines, conflicts = three_way_merge(
                    base_txt.splitlines(),
                    our_txt.splitlines(),
                    their_txt.splitlines()
                )

                merged_content = "\n".join(merged_lines)
                self.repo._write_workspace_file(fp, merged_content.encode("utf-8"))

                if conflicts > 0:
                    conflict_files.append(fp)
                    print(f"CONFLICT (content): Merge conflict in {fp}")
                else:
                    self.repo.stage_file(fp)

        if conflict_files:
            print(f"\nAutomatic merge failed; fix conflicts in {len(conflict_files)} file(s) and then run 'vcs save'.")
        else:
            commit_sha = self.repo.save(f"Merge branch '{target_branch}' into '{current_b}'")
            print(f"Successfully merged '{target_branch}' into '{current_b}'.")

    def _find_merge_base(self, c1_sha: str, c2_sha: str) -> str:
        def get_ancestors(commit_sha):
            ancestors = set()
            curr = commit_sha
            while curr:
                ancestors.add(curr)
                try:
                    _, body = self.store.read_object(curr)
                    data = json.loads(body.decode("utf-8"))
                    curr = data.get("parent")
                except Exception:
                    break
            return ancestors

        c1_ancestors = get_ancestors(c1_sha)
        curr = c2_sha
        while curr:
            if curr in c1_ancestors:
                return curr
            try:
                _, body = self.store.read_object(curr)
                data = json.loads(body.decode("utf-8"))
                curr = data.get("parent")
            except Exception:
                break
        return None

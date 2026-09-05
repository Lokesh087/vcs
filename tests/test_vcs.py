import os
import sys
import shutil
import tempfile
import unittest
import threading
import time

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from objects import ObjectStore
from diff import myers_diff, unified_diff, three_way_merge
from packfile import Packer, DeltaEncoder
from ignore import IgnoreMatcher
from repo import Repository
from branch import BranchManager
from tagger import Tagger
from stash import Stash
from remote import RemoteClient
from server import run_server, DEFAULT_AUTH_TOKEN

class TestVCSCore(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="pyvcs_test_")
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_object_store(self):
        store = ObjectStore(self.test_dir)
        blob_sha = store.store_blob_bytes(b"hello world vcs")
        obj_type, body = store.read_object(blob_sha)
        self.assertEqual(obj_type, "blob")
        self.assertEqual(body, b"hello world vcs")

        tree_sha = store.store_tree({"index.html": blob_sha})
        obj_type, body = store.read_object(tree_sha)
        self.assertEqual(obj_type, "tree")
        self.assertIn("index.html", body.decode("utf-8"))

        commit_sha = store.store_commit(tree_sha, "", "initial commit", "tester")
        obj_type, body = store.read_object(commit_sha)
        self.assertEqual(obj_type, "commit")
        self.assertIn("initial commit", body.decode("utf-8"))

    def test_myers_diff(self):
        a = ["line 1", "line 2", "line 3"]
        b = ["line 1", "line 2 modified", "line 3", "line 4"]
        ops = myers_diff(a, b)
        self.assertTrue(len(ops) > 0)

        udiff = unified_diff("\n".join(a), "\n".join(b))
        self.assertIn("-line 2", udiff)
        self.assertIn("+line 2 modified", udiff)
        self.assertIn("+line 4", udiff)

    def test_3way_merge_clean_and_conflict(self):
        base = ["A", "B", "C"]
        ours = ["A", "B modified ours", "C"]
        theirs = ["A", "B", "C added theirs"]

        merged, conflicts = three_way_merge(base, ours, theirs)
        self.assertEqual(conflicts, 0)
        self.assertIn("B modified ours", merged)
        self.assertIn("C added theirs", merged)

        # Conflict case
        theirs_conflicting = ["A", "B modified theirs", "C"]
        merged_c, conflicts_c = three_way_merge(base, ours, theirs_conflicting)
        self.assertGreater(conflicts_c, 0)
        merged_str = "\n".join(merged_c)
        self.assertIn("<<<<<<< OURS", merged_str)
        self.assertIn("=======", merged_str)
        self.assertIn(">>>>>>> THEIRS", merged_str)

    def test_packfile_delta_compression(self):
        store = ObjectStore(self.test_dir)
        packer = Packer(store)

        base_data = b"function main() {\n  console.log('v1');\n}"
        target_data = b"function main() {\n  console.log('v2 updated');\n}"

        base_sha = store.store_blob_bytes(base_data)
        target_sha = store.store_blob_bytes(target_data)

        # Pack loose objects
        pack_name = packer.pack_objects([base_sha, target_sha])
        self.assertTrue(pack_name.startswith("pack-"))

        # Transparent read from packfile
        obj_type, body = store.read_object(target_sha)
        self.assertEqual(body, target_data)

    def test_ignore_matching(self):
        with open(".vcsignore", "w", encoding="utf-8") as f:
            f.write("node_modules/\n*.log\n.env\ndist/*\n")

        ignore = IgnoreMatcher(self.test_dir)
        self.assertTrue(ignore.is_ignored("node_modules/express/index.js"))
        self.assertTrue(ignore.is_ignored("app.log"))
        self.assertTrue(ignore.is_ignored(".env"))
        self.assertTrue(ignore.is_ignored("dist/bundle.js"))
        self.assertFalse(ignore.is_ignored("src/index.js"))

    def test_repository_lifecycle(self):
        Repository.init(self.test_dir)
        repo = Repository(self.test_dir)

        with open("index.html", "w", encoding="utf-8") as f:
            f.write("<h1>Hello pyvcs</h1>")

        repo.stage("index.html")
        c1 = repo.save("Initial commit")

        with open("index.html", "w", encoding="utf-8") as f:
            f.write("<h1>Hello pyvcs (edited)</h1>")

        modified, deleted, added, untracked = repo.get_status_lists()
        self.assertIn("index.html", modified)

        # Test revert
        repo.revert("index.html")
        with open("index.html", "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "<h1>Hello pyvcs</h1>")

        # Test undo
        repo.undo()
        self.assertEqual(repo._get_head_commit(), "")

    def test_branching_and_stash(self):
        Repository.init(self.test_dir)
        repo = Repository(self.test_dir)

        with open("app.js", "w", encoding="utf-8") as f:
            f.write("console.log('base');")
        repo.stage("app.js")
        repo.save("base commit")

        # Create branch
        repo.branch_mgr.create("feature", switch_to=True)
        self.assertEqual(repo._current_branch(), "feature")

        with open("app.js", "w", encoding="utf-8") as f:
            f.write("console.log('feature work');")

        # Test stash
        repo.stash.push()
        with open("app.js", "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "console.log('base');")

        repo.stash.pop()
        with open("app.js", "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "console.log('feature work');")


class TestRemoteSync(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.remotes_dir = tempfile.mkdtemp(prefix="pyvcs_remotes_")
        cls.port = 5099
        cls.server_thread = threading.Thread(
            target=run_server,
            kwargs={"port": cls.port, "root_dir": cls.remotes_dir},
            daemon=True
        )
        cls.server_thread.start()
        time.sleep(0.3)  # Wait for HTTP server startup

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.remotes_dir, ignore_errors=True)

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="pyvcs_client_")
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_remote_push_fetch_clone(self):
        Repository.init(self.test_dir)
        repo = Repository(self.test_dir)

        with open("README.md", "w", encoding="utf-8") as f:
            f.write("# My Web Project")
        repo.stage(".")
        repo.save("Initial remote push test")

        client = RemoteClient(repo)
        remote_url = f"http://localhost:{self.port}/testrepo"
        client.add_remote("origin", remote_url)

        # Push to remote server
        client.push(token=DEFAULT_AUTH_TOKEN)

        # Clone into a new directory
        clone_dir = os.path.join(self.test_dir, "cloned_repo")
        RemoteClient.clone(remote_url, target_dir=clone_dir, token=DEFAULT_AUTH_TOKEN)

        cloned_readme = os.path.join(clone_dir, "README.md")
        self.assertTrue(os.path.exists(cloned_readme))
        with open(cloned_readme, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "# My Web Project")

if __name__ == "__main__":
    unittest.main()

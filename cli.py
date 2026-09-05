import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from pyvcs.repo import Repository
    from pyvcs.remote import RemoteClient
    from pyvcs.server import run_server
    from pyvcs.dashboard import run_dashboard
except ImportError:
    from repo import Repository
    from remote import RemoteClient
    from server import run_server
    from dashboard import run_dashboard

HELP_TEXT = """pyvcs - Modern Version Control System

[Repository Operations]
  vcs init [dir]                 Initialize a new repository
  vcs stage <file|dir|.>         Stage changes for commit
  vcs unstage <file>             Unstage changes from index
  vcs save -m "message"          Create a commit snapshot of staged changes
  vcs status                     View working directory & staging status
  vcs log                        Display commit history log
  vcs show <commit|tag>          Inspect details of a commit
  vcs diff [<commit|tag>]        Show unified diff of changes
  vcs blame <file>               Show line-by-line commit authorship

[Branching & Merging]
  vcs branch                     List all branches
  vcs branch <name>              Create a new branch
  vcs branch -d <name>           Delete a branch
  vcs switch <name>              Switch to branch
  vcs switch -c <name>           Create and switch to branch
  vcs merge <branch>             Merge specified branch into active branch

[Edits, Restores, & Shelving]
  vcs revert <file>              Discard local edits (restore from HEAD)
  vcs restore <commit|tag>       Restore whole project state to a past snapshot
  vcs undo                       Undo last commit (keep changes staged)
  vcs stash                      Shelve local uncommitted changes
  vcs stash pop                  Re-apply shelved changes
  vcs gc                         Compress objects into packfiles & prune

[Tags]
  vcs tag                        List all tags
  vcs tag <name> ["message"]     Create a new tag
  vcs tag -d <name>              Delete tag

[Remote Synchronization & GitHub Hosting]
  vcs remote add <name> <url>    Add remote server URL
  vcs push                       Upload local commits to pyvcs server
  vcs pull                       Fetch and merge remote updates
  vcs fetch                      Download missing objects from remote
  vcs clone <url> [dir]          Clone remote repository locally
  vcs server [port]              Run pyvcs HTTP remote server (default: 5000)
  vcs github <repo-url> [branch] Push tracked files directly to GitHub (no git binary needed)
  vcs dashboard [port]           Launch local web UI (status/log/push/github) (default: 8000)
"""

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP_TEXT)
        return

    cmd = args[0]
    cmd_args = args[1:]

    if cmd == "init":
        target = cmd_args[0] if cmd_args else "."
        Repository.init(target)
        return

    if cmd == "clone":
        if not cmd_args:
            raise SystemExit("Usage: vcs clone <url> [dir]")
        url = cmd_args[0]
        dest = cmd_args[1] if len(cmd_args) > 1 else None
        RemoteClient.clone(url, dest)
        return

    if cmd == "server":
        port = int(cmd_args[0]) if cmd_args else 5000
        run_server(port=port)
        return

    if cmd == "dashboard":
        port = int(cmd_args[0]) if cmd_args else 8000
        run_dashboard(port=port)
        return

    repo = Repository()

    if cmd == "stage":
        target = cmd_args[0] if cmd_args else "."
        repo.stage(target)

    elif cmd == "unstage":
        if not cmd_args:
            raise SystemExit("Usage: vcs unstage <file>")
        repo.unstage(cmd_args[0])

    elif cmd == "save":
        msg = "Update"
        if "-m" in cmd_args:
            idx = cmd_args.index("-m")
            if idx + 1 < len(cmd_args):
                msg = " ".join(cmd_args[idx + 1:])
        repo.save(msg)

    elif cmd == "status":
        repo.status()

    elif cmd == "log":
        repo.log()

    elif cmd == "show":
        if not cmd_args:
            raise SystemExit("Usage: vcs show <commit|tag>")
        repo.show(cmd_args[0])

    elif cmd == "diff":
        ref = cmd_args[0] if cmd_args else None
        repo.diff(ref)

    elif cmd == "blame":
        if not cmd_args:
            raise SystemExit("Usage: vcs blame <file>")
        repo.blame(cmd_args[0])

    elif cmd == "switch":
        if not cmd_args:
            raise SystemExit("Usage: vcs switch [-c] <branch>")
        if cmd_args[0] == "-c":
            if len(cmd_args) < 2:
                raise SystemExit("Usage: vcs switch -c <branch>")
            repo.branch_mgr.switch(cmd_args[1], create=True)
        else:
            repo.branch_mgr.switch(cmd_args[0], create=False)

    elif cmd == "branch":
        if not cmd_args:
            repo.branch_mgr.list_branches()
        elif cmd_args[0] == "-d":
            if len(cmd_args) < 2:
                raise SystemExit("Usage: vcs branch -d <name>")
            repo.branch_mgr.delete(cmd_args[1])
        else:
            repo.branch_mgr.create(cmd_args[0])

    elif cmd == "merge":
        if not cmd_args:
            raise SystemExit("Usage: vcs merge <branch>")
        repo.branch_mgr.merge(cmd_args[0])

    elif cmd == "revert":
        if not cmd_args:
            raise SystemExit("Usage: vcs revert <file>")
        repo.revert(cmd_args[0])

    elif cmd == "restore":
        if not cmd_args:
            raise SystemExit("Usage: vcs restore <commit|tag>")
        repo.restore(cmd_args[0])

    elif cmd == "undo":
        repo.undo()

    elif cmd == "stash":
        if cmd_args and cmd_args[0] == "pop":
            repo.stash.pop()
        else:
            repo.stash.push()

    elif cmd == "tag":
        if not cmd_args or cmd_args[0] == "-l":
            repo.tagger.list_tags()
        elif cmd_args[0] == "-d":
            if len(cmd_args) < 2:
                raise SystemExit("Usage: vcs tag -d <name>")
            repo.tagger.delete(cmd_args[1])
        else:
            name = cmd_args[0]
            msg = " ".join(cmd_args[1:]) if len(cmd_args) > 1 else ""
            repo.tagger.create(name, msg)

    elif cmd == "remote":
        if len(cmd_args) >= 3 and cmd_args[0] == "add":
            client = RemoteClient(repo)
            client.add_remote(cmd_args[1], cmd_args[2])
        else:
            print("Usage: vcs remote add <name> <url>")

    elif cmd == "push":
        client = RemoteClient(repo)
        client.push()

    elif cmd == "fetch":
        client = RemoteClient(repo)
        client.fetch()

    elif cmd == "pull":
        client = RemoteClient(repo)
        client.pull()

    elif cmd == "github":
        if not cmd_args:
            raise SystemExit("Usage: vcs github <https://github.com/username/repository.git> [branch]")
        client = RemoteClient(repo)
        branch = cmd_args[1] if len(cmd_args) > 1 else "main"
        client.github_sync(cmd_args[0], branch=branch)

    elif cmd == "gc":
        repo.gc()

    else:
        print(f"Unknown command: '{cmd}'")
        print(HELP_TEXT)

if __name__ == "__main__":
    main()

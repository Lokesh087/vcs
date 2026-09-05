"""
pyvcs Dashboard — a lightweight local web UI for pyvcs.

Ye module standard library (http.server) ke alawa kuch use nahi karta,
isliye koi extra pip install nahi chahiye. `vcs dashboard [port]` chalate
hi browser mein status/log/branches/tags/diff dikhta hai, aur stage,
save, push, pull, fetch, aur GitHub push seedhe UI se ho jaate hain.
"""

import os
import io
import json
import contextlib
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    from pyvcs.repo import Repository
    from pyvcs.remote import RemoteClient
except ImportError:
    from repo import Repository
    from remote import RemoteClient

DEFAULT_PORT = 8000


def _capture(fn, *args, **kwargs) -> str:
    """Run a repo/branch/tag method that prints to stdout and capture its text."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        buf.write(f"\n{e}")
    except Exception as e:
        buf.write(f"\nError: {e}")
    return buf.getvalue()


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>pyvcs dashboard</title>
<style>
  :root {{
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  header {{
    padding: 14px 24px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }}
  header h1 {{ font-size: 16px; margin: 0; color: var(--text); }}
  header .branch {{
    background: var(--panel); border: 1px solid var(--border);
    padding: 4px 10px; border-radius: 6px; font-size: 13px; color: var(--accent);
  }}
  main {{ padding: 20px 24px; display: grid; grid-template-columns: 1.1fr 1fr; gap: 18px; max-width: 1200px; margin: 0 auto; }}
  @media (max-width: 860px) {{ main {{ grid-template-columns: 1fr; }} }}
  .card {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; overflow: auto;
  }}
  .card h2 {{
    font-size: 13px; text-transform: uppercase; letter-spacing: .04em;
    color: var(--muted); margin: 0 0 10px 0;
  }}
  pre {{
    white-space: pre-wrap; word-break: break-word; font-size: 12.5px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    margin: 0; line-height: 1.5;
  }}
  form {{ display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }}
  input[type=text] {{
    flex: 1; min-width: 140px; background: #0d1117; border: 1px solid var(--border);
    color: var(--text); padding: 7px 10px; border-radius: 6px; font-size: 13px;
  }}
  button {{
    background: var(--accent); border: none; color: #0d1117; font-weight: 600;
    padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
  }}
  button.secondary {{ background: var(--panel); color: var(--text); border: 1px solid var(--border); }}
  button.green {{ background: var(--green); }}
  .row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }}
  .full {{ grid-column: 1 / -1; }}
  .msg {{ font-size: 12.5px; color: var(--yellow); margin: 0 0 10px 0; }}
</style>
</head>
<body>
<header>
  <h1>&#9679; pyvcs dashboard</h1>
  <span class="branch">branch: {branch}</span>
</header>
<main>
  {message_html}

  <div class="card full">
    <h2>Actions</h2>
    <form method="POST" action="/action/stage">
      <input type="text" name="target" placeholder="file or . (all)" value=".">
      <button type="submit">Stage</button>
    </form>
    <form method="POST" action="/action/save">
      <input type="text" name="message" placeholder="commit message" required>
      <button type="submit" class="green">Save (commit)</button>
    </form>
    <div class="row">
      <form method="POST" action="/action/push"><button type="submit">Push (pyvcs remote)</button></form>
      <form method="POST" action="/action/pull"><button type="submit" class="secondary">Pull</button></form>
      <form method="POST" action="/action/fetch"><button type="submit" class="secondary">Fetch</button></form>
    </div>
    <form method="POST" action="/action/github">
      <input type="text" name="url" placeholder="https://github.com/user/repo.git" value="{github_url}">
      <button type="submit">Push to GitHub</button>
    </form>
  </div>

  <div class="card">
    <h2>Status</h2>
    <pre>{status}</pre>
  </div>
  <div class="card">
    <h2>Branches &amp; Tags</h2>
    <pre>{branches}
{tags}</pre>
  </div>
  <div class="card full">
    <h2>Log</h2>
    <pre>{log}</pre>
  </div>
  <div class="card full">
    <h2>Diff (working directory vs HEAD)</h2>
    <pre>{diff}</pre>
  </div>
</main>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    repo_root = "."
    last_message = ""

    def log_message(self, fmt, *args):
        pass  # keep terminal quiet

    def _repo(self):
        return Repository(self.repo_root)

    def _render(self):
        repo = self._repo()
        branch = repo._current_branch()
        status = _capture(repo.status) or "(clean)"
        log = _capture(repo.log) or "No commits yet."
        branches = _capture(repo.branch_mgr.list_branches) or "(no branches)"
        tags = _capture(repo.tagger.list_tags) or "(no tags)"
        diff = _capture(repo.diff) or "(no differences)"

        client = RemoteClient(repo)
        remote_cfg = client._load_remote()
        github_url = remote_cfg.get("url", "") if remote_cfg else ""

        message_html = ""
        if DashboardHandler.last_message:
            message_html = f'<p class="msg full">{DashboardHandler.last_message}</p>'
            DashboardHandler.last_message = ""

        html = PAGE_TEMPLATE.format(
            branch=branch,
            status=status,
            log=log,
            branches=branches,
            tags=tags,
            diff=diff,
            github_url=github_url,
            message_html=message_html,
        )
        return html.encode("utf-8")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = self._render()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        fields = {k: v[0] for k, v in parse_qs(body).items()}

        repo = self._repo()
        action = parsed.path.replace("/action/", "")

        try:
            if action == "stage":
                target = fields.get("target", ".")
                out = _capture(repo.stage, target)
                DashboardHandler.last_message = out.strip() or "Staged."
            elif action == "save":
                msg = fields.get("message", "Update")
                out = _capture(repo.save, msg)
                DashboardHandler.last_message = out.strip() or "Saved."
            elif action == "push":
                client = RemoteClient(repo)
                out = _capture(client.push)
                DashboardHandler.last_message = out.strip() or "Pushed."
            elif action == "pull":
                client = RemoteClient(repo)
                out = _capture(client.pull)
                DashboardHandler.last_message = out.strip() or "Pulled."
            elif action == "fetch":
                client = RemoteClient(repo)
                out = _capture(client.fetch)
                DashboardHandler.last_message = out.strip() or "Fetched."
            elif action == "github":
                url = fields.get("url", "").strip()
                if not url:
                    DashboardHandler.last_message = "GitHub URL required."
                else:
                    client = RemoteClient(repo)
                    out = _capture(client.github_sync, url)
                    DashboardHandler.last_message = out.strip() or "GitHub sync attempted."
            else:
                DashboardHandler.last_message = f"Unknown action '{action}'."
        except Exception as e:
            DashboardHandler.last_message = f"Error: {e}"

        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()


def run_dashboard(port: int = DEFAULT_PORT, root_dir: str = ".", open_browser: bool = True):
    DashboardHandler.repo_root = root_dir
    # Fail fast with a clear message if not a pyvcs repo
    Repository(root_dir)

    server = HTTPServer(("localhost", port), DashboardHandler)
    url = f"http://localhost:{port}"
    print(f"pyvcs dashboard running at {url}  (Ctrl+C to stop)")

    if open_browser:
        def _try_open():
            try:
                webbrowser.open(url)
            except Exception:
                pass  # headless environments (e.g. servers, containers) just skip this
        threading.Timer(0.5, _try_open).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    import sys
    p = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run_dashboard(port=p)

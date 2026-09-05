import os
import sys
import json
import base64
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

DEFAULT_PORT = 5000
DEFAULT_AUTH_TOKEN = "pyvcs-secret-token"
REPOS_ROOT = "./remotes"

# Global dictionary of thread locks per repository branch
REF_LOCKS = {}
LOCKS_GUARD = threading.Lock()

def get_ref_lock(repo_name: str, branch_name: str) -> threading.Lock:
    key = f"{repo_name}:{branch_name}"
    with LOCKS_GUARD:
        if key not in REF_LOCKS:
            REF_LOCKS[key] = threading.Lock()
        return REF_LOCKS[key]


class VCSServerHandler(BaseHTTPRequestHandler):

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _verify_auth(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        expected = f"Bearer {os.environ.get('PYVCS_AUTH_TOKEN', DEFAULT_AUTH_TOKEN)}"
        if auth_header == expected:
            return True
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if len(parts) >= 2 and parts[1] == "info":
            repo_name = parts[0]
            repo_dir = os.path.join(REPOS_ROOT, repo_name)
            refs_file = os.path.join(repo_dir, "refs.json")
            refs = {}
            if os.path.exists(refs_file):
                with open(refs_file, "r", encoding="utf-8") as f:
                    refs = json.load(f)
            self._send_json(200, {"status": "ok", "branches": refs})
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        if not self._verify_auth():
            self._send_json(401, {"error": "Unauthorized: Invalid or missing Bearer token"})
            return

        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        payload = json.loads(body.decode("utf-8")) if body else {}

        if len(parts) >= 2 and parts[1] == "push":
            repo_name = parts[0]
            branch = payload.get("branch", "main")
            head = payload.get("head", "")
            objects = payload.get("objects", {})

            repo_dir = os.path.join(REPOS_ROOT, repo_name)
            obj_dir = os.path.join(repo_dir, "objects")
            os.makedirs(obj_dir, exist_ok=True)

            lock = get_ref_lock(repo_name, branch)
            with lock:
                # Store missing objects
                for sha, b64_data in objects.items():
                    sub = sha[:2]
                    fn = sha[2:]
                    sub_dir = os.path.join(obj_dir, sub)
                    os.makedirs(sub_dir, exist_ok=True)
                    obj_path = os.path.join(sub_dir, fn)
                    if not os.path.exists(obj_path):
                        with open(obj_path, "wb") as f:
                            f.write(base64.b64decode(b64_data))

                # Update remote refs safely under lock
                refs_file = os.path.join(repo_dir, "refs.json")
                refs = {}
                if os.path.exists(refs_file):
                    with open(refs_file, "r", encoding="utf-8") as f:
                        refs = json.load(f)

                refs[branch] = head
                with open(refs_file, "w", encoding="utf-8") as f:
                    json.dump(refs, f, indent=2)

            self._send_json(200, {"status": "ok", "branch": branch, "head": head})

        elif len(parts) >= 2 and parts[1] == "fetch":
            repo_name = parts[0]
            have = set(payload.get("have", []))
            repo_dir = os.path.join(REPOS_ROOT, repo_name)
            refs_file = os.path.join(repo_dir, "refs.json")

            refs = {}
            if os.path.exists(refs_file):
                with open(refs_file, "r", encoding="utf-8") as f:
                    refs = json.load(f)

            objects_out = {}
            obj_dir = os.path.join(repo_dir, "objects")
            if os.path.exists(obj_dir):
                for sub in os.listdir(obj_dir):
                    sub_p = os.path.join(obj_dir, sub)
                    if os.path.isdir(sub_p):
                        for fn in os.listdir(sub_p):
                            sha = sub + fn
                            if sha not in have:
                                with open(os.path.join(sub_p, fn), "rb") as f:
                                    objects_out[sha] = base64.b64encode(f.read()).decode("utf-8")

            self._send_json(200, {"status": "ok", "refs": refs, "objects": objects_out})
        else:
            self._send_json(404, {"error": "Endpoint not found"})


def run_server(port: int = DEFAULT_PORT, root_dir: str = "./remotes"):
    global REPOS_ROOT
    REPOS_ROOT = os.path.abspath(root_dir)
    os.makedirs(REPOS_ROOT, exist_ok=True)
    server_address = ("", port)
    httpd = HTTPServer(server_address, VCSServerHandler)
    print(f"pyvcs HTTP Remote Server running on http://localhost:{port} (repos root: {REPOS_ROOT})")
    httpd.serve_forever()

if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run_server(port=p)

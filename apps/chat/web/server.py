# server.py -- CodexChat web server (Python port of server.ps1 for non-Windows hosts).
# Serves static files and the chat API with the same routes, JSON shapes, and
# state file as the PowerShell original.
import json
import os
import secrets
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8280
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(WEB_DIR, "data", "chat-state.json")

state_lock = threading.Lock()
state = {
    "accounts": {},   # name -> {name, token, pubkey, contacts[], convIds[]}
    "sessions": {},   # token -> name
    "convs": {},      # convId -> {id, type, members[], messages[], name, created}
    "nextConvId": 1,
    "nextMsgId": 1,
}


def save_state():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def load_state():
    if not os.path.exists(STATE_FILE):
        return
    with open(STATE_FILE) as f:
        loaded = json.load(f)
    state.update(loaded)
    print(f"  Loaded {len(state['accounts'])} accounts, {len(state['convs'])} conversations")


def get_user(token):
    name = state["sessions"].get(token)
    return state["accounts"].get(name) if name else None


def new_token():
    return secrets.token_hex(8)


def handle_api(path, q):
    def qv(key):
        return q.get(key, [""])[0]

    if path == "/api/chat/register":
        name = qv("name")
        if not name:
            return {"error": "name required"}
        account = state["accounts"].get(name)
        if account:
            state["sessions"][account["token"]] = name
            save_state()
            return {"token": account["token"], "name": name}
        tok = new_token()
        state["accounts"][name] = {"name": name, "token": tok, "pubkey": "", "contacts": [], "convIds": []}
        state["sessions"][tok] = name
        save_state()
        return {"token": tok, "name": name}

    if path == "/api/chat/me":
        user = get_user(qv("t"))
        if not user:
            return {"error": "auth"}
        return {"name": user["name"]}

    if path == "/api/chat/conversations":
        user = get_user(qv("t"))
        if not user:
            return {"error": "auth"}
        result = {"count": str(len(user["convIds"]))}
        for i, cid in enumerate(user["convIds"]):
            conv = state["convs"].get(cid)
            if not conv:
                continue
            others = [m for m in conv["members"] if m != user["name"]]
            other = others[0] if others else conv["name"]
            last = conv["messages"][-1] if conv["messages"] else None
            result[f"name-{i}"] = conv["name"] if conv["type"] == "group" else other
            result[f"preview-{i}"] = last["body"][:40] if last else "No messages yet"
            result[f"time-{i}"] = last["time"] if last else ""
            result[f"id-{i}"] = cid
        return result

    if path == "/api/chat/messages":
        user = get_user(qv("t"))
        if not user:
            return {"error": "auth"}
        conv = state["convs"].get(qv("conv"))
        if not conv:
            return {"count": "0"}
        result = {"count": str(len(conv["messages"]))}
        for i, m in enumerate(conv["messages"]):
            result[f"body-{i}"] = m["body"]
            result[f"sender-{i}"] = m["sender"]
            result[f"time-{i}"] = m["time"]
            result[f"mine-{i}"] = "1" if m["sender"] == user["name"] else "0"
        return result

    if path == "/api/chat/send":
        user = get_user(qv("t"))
        if not user:
            return {"error": "auth"}
        body = qv("body")
        if not body:
            return {"error": "empty"}
        conv = state["convs"].get(qv("to"))
        if not conv:
            return {"error": "no conv"}
        msg = {"id": state["nextMsgId"], "sender": user["name"], "body": body,
               "time": datetime.now().strftime("%H:%M")}
        state["nextMsgId"] += 1
        conv["messages"].append(msg)
        save_state()
        return {"ok": True}

    if path == "/api/chat/start":
        user = get_user(qv("t"))
        if not user:
            return {"error": "auth"}
        with_name = qv("with")
        if not with_name:
            return {"error": "with required"}
        other = state["accounts"].get(with_name)
        if not other:
            tok2 = new_token()
            other = {"name": with_name, "token": tok2, "pubkey": "", "contacts": [], "convIds": []}
            state["accounts"][with_name] = other
            state["sessions"][tok2] = with_name
        for cid in user["convIds"]:
            c = state["convs"].get(cid)
            if c and c["type"] == "dm" and with_name in c["members"]:
                return {"convId": cid}
        conv_id = f"c{state['nextConvId']}"
        state["nextConvId"] += 1
        state["convs"][conv_id] = {"id": conv_id, "type": "dm", "members": [user["name"], with_name],
                                   "messages": [], "name": "", "created": datetime.now().isoformat()}
        user["convIds"].append(conv_id)
        other["convIds"].append(conv_id)
        save_state()
        return {"convId": conv_id}

    if path == "/api/chat/contacts":
        user = get_user(qv("t"))
        if not user:
            return {"error": "auth"}
        result = {"count": str(len(user["contacts"]))}
        for i, name in enumerate(user["contacts"]):
            result[f"name-{i}"] = name
        return result

    if path == "/api/chat/group":
        user = get_user(qv("t"))
        if not user:
            return {"error": "auth"}
        gname = qv("name")
        if not gname:
            return {"error": "name required"}
        members = [user["name"]]
        if qv("members"):
            members += [m.strip() for m in qv("members").split(",")
                        if m.strip() and m.strip() != user["name"]]
        conv_id = f"c{state['nextConvId']}"
        state["nextConvId"] += 1
        state["convs"][conv_id] = {"id": conv_id, "type": "group", "members": members,
                                   "messages": [], "name": gname, "created": datetime.now().isoformat()}
        for m in members:
            acc = state["accounts"].get(m)
            if acc:
                acc["convIds"].append(conv_id)
        save_state()
        return {"convId": conv_id}

    return {"error": "not found"}


MIME_TYPES = {
    ".html": "text/html;charset=utf-8", ".css": "text/css", ".js": "application/javascript",
    ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    def _serve(self):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            with state_lock:
                payload = json.dumps(handle_api(url.path, parse_qs(url.query)))
            buf = payload.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(buf)))
            self.end_headers()
            self.wfile.write(buf)
            return
        path = url.path if url.path != "/" else "/chat.html"
        file = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if file.startswith(WEB_DIR) and os.path.isfile(file):
            ext = os.path.splitext(file)[1]
            with open(file, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", MIME_TYPES.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404")

    do_GET = _serve
    do_POST = _serve

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    load_state()
    print(f"\n  CodexChat at http://localhost:{PORT}/\n")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

"""Local JSON-RPC proxy for anvil forks: upstream tx-hash lookups answer null
(public nodes reject them with an 'archive' 403), everything else forwarded."""
import json, sys, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = sys.argv[1]
NULL_METHODS = {"eth_getTransactionReceipt", "eth_getTransactionByHash"}

def handle(req):
    if req.get("method") in NULL_METHODS:
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": None}
    return None

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        batch = isinstance(body, list)
        reqs = body if batch else [body]
        local = [handle(r) for r in reqs]
        fwd = [r for r, l in zip(reqs, local) if l is None]
        remote = {}
        if fwd:
            data = json.dumps(fwd if batch else fwd[0]).encode()
            for attempt in range(5):
                try:
                    r = urllib.request.Request(UPSTREAM, data=data, headers={"Content-Type": "application/json", "User-Agent": "rpc-proxy"})
                    out = json.loads(urllib.request.urlopen(r, timeout=60).read())
                    break
                except Exception as e:
                    err = e
            else:
                out = [{"jsonrpc": "2.0", "id": q.get("id"), "error": {"code": -32000, "message": str(err)}} for q in fwd]
            for o in (out if isinstance(out, list) else [out]):
                remote[json.dumps(o.get("id"))] = o
        res = [l if l is not None else remote.get(json.dumps(r.get("id"))) for r, l in zip(reqs, local)]
        payload = json.dumps(res if batch else res[0]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

ThreadingHTTPServer.request_queue_size = 256
ThreadingHTTPServer.daemon_threads = True
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()

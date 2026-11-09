"""Local rating page for experiment 31: python3.15 serve.py, then open http://localhost:8731.

Serves index.html, data.json, and the clips in .local/exp31-tts; POST /rate appends to ../human-ratings.jsonl.
The clips and lines come from her real save and are explicit. It listens on localhost only; to let her rate
from her house, publish it with `tailscale funnel --bg --set-path /rate-sims-banter 8731`, and `tailscale funnel reset` afterwards.
"""
import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
AUDIO = HERE.parents[2] / '.local' / 'exp31-tts'
RATINGS = HERE.parent / 'human-ratings.jsonl'


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def translate_path(self, path):
        if path.startswith('/audio/'):
            return str(AUDIO / Path(path[len('/audio/'):]).name)
        return super().translate_path(path)

    def do_GET(self):
        path = urlsplit(self.path).path  # Without the query, so '/key.json?x' can't slip past the check below.
        if path == '/ratings':
            rows = [json.loads(l) for l in RATINGS.open(encoding='utf-8')] if RATINGS.exists() else []
            body = json.dumps(rows, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return
        if path.endswith('key.json'):
            self.send_error(404)  # Keep it blind.
            return
        super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/rate':
            self.send_error(404)
            return
        row = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        row['ts'] = time.time()
        with RATINGS.open('a', encoding='utf-8', newline='\n') as f:  # LF, like the rest of the repo (Windows text mode would write CRLF).
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.send_response(204)
        self.end_headers()


if __name__ == '__main__':
    print('http://localhost:8731', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8731), Handler).serve_forever()

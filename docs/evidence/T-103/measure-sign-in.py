"""量測：4 個 POST /sign-in 同時進行時，GET /health 的延遲。用法：python3 measure.py <PORT>"""
import sys, threading, time, urllib.request, urllib.parse
port = sys.argv[1]; base = f"http://127.0.0.1:{port}"
def sign_in():
    data = urllib.parse.urlencode({"name": "Wen", "password": "correct"}).encode()
    class NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    try: urllib.request.build_opener(NoRedir).open(urllib.request.Request(base + "/sign-in", data=data))
    except urllib.error.HTTPError as e: assert e.code == 303, e.code
def health():
    t = time.perf_counter(); urllib.request.urlopen(base + "/health").read(); return time.perf_counter() - t
print(f"idle GET /health: {health()*1000:.0f} ms")
ts = [threading.Thread(target=sign_in) for _ in range(4)]
t0 = time.perf_counter(); [t.start() for t in ts]; time.sleep(0.1)
print(f"GET /health during 4 concurrent sign-ins: {health()*1000:.0f} ms")
[t.join() for t in ts]; print(f"4 sign-ins finished in {time.perf_counter()-t0:.2f} s")

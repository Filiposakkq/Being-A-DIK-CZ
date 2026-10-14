import sys, time, http.client, tempfile, os
sys.path.insert(0, 'tools/translation-manager')
os.environ["PREHLED_CONFIG_DIR"] = tempfile.mkdtemp()
from prehled.app import App
from prehled.config import Config
from prehled import server
app = App(Config().load())
srv, sess, url = server.start_server(app)
port = srv.server_address[1]
def get(path="/app.js"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    c.request("GET", path); r = c.getresponse(); b = r.read(); c.close(); return len(b)
t = time.time(); fails = 0
for i in range(100):
    try: get()
    except Exception as e: fails += 1; last = repr(e)
print("sequential 100: fails", fails, "time", round(time.time()-t, 2), "s")
for path in ("/app.js", "/styles.css", "/api/ping"):
    t = time.time(); fails = 0
    for i in range(60):
        try: get(path)
        except Exception as e: fails += 1; last = repr(e)
    print(path, "fails", fails, round(time.time()-t, 2), "s")

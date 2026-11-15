# 差分模糊測試：隨機產生 URI，比較 parse_libpq_uri 與 libpq PQconninfoParse 對 host/hostaddr 的看法。
# 只解析字串，不連線。
import random, sys
sys.path.insert(0, ".")
from psycopg.conninfo import conninfo_to_dict
from app.core.local_url import parse_libpq_uri, UnsafeDatabaseUrl
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
atoms = ["localhost","127.0.0.1","[::1]","remote-db.invalid","@","?","#",":","/",",","%2F","%40","%3F","&","=","u","pw","5433","yc",
         "host=","hostaddr=","hostaddr=127.0.0.1","host=remote-db.invalid","[","]","%","%00","%zz","+"," "]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200000
agree = refused = libpq_err = 0; bad = []
for _ in range(N):
    url = random.choice(["postgresql://","postgres://"]) + "".join(random.choice(atoms) for _ in range(random.randint(0, 8)))
    try:
        theirs = conninfo_to_dict(url)
    except Exception:
        theirs = None
    try:
        ours = parse_libpq_uri(url)
    except UnsafeDatabaseUrl:
        refused += 1; continue
    if theirs is None:
        libpq_err += 1; continue   # 我們接受、libpq 拒絕：不會連線，無害；計數
    if any(ours.get(k) != theirs.get(k) for k in ("host", "hostaddr")):
        bad.append((url, ours, theirs))
    else:
        agree += 1
print(f"N={N} agree={agree} refused_by_us={refused} accepted_by_us_but_libpq_error={libpq_err} DISAGREE={len(bad)}")
for b in bad[:10]: print(b)

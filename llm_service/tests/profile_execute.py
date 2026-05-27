"""Profile /api/v1/execute — pinpoint 2s overhead with raw ASGI timing.

Run: python llm_service/tests/profile_execute.py

Decomposition via raw ASGI middleware (wraps send()):
  wall        = client round trip
  handler_ms  = ASGI scope start → http.response.start (X-Handler-Ms header)
  send_ms     = http.response.start → last body chunk sent to socket (temp file)
  server_total = handler + send (full server-side lifecycle)
  client_oh   = wall - server_total (true client transport overhead)
"""
import json
import os
import time
import urllib.request

BASE = "http://localhost:8900"
TIMING_FILE = os.path.join(os.environ.get("TEMP", "/tmp"), "llm_service_timing.json")

payload = {
    "pipeline_stage": "query_understanding",
    "template_key": "serving-query-understanding",
    "input": {"query": "SMF是什么网元"},
    "caller_service": "serving",
    "knowledge_domain": "cloud_core_network",
}

# warm up
print("Warming up...")
urllib.request.urlopen(
    urllib.request.Request(BASE + "/api/v1/execute", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}),
    timeout=60,
).read()

print()
print("=" * 100)
print("  /api/v1/execute — raw ASGI lifecycle: WHERE is the 2s?")
print("=" * 100)
print(f"  {'#':>3}  {'wall':>6}  {'handler':>8}  {'send_body':>10}  {'srv_total':>10}  {'client_oh':>10}  {'http_post':>9}")
print(f"  {'':>3}  {'':>6}  {'(→resp.start)':>8}  {'(→last byte)':>10}  {'(full srv)':>10}  {'(wall-srv)':>10}  {'(LLM net)':>9}")
print("  " + "-" * 96)

all_rows = []
for i in range(5):
    # Delete old timing file
    try:
        os.remove(TIMING_FILE)
    except OSError:
        pass

    req = urllib.request.Request(BASE + "/api/v1/execute", data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body_raw = resp.read().decode()
        handler_ms = int(resp.headers.get("X-Handler-Ms", "-1"))
    wall = (time.perf_counter() - t0) * 1000

    # Read server timing from temp file
    srv_total = handler_ms
    send_ms = 0
    try:
        with open(TIMING_FILE) as f:
            timing = json.load(f)
        srv_total = timing.get("total_ms", handler_ms)
        send_ms = timing.get("send_ms", 0)
    except Exception:
        pass

    d = json.loads(body_raw).get("data", {})
    prof = d.get("_profiling", {})
    http_post = prof.get("http_post_ms", 0)
    client_oh = wall - srv_total

    row = dict(wall=wall, handler=handler_ms, send=send_ms, srv_total=srv_total,
               client_oh=client_oh, http_post=http_post)
    all_rows.append(row)

    print(
        f"  {i+1:3d}  {wall:6.0f}  {handler_ms:8d}  {send_ms:10d}  {srv_total:10d}  {client_oh:10.0f}  {http_post:9d}"
    )

# averages
import statistics
walls = [r["wall"] for r in all_rows]
med_w = statistics.median(walls)
filtered = [r for r in all_rows if r["wall"] < med_w * 2]
if len(filtered) < 3:
    filtered = all_rows[:4]

n = len(filtered)
def avg(key): return sum(r[key] for r in filtered) / n

print("  " + "-" * 96)
print(
    f"  avg {avg('wall'):6.0f}  {avg('handler'):8.0f}  {avg('send'):10.0f}  {avg('srv_total'):10.0f}  {avg('client_oh'):10.0f}  {avg('http_post'):9.0f}"
)
print()
print(f"  === 定位结论 ===")
print(f"  1. LLM 纯网络调用:       {avg('http_post'):8.0f} ms  ({avg('http_post')/avg('wall')*100:.0f}% of wall)")
print(f"  2. handler 开销:          {avg('handler') - avg('http_post'):8.0f} ms  (template+parse+框架)")
print(f"  3. response send:         {avg('send'):8.0f} ms  (handler返回 → 最后字节写入socket)")
print(f"  4. client transport:      {avg('client_oh'):8.0f} ms  (wall - server_total)")
print(f"  总计 wall:                {avg('wall'):8.0f} ms")
print()
if avg('send') > 500:
    print(f"  >>> 根因: response send 耗 {avg('send'):.0f}ms — uvicorn/ASGI 发送响应慢 <<<")
elif avg('client_oh') > 500:
    print(f"  >>> 根因: client transport 耗 {avg('client_oh'):.0f}ms — HTTP 传输层开销 <<<")
elif avg('handler') > avg('http_post') * 1.5:
    print(f"  >>> 根因: handler 耗 {avg('handler'):.0f}ms — 业务代码开销 <<<")
else:
    print(f"  >>> 无明显瓶颈，各环节均正常 <<<")

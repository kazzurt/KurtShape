"""Exercise the actual open GUI document over the assistant transport."""
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.request
from assistant_client import send,ROOT

start=time.perf_counter()
listing=send({"op":"list_documents"})
assert listing["ok"]
state=listing["result"]["documents"][-1]
baseline=state["measurements"]["volume_mm3"]
original=dict(state)
request={"op":"set_parameter","document_id":state["document_id"],"expected_revision":state["revision"],"feature":"Pad","parameter":"Length","value":8}
reply=send(request)
assert reply["ok"],reply
state=reply["result"]
assert abs(state["measurements"]["volume_mm3"]-(2400-math.pi*16)*8)<1e-6
stale=send(request)
assert not stale["ok"] and stale["error"]["code"]=="stale_revision",stale
reply=send({"op":"undo","document_id":state["document_id"],"expected_revision":state["revision"]})
assert reply["ok"],reply
state=reply["result"]
assert abs(state["measurements"]["volume_mm3"]-baseline)<1e-6
session=json.loads((ROOT/"runtime"/"assistant-session.json").read_text())
unauthorized=urllib.request.Request(session["url"],data=b'{"op":"list_documents"}',headers={"Content-Type":"application/json"},method="POST")
try:
    urllib.request.build_opener(urllib.request.ProxyHandler({})).open(unauthorized,timeout=5)
    raise AssertionError("Unauthenticated operation accepted")
except urllib.error.HTTPError as exc:
    assert exc.code==403
report={"passed":True,"seconds":time.perf_counter()-start,"document_id":state["document_id"],
        "baseline_volume_mm3":baseline,"edited_volume_mm3":(2400-math.pi*16)*8,"roundtrip_ms":reply["result"]["operation_ms"],
        "checks":["Codex CLI inspects live GUI native document","actual thickness edit to 8 mm","stale replay rejected","native undo restores baseline","unauthenticated request rejected"],
        "Claude_client":"not configured or exercised; transport is reusable, acceptance remains pending"}
(ROOT/"validation"/"live-bridge-result.json").write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))

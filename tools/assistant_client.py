"""Same local operations for Codex/Claude/manual tooling; stdlib, no cloud access.

python -B tools/assistant_client.py --request-file examples/inspect-request.json
python -B tools/assistant_client.py --json '{"op":"list_documents"}'
"""
import argparse
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def send(request,session_path=None):
    session=json.loads(Path(session_path or ROOT/"runtime"/"assistant-session.json").read_text())
    message=urllib.request.Request(session["url"],data=json.dumps(request).encode(),
        headers={"Authorization":"Bearer "+session["token"],"Content-Type":"application/json"},method="POST")
    # Loopback never uses system proxies or external services.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(message,timeout=35) as response:
        return json.loads(response.read())


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--json")
    choice.add_argument("--request-file",type=Path)
    parser.add_argument("--session", type=Path, help="Session file for an explicitly selected application instance")
    args=parser.parse_args()
    request=json.loads(args.json if args.json else args.request_file.read_text())
    result=send(request,args.session)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["ok"] else 1)

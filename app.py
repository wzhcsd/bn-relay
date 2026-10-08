"""
Binance Futures Relay —— Render 部署版

端点：
  /ping                        健康检查（出口 IP + 币安连通性）
  /diag                        详细诊断（逐个币安接口）
  /fapi/<path>                 转发到 fapi.binance.com/fapi/<path>
  /dapi/<path>                 转发到 dapi.binance.com/dapi/<path>
  /spot/<path>                 转发到 api.binance.com/api/<path>

示例：
  /fapi/v1/klines?symbol=ETHUSDT&interval=1m&limit=1500
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

UPSTREAM = {
    "fapi": "https://fapi.binance.com/fapi",
    "dapi": "https://dapi.binance.com/dapi",
    "spot": "https://api.binance.com/api",
}

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "no-store",
}


def fetch_raw(target, timeout=25):
    """取原始响应，返回 (status, body_bytes, ms, ctype, error)"""
    t0 = time.time()
    try:
        req = urllib.request.Request(target, headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return (r.status, body, int((time.time() - t0) * 1000),
                    r.headers.get("Content-Type"), None)
    except urllib.error.HTTPError as e:
        body = e.read()
        return (e.code, body, int((time.time() - t0) * 1000),
                e.headers.get("Content-Type"), None)
    except Exception as e:
        return (0, b"", int((time.time() - t0) * 1000), None,
                f"{type(e).__name__}: {str(e)[:90]}")


DIAG_TARGETS = [
    ("fapi/v1/time", "https://fapi.binance.com/fapi/v1/time"),
    ("fapi klines ETH 1m",
     "https://fapi.binance.com/fapi/v1/klines?symbol=ETHUSDT&interval=1m&limit=2"),
    ("fapi klines BTC 1m",
     "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=2"),
    ("fapi ticker/24hr",
     "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT"),
    ("fapi fundingRate",
     "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=2"),
    ("fapi exchangeInfo", "https://fapi.binance.com/fapi/v1/exchangeInfo"),
    ("dapi/v1/time", "https://dapi.binance.com/dapi/v1/time"),
    ("dapi klines",
     "https://dapi.binance.com/dapi/v1/klines?symbol=BTCUSD_PERP&interval=1m&limit=2"),
    ("api.binance.com time", "https://api.binance.com/api/v3/time"),
    ("spot klines",
     "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=2"),
    ("data-api.vision time", "https://data-api.binance.vision/api/v3/time"),
    ("vision archive 10-06",
     "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/"
     "BTCUSDT-1m-2026-10-06.zip"),
]


@app.get("/")
def index():
    return jsonify({
        "ok": True,
        "service": "binance-futures-relay",
        "endpoints": ["/ping", "/diag", "/fapi/*", "/dapi/*", "/spot/*"],
        "example": "/fapi/v1/klines?symbol=ETHUSDT&interval=1m&limit=1500",
    })


@app.get("/ping")
def ping():
    out = {"ok": True, "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "egress": {}, "quick": {}}
    for name, url in [
        ("ipv4", "https://api.ipify.org?format=json"),
        ("ipv6", "https://api64.ipify.org?format=json"),
        ("ipinfo", "https://ipinfo.io/json"),
    ]:
        st, body, ms, _, err = fetch_raw(url, timeout=12)
        out["egress"][name] = err or body[:250].decode("utf-8", "replace")
    for name, url in [
        ("fapi", "https://fapi.binance.com/fapi/v1/time"),
        ("spot", "https://api.binance.com/api/v3/time"),
    ]:
        st, body, ms, ctype, err = fetch_raw(url, timeout=12)
        out["quick"][name] = {
            "status": st, "ms": ms, "bytes": len(body),
            "preview": body[:170].decode("utf-8", "replace").replace("\n", " "),
            "error": err,
        }
    resp = Response(json.dumps(out, indent=2, ensure_ascii=False),
                    mimetype="application/json")
    resp.headers.update(CORS)
    return resp


@app.get("/diag")
def diag():
    out = {"now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "egress": {}, "tests": []}
    for name, url in [
        ("ipv4", "https://api.ipify.org?format=json"),
        ("ipv6", "https://api64.ipify.org?format=json"),
        ("ipinfo", "https://ipinfo.io/json"),
    ]:
        st, body, ms, _, err = fetch_raw(url, timeout=12)
        out["egress"][name] = err or body[:300].decode("utf-8", "replace")
    for name, target in DIAG_TARGETS:
        st, body, ms, ctype, err = fetch_raw(target, timeout=20)
        rec = {"name": name, "target": target, "status": st, "ms": ms,
               "bytes": len(body), "ctype": ctype,
               "preview": body[:260].decode("utf-8", "replace").replace("\n", " ")}
        if err:
            rec["error"] = err
        try:
            j = json.loads(body.decode())
            if isinstance(j, list) and j:
                rec["parsed"] = "array"
                rec["sample"] = json.dumps(j[-1])[:170]
                if isinstance(j[0], list) and len(j[0]) > 5:
                    rec["is_kline"] = True
            elif isinstance(j, dict):
                rec["parsed"] = "object"
                if "serverTime" in j:
                    rec["has_serverTime"] = True
        except Exception:
            pass
        out["tests"].append(rec)
    resp = Response(json.dumps(out, indent=2, ensure_ascii=False),
                    mimetype="application/json")
    resp.headers.update(CORS)
    return resp


@app.route("/<seg>/<path:rest>", methods=["GET", "OPTIONS"])
def relay(seg, rest):
    if request.method == "OPTIONS":
        return Response("", status=204, headers=CORS)
    base = UPSTREAM.get(seg)
    if not base:
        return Response(json.dumps({
            "error": "unknown segment", "allowed": list(UPSTREAM),
        }), status=403, mimetype="application/json", headers=CORS)
    target = f"{base}/{rest}"
    if request.query_string:
        target += "?" + request.query_string.decode()
    st, body, ms, ctype, err = fetch_raw(target, timeout=30)
    if err:
        return Response(json.dumps({"error": "upstream failed",
                                    "target": target, "message": err}),
                        status=502, mimetype="application/json", headers=CORS)
    resp = Response(body, status=st, mimetype=ctype or "application/json")
    resp.headers["X-Upstream-Status"] = str(st)
    resp.headers["X-Upstream-Url"] = target
    resp.headers.update(CORS)
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

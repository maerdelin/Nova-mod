#!/usr/bin/env python3
"""External API probe of OpenList 189CloudPC QR endpoints, no account required.

Returns only stage/status metadata. Never print UUID, cookies, lt, reqId,
paramId, redirectURL, bearer tokens or full API response bodies.
"""
import http.cookiejar
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

APP_ID = "9317140619"
RETURN_URL = "https://m.cloud.189.cn/zhuanti/2020/loginErrorPc/index.html"
AUTH = "https://open.e.189.cn"
WEB = "https://cloud.189.cn"
STAGE = "INIT"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
headers_common = {"User-Agent": "Mozilla/5.0", "Accept": "application/json;charset=UTF-8"}

def request(method, url, params=None, form=None, headers=None):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    h = dict(headers_common)
    if headers: h.update(headers)
    req = urllib.request.Request(url,data=data,headers=h,method=method)
    with opener.open(req,timeout=15) as r:
        return r.geturl(),r.read(1000000).decode("utf-8","replace"),r.status

try:
    STAGE="UNIFY"
    url,body,code=request("GET",WEB+"/api/portal/unifyLoginForPC.action",
        params={"appId":APP_ID,"clientType":"10020","returnURL":RETURN_URL,
                "timeStamp":str(int(time.time()*1000))})
    u=urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    lt=u.get("lt",[""])[0] or ((re.search(r'lt = "([^"]+)"',body) or [None,""])[1])
    reqid=u.get("reqId",[""])[0] or ((re.search(r'reqId = "([^"]+)"',body) or [None,""])[1])
    paramid=((re.search(r'paramId = "([^"]+)"',body) or [None,""])[1])
    if not lt or not reqid: raise RuntimeError("challenge_fields_missing")
    print("QR_PROBE_UNIFY=PASS")
    if not urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("lt"):
        referer=AUTH+"/api/logbox/separate/web/index.html?"+urllib.parse.urlencode(
            {"appId":APP_ID,"lt":lt,"reqId":reqid})
    else:referer=url
    hd={"REQID":reqid,"lt":lt,"user-finger":str(secrets.randbelow(9000000000)+1000000000),"Referer":referer}
    if not paramid:
        STAGE="APP_CONF"
        _,raw,code=request("POST",AUTH+"/api/logbox/oauth2/appConf.do",
            form={"version":"2.0","appKey":APP_ID},headers=hd)
        conf=json.loads(raw)
        paramid=conf.get("data",{}).get("paramId","")
        if not paramid:raise RuntimeError("paramId_missing")
        print("QR_PROBE_APP_CONF=PASS")
    STAGE="GET_UUID"
    _,raw,code=request("POST",AUTH+"/api/logbox/oauth2/getUUID.do",
        form={"appId":APP_ID},headers=hd)
    q=json.loads(raw)
    uuid=q.get("uuid","");enc=q.get("encryuuid","")
    if not uuid:raise RuntimeError("uuid_missing")
    print("QR_PROBE_GET_UUID=PASS (contents not logged)")
    STAGE="QR_POLL"
    now=datetime.now()
    _,raw,code=request("POST",AUTH+"/api/logbox/oauth2/qrcodeLoginState.do",
        form={"appId":APP_ID,"clientType":"1","returnUrl":RETURN_URL,
              "paramId":paramid,"uuid":uuid,"encryuuid":enc,"cb_SaveName":"3",
              "isOauth2":"false","state":"","date":now.strftime("%Y-%m-%d%H:%M:%S.%f")[:-3],
              "timeStamp":str(int(time.time()*1000))},headers=hd)
    status=json.loads(raw).get("status",-999)
    if status not in [-106,-11002,0]:raise RuntimeError("unexpected_scan_state_"+str(status))
    print("QR_PROBE_POLL=PASS (waiting for human authorization)")
except Exception as err:
    print("QR_PROBE_FAIL_STAGE="+STAGE)
    print("QR_PROBE_ERROR_CLASS="+err.__class__.__name__)
    if isinstance(err,urllib.error.HTTPError):print("QR_PROBE_HTTP="+str(err.code))
    raise SystemExit(1)

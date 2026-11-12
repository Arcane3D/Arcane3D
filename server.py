"""Image to DXF: MCP server + OAuth 2.1 sign-up/login for ChatGPT plugins. Run: uvicorn server:app"""
import base64, hashlib, hmac, html, io, ipaddress, json, os, secrets, socket, sqlite3, time
import urllib.parse as up
import cv2, ezdxf, httpx, numpy as np
from ezdxf import units
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from PIL import Image
from starlette.concurrency import run_in_threadpool
from svgelements import SVG, Close, Path, Shape

BASE = os.environ["BASE_URL"].rstrip("/")
MCP = BASE + "/mcp"
SECRET = os.environ["SECRET_KEY"].encode()
DB = os.environ.get("DB_PATH", "data/app.db")
FILES = os.environ.get("FILES_DIR", "data/files")
REDIRECTS = [r for r in os.environ.get("ALLOWED_REDIRECTS", "https://chatgpt.com/connector_platform_oauth_redirect,https://chatgpt.com/connector/oauth/").split(",") if r]
SCOPE = "dxf:convert"
PARAMS = ("client_id", "redirect_uri", "state", "code_challenge", "resource")
os.makedirs(FILES, exist_ok=True)
os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
with db() as c:
    c.executescript("create table if not exists users(id integer primary key, email text unique, pw text); create table if not exists clients(id text primary key, redirects text); create table if not exists codes(code text primary key, uid int, cid text, uri text, chal text, res text, exp real); create table if not exists refresh(tok text primary key, uid int, cid text, exp real);")
def hash_pw(pw, salt=None):
    salt = salt or os.urandom(16); return salt.hex() + ":" + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()
def check_pw(pw, stored): return hmac.compare_digest(hash_pw(pw, bytes.fromhex(stored.split(":")[0])), stored)
def b64(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def sign(d):
    p = b64(json.dumps(d).encode()); return p + "." + b64(hmac.new(SECRET, p.encode(), "sha256").digest())
def unsign(t):
    try:
        p, s = t.split(".")
        if hmac.compare_digest(s, b64(hmac.new(SECRET, p.encode(), "sha256").digest())):
            d = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))); return d if d["exp"] > time.time() else None
    except Exception: pass
    return None
tries = {}
def throttled(key):
    now = time.time(); t = [x for x in tries.get(key, []) if now-x < 600] + [now]; tries[key] = t; return len(t)>10

def fetch(url):
    u = up.urlparse(url)
    if u.scheme != "https" or not u.hostname: raise ValueError("The file link must be https.")
    for ai in socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP):
        if not ipaddress.ip_address(ai[4][0]).is_global: raise ValueError("Blocked file link.")
    r = httpx.get(url, timeout=20); r.raise_for_status()
    if len(r.content)>15_000_000: raise ValueError("File is larger than 15 MB.")
    return r.content

def raster_loops(data, thr, invert, tol_mm, width_mm, min_mm=0.5):
    im=Image.open(io.BytesIO(data))
    if im.width*im.height>40_000_000: raise ValueError("Image is too large (over 40 megapixels).")
    a=np.array(im.convert("RGBA")); px=width_mm/a.shape[1]
    if a[...,3].min()<250: mask=(a[...,3]>127).astype(np.uint8)*255
    else:
        g=cv2.GaussianBlur(cv2.cvtColor(a[...,:3],cv2.COLOR_RGB2GRAY),(3,3),0); mode=cv2.THRESH_BINARY if invert else cv2.THRESH_BINARY_INV
        mask=cv2.threshold(g,thr,255,mode|(0 if thr else cv2.THRESH_OTSU))[1]
    cs,hier=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_NONE); out=[]
    for c,hh in zip(cs,hier[0] if hier is not None else []):
        if cv2.contourArea(c)*px*px<min_mm**2: continue
        c=cv2.approxPolyDP(c,max(0.5,tol_mm/px),True)[:,0,:]
        if len(c)>=3: out.append((c.astype(float),True,"INNER" if hh[3]!=-1 else "OUTER"))
    return out

def svg_loops(data):
    out=[]
    for e in SVG.parse(io.BytesIO(data),reify=True).elements():
        if not isinstance(e,Shape): continue
        p=Path(e); p.reify()
        for sp in p.as_subpaths():
            sp=Path(sp)
            if len(sp)<2: continue
            arr=np.array([[q.x,q.y] for q in (sp.point(t) for t in np.linspace(0,1,24*len(sp)+1))])
            closed=bool(np.allclose(arr[0],arr[-1],atol=1e-6) or any(isinstance(s,Close) for s in sp))
            out.append((arr[:-1] if closed else arr,closed,"PATHS"))
    return out

def to_dxf(loops,width_mm,path):
    allp=np.vstack([p for p,_,_ in loops]); lo,hi=allp.min(0),allp.max(0); s=width_mm/max(hi[0]-lo[0],1e-9)
    doc=ezdxf.new("R2010"); doc.units=units.MM
    for name,col in (("OUTER",7),("INNER",1),("PATHS",7)): doc.layers.add(name,color=col)
    msp=doc.modelspace()
    for p,closed,layer in loops:
        msp.add_lwpolyline([((x-lo[0])*s,(hi[1]-y)*s) for x,y in p],close=closed,dxfattribs={"layer":layer})
    doc.saveas(path); return round(width_mm,3),round((hi[1]-lo[1])*s,3)
def file_url(name): return f"{BASE}/files/{name}?t="+sign({"n":name,"exp":time.time()+3600})
def convert(a):
    f=a.get("image") or {}; width,tol=float(a.get("width_mm",100)),float(a.get("tolerance_mm",0.1))
    if not 1<=width<=5000: raise ValueError("width_mm must be between 1 and 5000.")
    data=fetch(f["download_url"]); is_svg=b"<svg" in data[:2048].lower() or str(f.get("mime_type","")).endswith("svg+xml") or str(f.get("file_name","")).lower().endswith(".svg")
    loops=svg_loops(data) if is_svg else raster_loops(data,int(a.get("threshold",0)),bool(a.get("invert",False)),tol,width)
    if not loops: raise ValueError("No shapes found. Try a different threshold, or turn on invert.")
    name=secrets.token_hex(8)+".dxf"; w,h=to_dxf(loops,width,os.path.join(FILES,name))
    for n in os.listdir(FILES):
        p=os.path.join(FILES,n)
        if time.time()-os.path.getmtime(p)>3600: os.remove(p)
    return {"download_url":file_url(name),"width_mm":w,"height_mm":h,"entities":len(loops)}

FILE_DEF={"type":"object","properties":{"download_url":{"type":"string"},"file_id":{"type":"string"},"mime_type":{"type":"string"},"file_name":{"type":"string"}},"required":["download_url","file_id"],"additionalProperties":False}
AUTH=[{"type":"oauth2","scopes":[SCOPE]}]
TOOL={"name":"image_to_dxf","title":"Convert image to DXF","description":"Convert an attached PNG, image, logo or SVG into a scaled DXF outline for CAD, CNC and laser cutting. Best for silhouettes and line art; photos become black-and-white contours.","inputSchema":{"type":"object","$defs":{"OpenAIFile":FILE_DEF},"properties":{"image":{"$ref":"#/$defs/OpenAIFile","description":"The image or SVG attached by the user."},"width_mm":{"type":"number","description":"Finished drawing width in millimetres.","default":100},"threshold":{"type":"integer","description":"Raster threshold 1-254; 0 selects automatically.","default":0},"invert":{"type":"boolean","description":"Trace light shapes on a dark background.","default":False},"tolerance_mm":{"type":"number","description":"Outline simplification tolerance in millimetres.","default":0.1}},"required":["image"],"additionalProperties":False},"annotations":{"readOnlyHint":True,"destructiveHint":False,"openWorldHint":False},"securitySchemes":AUTH,"_meta":{"openai/fileParams":["image"],"securitySchemes":AUTH}}
def who(request):
    h=request.headers.get("authorization",""); d=unsign(h[7:]) if h.lower().startswith("bearer ") else None
    return d if d and str(d.get("aud","")).rstrip("/") in (BASE,MCP) and SCOPE in d.get("scope","").split() else None
def need_login():
    ch=f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource", error="insufficient_scope", error_description="Log in to use Image to DXF"'
    return {"isError":True,"content":[{"type":"text","text":"Log in to connect your Image to DXF account."}],"_meta":{"mcp/www_authenticate":[ch]}}
async def call_tool(request,p):
    if p.get("name")!="image_to_dxf": return {"isError":True,"content":[{"type":"text","text":"Unknown tool."}]}
    if not who(request): return need_login()
    try: r=await run_in_threadpool(convert,p.get("arguments") or {})
    except Exception as e:
        msg=str(e) if isinstance(e,ValueError) else "Could not read that file as an image or SVG."
        return {"isError":True,"content":[{"type":"text","text":msg}]}
    return {"content":[{"type":"text","text":f"DXF ready: {r['width_mm']} x {r['height_mm']} mm, {r['entities']} paths. Download: {r['download_url']} (link expires in 1 hour)"}],"structuredContent":r}
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
@app.post("/mcp")
async def mcp(request:Request):
    m=await request.json(); i,meth=m.get("id"),m.get("method")
    if i is None: return Response(status_code=202)
    ok=lambda r:{"jsonrpc":"2.0","id":i,"result":r}
    if meth=="initialize":
        v=(m.get("params") or {}).get("protocolVersion","2025-06-18")
        return ok({"protocolVersion":v,"capabilities":{"tools":{}},"serverInfo":{"name":"image-to-dxf","version":"1.0.0"}})
    if meth=="tools/list": return ok({"tools":[TOOL]})
    if meth=="ping": return ok({})
    if meth=="tools/call": return ok(await call_tool(request,m.get("params") or {}))
    return {"jsonrpc":"2.0","id":i,"error":{"code":-32601,"message":"Method not found"}}
@app.get("/files/{name}")
def get_file(name:str,t:str=""):
    d=unsign(t)
    if not d or d.get("n")!=name or os.path.basename(name)!=name or not os.path.exists(os.path.join(FILES,name)): return Response(status_code=404)
    return FileResponse(os.path.join(FILES,name),media_type="application/dxf",filename=name)
@app.get("/")
def home(): return {"service":"image-to-dxf","mcp":MCP}
@app.get("/.well-known/openai-apps-challenge")
def challenge(): return Response(os.environ.get("OPENAI_CHALLENGE",""),media_type="text/plain")
@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
def prm(): return {"resource":BASE,"authorization_servers":[BASE],"scopes_supported":[SCOPE]}
@app.get("/.well-known/oauth-authorization-server")
def asm():
    return {"issuer":BASE,"authorization_endpoint":BASE+"/authorize","token_endpoint":BASE+"/token","registration_endpoint":BASE+"/register","response_types_supported":["code"],"grant_types_supported":["authorization_code","refresh_token"],"code_challenge_methods_supported":["S256"],"token_endpoint_auth_methods_supported":["none"],"client_id_metadata_document_supported":False,"authorization_response_iss_parameter_supported":True,"scopes_supported":[SCOPE]}
def ok_redirect(u): return any(u==r or (r.endswith("/") and u.startswith(r)) for r in REDIRECTS)
@app.post("/register")
async def register(request:Request):
    b=await request.json(); uris=b.get("redirect_uris") or []
    if not uris or not all(ok_redirect(u) for u in uris): return JSONResponse({"error":"invalid_redirect_uri"},400)
    cid=secrets.token_urlsafe(16)
    with db() as c: c.execute("insert into clients values(?,?)",(cid,json.dumps(uris)))
    return JSONResponse({"client_id":cid,"redirect_uris":uris,"token_endpoint_auth_method":"none","grant_types":["authorization_code","refresh_token"],"response_types":["code"],"client_name":str(b.get("client_name",""))[:100]},201)
def client_ok(cid,uri):
    with db() as c: r=c.execute("select redirects from clients where id=?",(cid,)).fetchone()
    return bool(r) and uri in json.loads(r["redirects"])
def redir(q,**p):
    p["iss"]=BASE
    if q.get("state"): p["state"]=q["state"]
    return q["redirect_uri"]+("&" if "?" in q["redirect_uri"] else "?")+up.urlencode(p)
PAGE="""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Log in to Image to DXF</title><style>:root{--bg:#eef1f4;--card:#fff;--ink:#101820;--mut:#56636e;--line:#c7d0d8;--acc:#0b57d0;--on:#fff;--err:#b3261e;color-scheme:light dark}@media(prefers-color-scheme:dark){:root{--bg:#0f151b;--card:#161e26;--ink:#e8edf1;--mut:#97a4af;--line:#2b3742;--acc:#7db0ff;--on:#08121f;--err:#ff9a90}}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}main{display:grid;gap:2rem;width:min(56rem,100% - 2rem);padding:2rem 0}@media(min-width:760px){main{grid-template-columns:1.1fr 1fr;align-items:center}}h1{font-size:clamp(1.9rem,5vw,2.8rem);line-height:1.05;margin:1rem 0 .75rem;letter-spacing:-.02em}p{margin:0;color:var(--mut);max-width:34ch}form{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1.5rem;display:grid;gap:1rem}label.f{display:grid;gap:.35rem;font-size:.9rem}input{font:inherit;padding:.7rem .8rem;border:1px solid var(--line);border-radius:8px;background:transparent;color:var(--ink)}button{font:inherit;font-weight:600;padding:.8rem;border:0;border-radius:8px;background:var(--acc);color:var(--on);cursor:pointer}.err{color:var(--err);min-height:1.2em;font-size:.9rem}</style><main><section><h1>Image to DXF for ChatGPT</h1><p>Log in or create an account to connect the plugin. Converted files are deleted after an hour.</p></section><form method=post action=/authorize>{{HIDDEN}}<p class=err role=alert>{{ERR}}</p><label class=f>Email<input name=email type=email required autocomplete=email></label><label class=f>Password<input name=password type=password required></label><button name=mode value=login>Log in and connect</button><button name=mode value=signup>Create account and connect</button><p>Passwords need at least 10 characters.</p></form></main>"""
def page(q,err=""):
    hid="".join(f'<input type=hidden name={k} value="{html.escape(q.get(k) or "",True)}">' for k in PARAMS)
    return HTMLResponse(PAGE.replace("{{HIDDEN}}",hid).replace("{{ERR}}",html.escape(err)),headers={"Cache-Control":"no-store","X-Frame-Options":"DENY"})
@app.get("/authorize")
def authorize(request:Request):
    q=dict(request.query_params)
    if not client_ok(q.get("client_id"),q.get("redirect_uri")): return HTMLResponse("Unknown client or redirect URI.",400)
    if q.get("response_type")!="code" or q.get("code_challenge_method")!="S256" or not q.get("code_challenge"): return RedirectResponse(redir(q,error="invalid_request"),303)
    return page(q)
@app.post("/authorize")
async def authorize_post(request:Request):
    f=dict((await request.form()).items()); q={k:f.get(k,"") for k in PARAMS}
    if not client_ok(q["client_id"],q["redirect_uri"]) or not q["code_challenge"]: return HTMLResponse("Invalid request.",400)
    email,pw,mode=f.get("email","").strip().lower(),f.get("password",""),f.get("mode","login")
    if throttled((request.client.host,email)): return page(q,"Too many attempts. Try again in 10 minutes.")
    with db() as c:
        if mode=="signup":
            if "@" not in email or len(pw)<10: return page(q,"Use a valid email and a password of at least 10 characters.")
            try: uid=c.execute("insert into users(email,pw) values(?,?)",(email,hash_pw(pw))).lastrowid
            except sqlite3.IntegrityError: return page(q,"That email already has an account. Log in instead.")
        else:
            r=c.execute("select id,pw from users where email=?",(email,)).fetchone()
            if not r or not check_pw(pw,r["pw"]): return page(q,"Email or password is incorrect.")
            uid=r["id"]
        code=secrets.token_urlsafe(32); c.execute("insert into codes values(?,?,?,?,?,?,?)",(code,uid,q["client_id"],q["redirect_uri"],q["code_challenge"],q["resource"],time.time()+300))
    return RedirectResponse(redir(q,code=code),303)
@app.post("/token")
async def token(request:Request):
    f=dict((await request.form()).items()); now=time.time(); err=lambda e:JSONResponse({"error":e},400,headers={"Cache-Control":"no-store"})
    with db() as c:
        if f.get("grant_type")=="authorization_code":
            r=c.execute("select * from codes where code=?",(f.get("code"),)).fetchone(); c.execute("delete from codes where code=?",(f.get("code"),))
            if not r or r["exp"]<now or r["cid"]!=f.get("client_id") or r["uri"]!=f.get("redirect_uri"): return err("invalid_grant")
            if not hmac.compare_digest(b64(hashlib.sha256(f.get("code_verifier","").encode()).digest()),r["chal"]): return err("invalid_grant")
            uid,cid,res=r["uid"],r["cid"],r["res"] or BASE
        elif f.get("grant_type")=="refresh_token":
            r=c.execute("select * from refresh where tok=?",(f.get("refresh_token"),)).fetchone()
            if not r or r["exp"]<now or r["cid"]!=f.get("client_id"): return err("invalid_grant")
            c.execute("delete from refresh where tok=?",(r["tok"],)); uid,cid,res=r["uid"],r["cid"],f.get("resource") or BASE
        else: return err("unsupported_grant_type")
        rt=secrets.token_urlsafe(32); c.execute("insert into refresh values(?,?,?,?)",(rt,uid,cid,now+30*86400))
    at=sign({"sub":str(uid),"aud":res,"iss":BASE,"scope":SCOPE,"exp":now+3600})
    return JSONResponse({"access_token":at,"token_type":"Bearer","expires_in":3600,"refresh_token":rt,"scope":SCOPE},headers={"Cache-Control":"no-store"})

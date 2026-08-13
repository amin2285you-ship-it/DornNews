from flask import Flask, request, redirect, session, render_template_string, abort, send_from_directory, jsonify
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, uuid, html

app = Flask(__name__)
app.secret_key = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
socketio = SocketIO(app, cors_allowed_origins="*")

DB = "chat.db"
UPLOADS = "uploads"
BACKGROUNDS = "backgrounds"
MAX_FILE = 50 * 1024 * 1024
IMG_EXT = {"jpg","jpeg","png","gif","webp"}
VID_EXT = {"mp4","webm","mov","m4v"}

os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(BACKGROUNDS, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT DEFAULT '',
        password TEXT NOT NULL,
        verified INTEGER DEFAULT 0,
        is_admin INTEGER DEFAULT 0,
        background_url TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        message TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        media_type TEXT DEFAULT '',
        media_url TEXT DEFAULT '',
        original_name TEXT DEFAULT '',
        pinned INTEGER DEFAULT 0
    )""")
    uc = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
    if "display_name" not in uc:
        c.execute("ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT ''")
    if "background_url" not in uc:
        c.execute("ALTER TABLE users ADD COLUMN background_url TEXT DEFAULT ''")
    mc = {r["name"] for r in c.execute("PRAGMA table_info(messages)")}
    for col, typ in [
        ("media_type","TEXT DEFAULT ''"),("media_url","TEXT DEFAULT ''"),
        ("original_name","TEXT DEFAULT ''"),("pinned","INTEGER DEFAULT 0")
    ]:
        if col not in mc:
            c.execute(f"ALTER TABLE messages ADD COLUMN {col} {typ}")
    a = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not a:
        c.execute("""INSERT INTO users(username,display_name,password,verified,is_admin)
                     VALUES(?,?,?,?,?)""",
                  ("admin","Admin",generate_password_hash("admin123"),1,1))
    c.commit(); c.close()

def get_user(username):
    c=db()
    u=c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    c.close()
    return u

def logged():
    return "user" in session

def admin_only():
    if not logged() or not session.get("admin"):
        abort(403)

def ext(name):
    return name.rsplit(".",1)[1].lower() if "." in name else ""

STYLE = """
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b0e14;color:#fff;font-family:Arial,Tahoma,sans-serif;direction:rtl;min-height:100vh}
.container{max-width:780px;margin:auto;padding:10px}
.card{background:#171c26ee;border-radius:20px;padding:17px;margin-top:12px;box-shadow:0 8px 30px #0009}
input,textarea{width:100%;background:#252c39;color:#fff;border:0;outline:0;border-radius:12px;padding:13px;margin:6px 0;font-size:16px}
textarea{min-height:75px}
button,.btn{border:0;background:#347cff;color:#fff;padding:10px 14px;border-radius:11px;cursor:pointer;text-decoration:none;display:inline-block}
.danger{background:#d9364f}.green{background:#159957}.gray{background:#4b5563}.purple{background:#7c4dff}
a{color:#70a5ff;text-decoration:none}.blue{color:#3194ff;font-weight:bold}.small{font-size:12px;color:#aab3c2}
.top{display:flex;justify-content:space-between;align-items:center;gap:8px}.actions{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
#messages{height:55vh;min-height:300px;overflow-y:auto;padding:4px}
.message{background:#242b38ee;border-radius:14px;padding:10px 12px;margin:8px 0;word-break:break-word}
.message.pinned{border:1px solid #ffc107}.media{margin-top:8px}.img{max-width:100%;max-height:430px;border-radius:12px}.vid{width:100%;max-width:550px;max-height:430px;border-radius:12px;background:#000}
.user{background:#242b38;border-radius:13px;padding:13px;margin:8px 0}.stat{display:inline-block;background:#252c39;padding:7px 10px;border-radius:9px;margin:3px}
.online{color:#45e879}.pinbox{background:#302810;border:1px solid #ffc107;border-radius:13px;padding:10px;margin-bottom:10px}
</style>
"""
PAGE = "<!doctype html><html lang='fa'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>چت آنلاین</title>"+STYLE+"</head><body><div class='container'>{{content|safe}}</div></body></html>"

def page(x): return render_template_string(PAGE, content=x)

def msg_html(m):
    u=get_user(m["username"])
    name=(u["display_name"] if u and u["display_name"] else m["username"])
    badge=" 🔵" if u and u["verified"] else ""
    pin=" 📌" if m["pinned"] else ""
    text=html.escape(m["message"] or "")
    media=""
    if m["media_type"]=="image":
        media=f"<div class='media'><img class='img' src='{html.escape(m['media_url'],quote=True)}'></div>"
    elif m["media_type"]=="video":
        media=f"<div class='media'><video class='vid' controls src='{html.escape(m['media_url'],quote=True)}'></video></div>"
    admin_tools=""
    if session.get("admin"):
        admin_tools=f"<div class='actions'><button class='purple' onclick='pinMsg({m['id']},{str(not bool(m['pinned'])).lower()})'>{'📌 برداشتن پین' if m['pinned'] else '📌 پین'}</button></div>"
    return f"<div class='message {'pinned' if m['pinned'] else ''}' id='m{m['id']}'><b>{html.escape(name)}</b> <span class='small'>@{html.escape(m['username'])}</span>{badge}{pin}{('<div>'+text+'</div>') if text else ''}{media}{admin_tools}</div>"

@app.route("/")
def home():
    if logged(): return redirect("/chat")
    return page("""<div class='card'><h1>💬 چت آنلاین</h1>
    <form method='post' action='/login'><input name='username' placeholder='نام کاربری' required>
    <input name='password' type='password' placeholder='رمز عبور' required><button>ورود 🚀</button></form>
    <p>حساب نداری؟ <a href='/register'>ثبت‌نام</a></p></div>""")

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="GET":
        return page("""<div class='card'><h2>📝 ثبت‌نام</h2>
        <form method='post'><input name='username' placeholder='نام کاربری' required>
        <input name='password' type='password' placeholder='رمز عبور' required>
        <button>ساخت حساب</button></form><br><a href='/'>← بازگشت</a></div>""")
    name=request.form.get("username","").strip()
    pw=request.form.get("password","")
    if not 3<=len(name)<=30 or len(pw)<4:
        return page("<div class='card'><h2>❌ نام کاربری ۳ تا ۳۰ و رمز حداقل ۴ کاراکتر.</h2><a href='/register'>بازگشت</a></div>")
    c=db()
    try:
        c.execute("INSERT INTO users(username,display_name,password) VALUES(?,?,?)",
                  (name,name,generate_password_hash(pw)))
        c.commit()
    except sqlite3.IntegrityError:
        c.close()
        return page("<div class='card'><h2>❌ این نام کاربری قبلاً استفاده شده.</h2><a href='/register'>بازگشت</a></div>")
    c.close(); return redirect("/")

@app.route("/login",methods=["POST"])
def login():
    u=get_user(request.form.get("username","").strip())
    if u and check_password_hash(u["password"],request.form.get("password","")):
        session.clear(); session["user"]=u["username"]; session["admin"]=bool(u["is_admin"]); return redirect("/chat")
    return page("<div class='card'><h2>❌ اطلاعات ورود اشتباه است.</h2><a href='/'>بازگشت</a></div>")

@app.route("/logout")
def logout():
    session.clear(); return redirect("/")

@app.route("/chat")
def chat():
    if not logged(): return redirect("/")
    u=get_user(session["user"])
    c=db(); ms=c.execute("SELECT * FROM messages ORDER BY id").fetchall()
    pins=c.execute("SELECT * FROM messages WHERE pinned=1 ORDER BY id DESC").fetchall(); c.close()
    bg=""
    if u and u["background_url"]:
        bg=f"<style>body{{background:linear-gradient(#0008,#0008),url('{html.escape(u['background_url'],quote=True)}') center/cover fixed}}</style>"
    history="".join(msg_html(m) for m in ms)
    pinbox=""
    if pins:
        pinbox="<div class='pinbox'><b>📌 پیام‌های سنجاق‌شده</b>"+ "".join(
            f"<div><b>{html.escape((get_user(m['username'])['display_name'] if get_user(m['username']) else m['username']))}</b>: {html.escape(m['message'] or ('🖼️ تصویر' if m['media_type']=='image' else '🎥 ویدیو'))}</div>" for m in pins)+"</div>"
    admin_link="<a class='btn green' href='/admin'>👑 پنل مدیریت</a>" if session.get("admin") else ""
    return page(bg+f"""<div class='card'><div class='top'><h2>💬 چت آنلاین</h2><a href='/logout'>خروج</a></div>
    <p>👤 {html.escape(u['display_name'] or u['username'])} <span class='small'>@{html.escape(u['username'])}</span> {"🔵" if u['verified'] else ""}</p>
    <p class='online'>🟢 آنلاین</p>
    <div class='actions'><a class='btn purple' href='/background'>🎨 بک‌گراند من</a>
    <a class='btn gray' href='/settings'>⚙️ تنظیمات حساب</a>{admin_link}</div><hr>{pinbox}
    <div id='messages'>{history}</div>
    <form id='form'><textarea id='text' maxlength='2000' placeholder='پیامت را بنویس...'></textarea>
    <input id='file' type='file' accept='image/*,video/*'><button id='send'>ارسال 🚀</button></form></div>
    <script src='https://cdn.socket.io/4.7.5/socket.io.min.js'></script><script>
    const s=io(),box=document.getElementById('messages'),form=document.getElementById('form'),text=document.getElementById('text'),file=document.getElementById('file'),send=document.getElementById('send');
    s.on('new_message',d=>{{let x=document.createElement('div');x.className='message'+(d.pinned?' pinned':'');let b=document.createElement('b');b.textContent=d.display_name||d.username;x.appendChild(b);let sp=document.createElement('span');sp.className='small';sp.textContent=' @'+d.username+(d.verified?' 🔵':'');x.appendChild(sp);if(d.message){{let t=document.createElement('div');t.textContent=d.message;x.appendChild(t)}}if(d.media_type==='image'){{let i=document.createElement('img');i.className='img';i.src=d.media_url;x.appendChild(i)}}if(d.media_type==='video'){{let v=document.createElement('video');v.className='vid';v.controls=true;v.src=d.media_url;x.appendChild(v)}}box.appendChild(x);box.scrollTop=box.scrollHeight}});
    form.onsubmit=async e=>{{e.preventDefault();let f=file.files[0],t=text.value.trim();if(!t&&!f)return;send.disabled=true;try{{if(f){{let fd=new FormData();fd.append('file',f);fd.append('message',t);let r=await fetch('/upload',{{method:'POST',body:fd}});let j=await r.json();if(!j.ok)alert(j.error)}}else s.emit('send_message',{{message:t}});text.value='';file.value=''}}catch(e){{alert('خطا در ارسال')}}send.disabled=false}};box.scrollTop=box.scrollHeight;
    async function pinMsg(id,state){{let r=await fetch('/admin/pin/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{pinned:state}})}});let j=await r.json();if(j.ok)location.reload();else alert(j.error||'خطا')}}
    </script>""")

@socketio.on("send_message")
def socket_message(data):
    if not logged(): return
    text=str(data.get("message","")).strip()[:2000]
    if not text:return
    c=db(); u=c.execute("SELECT * FROM users WHERE username=?",(session["user"],)).fetchone()
    cur=c.execute("INSERT INTO messages(username,message) VALUES(?,?)",(session["user"],text)); mid=cur.lastrowid;c.commit();c.close()
    socketio.emit("new_message",{"id":mid,"username":session["user"],"display_name":u["display_name"] or session["user"],"message":text,"verified":bool(u["verified"]),"media_type":"","media_url":"","pinned":False})

@app.route("/upload",methods=["POST"])
def upload():
    if not logged(): return jsonify(ok=False,error="ابتدا وارد شوید"),401
    f=request.files.get("file")
    if not f or not f.filename:return jsonify(ok=False,error="فایلی انتخاب نشده"),400
    e=ext(f.filename)
    kind="image" if e in IMG_EXT else "video" if e in VID_EXT else ""
    if not kind:return jsonify(ok=False,error="فقط عکس یا ویدیو مجاز است"),400
    f.stream.seek(0,2); size=f.stream.tell();f.stream.seek(0)
    if size>MAX_FILE:return jsonify(ok=False,error="حداکثر حجم 50MB است"),413
    name=uuid.uuid4().hex+"."+e;f.save(os.path.join(UPLOADS,name))
    text=str(request.form.get("message","")).strip()[:2000]
    c=db();u=c.execute("SELECT * FROM users WHERE username=?",(session["user"],)).fetchone()
    cur=c.execute("""INSERT INTO messages(username,message,media_type,media_url,original_name)
                     VALUES(?,?,?,?,?)""",(session["user"],text,kind,"/uploads/"+name,f.filename))
    mid=cur.lastrowid;c.commit();c.close()
    socketio.emit("new_message",{"id":mid,"username":session["user"],"display_name":u["display_name"] or session["user"],"message":text,"verified":bool(u["verified"]),"media_type":kind,"media_url":"/uploads/"+name,"pinned":False})
    return jsonify(ok=True)

@app.route("/uploads/<path:n>")
def uploads(n): return send_from_directory(UPLOADS,n)

@app.route("/background",methods=["GET","POST"])
def background():
    if not logged():return redirect("/")
    if request.method=="GET":
        u=get_user(session["user"])
        current=f"<img class='img' src='{html.escape(u['background_url'],quote=True)}'>" if u["background_url"] else "<p>بک‌گراندی انتخاب نشده.</p>"
        return page(f"""<div class='card'><h2>🎨 بک‌گراند اختصاصی من</h2>{current}
        <form method='post' enctype='multipart/form-data'><input name='background' type='file' accept='image/*' required><button class='green'>ذخیره بک‌گراند</button></form>
        <form method='post' action='/background/remove'><button class='danger'>🗑️ حذف بک‌گراند</button></form><br><a href='/chat'>← چت</a></div>""")
    f=request.files.get("background")
    if not f:return redirect("/background")
    e=ext(f.filename)
    if e not in IMG_EXT:return page("<div class='card'><h2>❌ فقط تصویر.</h2><a href='/background'>بازگشت</a></div>")
    name=uuid.uuid4().hex+"."+e;f.save(os.path.join(BACKGROUNDS,name))
    c=db();c.execute("UPDATE users SET background_url=? WHERE username=?",("/backgrounds/"+name,session["user"]));c.commit();c.close()
    return redirect("/chat")

@app.route("/background/remove",methods=["POST"])
def background_remove():
    if not logged():return redirect("/")
    c=db();c.execute("UPDATE users SET background_url='' WHERE username=?",(session["user"],));c.commit();c.close();return redirect("/chat")

@app.route("/backgrounds/<path:n>")
def backgrounds(n):return send_from_directory(BACKGROUNDS,n)

@app.route("/settings",methods=["GET","POST"])
def settings():
    if not logged():return redirect("/")
    u=get_user(session["user"])
    if request.method=="GET":
        return page(f"""<div class='card'><h2>⚙️ تنظیمات حساب</h2>
        <form method='post'><input name='display_name' value='{html.escape(u["display_name"] or u["username"],quote=True)}' placeholder='نام نمایشی'>
        <input name='username' value='{html.escape(u["username"],quote=True)}' placeholder='نام کاربری' required>
        <input name='old_password' type='password' placeholder='رمز فعلی' required>
        <input name='new_password' type='password' placeholder='رمز جدید (اختیاری)'><button class='green'>💾 ذخیره</button></form>
        <br><a href='/chat'>← چت</a></div>""")
    nu=request.form.get("username","").strip();dn=request.form.get("display_name","").strip();old=request.form.get("old_password","");new=request.form.get("new_password","")
    if not 3<=len(nu)<=30:return page("<div class='card'><h2>❌ نام کاربری نامعتبر است.</h2><a href='/settings'>بازگشت</a></div>")
    if not check_password_hash(u["password"],old):return page("<div class='card'><h2>❌ رمز فعلی اشتباه است.</h2><a href='/settings'>بازگشت</a></div>")
    if new and len(new)<4:return page("<div class='card'><h2>❌ رمز جدید کوتاه است.</h2><a href='/settings'>بازگشت</a></div>")
    c=db()
    try:
        if new:c.execute("UPDATE users SET username=?,display_name=?,password=? WHERE id=?",(nu,dn or nu,generate_password_hash(new),u["id"]))
        else:c.execute("UPDATE users SET username=?,display_name=? WHERE id=?",(nu,dn or nu,u["id"]))
        c.execute("UPDATE messages SET username=? WHERE username=?",(nu,u["username"]));c.commit()
    except sqlite3.IntegrityError:c.close();return page("<div class='card'><h2>❌ این نام کاربری وجود دارد.</h2><a href='/settings'>بازگشت</a></div>")
    c.close(); adm=bool(u["is_admin"]);session.clear();session["user"]=nu;session["admin"]=adm;return redirect("/chat")

@app.route("/admin")
def admin():
    admin_only();c=db()
    users=c.execute("""SELECT u.*,COUNT(m.id) message_count FROM users u
                       LEFT JOIN messages m ON m.username=u.username GROUP BY u.id ORDER BY u.id DESC""").fetchall()
    total=c.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"];c.close()
    out=""
    for u in users:
        verify="" if u["is_admin"] else f"<form method='post' action='/admin/verify/{u['id']}' style='display:inline'><button class='{'danger' if u['verified'] else 'green'}'>{'حذف تیک' if u['verified'] else '🔵 تیک آبی'}</button></form>"
        delete="" if u["is_admin"] else f"<form method='post' action='/admin/delete/{u['id']}' style='display:inline' onsubmit='return confirm(\"حذف کاربر؟\")'><button class='danger'>🗑️ حذف</button></form>"
        out+=f"""<div class='user'><b>👤 {html.escape(u["display_name"] or u["username"])}</b>
        <div class='small'>@{html.escape(u["username"])} — 💬 {u["message_count"]} پیام — {'🔵' if u['verified'] else '⚪'}</div>
        <div class='actions'>{verify}<a class='btn gray' href='/admin/messages/{u["id"]}'>📨 پیام‌ها</a>{delete}</div></div>"""
    return page(f"""<div class='card'><div class='top'><h2>👑 پنل مدیریت</h2><a href='/chat'>چت</a></div>
    <span class='stat'>👥 {len(users)} کاربر</span><span class='stat'>💬 {total} پیام</span><hr>{out}</div>""")

@app.route("/admin/verify/<int:uid>",methods=["POST"])
def verify(uid):
    admin_only();c=db();u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if u and not u["is_admin"]:c.execute("UPDATE users SET verified=? WHERE id=?",(0 if u["verified"] else 1,uid));c.commit()
    c.close();return redirect("/admin")

@app.route("/admin/delete/<int:uid>",methods=["POST"])
def delete(uid):
    admin_only();c=db();u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if u and not u["is_admin"]:
        c.execute("DELETE FROM messages WHERE username=?",(u["username"],));c.execute("DELETE FROM users WHERE id=?",(uid,));c.commit()
    c.close();return redirect("/admin")

@app.route("/admin/messages/<int:uid>")
def admin_messages(uid):
    admin_only();c=db();u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not u:c.close();return redirect("/admin")
    ms=c.execute("SELECT * FROM messages WHERE username=? ORDER BY id",(u["username"],)).fetchall();c.close()
    return page(f"""<div class='card'><h2>📨 پیام‌های {html.escape(u["display_name"] or u["username"])}</h2>
    <p>@{html.escape(u["username"])} — {len(ms)} پیام</p>{''.join(msg_html(m) for m in ms) or '<p>پیامی ندارد.</p>'}
    <a href='/admin'>← پنل مدیریت</a></div>""")

@app.route("/admin/pin/<int:mid>",methods=["POST"])
def pin(mid):
    admin_only();data=request.get_json(silent=True) or {};state=bool(data.get("pinned"))
    c=db();m=c.execute("SELECT id FROM messages WHERE id=?",(mid,)).fetchone()
    if not m:c.close();return jsonify(ok=False,error="پیام پیدا نشد"),404
    c.execute("UPDATE messages SET pinned=? WHERE id=?",(1 if state else 0,mid));c.commit();c.close()
    socketio.emit("pin_changed",{"id":mid,"pinned":state});return jsonify(ok=True)

@app.errorhandler(413)
def too_big(e):return page("<div class='card'><h2>❌ فایل بیشتر از 50MB است.</h2><a href='/chat'>بازگشت</a></div>"),413

if __name__=="__main__":
    init_db()
    print("\n==============================\n      CHAT SERVER STARTED\n==============================")
    print("Open: http://127.0.0.1:5000")
    print("Admin: admin / admin123\n")
    socketio.run(app,host="0.0.0.0",port=5000,debug=False,allow_unsafe_werkzeug=True)

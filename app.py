import os, io, base64, secrets, hashlib, hmac, csv
from datetime import datetime
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, abort, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///beautydrop.db").replace("postgres://", "postgresql+psycopg://", 1),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
db = SQLAlchemy(app)
STATUSES=["DISPATCHED","ASSIGNED","PICKED_UP","IN_TRANSIT","OUT_FOR_DELIVERY","DELIVERED","FAILED","RETURNED"]

class User(db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(120),nullable=False); email=db.Column(db.String(255),unique=True,nullable=False,index=True)
    password_hash=db.Column(db.Text,nullable=False); role=db.Column(db.String(20),nullable=False); store_name=db.Column(db.String(160)); active=db.Column(db.Boolean,default=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Delivery(db.Model):
    id=db.Column(db.Integer,primary_key=True); code=db.Column(db.String(32),unique=True,nullable=False,index=True); store_name=db.Column(db.String(160),nullable=False,index=True)
    customer=db.Column(db.String(160),nullable=False); phone=db.Column(db.String(40),nullable=False); address=db.Column(db.Text,nullable=False); order_number=db.Column(db.String(80)); packages=db.Column(db.Integer,default=1)
    km=db.Column(db.Float,default=0); service=db.Column(db.String(30),default="standard"); instructions=db.Column(db.Text); fee=db.Column(db.Numeric(10,2),default=0); status=db.Column(db.String(30),nullable=False,index=True)
    pickup_code=db.Column(db.String(16),nullable=False); delivery_pin=db.Column(db.String(8),nullable=False); driver_id=db.Column(db.Integer,db.ForeignKey("user.id")); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    picked_up_at=db.Column(db.DateTime); delivered_at=db.Column(db.DateTime); proof_note=db.Column(db.Text); signature=db.Column(db.Text)
class Event(db.Model):
    id=db.Column(db.Integer,primary_key=True); delivery_id=db.Column(db.Integer,db.ForeignKey("delivery.id"),nullable=False,index=True); event=db.Column(db.String(40)); note=db.Column(db.Text); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Invoice(db.Model):
    id=db.Column(db.Integer,primary_key=True); store_name=db.Column(db.String(160)); period=db.Column(db.String(80)); amount=db.Column(db.Numeric(10,2)); status=db.Column(db.String(20),default="OPEN"); created_at=db.Column(db.DateTime,default=datetime.utcnow)


def now(): return datetime.utcnow()
def hp(p):
    s=secrets.token_bytes(16); d=hashlib.pbkdf2_hmac("sha256",p.encode(),s,310000); return s.hex()+"$"+d.hex()
def cp(p,x):
    try:
        s,d=x.split("$",1); z=hashlib.pbkdf2_hmac("sha256",p.encode(),bytes.fromhex(s),310000); return hmac.compare_digest(z.hex(),d)
    except Exception:return False
def price(km,svc):
    if km<=5:f=9.99
    elif km<=10:f=12.99
    elif km<=15:f=16.99
    elif km<=20:f=21.99
    elif km<=30:f=27.99
    else:f=27.99+(km-30)*1.25
    return round(f+(7 if svc=="express" else 0),2)
def add_event(d,event,note=""):
    db.session.add(Event(delivery_id=d.id,event=event,note=note))
def me(): return db.session.get(User,session.get("uid")) if session.get("uid") else None
def guard(*roles):
    def deco(f):
        @wraps(f)
        def w(*a,**k):
            u=me()
            if not u or not u.active: session.clear(); return redirect(url_for("login",next=request.path))
            if roles and u.role not in roles: abort(403)
            return f(*a,**k)
        return w
    return deco

@app.context_processor
def inject(): return {"me":me()}

@app.route("/")
def home(): return render_template("home.html")
@app.route("/health")
def health(): return {"ok":True,"service":"BeautyDrop Canada"}
@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=User.query.filter(func.lower(User.email)==request.form["email"].strip().lower(),User.active.is_(True)).first()
        if u and cp(request.form["password"],u.password_hash): session.clear(); session["uid"]=u.id; return redirect(request.args.get("next") or url_for("dashboard"))
        return render_template("login.html",error="Invalid login.")
    return render_template("login.html")
@app.route("/logout")
def logout(): session.clear(); return redirect("/")
@app.route("/dashboard")
@guard()
def dashboard(): return redirect("/"+me().role)

@app.route("/store",methods=["GET","POST"])
@guard("store")
def store():
    u=me()
    if request.method=="POST":
        try: km=max(0,float(request.form.get("km") or 0)); packages=max(1,min(50,int(request.form.get("packages") or 1)))
        except ValueError: flash("Enter valid distance and package count.","error"); return redirect("/store")
        svc=request.form.get("service","standard") if request.form.get("service") in ("standard","express") else "standard"
        d=Delivery(code="BD-"+secrets.token_hex(4).upper(),store_name=u.store_name,customer=request.form["customer"].strip(),phone=request.form["phone"].strip(),address=request.form["address"].strip(),order_number=request.form.get("order_number",""),packages=packages,km=km,service=svc,instructions=request.form.get("instructions",""),fee=price(km,svc),status="DISPATCHED",pickup_code=secrets.token_hex(2).upper(),delivery_pin=str(secrets.randbelow(9000)+1000))
        db.session.add(d); db.session.flush(); add_event(d,"DISPATCHED","Merchant created delivery."); db.session.commit(); flash(f"Delivery {d.code} created.","ok")
    rows=Delivery.query.filter_by(store_name=u.store_name).order_by(Delivery.id.desc()).all(); return render_template("store.html",rows=rows)

@app.route("/driver")
@guard("driver")
def driver():
    rows=Delivery.query.filter(Delivery.status.notin_(["DELIVERED","RETURNED"])).order_by(Delivery.id.desc()).all(); return render_template("driver.html",rows=rows)
@app.post("/driver/<int:did>/pickup")
@guard("driver")
def pickup(did):
    d=db.session.get(Delivery,did)
    if not d: abort(404)
    if not hmac.compare_digest(request.form.get("pickup_code","").strip().upper(),d.pickup_code): flash("Pickup code is incorrect.","error"); return redirect("/driver")
    d.status="PICKED_UP"; d.picked_up_at=now(); d.driver_id=me().id; add_event(d,"PICKED_UP","Pickup code verified."); db.session.commit(); return redirect("/driver")
@app.post("/driver/<int:did>/deliver")
@guard("driver")
def deliver(did):
    d=db.session.get(Delivery,did)
    if not d: abort(404)
    if not hmac.compare_digest(request.form.get("pin","").strip(),d.delivery_pin): flash("Customer PIN is incorrect.","error"); return redirect("/driver")
    sig=request.form.get("signature","")
    if len(sig)>200000: abort(413)
    d.status="DELIVERED"; d.delivered_at=now(); d.proof_note=request.form.get("note",""); d.signature=sig; d.driver_id=me().id; add_event(d,"DELIVERED","Customer PIN verified."); db.session.commit(); return redirect("/driver")
@app.post("/driver/<int:did>/status")
@guard("driver")
def status(did):
    d=db.session.get(Delivery,did); s=request.form.get("status")
    if not d or s not in STATUSES: abort(400)
    d.status=s; d.driver_id=me().id; add_event(d,s,"Driver status update."); db.session.commit(); return redirect("/driver")

@app.route("/admin")
@guard("admin")
def admin():
    ds=Delivery.query.order_by(Delivery.id.desc()).all(); stores=User.query.filter_by(role="store").order_by(User.id.desc()).all(); drivers=User.query.filter_by(role="driver").order_by(User.id.desc()).all(); inv=Invoice.query.order_by(Invoice.id.desc()).all()
    return render_template("admin.html",deliveries=ds,stores=stores,drivers=drivers,invoices=inv)
@app.post("/admin/assign/<int:did>")
@guard("admin")
def assign(did):
    d=db.session.get(Delivery,did); driver=db.session.get(User,int(request.form["driver_id"]))
    if not d or not driver or driver.role!="driver": abort(400)
    d.driver_id=driver.id; d.status="ASSIGNED"; add_event(d,"ASSIGNED","Admin assigned courier."); db.session.commit(); return redirect("/admin")
@app.post("/admin/user")
@guard("admin")
def user():
    role=request.form.get("role")
    if role not in ("store","driver") or len(request.form.get("password", ""))<10: abort(400)
    u=User(name=request.form["name"].strip(),email=request.form["email"].strip().lower(),password_hash=hp(request.form["password"]),role=role,store_name=request.form.get("store_name",""))
    try: db.session.add(u); db.session.commit()
    except IntegrityError: db.session.rollback(); flash("That email already exists.","error")
    return redirect("/admin")
@app.post("/admin/invoice")
@guard("admin")
def invoice():
    a=db.session.query(func.coalesce(func.sum(Delivery.fee),0)).filter(Delivery.store_name==request.form["store_name"],Delivery.status=="DELIVERED").scalar() or 0
    db.session.add(Invoice(store_name=request.form["store_name"],period=request.form["period"],amount=a)); db.session.commit(); return redirect("/admin")
@app.get("/admin/export.csv")
@guard("admin")
def export_csv():
    out=io.StringIO(); w=csv.writer(out); w.writerow(["Delivery","Store","Customer","Status","Fee","Created","Picked Up","Delivered"])
    for d in Delivery.query.order_by(Delivery.id.desc()).all(): w.writerow([d.code,d.store_name,d.customer,d.status,d.fee,d.created_at,d.picked_up_at,d.delivered_at])
    return send_file(io.BytesIO(out.getvalue().encode()),mimetype="text/csv",as_attachment=True,download_name="beautydrop-deliveries.csv")

@app.route("/track/<code>")
def track(code):
    d=Delivery.query.filter_by(code=code.upper()).first()
    if not d: abort(404)
    ev=Event.query.filter_by(delivery_id=d.id).order_by(Event.id).all(); return render_template("track.html",d=d,events=ev)
@app.route("/api/delivery/<code>")
def api(code):
    d=Delivery.query.filter_by(code=code.upper()).first()
    if not d:return jsonify(error="not_found"),404
    return jsonify(code=d.code,status=d.status,store_name=d.store_name,created_at=d.created_at.isoformat(),picked_up_at=d.picked_up_at.isoformat() if d.picked_up_at else None,delivered_at=d.delivered_at.isoformat() if d.delivered_at else None)
@app.route("/label/<code>")
def label(code):
    d=Delivery.query.filter_by(code=code.upper()).first()
    if not d: abort(404)
    try:
        import qrcode
        img=qrcode.make(request.url_root.rstrip("/")+url_for("track",code=d.code)); b=io.BytesIO(); img.save(b,format="PNG"); b.seek(0); return send_file(b,mimetype="image/png",download_name=f"{d.code}-qr.png")
    except Exception: abort(500)

with app.app_context():
    db.create_all()
    if User.query.count()==0:
        db.session.add_all([User(name="BeautyDrop Admin",email="admin@beautydrop.local",password_hash=hp("ChangeMe123!"),role="admin"),User(name="Demo Beauty Store",email="store@beautydrop.local",password_hash=hp("ChangeMe123!"),role="store",store_name="Demo Beauty Store"),User(name="Demo Driver",email="driver@beautydrop.local",password_hash=hp("ChangeMe123!"),role="driver")]); db.session.commit()

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))

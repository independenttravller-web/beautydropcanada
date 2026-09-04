import os
import io
import csv
import secrets
import hashlib
import hmac
import smtplib
import click
from datetime import datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, session, render_template, jsonify,
    abort, flash, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=normalize_database_url(os.environ.get("DATABASE_URL", "sqlite:///beautydrop.db")),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.environ.get("SESSION_HOURS", "8"))),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    WTF_CSRF_TIME_LIMIT=3600,
)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["300 per hour"], storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"))

STATUSES = ["UPCOMING", "WAITING_FOR_DRIVER", "DRIVER_ASSIGNED", "DRIVER_ARRIVING", "PICKED_UP", "IN_TRANSIT", "ARRIVING", "DELIVERED", "DELIVERY_ATTEMPTED", "RETURNED", "CANCELLED"]
MANUAL_DRIVER_STATUSES = ["DRIVER_ARRIVING", "IN_TRANSIT", "ARRIVING", "DELIVERY_ATTEMPTED", "RETURNED"]
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    store_name = db.Column(db.String(160))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Delivery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    store_name = db.Column(db.String(160), nullable=False, index=True)
    customer = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    address = db.Column(db.Text, nullable=False)
    order_number = db.Column(db.String(80))
    packages = db.Column(db.Integer, default=1)
    km = db.Column(db.Float, default=0)
    service = db.Column(db.String(30), default="standard")
    instructions = db.Column(db.Text)
    fee = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(30), nullable=False, index=True)
    pickup_code = db.Column(db.String(16), nullable=False)
    delivery_pin = db.Column(db.String(8), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    picked_up_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    proof_note = db.Column(db.Text)
    signature = db.Column(db.Text)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("delivery.id"), nullable=False, index=True)
    event = db.Column(db.String(40))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(160), index=True)
    period = db.Column(db.String(80))
    amount = db.Column(db.Numeric(10, 2))
    status = db.Column(db.String(20), default="OPEN")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(160), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    sku = db.Column(db.String(80))
    price = db.Column(db.Numeric(10, 2), default=0)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DeliveryPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("delivery.id"), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    object_key = db.Column(db.String(500), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    provider = db.Column(db.String(40), default="stripe")
    provider_id = db.Column(db.String(255), index=True)
    payment_intent_id = db.Column(db.String(255), index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    tax = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(30), default="PENDING")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Consent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("delivery.id"), nullable=False, index=True)
    consent_type = db.Column(db.String(80), nullable=False)
    captured_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AgreementAcceptance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    agreement = db.Column(db.String(80), nullable=False)
    version = db.Column(db.String(40), nullable=False)
    accepted_at = db.Column(db.DateTime, default=datetime.utcnow)


class StoreProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(40))
    address = db.Column(db.Text)
    city = db.Column(db.String(120))
    province = db.Column(db.String(80), default="Ontario")
    postal_code = db.Column(db.String(20))
    website = db.Column(db.String(255))
    business_number = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DeliverySchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("delivery.id"), unique=True, nullable=False, index=True)
    customer_email = db.Column(db.String(255))
    order_value = db.Column(db.Numeric(10, 2), default=0)
    scheduled_for = db.Column(db.DateTime)
    delivery_window = db.Column(db.String(80))
    timing = db.Column(db.String(20), default="asap")
    estimated_minutes_min = db.Column(db.Integer)
    estimated_minutes_max = db.Column(db.Integer)
    tax = db.Column(db.Numeric(10, 2), default=0)
    total = db.Column(db.Numeric(10, 2), default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PricingConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    base_fee = db.Column(db.Numeric(10, 2), default=6.99)
    included_km = db.Column(db.Float, default=3)
    per_km = db.Column(db.Numeric(10, 2), default=1.25)
    minimum_fee = db.Column(db.Numeric(10, 2), default=8.99)
    maximum_radius = db.Column(db.Float, default=50)
    tax_rate = db.Column(db.Numeric(8, 4), default=0.13)
    rush_surcharge = db.Column(db.Numeric(10, 2), default=7.00)
    wait_time_surcharge = db.Column(db.Numeric(10, 2), default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def now():
    return datetime.utcnow()


def hash_password(password):
    return generate_password_hash(password, method="scrypt")


def legacy_password_ok(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000)
        return hmac.compare_digest(test.hex(), digest)
    except Exception:
        return False


def password_ok(password, stored):
    if not stored:
        return False
    if stored.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(stored, password)
        except Exception:
            return False
    return legacy_password_ok(password, stored)


def pricing_config():
    cfg = PricingConfig.query.order_by(PricingConfig.id.asc()).first()
    if not cfg:
        cfg = PricingConfig()
        db.session.add(cfg)
        db.session.commit()
    return cfg


def price(km, svc):
    cfg = pricing_config()
    km = max(0, float(km or 0))
    included = float(cfg.included_km or 0)
    fee = float(cfg.base_fee or 0) + max(0, km - included) * float(cfg.per_km or 0)
    fee = max(float(cfg.minimum_fee or 0), fee)
    if svc == "express":
        fee += float(cfg.rush_surcharge or 0)
    return round(fee, 2)


def estimate_minutes(km):
    km = max(0, float(km or 0))
    low = max(20, int(20 + km * 1.6))
    high = max(low + 10, int(35 + km * 2.0))
    return low, high


def tax_amount(amount):
    rate = Decimal(os.environ.get("TAX_RATE", "0"))
    return (Decimal(amount) * rate).quantize(Decimal("0.01"))


def add_event(delivery, event, note=""):
    db.session.add(Event(delivery_id=delivery.id, event=event, note=note[:500]))


def me():
    return db.session.get(User, session.get("uid")) if session.get("uid") else None


def guard(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = me()
            if not user or not user.active:
                session.clear()
                return redirect(url_for("login", next=request.path))
            if roles and user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return deco


def store_owns_delivery(user, delivery):
    return user.role == "admin" or (user.role == "store" and delivery.store_name == user.store_name)


def send_email(to_address, subject, body):
    host = os.environ.get("SMTP_HOST")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("MAIL_FROM", username or "noreply@beautydrop.ca")
    if not host:
        app.logger.warning("SMTP not configured; email skipped: %s", subject)
        return False
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


def send_sms(phone, body):
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    sender = os.environ.get("TWILIO_FROM_NUMBER")
    if not all((sid, token, sender, phone)):
        app.logger.info("SMS provider not configured; SMS skipped")
        return False
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(body=body[:1500], from_=sender, to=phone)
        return True
    except Exception:
        app.logger.exception("SMS send failed")
        return False


def storage_ready():
    return all(os.environ.get(k) for k in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"))


def s3_client():
    import boto3
    kwargs = {
        "aws_access_key_id": os.environ.get("S3_ACCESS_KEY"),
        "aws_secret_access_key": os.environ.get("S3_SECRET_KEY"),
        "region_name": os.environ.get("S3_REGION", "auto"),
    }
    if os.environ.get("S3_ENDPOINT_URL"):
        kwargs["endpoint_url"] = os.environ.get("S3_ENDPOINT_URL")
    return boto3.client("s3", **kwargs)


def upload_private_photo(file_obj, delivery_code, kind):
    if not storage_ready():
        raise RuntimeError("Private photo storage is not configured yet.")
    filename = secure_filename(file_obj.filename or "proof.jpg")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Upload JPG, PNG, or WEBP images only.")
    data = file_obj.read()
    if not data:
        raise ValueError("The proof image is empty.")
    try:
        from PIL import Image
        Image.open(io.BytesIO(data)).verify()
    except Exception as exc:
        raise ValueError("The uploaded proof is not a valid image.") from exc
    upload_stream = io.BytesIO(data)
    key = f"deliveries/{delivery_code}/{kind}/{secrets.token_hex(12)}.{ext}"
    s3_client().upload_fileobj(
        upload_stream,
        os.environ["S3_BUCKET"],
        key,
        ExtraArgs={"ContentType": file_obj.mimetype or "application/octet-stream"},
    )
    return key


def signed_photo_url(key):
    return s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["S3_BUCKET"], "Key": key},
        ExpiresIn=300,
    )


@app.context_processor
def inject():
    return {"me": me(), "year": datetime.utcnow().year}


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.route("/")
def home():
    return render_template("home.html", pricing=pricing_config())


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/for-stores")
def for_stores():
    return render_template("for_stores.html")


@app.route("/for-drivers")
def for_drivers():
    return render_template("for_drivers.html")


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/contact", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        email = request.form.get("email", "").strip()[:255]
        message = request.form.get("message", "").strip()[:2000]
        if not name or "@" not in email or not message:
            flash("Please complete all fields.", "error")
        else:
            inbox = os.environ.get("CONTACT_EMAIL")
            if inbox:
                send_email(inbox, f"BeautyDrop website inquiry from {name}", f"From: {name} <{email}>\n\n{message}")
            flash("Thanks — your message has been received.", "ok")
            return redirect(url_for("contact"))
    return render_template("contact.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/merchant-agreement")
def merchant_agreement():
    return render_template("merchant_agreement.html")

@app.route("/driver-agreement")
def driver_agreement():
    return render_template("driver_agreement.html")

@app.route("/delivery-terms")
def delivery_terms():
    return render_template("delivery_terms.html")


@app.route("/health")
def health():
    try:
        db.session.execute(db.select(func.count(User.id))).scalar()
        database = "ok"
    except Exception:
        database = "error"
    return {"ok": database == "ok", "service": "BeautyDrop Canada", "database": database}, (200 if database == "ok" else 503)


@app.route("/signup/store", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def store_signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        store_name = request.form.get("store_name", "").strip()[:160]
        email = request.form.get("email", "").strip().lower()[:255]
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()[:40]
        address = request.form.get("address", "").strip()[:500]
        city = request.form.get("city", "").strip()[:120]
        province = request.form.get("province", "Ontario").strip()[:80]
        postal_code = request.form.get("postal_code", "").strip()[:20]
        website = request.form.get("website", "").strip()[:255]
        business_number = request.form.get("business_number", "").strip()[:80]
        if not name or not store_name or "@" not in email or len(password) < 10 or not phone or not address or not city or not postal_code:
            flash("Complete all required store fields and use a password with at least 10 characters.", "error")
            return render_template("store_signup.html")
        if request.form.get("merchant_terms") != "yes":
            flash("You must accept the merchant terms to apply.", "error")
            return render_template("store_signup.html")
        user = User(name=name, email=email, password_hash=hash_password(password), role="store", store_name=store_name, active=False)
        try:
            db.session.add(user)
            db.session.flush()
            db.session.add(StoreProfile(user_id=user.id, phone=phone, address=address, city=city, province=province, postal_code=postal_code, website=website, business_number=business_number))
            db.session.add(AgreementAcceptance(user_id=user.id, agreement="merchant_terms", version="2026-09-03"))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("An account with that email already exists.", "error")
            return render_template("store_signup.html")
        flash("Your store application was received. BeautyDrop must approve the account before sign-in.", "ok")
        return redirect(url_for("login"))
    return render_template("store_signup.html")


@app.route("/signup/driver", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def driver_signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        email = request.form.get("email", "").strip().lower()[:255]
        password = request.form.get("password", "")
        if not name or "@" not in email or len(password) < 10:
            flash("Complete all required fields and use a password with at least 10 characters.", "error")
            return render_template("driver_signup.html")
        if request.form.get("driver_terms") != "yes":
            flash("You must accept the driver agreement to apply.", "error")
            return render_template("driver_signup.html")
        user = User(name=name, email=email, password_hash=hash_password(password), role="driver", active=False)
        try:
            db.session.add(user)
            db.session.flush()
            db.session.add(AgreementAcceptance(user_id=user.id, agreement="driver_terms", version="2026-09-03"))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("An account with that email already exists.", "error")
            return render_template("driver_signup.html")
        flash("Your driver application was received. BeautyDrop must approve the account before sign-in.", "ok")
        return redirect(url_for("login"))
    return render_template("driver_signup.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("8 per 15 minutes", methods=["POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email, User.active.is_(True)).first()
        if user and password_ok(password, user.password_hash):
            if not user.password_hash.startswith(("scrypt:", "pbkdf2:")):
                user.password_hash = hash_password(password)
                db.session.commit()
            session.clear()
            session["uid"] = user.id
            session.permanent = True
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            destinations = {"store": "store", "driver": "driver", "admin": "admin"}
            endpoint = destinations.get(user.role)
            if not endpoint:
                session.clear()
                flash("Your account role is not configured. Contact BeautyDrop support.", "error")
                return redirect(url_for("login"))
            return redirect(url_for(endpoint))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("4 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email, User.active.is_(True)).first()
        if user:
            raw = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw.encode()).hexdigest()
            reset = PasswordReset(user_id=user.id, token_hash=token_hash, expires_at=now() + timedelta(minutes=30))
            db.session.add(reset)
            db.session.commit()
            link = url_for("reset_password", token=raw, _external=True)
            try:
                send_email(user.email, "Reset your BeautyDrop password", f"Use this link within 30 minutes:\n\n{link}\n\nIf you did not request this, ignore this email.")
            except Exception:
                app.logger.exception("Password reset email failed")
        flash("If that email is registered, a reset link has been sent.", "ok")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def reset_password(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset = PasswordReset.query.filter_by(token_hash=token_hash, used_at=None).first()
    if not reset or reset.expires_at < now():
        flash("That password-reset link is invalid or expired.", "error")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 10:
            flash("Password must be at least 10 characters.", "error")
            return render_template("reset_password.html")
        user = db.session.get(User, reset.user_id)
        user.password_hash = hash_password(password)
        reset.used_at = now()
        db.session.commit()
        flash("Password updated. You can sign in now.", "ok")
        return redirect(url_for("login"))
    return render_template("reset_password.html")


@app.route("/dashboard")
@guard()
def dashboard():
    user = me()
    destinations = {"store": "store", "driver": "driver", "admin": "admin"}
    endpoint = destinations.get(user.role)
    if not endpoint:
        abort(403)
    return redirect(url_for(endpoint))


@app.route("/store")
@app.route("/store-dashboard")
@guard("store")
def store():
    user = me()
    rows = Delivery.query.filter_by(store_name=user.store_name).order_by(Delivery.id.desc()).all()
    schedules = {m.delivery_id: m for m in DeliverySchedule.query.filter(DeliverySchedule.delivery_id.in_([d.id for d in rows] or [-1])).all()}
    upcoming_statuses = {"UPCOMING", "WAITING_FOR_DRIVER", "DRIVER_ASSIGNED", "DRIVER_ARRIVING"}
    active_statuses = {"PICKED_UP", "IN_TRANSIT", "ARRIVING"}
    stats = {
        "active": sum(d.status in active_statuses for d in rows),
        "upcoming": sum(d.status in upcoming_statuses for d in rows),
        "delivered": sum(d.status == "DELIVERED" for d in rows),
        "month_spend": sum(float(d.fee or 0) for d in rows if d.created_at and d.created_at.strftime("%Y-%m") == now().strftime("%Y-%m")),
    }
    return render_template("store.html", rows=rows, schedules=schedules, stats=stats)


@app.route("/store-dashboard/create-delivery", methods=["GET", "POST"])
@guard("store")
def create_delivery():
    user = me()
    profile = StoreProfile.query.filter_by(user_id=user.id).first()
    cfg = pricing_config()
    if request.method == "POST":
        customer = request.form.get("customer", "").strip()[:160]
        phone = request.form.get("phone", "").strip()[:40]
        email = request.form.get("customer_email", "").strip().lower()[:255]
        address = request.form.get("address", "").strip()[:500]
        timing = request.form.get("timing", "asap")
        if timing not in ("asap", "scheduled"):
            timing = "asap"
        if not customer or not phone or not address:
            flash("Customer name, phone and delivery address are required.", "error")
            return render_template("create_delivery.html", pricing=cfg, profile=profile)
        try:
            km = max(0, min(float(cfg.maximum_radius or 50), float(request.form.get("km") or 0)))
            packages = max(1, min(50, int(request.form.get("packages") or 1)))
            order_value = max(Decimal("0"), Decimal(request.form.get("order_value") or "0"))
        except Exception:
            flash("Enter a valid distance, package count and order value.", "error")
            return render_template("create_delivery.html", pricing=cfg, profile=profile)
        if request.form.get("sms_consent") != "yes":
            flash("Confirm the customer requested delivery and transactional delivery updates.", "error")
            return render_template("create_delivery.html", pricing=cfg, profile=profile)
        svc = request.form.get("service", "standard")
        if svc not in ("standard", "express"):
            svc = "standard"
        scheduled_for = None
        delivery_window = request.form.get("delivery_window", "")[:80]
        if timing == "scheduled":
            raw_date = request.form.get("delivery_date", "").strip()
            raw_time = request.form.get("delivery_time", "").strip()
            try:
                scheduled_for = datetime.strptime(f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M")
            except ValueError:
                flash("Choose a valid scheduled delivery date and time.", "error")
                return render_template("create_delivery.html", pricing=cfg, profile=profile)
            if scheduled_for < now() - timedelta(minutes=5):
                flash("Scheduled delivery time must be in the future.", "error")
                return render_template("create_delivery.html", pricing=cfg, profile=profile)
        base_fee = Decimal(str(price(km, svc)))
        tax = (base_fee * Decimal(str(cfg.tax_rate or 0))).quantize(Decimal("0.01"))
        total = base_fee + tax
        mins_low, mins_high = estimate_minutes(km)
        delivery = Delivery(
            code="BD-" + secrets.token_hex(6).upper(), store_name=user.store_name, customer=customer, phone=phone, address=address,
            order_number=request.form.get("order_number", "").strip()[:80], packages=packages, km=km, service=svc,
            instructions=request.form.get("instructions", "").strip()[:1000], fee=base_fee,
            status="UPCOMING" if timing == "scheduled" else "WAITING_FOR_DRIVER",
            pickup_code=secrets.token_hex(3).upper(), delivery_pin=str(secrets.randbelow(900000) + 100000),
        )
        db.session.add(delivery)
        db.session.flush()
        db.session.add(DeliverySchedule(delivery_id=delivery.id, customer_email=email, order_value=order_value, scheduled_for=scheduled_for, delivery_window=delivery_window, timing=timing, estimated_minutes_min=mins_low, estimated_minutes_max=mins_high, tax=tax, total=total))
        add_event(delivery, delivery.status, "Merchant created delivery request.")
        db.session.add(Consent(delivery_id=delivery.id, consent_type="transactional_sms_delivery_updates", captured_by=user.id))
        db.session.commit()
        send_sms(phone, f"BeautyDrop: your delivery {delivery.code} was created. Track: {url_for('track', code=delivery.code, _external=True)}")
        flash(f"Delivery {delivery.code} created.", "ok")
        return redirect(url_for("store_delivery_detail", did=delivery.id))
    return render_template("create_delivery.html", pricing=cfg, profile=profile)


@app.get("/store-dashboard/delivery/<int:did>")
@guard("store")
def store_delivery_detail(did):
    delivery = db.session.get(Delivery, did)
    if not delivery or delivery.store_name != me().store_name:
        abort(404)
    schedule = DeliverySchedule.query.filter_by(delivery_id=delivery.id).first()
    events = Event.query.filter_by(delivery_id=delivery.id).order_by(Event.id).all()
    driver_user = db.session.get(User, delivery.driver_id) if delivery.driver_id else None
    return render_template("store_delivery_detail.html", d=delivery, schedule=schedule, events=events, driver_user=driver_user)


@app.route("/store-dashboard/delivery/<int:did>/edit", methods=["GET", "POST"])
@guard("store")
def edit_store_delivery(did):
    delivery = db.session.get(Delivery, did)
    if not delivery or delivery.store_name != me().store_name:
        abort(404)
    if delivery.status not in ("UPCOMING", "WAITING_FOR_DRIVER", "DRIVER_ASSIGNED"):
        flash("This delivery can no longer be edited because pickup has started.", "error")
        return redirect(url_for("store_delivery_detail", did=did))
    schedule = DeliverySchedule.query.filter_by(delivery_id=delivery.id).first()
    if request.method == "POST":
        delivery.customer = request.form.get("customer", delivery.customer).strip()[:160]
        delivery.phone = request.form.get("phone", delivery.phone).strip()[:40]
        delivery.address = request.form.get("address", delivery.address).strip()[:500]
        delivery.instructions = request.form.get("instructions", delivery.instructions or "").strip()[:1000]
        try:
            delivery.km = max(0, min(float(pricing_config().maximum_radius or 50), float(request.form.get("km") or delivery.km)))
        except ValueError:
            pass
        delivery.fee = Decimal(str(price(delivery.km, delivery.service)))
        if schedule:
            try:
                raw_date = request.form.get("delivery_date", "").strip()
                raw_time = request.form.get("delivery_time", "").strip()
                if raw_date and raw_time:
                    schedule.scheduled_for = datetime.strptime(f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M")
                schedule.delivery_window = request.form.get("delivery_window", schedule.delivery_window or "")[:80]
                schedule.tax = (Decimal(delivery.fee) * Decimal(str(pricing_config().tax_rate or 0))).quantize(Decimal("0.01"))
                schedule.total = Decimal(delivery.fee) + Decimal(schedule.tax)
            except ValueError:
                flash("Date/time format was not valid.", "error")
                return render_template("edit_delivery.html", d=delivery, schedule=schedule)
        add_event(delivery, "UPDATED", "Merchant updated delivery before pickup.")
        db.session.commit()
        flash("Delivery updated.", "ok")
        return redirect(url_for("store_delivery_detail", did=did))
    return render_template("edit_delivery.html", d=delivery, schedule=schedule)


@app.route("/store/products", methods=["GET", "POST"])
@guard("store")
def store_products():
    user = me()
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:180]
        sku = request.form.get("sku", "").strip()[:80]
        try:
            p = max(0, Decimal(request.form.get("price", "0")))
        except Exception:
            flash("Enter a valid product price.", "error")
            return redirect(url_for("store_products"))
        if not name:
            flash("Product name is required.", "error")
        else:
            db.session.add(Product(store_name=user.store_name, name=name, sku=sku, price=p))
            db.session.commit()
            flash("Product added.", "ok")
        return redirect(url_for("store_products"))
    products = Product.query.filter_by(store_name=user.store_name).order_by(Product.id.desc()).all()
    return render_template("products.html", products=products)


@app.post("/store/products/<int:pid>/toggle")
@guard("store")
def toggle_product(pid):
    product = db.session.get(Product, pid)
    if not product or product.store_name != me().store_name:
        abort(404)
    product.active = not product.active
    db.session.commit()
    return redirect(url_for("store_products"))


@app.route("/store/invoices")
@guard("store")
def store_invoices():
    invoices = Invoice.query.filter_by(store_name=me().store_name).order_by(Invoice.id.desc()).all()
    return render_template("store_invoices.html", invoices=invoices)


@app.route("/driver")
@app.route("/driver-dashboard")
@guard("driver")
def driver():
    user = me()
    rows = Delivery.query.filter(
        Delivery.status.notin_(["DELIVERED", "RETURNED", "CANCELLED"]),
        Delivery.driver_id == user.id
    ).order_by(Delivery.id.desc()).all()
    completed = Delivery.query.filter_by(driver_id=user.id, status="DELIVERED").order_by(Delivery.id.desc()).limit(10).all()
    return render_template("driver.html", rows=rows, completed=completed)


@app.post("/driver/<int:did>/pickup")
@guard("driver")
@limiter.limit("12 per hour")
def pickup(did):
    delivery = db.session.get(Delivery, did)
    if not delivery or delivery.driver_id != me().id:
        abort(404)
    code = request.form.get("pickup_code", "").strip().upper()
    if not hmac.compare_digest(code, delivery.pickup_code):
        flash("Pickup code is incorrect.", "error")
        return redirect(url_for("driver"))
    photo = request.files.get("pickup_photo")
    if photo and photo.filename:
        try:
            key = upload_private_photo(photo, delivery.code, "pickup")
            db.session.add(DeliveryPhoto(delivery_id=delivery.id, kind="pickup", object_key=key, uploaded_by=me().id))
        except Exception as exc:
            flash(str(exc), "error")
            return redirect(url_for("driver"))
    delivery.status = "PICKED_UP"
    delivery.picked_up_at = now()
    add_event(delivery, "PICKED_UP", "Pickup code verified.")
    db.session.commit()
    send_sms(delivery.phone, f"BeautyDrop: {delivery.code} was picked up and is on the way.")
    flash("Pickup confirmed.", "ok")
    return redirect(url_for("driver"))


@app.post("/driver/<int:did>/deliver")
@guard("driver")
@limiter.limit("12 per hour")
def deliver(did):
    delivery = db.session.get(Delivery, did)
    if not delivery or delivery.driver_id != me().id:
        abort(404)
    pin = request.form.get("pin", "").strip()
    if not hmac.compare_digest(pin, delivery.delivery_pin):
        flash("Customer PIN is incorrect.", "error")
        return redirect(url_for("driver"))
    proof_photo = request.files.get("delivery_photo")
    if proof_photo and proof_photo.filename:
        try:
            key = upload_private_photo(proof_photo, delivery.code, "delivery")
            db.session.add(DeliveryPhoto(delivery_id=delivery.id, kind="delivery", object_key=key, uploaded_by=me().id))
        except Exception as exc:
            flash(str(exc), "error")
            return redirect(url_for("driver"))
    signature = request.form.get("signature", "")[:200000]
    delivery.status = "DELIVERED"
    delivery.delivered_at = now()
    delivery.proof_note = request.form.get("note", "").strip()[:1000]
    delivery.signature = signature
    add_event(delivery, "DELIVERED", "Customer PIN verified.")
    db.session.commit()
    send_sms(delivery.phone, f"BeautyDrop: {delivery.code} has been delivered. Thank you.")
    flash("Delivery completed.", "ok")
    return redirect(url_for("driver"))


@app.post("/driver/<int:did>/status")
@guard("driver")
def status(did):
    delivery = db.session.get(Delivery, did)
    status_value = request.form.get("status")
    if not delivery or delivery.driver_id != me().id or status_value not in MANUAL_DRIVER_STATUSES:
        abort(400)
    delivery.status = status_value
    add_event(delivery, status_value, "Driver status update.")
    db.session.commit()
    if status_value in ("ARRIVING", "DELIVERY_ATTEMPTED"):
        send_sms(delivery.phone, f"BeautyDrop update for {delivery.code}: {status_value.replace('_', ' ').title()}.")
    return redirect(url_for("driver"))


@app.post("/store/delivery/<int:did>/cancel")
@guard("store")
def cancel_delivery(did):
    delivery = db.session.get(Delivery, did)
    if not delivery or delivery.store_name != me().store_name:
        abort(404)
    if delivery.status not in ("UPCOMING", "WAITING_FOR_DRIVER", "DRIVER_ASSIGNED"):
        flash("This delivery can no longer be cancelled from the store dashboard.", "error")
        return redirect(url_for("store"))
    delivery.status = "CANCELLED"
    add_event(delivery, "CANCELLED", "Merchant cancelled delivery before pickup.")
    db.session.commit()
    send_sms(delivery.phone, f"BeautyDrop: delivery {delivery.code} has been cancelled by the store.")
    flash("Delivery cancelled.", "ok")
    return redirect(url_for("store"))


@app.route("/admin")
@app.route("/admin-dashboard")
@guard("admin")
def admin():
    deliveries = Delivery.query.order_by(Delivery.id.desc()).limit(150).all()
    stores = User.query.filter_by(role="store").order_by(User.id.desc()).all()
    drivers = User.query.filter_by(role="driver").order_by(User.id.desc()).all()
    invoices = Invoice.query.order_by(Invoice.id.desc()).limit(100).all()
    payments = Payment.query.order_by(Payment.id.desc()).limit(100).all()
    stats = {
        "active": Delivery.query.filter(Delivery.status.notin_(["DELIVERED", "RETURNED", "CANCELLED"])).count(),
        "delivered": Delivery.query.filter_by(status="DELIVERED").count(),
        "stores": len(stores),
        "drivers": len(drivers),
    }
    integrations = {
        "sms": bool(os.environ.get("TWILIO_ACCOUNT_SID")),
        "storage": storage_ready(),
        "payments": bool(os.environ.get("STRIPE_SECRET_KEY")),
        "email": bool(os.environ.get("SMTP_HOST")),
        "monitoring": bool(os.environ.get("SENTRY_DSN")),
    }
    return render_template("admin.html", deliveries=deliveries, stores=stores, drivers=drivers, invoices=invoices, payments=payments, stats=stats, integrations=integrations, pricing=pricing_config())


@app.post("/admin/assign/<int:did>")
@guard("admin")
def assign(did):
    delivery = db.session.get(Delivery, did)
    try:
        driver_user = db.session.get(User, int(request.form.get("driver_id", "0")))
    except ValueError:
        driver_user = None
    if not delivery or not driver_user or driver_user.role != "driver" or not driver_user.active:
        abort(400)
    delivery.driver_id = driver_user.id
    delivery.status = "DRIVER_ASSIGNED"
    add_event(delivery, "DRIVER_ASSIGNED", f"Assigned to {driver_user.name}.")
    db.session.commit()
    flash(f"{delivery.code} assigned to {driver_user.name}.", "ok")
    return redirect(url_for("admin"))


@app.post("/admin/user")
@guard("admin")
def create_user():
    role = request.form.get("role")
    password = request.form.get("password", "")
    if role not in ("store", "driver") or len(password) < 10:
        flash("Choose store/driver and use a password of at least 10 characters.", "error")
        return redirect(url_for("admin"))
    user = User(
        name=request.form.get("name", "").strip()[:120],
        email=request.form.get("email", "").strip().lower()[:255],
        password_hash=hash_password(password),
        role=role,
        store_name=request.form.get("store_name", "").strip()[:160] if role == "store" else None,
    )
    if not user.name or "@" not in user.email or (role == "store" and not user.store_name):
        flash("Complete all required account fields.", "error")
        return redirect(url_for("admin"))
    try:
        db.session.add(user)
        db.session.commit()
        flash("Account created.", "ok")
    except IntegrityError:
        db.session.rollback()
        flash("That email already exists.", "error")
    return redirect(url_for("admin"))


@app.post("/admin/user/<int:uid>/toggle")
@guard("admin")
def toggle_user(uid):
    user = db.session.get(User, uid)
    if not user or user.role == "admin":
        abort(400)
    user.active = not user.active
    db.session.commit()
    if user.active:
        try:
            send_email(user.email, "Your BeautyDrop account is approved", "Your BeautyDrop account has been approved. You can now sign in.")
        except Exception:
            app.logger.exception("Approval email failed")
    return redirect(url_for("admin"))


@app.post("/admin/invoice")
@guard("admin")
def create_invoice():
    store_name = request.form.get("store_name", "").strip()[:160]
    period = request.form.get("period", "").strip()[:80]
    amount = db.session.query(func.coalesce(func.sum(Delivery.fee), 0)).filter(
        Delivery.store_name == store_name, Delivery.status == "DELIVERED"
    ).scalar() or 0
    db.session.add(Invoice(store_name=store_name, period=period, amount=amount))
    db.session.commit()
    flash("Invoice created.", "ok")
    return redirect(url_for("admin"))


@app.post("/invoice/<int:iid>/checkout")
@guard("store", "admin")
def invoice_checkout(iid):
    invoice = db.session.get(Invoice, iid)
    user = me()
    if not invoice or (user.role == "store" and invoice.store_name != user.store_name):
        abort(404)
    stripe_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_key:
        flash("Online payments are not configured yet. Add Stripe production credentials in Render.", "error")
        return redirect(url_for("store_invoices") if user.role == "store" else url_for("admin"))
    import stripe
    stripe.api_key = stripe_key
    tax = tax_amount(invoice.amount)
    total = Decimal(invoice.amount) + tax
    checkout = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": os.environ.get("CURRENCY", "cad"),
                "product_data": {"name": f"BeautyDrop invoice {invoice.id} — {invoice.period}"},
                "unit_amount": int(total * 100),
            },
            "quantity": 1,
        }],
        success_url=url_for("payment_success", iid=invoice.id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("store_invoices", _external=True),
        metadata={"invoice_id": str(invoice.id)},
    )
    payment = Payment(invoice_id=invoice.id, provider_id=checkout.id, amount=invoice.amount, tax=tax, status="PENDING")
    db.session.add(payment)
    db.session.commit()
    return redirect(checkout.url, code=303)


@app.get("/invoice/<int:iid>/success")
@guard("store", "admin")
def payment_success(iid):
    invoice = db.session.get(Invoice, iid)
    if not invoice or (me().role == "store" and invoice.store_name != me().store_name):
        abort(404)
    flash("Payment received. Final confirmation is processed by the payment webhook.", "ok")
    return redirect(url_for("store_invoices") if me().role == "store" else url_for("admin"))


@app.post("/webhooks/stripe")
@csrf.exempt
def stripe_webhook():
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        return "not configured", 503
    import stripe
    try:
        event = stripe.Webhook.construct_event(request.data, request.headers.get("Stripe-Signature", ""), secret)
    except Exception:
        return "invalid", 400
    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        payment = Payment.query.filter_by(provider_id=obj.get("id")).first()
        if payment:
            payment.status = "PAID"
            payment.payment_intent_id = obj.get("payment_intent")
            invoice = db.session.get(Invoice, payment.invoice_id)
            if invoice:
                invoice.status = "PAID"
            db.session.commit()
    elif event["type"] in ("checkout.session.expired", "payment_intent.payment_failed"):
        provider_id = event["data"]["object"].get("id")
        payment = Payment.query.filter_by(provider_id=provider_id).first()
        if payment:
            payment.status = "FAILED"
            db.session.commit()
    return "ok"


@app.post("/admin/payment/<int:pid>/refund")
@guard("admin")
def refund_payment(pid):
    payment = db.session.get(Payment, pid)
    if not payment or payment.status != "PAID" or not payment.payment_intent_id:
        flash("This payment cannot be refunded from BeautyDrop.", "error")
        return redirect(url_for("admin"))
    stripe_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_key:
        flash("Stripe production credentials are not configured.", "error")
        return redirect(url_for("admin"))
    import stripe
    stripe.api_key = stripe_key
    try:
        stripe.Refund.create(payment_intent=payment.payment_intent_id)
        payment.status = "REFUNDED"
        invoice = db.session.get(Invoice, payment.invoice_id)
        if invoice:
            invoice.status = "REFUNDED"
        db.session.commit()
        flash("Stripe refund submitted.", "ok")
    except Exception:
        app.logger.exception("Stripe refund failed")
        flash("Refund failed. Check Stripe and application logs before retrying.", "error")
    return redirect(url_for("admin"))


@app.get("/admin/export.csv")
@guard("admin")
def export_csv():
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Delivery", "Store", "Customer", "Status", "Fee", "Created", "Picked Up", "Delivered"])
    for delivery in Delivery.query.order_by(Delivery.id.desc()).all():
        writer.writerow([delivery.code, delivery.store_name, delivery.customer, delivery.status, delivery.fee, delivery.created_at, delivery.picked_up_at, delivery.delivered_at])
    return send_file(io.BytesIO(out.getvalue().encode()), mimetype="text/csv", as_attachment=True, download_name="beautydrop-deliveries.csv")


@app.post("/admin/pricing")
@guard("admin")
def update_pricing():
    cfg = pricing_config()
    try:
        cfg.base_fee = Decimal(request.form.get("base_fee", str(cfg.base_fee)))
        cfg.included_km = float(request.form.get("included_km", cfg.included_km))
        cfg.per_km = Decimal(request.form.get("per_km", str(cfg.per_km)))
        cfg.minimum_fee = Decimal(request.form.get("minimum_fee", str(cfg.minimum_fee)))
        cfg.maximum_radius = float(request.form.get("maximum_radius", cfg.maximum_radius))
        cfg.tax_rate = Decimal(request.form.get("tax_rate", str(cfg.tax_rate)))
        cfg.rush_surcharge = Decimal(request.form.get("rush_surcharge", str(cfg.rush_surcharge)))
        cfg.wait_time_surcharge = Decimal(request.form.get("wait_time_surcharge", str(cfg.wait_time_surcharge)))
        if cfg.maximum_radius <= 0 or cfg.per_km < 0 or cfg.minimum_fee < 0 or cfg.tax_rate < 0:
            raise ValueError
    except Exception:
        flash("Enter valid non-negative pricing values.", "error")
        return redirect(url_for("admin"))
    db.session.commit()
    flash("Delivery pricing updated.", "ok")
    return redirect(url_for("admin"))


@app.get("/api/estimate")
@limiter.limit("120 per hour")
def estimate_api():
    try:
        km = float(request.args.get("km", "0"))
    except ValueError:
        return jsonify(error="invalid_distance"), 400
    cfg = pricing_config()
    if km < 0 or km > float(cfg.maximum_radius or 50):
        return jsonify(error="outside_service_radius", maximum_radius=float(cfg.maximum_radius or 50)), 400
    svc = request.args.get("service", "standard")
    if svc not in ("standard", "express"):
        svc = "standard"
    fee = Decimal(str(price(km, svc)))
    tax = (fee * Decimal(str(cfg.tax_rate or 0))).quantize(Decimal("0.01"))
    low, high = estimate_minutes(km)
    return jsonify(km=round(km,1), fee=float(fee), tax=float(tax), total=float(fee+tax), eta_min=low, eta_max=high, service=svc)


@app.route("/track", methods=["GET", "POST"])
@limiter.limit("60 per hour")
def tracking_search():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        if not code:
            flash("Enter your BeautyDrop tracking code.", "error")
            return redirect(url_for("tracking_search"))
        return redirect(url_for("track", code=code))
    return render_template("track_search.html")


@app.route("/track/<code>")
@limiter.limit("120 per hour")
def track(code):
    delivery = Delivery.query.filter_by(code=code.upper()).first()
    if not delivery:
        abort(404)
    events = Event.query.filter_by(delivery_id=delivery.id).order_by(Event.id).all()
    return render_template("track.html", d=delivery, events=events)


@app.route("/api/delivery/<code>")
@limiter.limit("120 per hour")
def api(code):
    delivery = Delivery.query.filter_by(code=code.upper()).first()
    if not delivery:
        return jsonify(error="not_found"), 404
    return jsonify(
        code=delivery.code,
        status=delivery.status,
        store_name=delivery.store_name,
        created_at=delivery.created_at.isoformat(),
        picked_up_at=delivery.picked_up_at.isoformat() if delivery.picked_up_at else None,
        delivered_at=delivery.delivered_at.isoformat() if delivery.delivered_at else None,
    )


@app.route("/label/<code>")
@guard("store", "admin")
def label(code):
    delivery = Delivery.query.filter_by(code=code.upper()).first()
    if not delivery or not store_owns_delivery(me(), delivery):
        abort(404)
    import qrcode
    img = qrcode.make(request.url_root.rstrip("/") + url_for("track", code=delivery.code))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png", download_name=f"{delivery.code}-qr.png")


@app.route("/proof/<int:photo_id>")
@guard("store", "driver", "admin")
def proof_photo(photo_id):
    photo = db.session.get(DeliveryPhoto, photo_id)
    if not photo:
        abort(404)
    delivery = db.session.get(Delivery, photo.delivery_id)
    user = me()
    allowed = user.role == "admin" or (user.role == "store" and delivery.store_name == user.store_name) or (user.role == "driver" and delivery.driver_id == user.id)
    if not allowed:
        abort(403)
    if not storage_ready():
        abort(503)
    return redirect(signed_photo_url(photo.object_key))


@app.cli.command("cleanup-photos")
@click.option("--days", default=None, type=int, help="Delete proof photos older than this many days.")
def cleanup_photos(days):
    retention_days = days or int(os.environ.get("PHOTO_RETENTION_DAYS", "90"))
    cutoff = now() - timedelta(days=retention_days)
    rows = DeliveryPhoto.query.filter(DeliveryPhoto.created_at < cutoff).all()
    if not rows:
        click.echo("No expired proof photos found.")
        return
    if not storage_ready():
        raise click.ClickException("Object storage is not configured.")
    client = s3_client()
    deleted = 0
    for photo in rows:
        try:
            client.delete_object(Bucket=os.environ["S3_BUCKET"], Key=photo.object_key)
            db.session.delete(photo)
            deleted += 1
        except Exception:
            app.logger.exception("Could not delete proof object %s", photo.object_key)
    db.session.commit()
    click.echo(f"Deleted {deleted} expired proof photo(s).")


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, title="Access denied", message="You do not have permission to view this page."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, title="Page not found", message="The page or delivery you requested could not be found."), 404


@app.errorhandler(429)
def too_many(_):
    return render_template("error.html", code=429, title="Too many attempts", message="Please wait a little while and try again."), 429


@app.errorhandler(500)
def server_error(_):
    return render_template("error.html", code=500, title="Something went wrong", message="The error has been logged. Please try again."), 500


with app.app_context():
    db.create_all()
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if admin_email and len(admin_password) >= 10 and not User.query.filter(func.lower(User.email) == admin_email).first():
        db.session.add(User(name="BeautyDrop Admin", email=admin_email, password_hash=hash_password(admin_password), role="admin"))
        db.session.commit()


sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")))
    except Exception:
        app.logger.exception("Sentry initialization failed")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")

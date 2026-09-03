# BeautyDrop Canada — Launch Gate

This build completes the website and application code needed for a launch candidate. The items below marked **External** cannot be completed by code alone because they require business accounts, credentials, professional review, or operating decisions.

## Core app — INCLUDED
- Public marketing website: Home, About, For Stores, For Drivers, Pricing, Contact
- Store account signup/sign in
- Store delivery dashboard
- Store-specific products
- Store invoices
- Driver dashboard
- Admin dispatch center
- Public tracking search and tracking detail page
- QR tracking label
- Delivery event history
- Pickup code verification
- Customer PIN verification
- Optional pickup/delivery proof photo workflow
- Responsive mobile/desktop design
- 403 / 404 / 429 / 500 error pages

## Authentication & security — INCLUDED
- CSRF protection through Flask-WTF on state-changing forms
- Login rate limiting
- Password-reset request rate limiting
- Secure scrypt password hashing for all new/updated passwords
- Compatibility upgrade path for legacy BeautyDrop hashes
- Expiring, single-use password-reset tokens
- 8-hour expiring authenticated sessions by default
- HttpOnly / SameSite / Secure cookie controls
- Input length and type validation on major form fields
- Store authorization checks for store-owned data
- Driver authorization checks for assigned jobs
- Private delivery-photo authorization route
- Security response headers (CSP, HSTS on HTTPS, no-sniff, frame denial)
- Reduced public tracking data to avoid exposing customer address/phone/name

## SMS — CODE INCLUDED / EXTERNAL ACCOUNT REQUIRED
Integration is implemented for Twilio. Configure:
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_FROM_NUMBER

Transactional messages are wired for delivery creation, pickup, out-for-delivery/failure, and delivery completion.

**External:** obtain a Twilio account/number and confirm Canadian SMS consent/compliance requirements.

## Delivery proof — CODE INCLUDED / EXTERNAL STORAGE REQUIRED
Private S3-compatible object storage integration is implemented. Configure:
- S3_BUCKET
- S3_ACCESS_KEY
- S3_SECRET_KEY
- S3_ENDPOINT_URL (when using R2 or another S3-compatible provider)
- S3_REGION

Proof files are stored using non-public object keys. Authorized users receive short-lived signed links.

**External:** choose the storage provider and document a retention/deletion period.

## Payments — CODE INCLUDED / EXTERNAL STRIPE ACCOUNT REQUIRED
Stripe Checkout and a signed webhook endpoint are included for invoice payments. Configure:
- STRIPE_SECRET_KEY
- STRIPE_WEBHOOK_SECRET

The webhook marks successful checkout payments and associated invoices paid.

**External:** activate a real Stripe business account, configure the production webhook, decide refund/cancellation policy, and test live-mode payment/refund flows.

## Taxes — CONFIGURABLE / PROFESSIONAL CONFIRMATION REQUIRED
TAX_RATE is configurable and defaults to 0 so the app does not charge an unverified tax rate.

**External:** confirm GST/HST registration, applicable tax rate(s), invoice requirements and filing obligations with a Canadian tax professional/accountant before charging tax.

## Email/password reset — CODE INCLUDED / EXTERNAL EMAIL SERVICE REQUIRED
SMTP delivery is implemented. Configure:
- SMTP_HOST
- SMTP_PORT
- SMTP_USERNAME
- SMTP_PASSWORD
- MAIL_FROM

**External:** choose a production email provider and verify the sending domain.

## Monitoring — CODE INCLUDED / EXTERNAL ACCOUNT REQUIRED
Sentry integration is included via SENTRY_DSN.

Render application logs and health checks remain available.

**External:** create/configure the monitoring account and alert routing.

## Backups — EXTERNAL RENDER SETUP REQUIRED
The application uses the managed PostgreSQL database configured by Render.

**External:** select a Render database plan/backup policy suitable for production, verify automated backups are enabled, and perform a restoration test before launch. Do not rely on a free database tier for a business-critical production launch without confirming its backup/retention guarantees.

## Legal — DRAFT PAGES INCLUDED / PROFESSIONAL REVIEW REQUIRED
The website includes draft Privacy Policy and Terms of Service pages.

Still required before paid launch:
- Canadian lawyer review of Privacy Policy and Terms
- Merchant/store agreement
- Driver/independent contractor agreement
- Delivery/customer terms
- SMS consent language/process review
- Insurance broker review for commercial auto/courier/general liability/cargo exposures
- Legal review of contractor classification, prohibited goods, liability allocation and service areas

## Production data/security actions before launch
1. Set ADMIN_EMAIL and a unique ADMIN_PASSWORD in Render.
2. Remove/disable any old demo accounts that may already exist in the production database.
3. Do not publish or commit production secrets to GitHub.
4. Test one store account cannot view another store's deliveries/products/invoices.
5. Test one driver cannot complete another driver's assigned delivery.
6. Confirm all state-changing forms reject requests without a CSRF token.
7. Test password-reset link expiration and one-time use.
8. Test public tracking does not expose customer PII.
9. Test a real proof-photo upload after private storage credentials are added.
10. Test every configured SMS event with a Canadian mobile number.
11. Test Stripe live webhook verification and a refund/cancellation flow.
12. Confirm database backups and perform a restoration test.
13. Confirm legal/insurance/tax review is complete.

## Release decision
Do not call the service fully production-ready until every **External** requirement applicable to your launch is completed and documented.

## Shared login rate limiting — INCLUDED IN BLUEPRINT
The Render Blueprint creates a private `beautydrop-rate-limit` Key Value instance and supplies its internal connection string to Flask-Limiter. This avoids relying on per-process in-memory limits in production. The free Key Value tier is acceptable for disposable rate-limit counters because persistence is not required for this use case.

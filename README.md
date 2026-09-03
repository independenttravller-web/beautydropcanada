# BeautyDrop Canada V6 — Full Website Launch Candidate

BeautyDrop is a Flask/PostgreSQL delivery platform for beauty retailers, drivers, customers and administrators.

## Website included
- Full public homepage
- About
- For Stores
- For Drivers
- Pricing
- Contact
- Privacy Policy draft
- Terms of Service draft
- Store signup and login
- Forgot/reset password
- Store dashboard
- Product management
- Store invoices + optional Stripe Checkout
- Driver dashboard
- Admin operations dashboard
- Public delivery tracking
- QR tracking labels
- Responsive purple/white BeautyDrop design

## Security and operations included
- CSRF protection
- Login and reset rate limits
- Secure password hashing
- Expiring single-use reset tokens
- Secure session settings
- Authorization checks by role/store/driver
- Security headers
- Private S3-compatible delivery-photo workflow
- Optional Twilio SMS
- Optional SMTP email
- Optional Stripe payments/webhook
- Optional Sentry monitoring
- Render health endpoint

## Render deployment
1. Push the entire project to the GitHub repository.
2. Render reads `render.yaml`.
3. Set the required production environment values in Render, especially `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
4. Deploy.
5. Open `/health` and confirm HTTP 200 and `database: ok`.
6. Sign in with the admin account you configured.
7. Complete the external items in `LAUNCH_CHECKLIST.md` before accepting real customer data or payments.

## Existing databases
This build preserves the original Delivery/User/Invoice table columns and adds new tables with `db.create_all()`, which minimizes the risk of breaking an existing V6 database. For future schema changes, use Flask-Migrate/Alembic migrations rather than editing live tables manually.

## Important
Do not use old `@beautydrop.local` demo credentials in production. If they already exist in the database from an earlier V6 deployment, disable them from the admin dashboard before launch.

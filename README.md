# BeautyDrop Canada V6 — Production Starter

This version is prepared for simple cloud deployment with Render Blueprint and PostgreSQL.

## Easiest deployment
1. Put this folder in a GitHub repository.
2. In Render choose **New → Blueprint** and select the repository.
3. Render reads `render.yaml`, creates the web service and PostgreSQL database, generates a SECRET_KEY, and deploys the app.
4. Open the generated HTTPS URL.

Render's Blueprint config is included so you do not need to manually enter build/start commands.

## Demo accounts
- admin@beautydrop.local / ChangeMe123!
- store@beautydrop.local / ChangeMe123!
- driver@beautydrop.local / ChangeMe123!

Change these passwords before real use.

## Included
- Merchant, driver, admin roles
- PostgreSQL in production / SQLite fallback locally
- Delivery IDs and status workflow
- Pickup code verification
- Customer PIN verification
- Public tracking page and JSON tracking API
- Audit/event trail
- Driver assignment
- QR-code label endpoint
- Customer signature field
- Invoice totals
- CSV export
- Secure server-side password hashing
- Secure session defaults
- Health endpoint

## Before accepting real customer data
Add/confirm: CSRF protection, login rate limiting, password reset, SMS provider, object storage for delivery photos, formal privacy policy/terms, insurance and legal review, monitoring/backups, and production payment/tax setup.

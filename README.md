# BeautyDrop Canada V7 Complete

This build fixes the store login and delivery workflow and keeps the purple/white BeautyDrop design.

## Working flow

Store application -> admin approval -> store login -> Store Dashboard -> Create Delivery -> schedule ASAP or later -> see estimated delivery fee/tax/ETA -> submit -> admin sees request -> admin assigns driver -> driver sees assigned job -> pickup verification -> status updates -> customer tracking -> delivery PIN/proof -> delivery history.

Driver application -> admin approval -> driver login -> Driver Dashboard.

Admin Dashboard includes account approvals, dispatch assignment, invoices/payments, integration status, CSV export and editable delivery pricing. Homepage and store delivery form use the same pricing rules.

## Important URLs

- `/` public homepage + range meter
- `/signup/store` store application
- `/signup/driver` driver application
- `/login` role-aware login
- `/store-dashboard` store workspace
- `/store-dashboard/create-delivery` create/schedule delivery
- `/driver-dashboard` driver workspace
- `/admin-dashboard` admin workspace
- `/track` public tracking

## Deployment

Designed for Render using `render.yaml`, Postgres, and Render Key Value.

For an existing Render Blueprint, add any new `sync: false` environment variables manually in Render. At minimum set a strong `ADMIN_EMAIL` and `ADMIN_PASSWORD` so a new administrator can be created.

Production integrations such as Stripe, Twilio, object storage, SMTP email and Sentry require your own external account credentials. Legal documents in this project are drafts and should be reviewed for your actual business before launch.

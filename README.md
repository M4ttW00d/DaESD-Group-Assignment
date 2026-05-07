# Bristol Regional Food Network

A distributed multi-vendor marketplace connecting Bristol-area food producers with customers, community group representatives, and admins. Built as a microservices system for the Distributed and Enterprise Software Engineering module.

🌐 **Live site:** [brfn.co.uk](https://brfn.co.uk) (Online until **1/6/2025**, unless a delayed termination date is agreed)

## Architecture

Five containerised services on a shared MySQL backend, orchestrated with Docker Compose:

| Service | Port | Responsibility |
|---|---|---|
| **frontend** | 8000 | Server-rendered web UI (Django + templates) |
| **notifications-api** | 8001 | In-app + transactional email notifications (via Brevo) |
| **platform-api** | 8002 | Core business logic - users, products, orders, baskets, reviews, recurring orders, surplus deals, food miles |
| **payment-gateway** | 8003 | Stripe-backed payment processing, webhooks, weekly producer settlements via Stripe Connect |
| **platform-cron** | - | Scheduled jobs (recurring orders, reminders, seasonal alerts) |
| **db** | 3306 | MySQL 8.0 - single shared database |

In production (brfn.co.uk), all services sit behind nginx with HTTPS via Let's Encrypt.

## Notable features

- **Multi-vendor checkout** - a single customer order is split into per-producer sub-orders with independent fulfillment lifecycles
- **Stripe payments** - hosted checkout, refunds, webhooks, weekly producer settlements with a 95/5 commission split
- **Food miles** - straight-line distance from customer to producer postcode, calculated via postcodes.io and stored on each order
- **Surplus deals** - producers can apply percentage discounts; pricing flows through baskets and checkout automatically
- **Recurring orders** - weekly schedules processed by a cron service, with reminder emails the day before
- **Reviews** - 1–5 star reviews with auto-recomputed product ratings via Django signals
- **Bulk orders** - community group representatives can place larger orders with delivery instructions
- **Seasonal reminders** - monthly emails about what's in season from local producers
- **GDPR soft-delete** - user deletion scrubs PII rather than dropping rows, preserving historical order data
- **Custom admin dashboard** - bespoke UI for revenue, commission, food miles, settlements, and user management

## Team Members & Service Ownership

| Service Ownership | Primary Responsibilities | Owner |
|-------------------|--------------------------|-------|
| Frontend Service | Web UI, templates, user experience | Matt Wood |
| Notifications API | Producer and customer notifications, email | Kaan Karadag |
| Customer (Platform API) | Baskets, checkout, multi-vendor orders, order history | Dina Metwalli |
| Producer (Platform API) | Browse, search, listings, fulfillment, surplus alerts, users | Leon Stansfield |
| Payment Gateway | Stripe integration, settlements, invoices | Amine Ziani |
| Platform API (cross-cutting) | Payments, discounts, catalog | Matt & Kaan |

## Quick Start

### Prerequisites
- Docker Desktop (or Docker Engine + Compose plugin on Linux)
- Git

### First-time setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/matthewwooduwe/DaESD-Group-Assignment.git
cd DaESD-Group-Assignment

# 2. Create your local env file
cp .env.example .env
# Defaults work for local development. For production deployment you'll
# want a real SECRET_KEY, JWT_SECRET_KEY, and database passwords.

# 3. Build and start everything
docker compose up --build

# 4. Run migrations for notifications and payment-gateway services.
docker compose exec notifications-api python manage.py migrate
docker compose exec payment-gateway python manage.py migrate
```

Migrations run automatically for the platform-api container's first boot (controlled by `RUN_MIGRATIONS=true`). You should now have:

- Frontend: <http://localhost:8000>
- Notifications API: <http://localhost:8001>
- Platform API: <http://localhost:8002>
- Payment Gateway: <http://localhost:8003>
- MySQL: localhost:3306

### Optional: seed demo data

```bash
docker compose exec platform-api python manage.py seed_db
```

Populates the database with sample products, producers, customers, and orders.

### Optional: Django superuser

```bash
docker compose exec platform-api python manage.py createsuperuser
```

## Sensitive credentials (Stripe + Email)

Real Stripe and Brevo credentials are kept out of `.env` and `docker-compose.yml`. Each service reads them from a local `.env.secure` file that's gitignored:

**`services/payment-gateway-service/.env.secure`** (for live Stripe - optional in development):

```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_CURRENCY=gbp
```

**`services/notifications-service/.env.secure`** (for transactional emails via Brevo):

```
BREVO_SECRET_KEY=xkeysib-...
BREVO_SENDER_EMAIL=verified-sender@yourdomain.com
BREVO_SENDER_NAME=BRFN Marketplace
```

In development without these, Stripe checkout and email sending will no-op gracefully - in-app notifications and the rest of the site continue to work normally.

## Daily Workflow

```bash
# Start work
git pull origin main
git checkout -b feature/your-thing
docker compose up

# Watch logs
docker compose logs -f platform-api

# Open a Django shell
docker compose exec platform-api python manage.py shell

# Make a model change → migrate
docker compose exec platform-api python manage.py makemigrations
docker compose exec platform-api python manage.py migrate

# Stop everything
docker compose down
```

## Branches

- `main` - protected; integration branch
- `aws-live` - running on the live brfn.co.uk EC2 instance
- `feature/*` - feature branches off main, merged via PR
- `fix/*` - bug fix branches

PR review is required before merging into `main`. The `aws-live` branch is updated via cherry-pick or selective `git checkout origin/main -- <file>` to avoid disturbing production-only config.

## Useful Commands

```bash
# Database access
docker compose exec db mysql -u brfn_user -p brfn_db

# Rebuild a specific service after dependency changes
docker compose build platform-api

# Restart one service (faster than up --build for code-only changes)
docker compose restart frontend

# Backfill food miles on existing orders (one-shot management command)
docker compose exec platform-api python manage.py backfill_food_miles

# Wipe everything and start fresh (WARNING: drops all data)
docker compose down -v
```

## Testing

```bash
# Run all tests for a service
docker compose exec platform-api python manage.py test

# Run a specific test
docker compose exec platform-api python manage.py test orders.tests.OrderModelTests

# With coverage
docker compose exec platform-api coverage run --source='.' manage.py test
docker compose exec platform-api coverage report
```

## Sprint Workflow

| Sprint | Weeks | Focus |
|---|---|---|
| Sprint 0 | 1–3 | Setup, Docker, team roles, architecture |
| Sprint 1 | 4–6 | Database models, auth, core CRUD |
| Sprint 2 | 7–9 | Inter-service APIs, business logic |
| Sprint 3 | 10–12 | Full implementation, test coverage, security, presentation |

Project board: <https://github.com/users/matthewwooduwe/projects/1>

## Troubleshooting

**Port already in use** - another process (or a previous compose run) is using one of 8000/8001/8002/8003/3306. Run `docker compose down` to release; `lsof -i :8000` to identify a non-Docker culprit.

**Database connection errors on first start** - the `db` service can take 10–20 seconds to come up. The `depends_on: { condition: service_healthy }` blocks should handle this; if not, `docker compose down -v && docker compose up --build` will reset cleanly.

**Permission errors on volumes (Linux)** - `sudo chown -R $USER:$USER .`

**Login returns 403 (production behind a proxy)** - Django's CSRF middleware needs `CSRF_TRUSTED_ORIGINS` and `SECURE_PROXY_SSL_HEADER` set. See the production settings blocks in each service's `settings.py`.

## Project Documentation

- [Contributing guide](docs/CONTRIBUTING.md)
- [Producer walkthrough](PRODUCER_WALKTHROUGH.md)
- [Cross-platform setup notes](docs/CROSS_PLATFORM_GUIDE.md)
- [Sprint backlogs](docs/sprint-backlogs/)
- [Standup notes](docs/standups/)
- [Service relationship diagram](docs/services/)
- [Contributions matrix template](docs/Contributions_Matrix_Template.md)

## Assessment

- **Group mark:** Sprint 1 (15%) + Sprint 2 (15%) + Sprint 3 (50%)
- **Individual mark:** Group mark × Contribution % + Standup score (20%)
- **Test cases:** must pass 70%+ for first-class marks
- **Submission:** GitHub link + signed contributions matrix by 7th May 2026

## Support

- **Module Leaders:** Dr. Khoa Phung, Dilshan Jayatilake
- **Team Lead:** Matt Wood
- **Teams Channel:** DESD group 1

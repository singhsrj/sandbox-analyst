# Deploying SandboxAnalyst

Target (ADR-026): the **web app on Vercel** (free, HTTPS on `*.vercel.app`) and the **API on one small EC2 server** in `ap-south-1` running Docker: Caddy terminates HTTPS and is the only way in, the API sits on a private Docker network. Neon, E2B, Bedrock and Langfuse stay where they are.

```
browser ── HTTPS ──> Vercel (Next.js, static)
   │
   └──── HTTPS ──> <name>.duckdns.org : Caddy ──> api (private network) ──> Neon / E2B / Bedrock / Langfuse
```

Facts checked on 2026-11-06 (re-check before you rely on them):
- **t4g.small** (2 vCPU Graviton, 2 GB RAM) is free for up to 750 hours a month until 2026-12-31 for all AWS accounts; after that it is billed (from credits). The image builds and imports on arm64 (verified with an emulated arm64 build).
- A public IPv4 address costs $0.005 an hour (about $3.65 a month); the EC2 free tier includes 750 hours a month of it.
- **DuckDNS** is on the Public Suffix List, so `<name>.duckdns.org` gets its own Let's Encrypt rate limit. `sslip.io` is not on it: all its users share one limit of 50 certificates a week, so issuance can fail.

## 0. Before anything: a spending alarm

AWS console → **Billing and Cost Management → Budgets → Create budget → Cost budget**:
- Monthly amount: **$15** (adjust).
- Under advanced options, **untick "Credits"** so the budget tracks real usage, not usage after credits.
- Alerts at 50%, 80% and 100% of actual cost, to your email.

## 1. The server

1. **EC2 → Launch instance** in **Asia Pacific (Mumbai) ap-south-1**:
   - Name `sandbox-analyst`, AMI **Ubuntu Server 24.04 LTS (64-bit Arm)**, type **t4g.small**.
   - Key pair: create one (`.pem`), keep it private.
   - Network: create a security group with
     - SSH (22) from **My IP** only,
     - HTTP (80) and HTTPS (443) from anywhere (Caddy needs 80 for the certificate challenge and redirects it to 443).
   - Storage: 20 GB gp3.
2. **Elastic IP:** EC2 → Elastic IPs → Allocate → Associate with the instance. The address then survives a stop/start, so DNS does not have to change.
3. **DNS:** sign in at duckdns.org (GitHub/Google), add a subdomain (for example `sandbox-analyst`), set its IP to the Elastic IP. Check: `nslookup sandbox-analyst.duckdns.org` returns it.

## 2. Install and start

```bash
ssh -i sandbox-analyst.pem ubuntu@<elastic-ip>

# Docker Engine + Compose plugin (official convenience script; review it first if you prefer)
curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
sudo usermod -aG docker ubuntu && exit      # log in again so the group applies
ssh -i sandbox-analyst.pem ubuntu@<elastic-ip>

git clone https://github.com/singhsrj/sandbox-analyst.git && cd sandbox-analyst/deploy
cp .env.production.example .env && chmod 600 .env
nano .env        # API_HOST=sandbox-analyst.duckdns.org, secrets, CORS_ALLOW_ORIGINS (step 4)
docker compose up -d --build
docker compose ps                 # api "healthy", caddy "Up"
docker compose logs caddy | grep -i certificate   # "certificate obtained successfully"
curl https://sandbox-analyst.duckdns.org/api/health
```

The server never gets `ADMIN_DATABASE_URL`: migrations and seeding run from your machine.

**Check the client IP once** (the per-network rate limits depend on it): open the health URL from your phone on mobile data, then `docker compose logs api | tail` must show that phone's public IP, not `172.28.0.x`. If it shows `172.28.0.1`, Docker's userland proxy is hiding client addresses; fix that before going public (see ADR-026).

## 3. The web app on Vercel

1. vercel.com → sign in with GitHub → **Add New → Project** → import `singhsrj/sandbox-analyst`.
2. **Root directory: `web`**. Framework: Next.js (detected).
3. Environment variable: `NEXT_PUBLIC_API_BASE_URL = https://sandbox-analyst.duckdns.org` (public value, no secrets).
4. Deploy. Note the URL, for example `https://sandbox-analyst.vercel.app`.

## 4. Connect the two

On the server: set `CORS_ALLOW_ORIGINS=https://sandbox-analyst.vercel.app` in `deploy/.env`, then `docker compose up -d` (recreates the API). Open the Vercel URL: examples, schema and recorded runs work without a code; live questions need `DEMO_ACCESS_CODE`.

Smoke test from your machine (real browser, live stack, costs tokens):
```bash
cd web && WEB_URL=https://sandbox-analyst.vercel.app node e2e/smoke.mjs
```

## Operating it

| Task | Command (in `~/sandbox-analyst/deploy`) |
|---|---|
| Update to the latest commit | `git pull && docker compose up -d --build` |
| Logs | `docker compose logs -f api` |
| Restart the API | `docker compose restart api` |
| Roll back | `git checkout <previous-commit> && docker compose up -d --build` |
| Stop everything | `docker compose down` (volumes keep certificates and files) |
| Turn live runs off, keep the site up | remove `DEMO_ACCESS_CODE` from `.env`, `docker compose up -d` (recorded runs stay available) |

Costs to watch: Bedrock tokens (bounded by the daily token budgets in `.env`), E2B sandbox time (idle sandboxes are killed after 5 minutes), the server after 2026-12-31, the public IPv4 address. The AWS budget alarm from step 0 covers all AWS-side costs.

# VPS Docker Deployment

Use this path when Render asks for payment information or when you need a
stable link that can be shared long term. Docker packages ScholarMind, but a
public link still needs a server with a public IP address.

Recommended setup:

- A VPS from any provider you can pay for, such as Tencent Cloud, Alibaba Cloud,
  Huawei Cloud, UCloud, DigitalOcean, Hetzner, or any school/cloud server.
- Ubuntu 22.04 or 24.04.
- 2 CPU cores and 4 GB RAM recommended. 1 CPU / 2 GB can work for a short demo,
  but wiki and PDF tasks will be slow.
- Open inbound ports `80` and, if using a domain, `443`.

## What the final user sees

Direct IP mode:

```text
http://SERVER_IP/
```

Domain mode:

```text
https://scholarmind.example.com/
```

Users only need this URL and the `AUTH_PASSWORD`. They do not need the source
code, Python, Node, or Docker.

## 1. Install Docker on the server

SSH into the server, then install Docker:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
newgrp docker
```

Check:

```bash
docker --version
docker compose version
```

## 2. Prepare the deploy folder

Create one folder on the server:

```bash
mkdir -p ~/scholarmind
cd ~/scholarmind
```

Download these three files from the GitHub repository:

```bash
curl -fsSLO https://raw.githubusercontent.com/cjx528/ScholarMind/main/deploy/docker-compose.server.yml
curl -fsSLO https://raw.githubusercontent.com/cjx528/ScholarMind/main/deploy/docker-compose.server-domain.yml
curl -fsSLO https://raw.githubusercontent.com/cjx528/ScholarMind/main/deploy/Caddyfile
curl -fsSLo .env.server https://raw.githubusercontent.com/cjx528/ScholarMind/main/deploy/.env.server.example
```

Edit `.env.server`:

```bash
nano .env.server
```

Required values:

```env
ZHIPU_API_KEY=your_real_key
EMBEDDING_API_KEY=your_real_key
AUTH_PASSWORD=your_site_password
AUTH_SECRET_KEY=replace_with_a_long_random_string
```

Generate a random secret if `openssl` is available:

```bash
openssl rand -hex 32
```

## 3A. Start with a direct IP link

Use this when you do not have a domain name yet:

```bash
docker compose --env-file .env.server -f docker-compose.server.yml pull
docker compose --env-file .env.server -f docker-compose.server.yml up -d
```

Open:

```text
http://SERVER_IP/
http://SERVER_IP/health
```

## 3B. Start with a domain and HTTPS

Point your domain DNS `A` record to the server IP first. Then set `.env.server`:

```env
SCHOLARMIND_DOMAIN=scholarmind.example.com
PUBLIC_ORIGIN=https://scholarmind.example.com
```

Start:

```bash
docker compose --env-file .env.server -f docker-compose.server-domain.yml pull
docker compose --env-file .env.server -f docker-compose.server-domain.yml up -d
```

Open:

```text
https://scholarmind.example.com/
https://scholarmind.example.com/health
```

Caddy obtains and renews HTTPS certificates automatically.

## Operations

Check status:

```bash
docker compose --env-file .env.server -f docker-compose.server.yml ps
docker logs -f scholarmind-web
```

For the domain compose file, replace the first command with:

```bash
docker compose --env-file .env.server -f docker-compose.server-domain.yml ps
```

Update to the newest image:

```bash
docker compose --env-file .env.server -f docker-compose.server.yml pull
docker compose --env-file .env.server -f docker-compose.server.yml up -d
```

For domain mode:

```bash
docker compose --env-file .env.server -f docker-compose.server-domain.yml pull
docker compose --env-file .env.server -f docker-compose.server-domain.yml up -d
```

Backup persistent data:

```bash
docker run --rm -v scholarmind_scholarmind_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/scholarmind-data-backup.tgz -C /data .
```

The persistent volume stores the SQLite database and downloaded PDFs.

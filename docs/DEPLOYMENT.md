# Deployment Guide

Cram-It is designed to be self-hosted. This guide covers local development, tunneled access, and production deployment.

---

## Table of Contents

1. [Local Development](#local-development)
2. [Cloudflare Tunnel](#cloudflare-tunnel)
3. [systemd Service](#systemd-service)
4. [Docker Deployment](#docker-deployment)
5. [HTTPS / SSL](#https--ssl)
6. [PWA Installation](#pwa-installation)

---

## Local Development

### Prerequisites

- Python 3.10+
- pip
- 4GB+ RAM (for sentence-transformers model)

### Setup

```bash
# Clone the repository
git clone https://github.com/babyLegionite/cram-it.git
cd cram-it

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run the server
python server.py
```

The server starts on `http://localhost:3000`.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `CRAM_IT_PORT` | No | 3000 | Server port |
| `CRAM_IT_PACK` | No | (first available) | Default pack to load |
| `CRAM_IT_DATA_DIR` | No | `./data` | Data directory path |
| `SECRET_KEY` | No | (random) | Flask session secret |
| `TELEGRAM_BOT_TOKEN` | No | — | Feedback notification bot |
| `TELEGRAM_CHAT_ID` | No | — | Feedback notification chat |

### First Run

On first run, Cram-It will:
1. Create `data/` directory with `learner.db`, `chroma_db/`, `profiles/`
2. Load the first available pack from `packs/`
3. Initialize the sentence-transformers model (downloads ~90MB on first run)

### Battle Mode

Battle Mode runs as a separate process:

```bash
# In a second terminal
cd kahoot
python game.py
```

Battle Mode starts on `http://localhost:4000`.

---

## Cloudflare Tunnel

Cloudflare Tunnels let you expose your local server to the internet without port forwarding, with free HTTPS.

### Install cloudflared

```bash
# macOS
brew install cloudflared

# Linux
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Windows
# Download from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
```

### Quick Tunnel (No Account Required)

```bash
# Tunnel the main server
cloudflared tunnel --url http://localhost:3000

# Tunnel Battle Mode (separate terminal)
cloudflared tunnel --url http://localhost:4000
```

This gives you a random `*.trycloudflare.com` URL.

### Named Tunnel (Custom Domain)

1. Log in to Cloudflare: `cloudflared tunnel login`
2. Create a tunnel: `cloudflared tunnel create cram-it`
3. Configure DNS in your Cloudflare dashboard
4. Create config file:

```yaml
# ~/.cloudflared/config.yml
tunnel: <TUNNEL_ID>
credentials-file: /path/to/credentials.json

ingress:
  - hostname: study.yourdomain.com
    service: http://localhost:3000
  - hostname: battle.yourdomain.com
    service: http://localhost:4000
  - service: http_status:404
```

5. Run: `cloudflared tunnel run cram-it`

### Running Both Together

Create a Makefile or shell script:

```bash
#!/bin/bash
# run.sh - Start everything

# Start Flask server
python server.py &
FLASK_PID=$!

# Start Battle Mode
cd kahoot && python game.py &
BATTLE_PID=$!

# Start tunnels
cloudflared tunnel --url http://localhost:3000 &
TUNNEL1_PID=$!

cloudflared tunnel --url http://localhost:4000 &
TUNNEL2_PID=$!

echo "Cram-It running. PIDs: Flask=$FLASK_PID Battle=$BATTLE_PID"
echo "Press Ctrl+C to stop all"

trap "kill $FLASK_PID $BATTLE_PID $TUNNEL1_PID $TUNNEL2_PID" EXIT
wait
```

---

## systemd Service

For running Cram-It as a persistent service on Linux:

### Main Server Service

```ini
# /etc/systemd/system/cram-it.service
[Unit]
Description=Cram-It Study Platform
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/cram-it
Environment="PATH=/home/YOUR_USERNAME/cram-it/venv/bin:/usr/bin"
Environment="ANTHROPIC_API_KEY=your_key_here"
Environment="CRAM_IT_PORT=3000"
ExecStart=/home/YOUR_USERNAME/cram-it/venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Battle Mode Service

```ini
# /etc/systemd/system/cram-it-battle.service
[Unit]
Description=Cram-It Battle Mode
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/cram-it/kahoot
Environment="PATH=/home/YOUR_USERNAME/cram-it/venv/bin:/usr/bin"
Environment="ANTHROPIC_API_KEY=your_key_here"
ExecStart=/home/YOUR_USERNAME/cram-it/venv/bin/python game.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Cloudflare Tunnel Service

```ini
# /etc/systemd/system/cram-it-tunnel.service
[Unit]
Description=Cram-It Cloudflare Tunnel
After=network.target cram-it.service

[Service]
Type=simple
User=YOUR_USERNAME
ExecStart=/usr/local/bin/cloudflared tunnel run cram-it
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Managing Services

```bash
# Enable and start
sudo systemctl enable cram-it cram-it-battle cram-it-tunnel
sudo systemctl start cram-it cram-it-battle cram-it-tunnel

# Check status
sudo systemctl status cram-it

# View logs
journalctl -u cram-it -f

# Restart after updates
sudo systemctl restart cram-it
```

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Pre-download sentence-transformers model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

EXPOSE 3000

CMD ["python", "server.py"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  cram-it:
    build: .
    ports:
      - "3000:3000"
    volumes:
      - ./data:/app/data
      - ./packs:/app/packs
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - CRAM_IT_PORT=3000
    restart: unless-stopped

  battle:
    build: .
    command: python kahoot/game.py
    ports:
      - "4000:4000"
    volumes:
      - ./packs:/app/packs
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    restart: unless-stopped

  tunnel:
    image: cloudflare/cloudflared:latest
    command: tunnel --config /etc/cloudflared/config.yml run
    volumes:
      - ./cloudflared:/etc/cloudflared
    depends_on:
      - cram-it
      - battle
    restart: unless-stopped
```

### Running with Docker

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f cram-it

# Rebuild after changes
docker-compose build && docker-compose up -d

# Stop
docker-compose down
```

### Data Persistence

The `data/` directory is mounted as a volume, so your SQLite database, ChromaDB embeddings, and user profiles persist across container restarts.

---

## HTTPS / SSL

### Option 1: Cloudflare Tunnel (Recommended)

Cloudflare Tunnels provide HTTPS automatically. This is the simplest option — no certificate management needed.

### Option 2: Let's Encrypt + nginx

If hosting on a VPS with a domain:

```nginx
# /etc/nginx/sites-available/cram-it
server {
    listen 443 ssl;
    server_name study.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/study.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/study.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE support (for AI tutor streaming)
    location /api/agent/stream {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    # WebSocket support (for Battle Mode)
    location /socket.io/ {
        proxy_pass http://127.0.0.1:4000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
# Get certificate
sudo certbot --nginx -d study.yourdomain.com
```

### Why HTTPS Matters

- **PWA installation** requires HTTPS (or localhost)
- **Service worker** only works on HTTPS (or localhost)
- **Security**: API keys are sent in requests

---

## PWA Installation

Once Cram-It is served over HTTPS, it can be installed as a native-feeling app.

### iPhone / iPad

1. Open Cram-It in Safari (must be Safari, not Chrome)
2. Tap the **Share** button (box with arrow)
3. Scroll down and tap **Add to Home Screen**
4. Name it and tap **Add**
5. The app now launches in standalone mode (no browser chrome)

### Android

1. Open Cram-It in Chrome
2. Tap the **three-dot menu**
3. Tap **Install app** or **Add to Home Screen**
4. Confirm the installation
5. The app appears in your app drawer

### Desktop (Chrome/Edge)

1. Open Cram-It in Chrome or Edge
2. Click the install icon in the address bar (or menu > Install)
3. The app opens in its own window

### Offline Behavior

After installation, the PWA:
- Caches the app shell for instant loading
- API responses are cached for offline viewing of last data
- The AI tutor requires an internet connection
- Drill mode can partially work offline with cached questions
- Full functionality resumes when online

### Updating the PWA

The service worker checks for updates on each visit. When a new version is detected:
1. New assets are cached in the background
2. On next visit, the updated version loads
3. To force update: clear site data in browser settings

#!/usr/bin/env bash
set -Eeuo pipefail

# Bootstrap a pre-created Oracle Cloud Always Free Ubuntu ARM64 VM.
# This script installs Docker and deploys the project; it does NOT create OCI resources.

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Usage: sudo bash scripts/install-oracle-vm.sh your.dns.name" >&2
  exit 2
fi

if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Invalid hostname. Provide a DNS hostname only, without https:// or a path." >&2
  exit 2
fi

if [[ ! -f /etc/os-release ]]; then
  echo "Cannot identify Linux distribution." >&2
  exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "This installer is for Ubuntu Server images only. Detected: ${ID:-unknown}" >&2
  exit 1
fi

ARCH="$(dpkg --print-architecture)"
if [[ "$ARCH" != "arm64" ]]; then
  echo "WARNING: this project is prepared for OCI Ampere A1 (arm64); detected $ARCH." >&2
  read -r -p "Continue anyway? Type YES to continue: " CONFIRM
  [[ "$CONFIRM" == "YES" ]] || exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git openssl ufw

# Install Docker Engine and the Compose plugin from Docker's official Ubuntu apt repository.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
CODENAME="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

APP_DIR="/opt/image-to-dxf"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" checkout main
  git -C "$APP_DIR" pull --ff-only origin main
elif [[ -e "$APP_DIR" ]]; then
  echo "$APP_DIR already exists and is not a Git checkout. Move it aside and rerun." >&2
  exit 1
else
  git clone --branch main --depth 1 https://github.com/Arcane3D/Arcane3D.git "$APP_DIR"
fi

cd "$APP_DIR"

if [[ ! -f .env ]]; then
  SECRET="$(openssl rand -hex 48)"
  cat > .env <<EOF
PUBLIC_DOMAIN=$DOMAIN
SECRET_KEY=$SECRET
ALLOWED_REDIRECTS=https://chatgpt.com/connector_platform_oauth_redirect,https://chatgpt.com/connector/oauth/
EOF
  chmod 600 .env
else
  echo "Existing .env preserved. Confirm PUBLIC_DOMAIN matches: $DOMAIN"
fi

# Open the host firewall for SSH and the HTTPS reverse proxy only.
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# Validate Compose configuration before building and starting services.
docker compose config --quiet
docker compose up -d --build

echo
echo "Deployment commands completed."
echo "Public URL: https://$DOMAIN/"
echo "MCP URL:    https://$DOMAIN/mcp"
echo
echo "If HTTPS is not ready yet, check that DNS points to this VM and that OCI VCN"
echo "security rules allow inbound TCP 80/443. Do not open port 8787 publicly."
echo "Inspect with: cd $APP_DIR && docker compose ps && docker compose logs --tail=100 api caddy"

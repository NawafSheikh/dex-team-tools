#!/usr/bin/env bash
# Install or update dev-tools on a Linux host with Docker. Copy this folder to /opt/devtools/src and run as root.
# Idempotent: keeps existing keys, rebuilds the image only with --rebuild.
# The sandbox gets NO GitHub credential; gitops.push runs a one-shot broker container with the key.
set -euo pipefail

SRC=/opt/devtools/src
NET=devbox-net
SUBNET=172.31.250.0/24
WORK=/srv/devbox/work

install -d -m 700 /opt/devtools/secrets /opt/devtools/state
install -d -m 755 /opt/devtools/logs
SUB_USER=${DEVTOOLS_SUBAGENT_USER:-devtools}
id -u "$SUB_USER" >/dev/null 2>&1 || useradd --system --create-home "$SUB_USER"
install -d -o "$SUB_USER" -m 700 /opt/devtools/claude-sub
install -d -o 1500 -g 1500 -m 755 "$WORK"
if [ ! -f /opt/devtools/secrets/deploy_key ]; then
  ssh-keygen -q -t ed25519 -N "" -C "devbox-deploy" -f /opt/devtools/secrets/deploy_key
fi
chown 1500:1500 /opt/devtools/secrets/deploy_key && chmod 600 /opt/devtools/secrets/deploy_key
chmod 711 /opt/devtools/secrets

if [ ! -f /opt/devtools/.env ]; then
  umask 077
  cat > /opt/devtools/.env <<EOF
DEVTOOLS_API_KEY=$(openssl rand -hex 32)
DEVTOOLS_SUB_KEY=$(openssl rand -hex 32)
DEVTOOLS_PORT=8095
DEVTOOLS_PUBLIC_HOSTS=
DEVTOOLS_GITHUB_REPOS=
EOF
fi

/opt/devtools/venv/bin/pip -q install "mcp==2.3.0" "uvicorn==0.38.0"

if [[ "${1:-}" == "--rebuild" ]] || ! docker image inspect devbox:1 >/dev/null 2>&1; then
  docker build -t devbox:1 "$SRC/sandbox"
fi

docker network inspect "$NET" >/dev/null 2>&1 || \
  docker network create --driver bridge --subnet "$SUBNET" -o com.docker.network.bridge.name=br-devbox "$NET"

# Firewall: the sandbox reaches the internet only. Not the host, not other containers.
cat > /usr/local/sbin/devbox-firewall <<EOF
#!/bin/sh
iptables -C INPUT -s $SUBNET -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
  iptables -I INPUT 1 -s $SUBNET -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -C INPUT -s $SUBNET -j REJECT 2>/dev/null || iptables -I INPUT 2 -s $SUBNET -j REJECT
for dst in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16; do
  iptables -C DOCKER-USER -s $SUBNET -d \$dst -j REJECT 2>/dev/null || iptables -I DOCKER-USER -s $SUBNET -d \$dst -j REJECT
done
EOF
chmod 755 /usr/local/sbin/devbox-firewall
/usr/local/sbin/devbox-firewall

if [[ "${1:-}" == "--rebuild" ]] && docker container inspect devbox >/dev/null 2>&1; then
  docker rm -f devbox
fi
if ! docker container inspect devbox >/dev/null 2>&1; then
  docker run -d --init --name devbox --hostname devbox --network "$NET" --restart unless-stopped \
    --memory 1200m --memory-swap 1600m --cpus 1.5 --pids-limit 256 \
    --cap-drop ALL --security-opt no-new-privileges \
    -v "$WORK":/work \
    devbox:1
fi

cp "$SRC/deploy/devtools.service" /etc/systemd/system/devtools.service
cp "$SRC/deploy/devbox-firewall.service" /etc/systemd/system/devbox-firewall.service
systemctl daemon-reload
systemctl enable --now devbox-firewall.service >/dev/null
systemctl enable devtools.service >/dev/null
systemctl restart devtools.service
sleep 2
systemctl is-active devtools.service

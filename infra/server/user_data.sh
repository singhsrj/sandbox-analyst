#!/bin/bash
# First boot of the API server: Docker, swap, the repository. No secrets here (user data is
# readable from the instance metadata); deploy/.env is copied over SSH afterwards.
set -euo pipefail
exec > /var/log/sandbox-analyst-setup.log 2>&1

# 2 GB swap: building the image and running the agent on 2 GB of RAM needs headroom.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

apt-get update -y
apt-get install -y ca-certificates curl git
# Docker Engine + Compose plugin from Docker's official apt repository.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu
systemctl enable --now docker

# Security updates are installed automatically (Ubuntu default); make sure it is on.
apt-get install -y unattended-upgrades

sudo -u ubuntu git clone ${repo_url} /home/ubuntu/sandbox-analyst
touch /var/lib/cloud/sandbox-analyst-ready

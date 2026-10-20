#!/usr/bin/env bash
# 排课系统部署脚本（Jason 的 fork 简体版 · 源码构建）— 草案，待探针结果微调
# 用法：在服务器 VNC 终端整体粘贴执行。出错停在出错处，截图回传即可定位。
set -euo pipefail

echo '===== 1/5 安装 Docker + git ====='
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git
sudo systemctl enable --now docker

echo '===== 2/5 配置镜像加速（拉 Docker Hub 兜底） ====='
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{"registry-mirrors":["https://docker.m.daocloud.io","https://docker.1panel.live"]}
JSON
sudo systemctl restart docker
docker --version; docker compose version

echo '===== 3/5 拉取代码（他的 fork，已含简体改动） ====='
[ -d ~/Course_Scheduling_System ] || git clone --depth 1 https://github.com/jason8668/Course_Scheduling_System.git ~/Course_Scheduling_System
cd ~/Course_Scheduling_System

echo '===== 4/5 生成 .env（管理员密码随机生成，记好下面的输出） ====='
if [ ! -f .env ]; then
  ADMIN_PW="$(openssl rand -base64 12 | tr -d '/+=' | head -c 16)"
  cat > .env <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$ADMIN_PW
SCHOOL_NAME=示范学校
TZ=Asia/Shanghai
SECRET_KEY=$(openssl rand -hex 32)
HTTP_PORT=80
IMAGE_TAG=latest
EOF
  echo ">>> 管理员账号: admin"
  echo ">>> 管理员初始密码: $ADMIN_PW （首次登录会强制改密码）"
fi

echo '===== 5/5 构建并启动（源码构建，切勿用 pull 的官方繁体镜像） ====='
sudo docker compose up -d --build
sudo docker compose ps
sleep 10
curl -s -o /dev/null -w '健康检查 HTTP:%{http_code}\n' http://localhost/api/health || true
echo '完成：浏览器打开 http://36.133.38.128'

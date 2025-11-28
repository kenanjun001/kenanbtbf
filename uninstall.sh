#!/bin/bash

# DB Backup Bot 卸载脚本

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }

SERVICE_NAME="db-backup-bot"
INSTALL_DIR="/opt/db-backup-bot"

log "停止服务..."
systemctl stop $SERVICE_NAME 2>/dev/null || true
systemctl disable $SERVICE_NAME 2>/dev/null || true

log "删除服务文件..."
rm -f /etc/systemd/system/$SERVICE_NAME.service
systemctl daemon-reload

read -p "是否删除数据文件? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf $INSTALL_DIR
    log "已删除所有文件"
else
    rm -rf $INSTALL_DIR/venv
    rm -f $INSTALL_DIR/*.py
    rm -rf $INSTALL_DIR/templates
    log "已保留数据目录: $INSTALL_DIR/data"
fi

log "卸载完成!"

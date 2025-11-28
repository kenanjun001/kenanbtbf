#!/bin/bash

# DB Backup Bot 一键安装脚本
# 支持: Ubuntu/Debian/CentOS (ARM64/x86_64)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# 检查root
[ "$EUID" -ne 0 ] && error "请使用 root 用户运行"

INSTALL_DIR="/opt/db-backup-bot"
SERVICE_NAME="db-backup-bot"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

log "=========================================="
log "  DB Backup Bot 安装脚本 (ARM/x86)"
log "=========================================="

# 检测架构
ARCH=$(uname -m)
log "系统架构: $ARCH"

# 检测系统
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    log "操作系统: $OS"
else
    error "无法检测操作系统"
fi

# 安装依赖
log "安装系统依赖..."
case $OS in
    ubuntu|debian)
        apt-get update
        apt-get install -y python3 python3-pip python3-venv curl
        ;;
    centos|rhel|rocky|almalinux)
        yum install -y python3 python3-pip curl
        ;;
    *)
        error "不支持的系统: $OS"
        ;;
esac

# 停止旧服务
systemctl stop $SERVICE_NAME 2>/dev/null || true

# 创建安装目录
log "创建安装目录..."
mkdir -p $INSTALL_DIR/{data,backups}

# 复制文件
log "复制程序文件..."
cp "$SCRIPT_DIR"/*.py "$INSTALL_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR"/requirements.txt "$INSTALL_DIR/" 2>/dev/null || true
cp -r "$SCRIPT_DIR"/templates "$INSTALL_DIR/" 2>/dev/null || true

# 检查文件
[ ! -f "$INSTALL_DIR/app.py" ] && error "未找到 app.py，请确保程序文件完整"

# 创建虚拟环境
log "创建Python虚拟环境..."
cd $INSTALL_DIR
python3 -m venv venv
source venv/bin/activate

log "安装Python依赖..."
pip install --upgrade pip
pip install -r requirements.txt
pip install python-dotenv

# 创建systemd服务
log "创建系统服务..."
cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=DB Backup Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python start.py
Restart=always
RestartSec=10
Environment=FLASK_ENV=production

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME

sleep 2

# 检查状态
if systemctl is-active --quiet $SERVICE_NAME; then
    IP=$(curl -s ip.sb 2>/dev/null || hostname -I | awk '{print $1}')
    
    echo ""
    log "=========================================="
    log "  安装成功! 服务已后台运行"
    log "=========================================="
    echo ""
    echo -e "  访问地址: ${GREEN}http://$IP:5000${NC}"
    echo -e "  默认账号: ${GREEN}admin${NC}"
    echo -e "  默认密码: ${GREEN}admin123${NC}"
    echo ""
    echo "  服务管理命令:"
    echo "    systemctl start $SERVICE_NAME    # 启动"
    echo "    systemctl stop $SERVICE_NAME     # 停止"
    echo "    systemctl restart $SERVICE_NAME  # 重启"
    echo "    systemctl status $SERVICE_NAME   # 状态"
    echo "    journalctl -u $SERVICE_NAME -f   # 日志"
    echo ""
else
    error "启动失败，查看日志: journalctl -u $SERVICE_NAME -f"
fi

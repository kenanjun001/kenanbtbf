#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DB Backup Bot 启动脚本
双击运行或命令行执行: python start.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
VENV_DIR = BASE_DIR / "venv"
REQUIREMENTS = BASE_DIR / "requirements.txt"
ENV_FILE = BASE_DIR / ".env"
ENV_EXAMPLE = BASE_DIR / ".env.example"
BACKUPS_DIR = BASE_DIR / "backups"


def run_cmd(cmd, check=True):
    """执行命令"""
    print(f">>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if check and result.returncode != 0:
        print(f"[错误] 命令执行失败: {result.returncode}")
        return False
    return True


def get_python():
    """获取Python路径"""
    if sys.platform == "win32":
        venv_python = VENV_DIR / "Scripts" / "python.exe"
        venv_pip = VENV_DIR / "Scripts" / "pip.exe"
    else:
        venv_python = VENV_DIR / "bin" / "python"
        venv_pip = VENV_DIR / "bin" / "pip"
    return venv_python, venv_pip


def setup_venv():
    """创建虚拟环境"""
    if not VENV_DIR.exists():
        print("[INFO] 创建虚拟环境...")
        if not run_cmd([sys.executable, "-m", "venv", str(VENV_DIR)]):
            return False
    return True


def install_deps():
    """安装依赖"""
    venv_python, venv_pip = get_python()
    
    if not venv_pip.exists():
        print("[错误] 虚拟环境创建失败")
        return False
    
    print("[INFO] 安装依赖...")
    return run_cmd([str(venv_pip), "install", "-r", str(REQUIREMENTS)])


def setup_env():
    """配置环境变量文件"""
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        print("[INFO] 创建配置文件 .env")
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        print()
        print("=" * 50)
        print("请编辑 .env 文件配置以下内容:")
        print("  - TG_BOT_TOKEN: Telegram Bot Token")
        print("  - TG_CHAT_IDS: 接收通知的Chat ID")
        print("  - ADMIN_PASSWORD: 管理员密码")
        print("=" * 50)
        print()


def main():
    print("=" * 50)
    print("   DB Backup Bot - 数据库备份管理系统")
    print("=" * 50)
    print()
    
    # 检查 Python 版本
    print(f"[INFO] Python: {sys.version}")
    if sys.version_info < (3, 8):
        print("[错误] 需要 Python 3.8+")
        input("按回车键退出...")
        return
    
    # 创建虚拟环境
    if not setup_venv():
        input("按回车键退出...")
        return
    
    # 安装依赖
    if not install_deps():
        input("按回车键退出...")
        return
    
    # 配置文件
    setup_env()
    
    # 创建备份目录
    BACKUPS_DIR.mkdir(exist_ok=True)
    
    # 启动服务
    venv_python, _ = get_python()
    app_py = BASE_DIR / "app.py"
    
    print()
    print("[INFO] 启动服务...")
    print("[INFO] 访问地址: http://localhost:5000")
    print("[INFO] 默认账号: admin / admin123")
    print("[INFO] 按 Ctrl+C 停止服务")
    print()
    
    try:
        subprocess.run([str(venv_python), str(app_py)], cwd=BASE_DIR)
    except KeyboardInterrupt:
        print("\n[INFO] 服务已停止")
    
    print()
    input("按回车键退出...")


if __name__ == "__main__":
    main()

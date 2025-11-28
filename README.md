# DB Backup Bot

🗄️ 数据库备份机器人 - 通过宝塔面板API自动备份数据库并推送到Telegram

## ✨ 功能特性

- 🔌 **宝塔面板集成** - 通过API远程执行数据库备份
- 📤 **Telegram推送** - 备份完成自动推送文件到Telegram
- ⏰ **定时备份** - 支持每小时/每天/每周自动备份
- 🗑️ **自动清理** - 备份推送后自动删除服务器文件和回收站
- 📊 **Web管理界面** - 简洁的管理后台
- 🔐 **安全认证** - Web界面登录保护
- 💾 **大文件支持** - 支持GB级别数据库备份（需Telegram Premium）

## 📋 系统要求

- Linux服务器（Ubuntu/Debian/CentOS，支持ARM64和x86_64）
- Python 3.8+
- 宝塔面板（需开启API）

## 🚀 一键安装

```bash
# 1. 下载
git clone https://github.com/kenanjun001/kenanbtbf.git
cd kenanbtbf

# 2. 安装
chmod +x install.sh
./install.sh
```

安装完成后会自动创建systemd服务，支持开机自启和后台运行。

## 📱 访问面板

- **地址**: `http://服务器IP:5000`
- **账号**: `admin`
- **密码**: `admin123`

⚠️ 请首次登录后修改密码！

## ⚙️ 配置步骤

### 1. 配置Telegram Bot

1. 在Telegram中找 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 创建机器人
3. 获取 Bot Token（格式：`123456789:ABCdefGHI...`）
4. 获取 Chat ID：
   - 给机器人发送一条消息
   - 访问 `https://api.telegram.org/bot<你的Token>/getUpdates`
   - 找到 `chat.id`
5. 在程序的 **设置** 页面填入 Bot Token 和 Chat ID

### 2. 配置宝塔面板

1. 登录宝塔面板
2. 进入 **设置** → **API接口**
3. 开启API接口
4. 添加IP白名单（运行本程序的服务器IP）
   - 查看IP: `curl ip.sb`
5. 复制API密钥
6. 在程序的 **宝塔面板** 页面添加：
   - 名称：随便填
   - URL：`http://宝塔服务器IP:8888`（或你的面板地址）
   - API密钥：粘贴复制的密钥

### 3. 备份数据库

1. 进入 **宝塔面板** 页面
2. 点击 **加载数据库**
3. 选择要备份的数据库
4. 点击 **立即备份** 或设置定时备份

## 🔧 服务管理

```bash
# 启动服务
systemctl start db-backup-bot

# 停止服务
systemctl stop db-backup-bot

# 重启服务
systemctl restart db-backup-bot

# 查看状态
systemctl status db-backup-bot

# 查看日志
journalctl -u db-backup-bot -f
```

## 📁 目录结构

```
/opt/db-backup-bot/          # 安装目录（install.sh安装时）
├── app.py                   # 主程序
├── start.py                 # 启动脚本
├── models.py                # 数据模型
├── bt_panel.py              # 宝塔API客户端
├── telegram_bot.py          # Telegram推送
├── backup.py                # 备份逻辑
├── config.py                # 配置文件
├── scheduler.py             # 定时任务
├── requirements.txt         # 依赖列表
├── templates/               # 网页模板
├── data/                    # 数据目录
│   └── data.db             # SQLite数据库
├── backups/                 # 备份临时目录
└── venv/                    # Python虚拟环境
```

## 🔄 更新程序

```bash
cd /opt/db-backup-bot
systemctl stop db-backup-bot

# 备份数据
cp data/data.db data/data.db.bak

# 下载新版本并覆盖文件
# ...

systemctl start db-backup-bot
```

## 🗑️ 卸载

```bash
chmod +x uninstall.sh
./uninstall.sh
```

## ❓ 常见问题

### Q: 宝塔API连接失败？
A: 检查以下几点：
- 宝塔面板API是否开启
- IP白名单是否添加
- 面板URL是否正确（包含端口）
- 防火墙是否放行

### Q: Telegram收不到消息？
A: 检查以下几点：
- Bot Token是否正确
- Chat ID是否正确
- 是否已给机器人发送过消息（激活对话）

### Q: 大文件备份失败？
A: 
- Telegram普通用户单文件限制50MB
- Telegram Premium用户单文件限制4GB
- 程序已设置2小时上传超时，支持大文件

### Q: 服务无法启动？
A: 查看日志排查：
```bash
journalctl -u db-backup-bot -f
```

## 📝 更新日志

### v1.0.0
- 初始版本
- 支持宝塔面板API备份
- 支持Telegram推送
- 支持定时备份
- 自动清理备份文件

## 📄 License

MIT License

## 🙏 致谢

- [Flask](https://flask.palletsprojects.com/)
- [python-telegram-bot](https://python-telegram-bot.org/)
- [APScheduler](https://apscheduler.readthedocs.io/)
- [宝塔面板](https://www.bt.cn/)

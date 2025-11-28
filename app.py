import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config, BACKUP_DIR
from models import db, User, DatabaseConfig, BackupHistory, SystemLog, Settings, BtPanelConfig, BtDatabaseConfig
from backup import run_backup, restore_backup, log
from telegram_bot import sync_upload_backup, sync_send_notification
from scheduler import scheduler, init_scheduler, update_job, remove_job, get_scheduled_jobs
from bt_panel import BtPanel

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# API token for external calls
API_TOKEN = None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def api_auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-API-Token')
        if token and API_TOKEN and token == API_TOKEN:
            return f(*args, **kwargs)
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized'}), 401
    return decorated

# Initialize database
with app.app_context():
    db.create_all()
    
    # Create default admin user
    if not User.query.filter_by(username=Config.ADMIN_USERNAME).first():
        admin = User(
            username=Config.ADMIN_USERNAME,
            password_hash=generate_password_hash(Config.ADMIN_PASSWORD)
        )
        db.session.add(admin)
        db.session.commit()
        log(f'Created admin user: {Config.ADMIN_USERNAME}')
    
    # Generate API token
    API_TOKEN = Settings.get('api_token')
    if not API_TOKEN:
        API_TOKEN = secrets.token_urlsafe(32)
        Settings.set('api_token', API_TOKEN)

# Initialize scheduler
init_scheduler(app)

# ==================== Auth Routes ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user:
            # Check lockout
            if user.locked_until and user.locked_until > datetime.utcnow():
                remaining = (user.locked_until - datetime.utcnow()).seconds // 60
                flash(f'Account locked. Try again in {remaining} minutes.', 'error')
                return render_template('login.html')
            
            if check_password_hash(user.password_hash, password):
                user.login_attempts = 0
                user.locked_until = None
                db.session.commit()
                login_user(user)
                log(f'User {username} logged in')
                return redirect(url_for('dashboard'))
            else:
                user.login_attempts += 1
                if user.login_attempts >= Config.MAX_LOGIN_ATTEMPTS:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=Config.LOGIN_LOCKOUT_MINUTES)
                    log(f'Account {username} locked due to failed attempts', 'warning')
                db.session.commit()
        
        flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==================== Dashboard ====================

@app.route('/')
@login_required
def dashboard():
    databases = DatabaseConfig.query.all()
    bt_databases = BtDatabaseConfig.query.all()
    recent_backups = BackupHistory.query.order_by(BackupHistory.created_at.desc()).limit(10).all()
    jobs = get_scheduled_jobs()
    
    # 统计直连数据库 + 宝塔数据库
    total_db = len(databases) + len(bt_databases)
    enabled_db = sum(1 for d in databases if d.enabled) + sum(1 for d in bt_databases if d.enabled)
    
    stats = {
        'total_databases': total_db,
        'enabled_databases': enabled_db,
        'total_backups': BackupHistory.query.count(),
        'successful_backups': BackupHistory.query.filter_by(status='success').count(),
        'failed_backups': BackupHistory.query.filter_by(status='failed').count(),
    }
    
    return render_template('dashboard.html', 
                         databases=databases, 
                         bt_databases=bt_databases,
                         recent_backups=recent_backups,
                         scheduled_jobs=jobs,
                         stats=stats)

# ==================== Database Management ====================

@app.route('/databases')
@login_required
def databases():
    databases = DatabaseConfig.query.all()
    return render_template('databases.html', databases=databases)

@app.route('/api/databases', methods=['GET'])
@api_auth_required
def api_get_databases():
    databases = DatabaseConfig.query.all()
    return jsonify([d.to_dict() for d in databases])

@app.route('/api/databases', methods=['POST'])
@api_auth_required
def api_create_database():
    data = request.json
    
    db_config = DatabaseConfig(
        name=data['name'],
        db_type=data['db_type'],
        host=data.get('host', 'localhost'),
        port=data.get('port'),
        database=data['database'],
        username=data.get('username'),
        enabled=data.get('enabled', True),
        schedule_enabled=data.get('schedule_enabled', False),
        schedule_type=data.get('schedule_type', 'daily'),
        schedule_time=data.get('schedule_time', '03:00'),
        schedule_day=data.get('schedule_day', 0),
        schedule_cron=data.get('schedule_cron')
    )
    db_config.password = data.get('password', '')
    
    db.session.add(db_config)
    db.session.commit()
    
    if db_config.schedule_enabled:
        update_job(db_config)
    
    log(f'Created database config: {db_config.name}')
    return jsonify(db_config.to_dict()), 201

@app.route('/api/databases/<int:id>', methods=['GET'])
@api_auth_required
def api_get_database(id):
    db_config = DatabaseConfig.query.get_or_404(id)
    return jsonify(db_config.to_dict())

@app.route('/api/databases/<int:id>', methods=['PUT'])
@api_auth_required
def api_update_database(id):
    db_config = DatabaseConfig.query.get_or_404(id)
    data = request.json
    
    db_config.name = data.get('name', db_config.name)
    db_config.db_type = data.get('db_type', db_config.db_type)
    db_config.host = data.get('host', db_config.host)
    db_config.port = data.get('port', db_config.port)
    db_config.database = data.get('database', db_config.database)
    db_config.username = data.get('username', db_config.username)
    db_config.enabled = data.get('enabled', db_config.enabled)
    db_config.schedule_enabled = data.get('schedule_enabled', db_config.schedule_enabled)
    db_config.schedule_type = data.get('schedule_type', db_config.schedule_type)
    db_config.schedule_time = data.get('schedule_time', db_config.schedule_time)
    db_config.schedule_day = data.get('schedule_day', db_config.schedule_day)
    db_config.schedule_cron = data.get('schedule_cron', db_config.schedule_cron)
    
    if 'password' in data:
        db_config.password = data['password']
    
    db.session.commit()
    update_job(db_config)
    
    log(f'Updated database config: {db_config.name}')
    return jsonify(db_config.to_dict())

@app.route('/api/databases/<int:id>', methods=['DELETE'])
@api_auth_required
def api_delete_database(id):
    db_config = DatabaseConfig.query.get_or_404(id)
    name = db_config.name
    
    remove_job(id)
    db.session.delete(db_config)
    db.session.commit()
    
    log(f'Deleted database config: {name}')
    return jsonify({'success': True})

# ==================== Backup Operations ====================

@app.route('/backups')
@login_required
def backups():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    backups = BackupHistory.query.order_by(BackupHistory.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('backups.html', backups=backups)

@app.route('/api/backup/<int:db_id>', methods=['POST'])
@api_auth_required
def api_trigger_backup(db_id):
    db_config = DatabaseConfig.query.get_or_404(db_id)
    
    backup = run_backup(db_config)
    
    if backup.status == 'success':
        # Upload to Telegram
        sync_upload_backup(backup)
        sync_send_notification(
            f"✅ <b>Manual Backup Successful</b>\n"
            f"📊 Database: {db_config.name}\n"
            f"📁 File: {backup.filename}\n"
            f"📏 Size: {backup.file_size_str}"
        )
    else:
        sync_send_notification(
            f"❌ <b>Manual Backup Failed</b>\n"
            f"📊 Database: {db_config.name}\n"
            f"⚠️ Error: {backup.error_message}"
        )
    
    return jsonify(backup.to_dict())

@app.route('/api/backup/<int:backup_id>/download')
@api_auth_required
def api_download_backup(backup_id):
    backup = BackupHistory.query.get_or_404(backup_id)
    filepath = BACKUP_DIR / backup.filename
    
    if not filepath.exists():
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(filepath, as_attachment=True, download_name=backup.filename)

@app.route('/api/backup/<int:backup_id>/upload-tg', methods=['POST'])
@api_auth_required
def api_upload_to_tg(backup_id):
    backup = BackupHistory.query.get_or_404(backup_id)
    success = sync_upload_backup(backup)
    
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Upload failed'}), 500

@app.route('/api/backup/<int:backup_id>/restore', methods=['POST'])
@api_auth_required
def api_restore_backup(backup_id):
    backup = BackupHistory.query.get_or_404(backup_id)
    success = restore_backup(backup)
    
    if success:
        log(f'Restored backup: {backup.filename}')
        return jsonify({'success': True})
    return jsonify({'error': 'Restore failed'}), 500

@app.route('/api/backup/<int:backup_id>', methods=['DELETE'])
@api_auth_required
def api_delete_backup(backup_id):
    backup = BackupHistory.query.get_or_404(backup_id)
    
    filepath = BACKUP_DIR / backup.filename
    if filepath.exists():
        filepath.unlink()
    
    db.session.delete(backup)
    db.session.commit()
    
    log(f'Deleted backup: {backup.filename}')
    return jsonify({'success': True})

# ==================== Settings ====================

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html',
                         tg_token=Settings.get('tg_bot_token', Config.TG_BOT_TOKEN),
                         tg_chat_ids=Settings.get('tg_chat_ids', ','.join(Config.TG_CHAT_IDS)),
                         max_backups=Settings.get('max_local_backups', Config.MAX_LOCAL_BACKUPS),
                         api_token=API_TOKEN)

@app.route('/api/settings', methods=['POST'])
@api_auth_required
def api_update_settings():
    data = request.json
    
    if 'tg_bot_token' in data:
        Settings.set('tg_bot_token', data['tg_bot_token'])
    if 'tg_chat_ids' in data:
        Settings.set('tg_chat_ids', data['tg_chat_ids'])
    if 'max_local_backups' in data:
        Settings.set('max_local_backups', data['max_local_backups'])
    
    log('Settings updated')
    return jsonify({'success': True})

@app.route('/api/settings/test-telegram', methods=['POST'])
@api_auth_required
def api_test_telegram():
    success = sync_send_notification('🧪 Test notification from DB Backup Bot')
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to send test notification'}), 500

@app.route('/api/settings/regenerate-token', methods=['POST'])
@api_auth_required
def api_regenerate_token():
    global API_TOKEN
    API_TOKEN = secrets.token_urlsafe(32)
    Settings.set('api_token', API_TOKEN)
    log('API token regenerated')
    return jsonify({'token': API_TOKEN})

# ==================== Logs ====================

@app.route('/logs')
@login_required
def logs():
    page = request.args.get('page', 1, type=int)
    level = request.args.get('level', '')
    per_page = 50
    
    query = SystemLog.query
    if level:
        query = query.filter_by(level=level)
    
    logs = query.order_by(SystemLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('logs.html', logs=logs, current_level=level)

@app.route('/api/logs')
@api_auth_required
def api_get_logs():
    limit = request.args.get('limit', 100, type=int)
    level = request.args.get('level', '')
    
    query = SystemLog.query
    if level:
        query = query.filter_by(level=level)
    
    logs = query.order_by(SystemLog.created_at.desc()).limit(limit).all()
    return jsonify([l.to_dict() for l in logs])

# ==================== Change Password ====================

@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    data = request.json
    
    if not check_password_hash(current_user.password_hash, data.get('current_password', '')):
        return jsonify({'error': 'Current password is incorrect'}), 400
    
    if len(data.get('new_password', '')) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    
    current_user.password_hash = generate_password_hash(data['new_password'])
    db.session.commit()
    
    log(f'Password changed for user: {current_user.username}')
    return jsonify({'success': True})

# ==================== 宝塔面板管理 ====================

@app.route('/bt-panels')
@login_required
def bt_panels():
    panels = BtPanelConfig.query.all()
    return render_template('bt_panels.html', panels=panels)

@app.route('/api/bt-panels', methods=['GET'])
@api_auth_required
def api_get_bt_panels():
    panels = BtPanelConfig.query.all()
    return jsonify([p.to_dict() for p in panels])

@app.route('/api/bt-panels', methods=['POST'])
@api_auth_required
def api_create_bt_panel():
    data = request.json
    
    panel = BtPanelConfig(
        name=data['name'],
        url=data['url'],
        enabled=data.get('enabled', True)
    )
    panel.api_key = data['api_key']
    
    db.session.add(panel)
    db.session.commit()
    
    log(f'Created BT panel config: {panel.name}')
    return jsonify(panel.to_dict()), 201

@app.route('/api/bt-panels/<int:id>', methods=['PUT'])
@api_auth_required
def api_update_bt_panel(id):
    panel = BtPanelConfig.query.get_or_404(id)
    data = request.json
    
    panel.name = data.get('name', panel.name)
    panel.url = data.get('url', panel.url)
    panel.enabled = data.get('enabled', panel.enabled)
    
    if 'api_key' in data and data['api_key']:
        panel.api_key = data['api_key']
    
    db.session.commit()
    log(f'Updated BT panel config: {panel.name}')
    return jsonify(panel.to_dict())

@app.route('/api/bt-panels/<int:id>', methods=['DELETE'])
@api_auth_required
def api_delete_bt_panel(id):
    panel = BtPanelConfig.query.get_or_404(id)
    name = panel.name
    
    db.session.delete(panel)
    db.session.commit()
    
    log(f'Deleted BT panel config: {name}')
    return jsonify({'success': True})

@app.route('/api/bt-panels/<int:id>/test', methods=['POST'])
@api_auth_required
def api_test_bt_panel(id):
    panel = BtPanelConfig.query.get_or_404(id)
    bt = BtPanel(panel.url, panel.api_key)
    result = bt.test_connection()
    
    if result.get('status') is not False:
        return jsonify({'success': True, 'data': result})
    return jsonify({'success': False, 'error': result.get('msg', 'Connection failed')}), 400

@app.route('/api/bt-panels/<int:id>/databases', methods=['GET'])
@api_auth_required
def api_get_panel_databases(id):
    panel = BtPanelConfig.query.get_or_404(id)
    bt = BtPanel(panel.url, panel.api_key)
    result = bt.get_databases()
    return jsonify(result)

@app.route('/api/bt-panels/<int:id>/backup', methods=['POST'])
@api_auth_required
def api_bt_backup(id):
    """通过宝塔API执行备份"""
    panel = BtPanelConfig.query.get_or_404(id)
    data = request.json
    db_id = data.get('db_id')
    db_name = data.get('db_name', 'unknown')
    push_to_tg = data.get('push_to_tg', True)
    
    if not db_id:
        return jsonify({'error': 'db_id is required'}), 400
    
    bt = BtPanel(panel.url, panel.api_key)
    
    # 执行备份
    log(f'Starting BT backup for {db_name} (id={db_id}) on {panel.name}')
    result = bt.backup_database(db_id)
    
    log(f'Backup result: {result}')
    
    if result.get('status'):
        log(f'BT backup completed for {db_name}')
        
        backup_file = None
        
        # 如果需要推送到TG，下载备份文件
        if push_to_tg:
            import time
            
            # 等待备份压缩完成（大文件需要更长时间）
            # 先等待5秒，然后循环检查文件是否存在
            time.sleep(5)
            
            # 从备份结果中获取文件名，或者查询备份列表
            # 宝塔备份API返回的msg中可能包含文件路径
            backup_path = None
            
            # 尝试从返回结果获取文件路径
            msg = result.get('msg', '')
            if '/www/backup' in str(msg):
                backup_path = msg
            
            # 如果没有直接返回路径，查询数据库备份列表获取最新备份
            if not backup_path:
                list_result = bt._request('/database?action=GetBackupList', {
                    'p': 1,
                    'limit': 5,
                    'type': 0,
                    'tojs': '',
                    'table': 'backup',
                    'search': db_name
                })
                log(f'Backup list result: {list_result}')
                
                # 尝试不同格式
                backups = list_result.get('data') or list_result.get('page') or []
                if backups and len(backups) > 0:
                    latest = backups[0]
                    backup_path = latest.get('filename') or latest.get('name') or latest.get('path')
            
            # 如果还是没有，用标准路径格式猜测
            if not backup_path:
                # 获取目录下最新文件
                backup_dir = f'/www/backup/database/mysql/{db_name}'
                
                # 等待文件生成，最多等待10分钟（大文件压缩需要时间）
                max_wait = 600  # 10分钟
                wait_interval = 10  # 每10秒检查一次
                waited = 0
                
                while waited < max_wait:
                    dir_result = bt._request('/files?action=GetDir', {
                        'path': backup_dir,
                        'showRow': 10,
                        'p': 1,
                        'sort': 'mtime',
                        'reverse': 'true'
                    })
                    
                    files_raw = dir_result.get('FILES') or []
                    for f in files_raw:
                        if isinstance(f, str):
                            parts = f.split(';')
                            fname = parts[0]
                            if fname.endswith('.sql.zip') or fname.endswith('.sql.gz'):
                                # 检查文件大小是否还在变化（压缩中）
                                file_size = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                                if file_size > 1000:  # 至少1KB
                                    backup_path = f'{backup_dir}/{fname}'
                                    log(f'Found backup file: {fname} ({file_size} bytes)')
                                    break
                    
                    if backup_path:
                        # 再等待几秒确保文件写入完成
                        time.sleep(3)
                        break
                    
                    log(f'Waiting for backup file... ({waited}s)')
                    time.sleep(wait_interval)
                    waited += wait_interval
            if backup_path:
                log(f'Found backup: {backup_path}')
                
                local_filename = Path(backup_path).name
                save_path = BACKUP_DIR / local_filename
                
                # 尝试下载（宝塔API可能不支持）
                downloaded = bt.download_backup(backup_path, str(save_path))
                
                if downloaded and save_path.exists() and save_path.stat().st_size > 100:
                    from backup import calculate_hash
                    
                    backup_record = BackupHistory(
                        database_id=None,
                        filename=local_filename,
                        file_size=save_path.stat().st_size,
                        file_hash=calculate_hash(save_path),
                        status='success',
                        duration=0
                    )
                    db.session.add(backup_record)
                    db.session.commit()
                    
                    # 上传到Telegram
                    log(f'Uploading to Telegram: {local_filename} ({save_path.stat().st_size} bytes)')
                    sync_upload_backup(backup_record)
                    backup_file = backup_record.to_dict()
                    
                    log(f'Backup uploaded to TG: {local_filename}')
                    
                    # 删除本地备份文件
                    try:
                        save_path.unlink()
                        log(f'Deleted local backup: {local_filename}')
                    except Exception as e:
                        log(f'Failed to delete local backup: {e}', 'warning')
                else:
                    # 下载失败，尝试在服务器上直接执行curl推送到Telegram
                    log(f'Download failed, trying server-side push...')
                    
                    bot_token = Settings.get('tg_bot_token', '')
                    chat_ids = Settings.get('tg_chat_ids', '')
                    
                    if bot_token and chat_ids:
                        chat_id = chat_ids.split(',')[0].strip()
                        
                        # URL编码的caption
                        import urllib.parse
                        caption = f"🗄️ Database Backup\n📊 DB: {db_name}\n📁 File: {local_filename}\n🖥️ Panel: {panel.name}"
                        
                        # curl命令，加超时设置（2小时，支持大文件上传）
                        curl_cmd = f'curl -s --max-time 7200 -X POST "https://api.telegram.org/bot{bot_token}/sendDocument" -F chat_id="{chat_id}" -F document=@"{backup_path}" -F caption="{caption}"'
                        
                        # 尝试通过计划任务执行（这是最可靠的方式）
                        import time as t
                        task_name = f'tg_push_{int(t.time())}'
                        
                        # 创建一次性计划任务
                        create_result = bt._request('/crontab?action=AddCrontab', {
                            'name': task_name,
                            'type': 'minute-n',
                            'where1': '1',
                            'hour': '',
                            'minute': '',
                            'week': '',
                            'sType': 'toShell',
                            'sBody': curl_cmd,
                            'sName': '',
                            'backupTo': '',
                            'save': '',
                            'urladdress': ''
                        })
                        log(f'Create crontab result: {create_result}')
                        
                        if create_result.get('status'):
                            # 获取任务ID并立即执行
                            cron_id = create_result.get('id')
                            if cron_id:
                                exec_result = bt._request('/crontab?action=StartTask', {
                                    'id': cron_id
                                })
                                log(f'Execute crontab result: {exec_result}')
                                
                                # 等待执行完成
                                t.sleep(3)
                                
                                # 删除计划任务
                                del_result = bt._request('/crontab?action=DelCrontab', {
                                    'id': cron_id
                                })
                                log(f'Delete crontab result: {del_result}')
                    else:
                        log(f'Telegram not configured', 'warning')
                
                # 删除宝塔服务器上的备份文件
                delete_result = bt._request('/files?action=DeleteFile', {
                    'path': backup_path
                })
                log(f'Delete remote result: {delete_result}')
                
                # 清空回收站
                recycle_result = bt._request('/files?action=Close_Recycle_bin', {
                    'status': 1
                })
                if not recycle_result.get('status'):
                    # 尝试另一种方式清空回收站
                    recycle_result = bt._request('/files?action=Re_Recycle_bin', {
                        'path': 'all'
                    })
                log(f'Clear recycle bin result: {recycle_result}')
            else:
                log(f'Could not find backup file path', 'warning')
        
        # 发送通知
        sync_send_notification(
            f"✅ <b>宝塔备份成功</b>\n"
            f"📊 数据库: {db_name}\n"
            f"🖥️ 面板: {panel.name}"
        )
        
        return jsonify({
            'success': True, 
            'message': result.get('msg', 'Backup completed'),
            'backup_file': backup_file
        })
    else:
        error_msg = result.get('msg', 'Backup failed')
        log(f'BT backup failed for {db_name}: {error_msg}', 'error')
        
        sync_send_notification(
            f"❌ <b>宝塔备份失败</b>\n"
            f"📊 数据库: {db_name}\n"
            f"⚠️ 错误: {error_msg}"
        )
        
        return jsonify({'success': False, 'error': error_msg}), 500


# ==================== 宝塔数据库定时备份 ====================

@app.route('/api/bt-databases', methods=['GET'])
@api_auth_required
def api_get_bt_databases():
    """获取所有宝塔数据库定时备份配置"""
    configs = BtDatabaseConfig.query.all()
    return jsonify([c.to_dict() for c in configs])

@app.route('/api/bt-databases', methods=['POST'])
@api_auth_required
def api_create_bt_database():
    """创建宝塔数据库定时备份配置"""
    data = request.json
    
    config = BtDatabaseConfig(
        panel_id=data['panel_id'],
        bt_db_id=data['bt_db_id'],
        db_name=data['db_name'],
        enabled=data.get('enabled', True),
        schedule_enabled=data.get('schedule_enabled', False),
        schedule_type=data.get('schedule_type', 'daily'),
        schedule_time=data.get('schedule_time', '03:00'),
        schedule_day=data.get('schedule_day', 0),
        push_to_tg=data.get('push_to_tg', True)
    )
    
    db.session.add(config)
    db.session.commit()
    
    # 更新定时任务
    if config.schedule_enabled:
        update_bt_job(config)
    
    log(f'Created BT database config: {config.db_name}')
    return jsonify(config.to_dict()), 201

@app.route('/api/bt-databases/<int:id>', methods=['PUT'])
@api_auth_required
def api_update_bt_database(id):
    """更新宝塔数据库定时备份配置"""
    config = BtDatabaseConfig.query.get_or_404(id)
    data = request.json
    
    config.enabled = data.get('enabled', config.enabled)
    config.schedule_enabled = data.get('schedule_enabled', config.schedule_enabled)
    config.schedule_type = data.get('schedule_type', config.schedule_type)
    config.schedule_time = data.get('schedule_time', config.schedule_time)
    config.schedule_day = data.get('schedule_day', config.schedule_day)
    config.push_to_tg = data.get('push_to_tg', config.push_to_tg)
    
    db.session.commit()
    
    # 更新定时任务
    update_bt_job(config)
    
    log(f'Updated BT database config: {config.db_name}')
    return jsonify(config.to_dict())

@app.route('/api/bt-databases/<int:id>', methods=['DELETE'])
@api_auth_required
def api_delete_bt_database(id):
    """删除宝塔数据库定时备份配置"""
    config = BtDatabaseConfig.query.get_or_404(id)
    name = config.db_name
    
    # 移除定时任务
    remove_bt_job(id)
    
    db.session.delete(config)
    db.session.commit()
    
    log(f'Deleted BT database config: {name}')
    return jsonify({'success': True})


def bt_backup_job(config_id: int):
    """宝塔定时备份任务"""
    with app.app_context():
        config = BtDatabaseConfig.query.get(config_id)
        if not config or not config.enabled:
            return
        
        panel = config.panel
        if not panel or not panel.enabled:
            return
        
        bt = BtPanel(panel.url, panel.api_key)
        db_name = config.db_name
        
        log(f'[Scheduled] Starting BT backup for {db_name}')
        result = bt.backup_database(config.bt_db_id)
        
        if result.get('status'):
            log(f'[Scheduled] BT backup completed for {db_name}')
            
            # 如果需要推送到TG
            if config.push_to_tg:
                import time as t
                t.sleep(1)
                
                backup_path = None
                
                # 从返回结果获取
                msg = result.get('msg', '')
                if '/www/backup' in str(msg):
                    backup_path = msg
                
                # 查询备份列表
                if not backup_path:
                    backup_dir = f'/www/backup/database/mysql/{db_name}'
                    dir_result = bt._request('/files?action=GetDir', {
                        'path': backup_dir,
                        'showRow': 10,
                        'p': 1
                    })
                    
                    files_raw = dir_result.get('FILES') or []
                    for f in files_raw:
                        if isinstance(f, str):
                            parts = f.split(';')
                            fname = parts[0]
                            if fname.endswith('.sql.zip') or fname.endswith('.sql.gz'):
                                backup_path = f'{backup_dir}/{fname}'
                                break
                
                if backup_path:
                    local_filename = Path(backup_path).name
                    log(f'[Scheduled] Found backup: {backup_path}')
                    
                    # 获取TG配置
                    bot_token = Settings.get('tg_bot_token', '')
                    chat_ids = Settings.get('tg_chat_ids', '')
                    
                    if bot_token and chat_ids:
                        chat_id = chat_ids.split(',')[0].strip()
                        
                        caption = f"🗄️ Database Backup (Scheduled)\n📊 DB: {db_name}\n📁 File: {local_filename}\n🖥️ Panel: {panel.name}"
                        
                        # curl命令，加超时设置（2小时，支持大文件）
                        curl_cmd = f'curl -s --max-time 7200 -X POST "https://api.telegram.org/bot{bot_token}/sendDocument" -F chat_id="{chat_id}" -F document=@"{backup_path}" -F caption="{caption}"'
                        
                        task_name = f'tg_scheduled_{int(t.time())}'
                        
                        # 创建一次性计划任务
                        create_result = bt._request('/crontab?action=AddCrontab', {
                            'name': task_name,
                            'type': 'minute-n',
                            'where1': '1',
                            'hour': '',
                            'minute': '',
                            'week': '',
                            'sType': 'toShell',
                            'sBody': curl_cmd,
                            'sName': '',
                            'backupTo': '',
                            'save': '',
                            'urladdress': ''
                        })
                        log(f'[Scheduled] Create crontab result: {create_result}')
                        
                        if create_result.get('status'):
                            cron_id = create_result.get('id')
                            if cron_id:
                                # 执行计划任务
                                exec_result = bt._request('/crontab?action=StartTask', {
                                    'id': cron_id
                                })
                                log(f'[Scheduled] Execute crontab result: {exec_result}')
                                
                                # 等待执行完成
                                t.sleep(5)
                                
                                # 删除计划任务
                                del_result = bt._request('/crontab?action=DelCrontab', {
                                    'id': cron_id
                                })
                                log(f'[Scheduled] Delete crontab result: {del_result}')
                    
                    # 删除备份文件
                    delete_result = bt._request('/files?action=DeleteFile', {
                        'path': backup_path
                    })
                    log(f'[Scheduled] Delete file result: {delete_result}')
                    
                    # 清空回收站
                    recycle_result = bt._request('/files?action=Close_Recycle_bin', {
                        'status': 1
                    })
                    if not recycle_result.get('status'):
                        recycle_result = bt._request('/files?action=Re_Recycle_bin', {
                            'path': 'all'
                        })
                    log(f'[Scheduled] Clear recycle bin result: {recycle_result}')
            
            sync_send_notification(
                f"✅ <b>定时备份成功</b>\n"
                f"📊 数据库: {db_name}\n"
                f"🖥️ 面板: {panel.name}"
            )
        else:
            error_msg = result.get('msg', 'Backup failed')
            log(f'[Scheduled] BT backup failed for {db_name}: {error_msg}', 'error')
            sync_send_notification(
                f"❌ <b>定时备份失败</b>\n"
                f"📊 数据库: {db_name}\n"
                f"⚠️ 错误: {error_msg}"
            )


def update_bt_job(config: BtDatabaseConfig):
    """更新宝塔备份定时任务"""
    from apscheduler.triggers.cron import CronTrigger
    
    job_id = f'bt_backup_{config.id}'
    
    # 移除已有任务
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # 添加新任务
    if config.enabled and config.schedule_enabled:
        hour, minute = (config.schedule_time or '03:00').split(':')
        
        if config.schedule_type == 'hourly':
            trigger = CronTrigger(minute=minute)
        elif config.schedule_type == 'daily':
            trigger = CronTrigger(hour=hour, minute=minute)
        elif config.schedule_type == 'weekly':
            trigger = CronTrigger(day_of_week=config.schedule_day, hour=hour, minute=minute)
        else:
            trigger = CronTrigger(hour=hour, minute=minute)
        
        scheduler.add_job(
            bt_backup_job,
            trigger=trigger,
            args=[config.id],
            id=job_id,
            name=f'BT Backup: {config.db_name}',
            replace_existing=True
        )
        log(f'Scheduled BT backup for {config.db_name}: {config.schedule_type} @ {config.schedule_time}')


def remove_bt_job(config_id: int):
    """移除宝塔备份定时任务"""
    job_id = f'bt_backup_{config_id}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

@app.route('/api/bt-panels/<int:id>/download', methods=['POST'])
@api_auth_required  
def api_bt_download_backup(id):
    """从宝塔下载备份文件到本地"""
    panel = BtPanelConfig.query.get_or_404(id)
    data = request.json
    filename = data.get('filename')  # 服务器上的文件路径
    
    if not filename:
        return jsonify({'error': 'filename is required'}), 400
    
    bt = BtPanel(panel.url, panel.api_key)
    
    # 本地保存路径
    local_filename = Path(filename).name
    save_path = BACKUP_DIR / local_filename
    
    log(f'Downloading backup from BT: {filename}')
    success = bt.download_backup(filename, str(save_path))
    
    if success and save_path.exists():
        # 创建备份记录
        from backup import calculate_hash
        
        backup = BackupHistory(
            database_id=None,  # 宝塔备份不关联本地数据库配置
            filename=local_filename,
            file_size=save_path.stat().st_size,
            file_hash=calculate_hash(save_path),
            status='success',
            duration=0
        )
        db.session.add(backup)
        db.session.commit()
        
        # 上传到Telegram
        sync_upload_backup(backup)
        
        log(f'Downloaded and uploaded backup: {local_filename}')
        return jsonify({'success': True, 'backup': backup.to_dict()})
    
    return jsonify({'error': 'Download failed'}), 500


def init_bt_schedules():
    """加载宝塔定时备份任务"""
    with app.app_context():
        bt_configs = BtDatabaseConfig.query.filter_by(enabled=True, schedule_enabled=True).all()
        for config in bt_configs:
            update_bt_job(config)
        if bt_configs:
            print(f'[INFO] Loaded {len(bt_configs)} BT backup schedules')


if __name__ == '__main__':
    init_bt_schedules()
    app.run(host='0.0.0.0', port=5000, debug=True)

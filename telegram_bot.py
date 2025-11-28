import asyncio
import math
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError
from config import Config, BACKUP_DIR
from models import db, BackupHistory, Settings
from backup import log

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit

def get_bot():
    token = Settings.get('tg_bot_token', Config.TG_BOT_TOKEN)
    if not token:
        return None
    return Bot(token=token)

def get_chat_ids():
    ids = Settings.get('tg_chat_ids', '')
    if ids:
        return [x.strip() for x in ids.split(',') if x.strip()]
    return Config.TG_CHAT_IDS

async def send_notification(message: str, parse_mode: str = 'HTML'):
    """Send text notification to all configured chats"""
    bot = get_bot()
    if not bot:
        log('Telegram bot not configured', 'warning')
        return False
    
    chat_ids = get_chat_ids()
    if not chat_ids:
        log('No Telegram chat IDs configured', 'warning')
        return False
    
    success = True
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode=parse_mode)
        except TelegramError as e:
            log(f'Failed to send notification to {chat_id}: {e}', 'error')
            success = False
    
    return success

async def upload_backup(backup: BackupHistory) -> bool:
    """Upload backup file to Telegram"""
    bot = get_bot()
    if not bot:
        log('Telegram bot not configured', 'warning')
        return False
    
    chat_ids = get_chat_ids()
    if not chat_ids:
        log('No Telegram chat IDs configured', 'warning')
        return False
    
    filepath = BACKUP_DIR / backup.filename
    if not filepath.exists():
        log(f'Backup file not found: {backup.filename}', 'error')
        return False
    
    file_size = filepath.stat().st_size
    
    try:
        # Check if file needs splitting
        if file_size > MAX_FILE_SIZE:
            return await upload_split_file(bot, chat_ids, backup, filepath)
        
        # 获取数据库名称（兼容宝塔备份没有关联数据库的情况）
        db_name = backup.database.name if backup.database else backup.filename.split('_')[0]
        duration = backup.duration if backup.duration else 0
        
        caption = (
            f"🗄️ <b>Database Backup</b>\n"
            f"📊 DB: {db_name}\n"
            f"📁 File: {backup.filename}\n"
            f"📏 Size: {backup.file_size_str}\n"
            f"🔐 SHA256: <code>{backup.file_hash[:16]}...</code>"
        )
        
        with open(filepath, 'rb') as f:
            msg = await bot.send_document(
                chat_id=chat_ids[0],
                document=f,
                filename=backup.filename,
                caption=caption,
                parse_mode='HTML'
            )
        
        backup.tg_uploaded = True
        backup.tg_file_id = msg.document.file_id
        db.session.commit()
        
        # Forward to other chats using file_id
        for chat_id in chat_ids[1:]:
            try:
                await bot.send_document(
                    chat_id=chat_id,
                    document=backup.tg_file_id,
                    caption=caption,
                    parse_mode='HTML'
                )
            except TelegramError as e:
                log(f'Failed to forward to {chat_id}: {e}', 'warning')
        
        log(f'Uploaded backup to Telegram: {backup.filename}')
        return True
        
    except TelegramError as e:
        log(f'Failed to upload backup: {e}', 'error')
        return False

async def upload_split_file(bot: Bot, chat_ids: list, backup: BackupHistory, filepath: Path) -> bool:
    """Split and upload large files"""
    file_size = filepath.stat().st_size
    num_parts = math.ceil(file_size / MAX_FILE_SIZE)
    
    db_name = backup.database.name if backup.database else backup.filename.split('_')[0]
    
    log(f'Splitting {backup.filename} into {num_parts} parts')
    
    # Notify about split upload
    await bot.send_message(
        chat_id=chat_ids[0],
        text=f"🗄️ <b>Large Backup Upload</b>\n"
             f"📊 DB: {db_name}\n"
             f"📁 File: {backup.filename}\n"
             f"📏 Total Size: {backup.file_size_str}\n"
             f"📦 Parts: {num_parts}",
        parse_mode='HTML'
    )
    
    with open(filepath, 'rb') as f:
        for part_num in range(num_parts):
            chunk = f.read(MAX_FILE_SIZE)
            part_filename = f'{backup.filename}.part{part_num + 1:03d}'
            
            for chat_id in chat_ids:
                try:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=chunk,
                        filename=part_filename,
                        caption=f"Part {part_num + 1}/{num_parts}"
                    )
                except TelegramError as e:
                    log(f'Failed to upload part {part_num + 1} to {chat_id}: {e}', 'error')
                    return False
    
    backup.tg_uploaded = True
    db.session.commit()
    
    log(f'Uploaded split backup ({num_parts} parts): {backup.filename}')
    return True

def sync_send_notification(message: str):
    """Synchronous wrapper for send_notification"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(send_notification(message))

def sync_upload_backup(backup: BackupHistory):
    """Synchronous wrapper for upload_backup"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(upload_backup(backup))

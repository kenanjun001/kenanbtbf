from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from models import db, DatabaseConfig
from backup import run_backup, log
from telegram_bot import sync_upload_backup, sync_send_notification

scheduler = BackgroundScheduler()

def backup_job(db_id: int):
    """Execute backup job for a database"""
    from app import app
    
    with app.app_context():
        db_config = DatabaseConfig.query.get(db_id)
        if not db_config or not db_config.enabled:
            return
        
        backup = run_backup(db_config)
        
        if backup.status == 'success':
            sync_upload_backup(backup)
            sync_send_notification(
                f"✅ <b>Backup Successful</b>\n"
                f"📊 Database: {db_config.name}\n"
                f"📁 File: {backup.filename}\n"
                f"📏 Size: {backup.file_size_str}\n"
                f"⏱️ Duration: {backup.duration:.1f}s"
            )
        else:
            sync_send_notification(
                f"❌ <b>Backup Failed</b>\n"
                f"📊 Database: {db_config.name}\n"
                f"⚠️ Error: {backup.error_message}"
            )

def get_cron_trigger(db_config: DatabaseConfig) -> CronTrigger:
    """Convert schedule settings to APScheduler CronTrigger"""
    if db_config.schedule_type == 'custom' and db_config.schedule_cron:
        parts = db_config.schedule_cron.split()
        if len(parts) == 5:
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4]
            )
    
    hour, minute = (db_config.schedule_time or '03:00').split(':')
    
    if db_config.schedule_type == 'hourly':
        return CronTrigger(minute=minute)
    elif db_config.schedule_type == 'daily':
        return CronTrigger(hour=hour, minute=minute)
    elif db_config.schedule_type == 'weekly':
        return CronTrigger(
            day_of_week=db_config.schedule_day,
            hour=hour,
            minute=minute
        )
    else:
        return CronTrigger(hour=hour, minute=minute)

def update_job(db_config: DatabaseConfig):
    """Update or add a backup job for a database"""
    job_id = f'backup_{db_config.id}'
    
    # Remove existing job
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # Add new job if enabled
    if db_config.enabled and db_config.schedule_enabled:
        trigger = get_cron_trigger(db_config)
        scheduler.add_job(
            backup_job,
            trigger=trigger,
            args=[db_config.id],
            id=job_id,
            name=f'Backup: {db_config.name}',
            replace_existing=True
        )
        log(f'Scheduled backup for {db_config.name}: {db_config.schedule_type}')

def remove_job(db_id: int):
    """Remove a backup job"""
    job_id = f'backup_{db_id}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

def init_scheduler(app):
    """Initialize scheduler with existing database configs"""
    with app.app_context():
        configs = DatabaseConfig.query.filter_by(enabled=True, schedule_enabled=True).all()
        for config in configs:
            update_job(config)
    
    if not scheduler.running:
        scheduler.start()
        print('[INFO] Scheduler started')

def get_scheduled_jobs():
    """Get list of scheduled jobs"""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None
        })
    return jobs

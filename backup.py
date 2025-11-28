import os
import gzip
import hashlib
import time
from datetime import datetime
from pathlib import Path
from config import BACKUP_DIR, Config
from models import db, DatabaseConfig, BackupHistory, SystemLog

def log(message: str, level: str = 'info', details: str = None):
    entry = SystemLog(level=level, message=message, details=details)
    db.session.add(entry)
    db.session.commit()
    print(f'[{level.upper()}] {message}')

def calculate_hash(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

def cleanup_old_backups(db_config: DatabaseConfig):
    """Remove old backups keeping only MAX_LOCAL_BACKUPS"""
    backups = BackupHistory.query.filter_by(
        database_id=db_config.id, status='success'
    ).order_by(BackupHistory.created_at.desc()).all()
    
    if len(backups) > Config.MAX_LOCAL_BACKUPS:
        for old_backup in backups[Config.MAX_LOCAL_BACKUPS:]:
            filepath = BACKUP_DIR / old_backup.filename
            if filepath.exists():
                filepath.unlink()
                log(f'Deleted old backup: {old_backup.filename}')
            db.session.delete(old_backup)
        db.session.commit()


def dump_mysql(db_config: DatabaseConfig, output_path: Path):
    """使用 pymysql 导出 MySQL 数据库"""
    import pymysql
    
    conn = pymysql.connect(
        host=db_config.host,
        port=db_config.port or 3306,
        user=db_config.username,
        password=db_config.password,
        database=db_config.database,
        charset='utf8mb4'
    )
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"-- MySQL Dump\n")
        f.write(f"-- Database: {db_config.database}\n")
        f.write(f"-- Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("SET NAMES utf8mb4;\n")
        f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")
        
        cursor = conn.cursor()
        
        # 获取所有表
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            f.write(f"-- ----------------------------\n")
            f.write(f"-- Table structure for {table}\n")
            f.write(f"-- ----------------------------\n")
            f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
            
            # 获取建表语句
            cursor.execute(f"SHOW CREATE TABLE `{table}`")
            create_sql = cursor.fetchone()[1]
            f.write(f"{create_sql};\n\n")
            
            # 获取数据
            cursor.execute(f"SELECT * FROM `{table}`")
            rows = cursor.fetchall()
            
            if rows:
                f.write(f"-- ----------------------------\n")
                f.write(f"-- Records of {table}\n")
                f.write(f"-- ----------------------------\n")
                
                # 获取列名
                cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                columns = [row[0] for row in cursor.fetchall()]
                columns_str = ', '.join([f'`{c}`' for c in columns])
                
                for row in rows:
                    values = []
                    for val in row:
                        if val is None:
                            values.append('NULL')
                        elif isinstance(val, (int, float)):
                            values.append(str(val))
                        elif isinstance(val, bytes):
                            values.append(f"X'{val.hex()}'")
                        elif isinstance(val, datetime):
                            values.append(f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'")
                        else:
                            escaped = str(val).replace("\\", "\\\\").replace("'", "\\'")
                            values.append(f"'{escaped}'")
                    
                    values_str = ', '.join(values)
                    f.write(f"INSERT INTO `{table}` ({columns_str}) VALUES ({values_str});\n")
                
                f.write("\n")
        
        f.write("SET FOREIGN_KEY_CHECKS = 1;\n")
        
        cursor.close()
        conn.close()


def dump_postgresql(db_config: DatabaseConfig, output_path: Path):
    """使用 psycopg2 导出 PostgreSQL 数据库"""
    import psycopg2
    
    conn = psycopg2.connect(
        host=db_config.host,
        port=db_config.port or 5432,
        user=db_config.username,
        password=db_config.password,
        database=db_config.database
    )
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"-- PostgreSQL Dump\n")
        f.write(f"-- Database: {db_config.database}\n")
        f.write(f"-- Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        cursor = conn.cursor()
        
        # 获取所有表
        cursor.execute("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            f.write(f"-- Table: {table}\n")
            f.write(f"DROP TABLE IF EXISTS \"{table}\" CASCADE;\n")
            
            # 获取列信息
            cursor.execute(f"""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = %s AND table_schema = 'public'
                ORDER BY ordinal_position
            """, (table,))
            columns_info = cursor.fetchall()
            
            # 构建建表语句
            col_defs = []
            for col in columns_info:
                col_def = f'"{col[0]}" {col[1]}'
                if col[2] == 'NO':
                    col_def += ' NOT NULL'
                if col[3]:
                    col_def += f' DEFAULT {col[3]}'
                col_defs.append(col_def)
            
            f.write(f"CREATE TABLE \"{table}\" (\n  ")
            f.write(',\n  '.join(col_defs))
            f.write("\n);\n\n")
            
            # 导出数据
            cursor.execute(f'SELECT * FROM "{table}"')
            rows = cursor.fetchall()
            
            if rows:
                columns = [desc[0] for desc in cursor.description]
                columns_str = ', '.join([f'"{c}"' for c in columns])
                
                for row in rows:
                    values = []
                    for val in row:
                        if val is None:
                            values.append('NULL')
                        elif isinstance(val, (int, float)):
                            values.append(str(val))
                        elif isinstance(val, bytes):
                            values.append(f"E'\\\\x{val.hex()}'")
                        else:
                            escaped = str(val).replace("'", "''")
                            values.append(f"'{escaped}'")
                    
                    values_str = ', '.join(values)
                    f.write(f"INSERT INTO \"{table}\" ({columns_str}) VALUES ({values_str});\n")
                
                f.write("\n")
        
        cursor.close()
        conn.close()


def dump_sqlite(db_config: DatabaseConfig, output_path: Path):
    """导出 SQLite 数据库"""
    import sqlite3
    
    conn = sqlite3.connect(db_config.database)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for line in conn.iterdump():
            f.write(f'{line}\n')
    
    conn.close()


def run_backup(db_config: DatabaseConfig, retry_count: int = 3) -> BackupHistory:
    """Execute backup for a database configuration"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_filename = f'{db_config.name}_{timestamp}.sql'
    gz_filename = f'{base_filename}.gz'
    
    backup = BackupHistory(
        database_id=db_config.id,
        filename=gz_filename,
        status='pending'
    )
    db.session.add(backup)
    db.session.commit()
    
    start_time = time.time()
    sql_path = BACKUP_DIR / base_filename
    gz_path = BACKUP_DIR / gz_filename
    
    for attempt in range(retry_count):
        try:
            log(f'Starting backup for {db_config.name} (attempt {attempt + 1})')
            
            # 根据数据库类型选择导出方法
            if db_config.db_type == 'mysql':
                dump_mysql(db_config, sql_path)
            elif db_config.db_type == 'postgresql':
                dump_postgresql(db_config, sql_path)
            elif db_config.db_type == 'sqlite':
                dump_sqlite(db_config, sql_path)
            else:
                raise ValueError(f'Unsupported database type: {db_config.db_type}')
            
            # Compress
            with open(sql_path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    f_out.writelines(f_in)
            
            # Remove uncompressed file
            sql_path.unlink()
            
            # Update backup record
            backup.file_size = gz_path.stat().st_size
            backup.file_hash = calculate_hash(gz_path)
            backup.duration = time.time() - start_time
            backup.status = 'success'
            db.session.commit()
            
            log(f'Backup completed: {gz_filename} ({backup.file_size} bytes)')
            cleanup_old_backups(db_config)
            
            return backup
            
        except Exception as e:
            error_msg = str(e)
            log(f'Backup failed for {db_config.name}: {error_msg}', 'error')
            
            if attempt == retry_count - 1:
                backup.status = 'failed'
                backup.error_message = error_msg
                backup.duration = time.time() - start_time
                db.session.commit()
                
                # Cleanup partial files
                for p in [sql_path, gz_path]:
                    if p.exists():
                        p.unlink()
            else:
                time.sleep(5)  # Wait before retry
    
    return backup


def restore_backup(backup: BackupHistory) -> bool:
    """Restore a database from backup"""
    db_config = backup.database
    gz_path = BACKUP_DIR / backup.filename
    
    if not gz_path.exists():
        log(f'Backup file not found: {backup.filename}', 'error')
        return False
    
    try:
        # Decompress
        sql_path = gz_path.with_suffix('')
        with gzip.open(gz_path, 'rb') as f_in:
            with open(sql_path, 'wb') as f_out:
                f_out.writelines(f_in)
        
        # Read SQL content
        with open(sql_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Execute restore based on database type
        if db_config.db_type == 'mysql':
            import pymysql
            conn = pymysql.connect(
                host=db_config.host,
                port=db_config.port or 3306,
                user=db_config.username,
                password=db_config.password,
                database=db_config.database,
                charset='utf8mb4'
            )
            cursor = conn.cursor()
            for statement in sql_content.split(';\n'):
                statement = statement.strip()
                if statement and not statement.startswith('--'):
                    try:
                        cursor.execute(statement)
                    except:
                        pass
            conn.commit()
            cursor.close()
            conn.close()
            
        elif db_config.db_type == 'postgresql':
            import psycopg2
            conn = psycopg2.connect(
                host=db_config.host,
                port=db_config.port or 5432,
                user=db_config.username,
                password=db_config.password,
                database=db_config.database
            )
            cursor = conn.cursor()
            cursor.execute(sql_content)
            conn.commit()
            cursor.close()
            conn.close()
            
        elif db_config.db_type == 'sqlite':
            import sqlite3
            conn = sqlite3.connect(db_config.database)
            conn.executescript(sql_content)
            conn.close()
        
        sql_path.unlink()
        log(f'Restore completed: {backup.filename}')
        return True
        
    except Exception as e:
        log(f'Restore failed: {str(e)}', 'error')
        return False

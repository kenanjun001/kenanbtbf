"""
宝塔面板 API 集成
支持：获取数据库列表、执行备份、下载备份文件
"""

import hashlib
import time
import requests
from typing import Optional

class BtPanel:
    def __init__(self, url: str, api_key: str):
        """
        初始化宝塔面板 API
        :param url: 面板地址，如 http://104.250.137.18:8888
        :param api_key: API 密钥（在面板设置 -> API接口 中获取）
        """
        self.url = url.rstrip('/')
        self.api_key = api_key
    
    def _sign(self) -> dict:
        """生成签名"""
        now_time = int(time.time())
        token = hashlib.md5(f"{now_time}{hashlib.md5(self.api_key.encode()).hexdigest()}".encode()).hexdigest()
        return {
            'request_token': token,
            'request_time': now_time
        }
    
    def _request(self, endpoint: str, data: dict = None) -> dict:
        """发送 API 请求"""
        url = f"{self.url}{endpoint}"
        post_data = self._sign()
        if data:
            post_data.update(data)
        
        try:
            response = requests.post(url, data=post_data, timeout=300, verify=False)
            return response.json()
        except Exception as e:
            return {'status': False, 'msg': str(e)}
    
    def get_databases(self, db_type: str = 'mysql') -> dict:
        """
        获取数据库列表
        :param db_type: 数据库类型 mysql/mongodb
        """
        if db_type == 'mysql':
            return self._request('/data?action=getData', {
                'table': 'databases',
                'limit': 100,
                'tojs': 'database.get_list'
            })
        return {'status': False, 'msg': 'Unsupported database type'}
    
    def backup_database(self, db_id: int) -> dict:
        """
        执行数据库备份
        :param db_id: 数据库ID（不是名称）
        """
        return self._request('/database?action=ToBackup', {
            'id': db_id
        })
    
    def get_backup_list(self, db_id: int = 0, search: str = '') -> dict:
        """
        获取数据库备份列表
        :param db_id: 数据库ID
        :param search: 搜索关键字
        """
        return self._request('/data?action=getData', {
            'table': 'backup',
            'limit': 100,
            'type': 1,  # 1=数据库备份
            'tojs': 'database.get_backup_list',
            'search': search,
            'pid': db_id
        })
    
    def get_database_backup_list(self, db_id: int) -> dict:
        """
        获取指定数据库的备份列表
        :param db_id: 数据库ID
        """
        # 先尝试新版API
        result = self._request('/database?action=QueryBackups', {
            'id': db_id,
            'p': 1,
            'limit': 10,
            'type': 0
        })
        
        if result.get('status') is False:
            # 尝试旧版API
            result = self._request('/data?action=getData', {
                'table': 'backup',
                'search': '',
                'limit': 20,
                'type': 1,
                'pid': db_id
            })
        
        return result
    
    def get_backup_path(self) -> str:
        """获取备份目录路径"""
        result = self._request('/config?action=get_config')
        if result.get('backup_path'):
            return result['backup_path']
        return '/www/backup/database'
    
    def delete_backup(self, backup_id: int) -> dict:
        """
        删除备份文件
        :param backup_id: 备份ID
        """
        return self._request('/database?action=DelBackup', {
            'id': backup_id
        })
    
    def download_backup(self, filename: str, save_path: str) -> bool:
        """
        下载备份文件 - 宝塔API不支持远程下载文件
        返回False表示需要使用其他方式（SSH或服务器本地脚本）
        """
        print(f"宝塔API不支持远程下载文件: {filename}")
        print("建议：在宝塔服务器上部署脚本直接推送到Telegram")
        return False
    
    def exec_shell(self, command: str) -> dict:
        """
        在宝塔服务器上执行Shell命令
        :param command: 要执行的命令
        """
        return self._request('/system?action=ServiceAdmin', {
            'name': command,
            'type': 'status'
        })
    
    def upload_to_telegram(self, filepath: str, bot_token: str, chat_id: str, db_name: str) -> dict:
        """
        通过宝塔API在服务器上执行curl命令，将备份文件直接推送到Telegram
        :param filepath: 服务器上的备份文件路径
        :param bot_token: Telegram Bot Token
        :param chat_id: Telegram Chat ID
        :param db_name: 数据库名称（用于消息）
        """
        import time
        from pathlib import Path
        
        filename = Path(filepath).name
        caption = f"🗄️ Database Backup\\n📊 DB: {db_name}\\n📁 File: {filename}\\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        # 构造curl命令
        curl_cmd = f'''curl -s -X POST "https://api.telegram.org/bot{bot_token}/sendDocument" -F chat_id="{chat_id}" -F document=@"{filepath}" -F caption="{caption}" -F parse_mode="HTML"'''
        
        # 使用宝塔的终端执行命令
        result = self._request('/files?action=ExecShell', {
            'command': curl_cmd
        })
        
        return result
    
    def get_file_body(self, filename: str) -> dict:
        """
        读取文件内容
        :param filename: 文件路径
        """
        return self._request('/files?action=GetFileBody', {
            'path': filename
        })
    
    def test_connection(self) -> dict:
        """测试 API 连接"""
        return self._request('/system?action=GetSystemTotal')


def test_bt_api():
    """测试宝塔 API"""
    # 替换为你的面板地址和 API 密钥
    bt = BtPanel('http://104.250.137.18:8888', 'your_api_key')
    
    # 测试连接
    result = bt.test_connection()
    print("Connection test:", result)
    
    # 获取数据库列表
    result = bt.get_databases()
    print("Databases:", result)


if __name__ == '__main__':
    test_bt_api()

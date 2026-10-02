"""
Pytest配置文件
"""
import os
import tempfile
import django
from django.conf import settings

# 设置Django配置
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse_system.settings')


def pytest_configure():
    """Pytest配置"""
    settings.DEBUG = False
    django.setup()

    # 并发测试需要真实多连接串行等待（见 test_freeze_concurrency.py）：
    # SQLite 测试库默认是 :memory:，每个连接是独立实例，无法跨线程验证
    # 写锁协议。显式指定文件型测试库，配合应用 ready() 中的 WAL/
    # busy_timeout。DB 在 session 级夹具阶段才创建，此刻改写生效。
    test_db_dir = tempfile.mkdtemp(prefix='custody-test-db-')
    test_db_path = os.path.join(test_db_dir, 'test_db.sqlite3')
    settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = test_db_path

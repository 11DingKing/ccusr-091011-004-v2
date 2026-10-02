from django.apps import AppConfig


class WarehouseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.warehouse'
    verbose_name = '库房管理'

    def ready(self):
        # SQLite 写连接在默认回滚日志模式下会因并发写直接死锁；
        # 切到 WAL 后写-写仍严格串行（冻结并发协议依赖此点），
        # 但后到者会按 busy_timeout 等待而非立即报错，读-写也不再互斥。
        from django.db.backends.signals import connection_created

        def _tune_sqlite(sender, connection, **kwargs):
            if connection.vendor != 'sqlite':
                return
            cursor = connection.cursor()
            db_name = connection.settings_dict.get('NAME', ':memory:')
            cursor.execute('PRAGMA busy_timeout=20000')
            if db_name and db_name != ':memory:':
                cursor.execute('PRAGMA journal_mode=WAL')
                cursor.execute('PRAGMA synchronous=NORMAL')

        connection_created.connect(_tune_sqlite)

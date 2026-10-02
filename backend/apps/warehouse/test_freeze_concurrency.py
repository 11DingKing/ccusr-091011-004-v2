"""
法律冻结与业务放行并发测试。

用真实双线程在文件型 SQLite 测试库上验证：同一物资上的"建立冻结"与
"放行操作"经物资行写锁全序串行，不会出现"读到无冻结 → 冻结提交 →
放行提交"的空档，也不会放行在冻结提交之后才落库。
"""
import threading
import time
from datetime import timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from apps.authentication.models import User
from apps.warehouse.models import (
    Category, FreezeItem, Goods, LegalFreeze, StockOut, Unit, Variety,
    get_blocking_items,
)
from apps.warehouse import services


class FreezeConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user("conc-user", "testpass123", role="admin")
        unit = Unit.objects.create(name="件", created_by=self.user)
        category = Category.objects.create(name="受控器材", unit=unit, created_by=self.user)
        variety = Variety.objects.create(name="终端", category=category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=variety, name="并发验证终端", code="CONC-001",
            quantity=Decimal("10"),
        )
        # 一份已进入领用审批流程的申请（冻结下达前已 pending）
        self.stock_out = StockOut.objects.create(
            goods=self.goods, operator=self.user,
            receiver="领用员", quantity=Decimal("1"), status="pending",
        )

    def _freeze_kwargs(self, no):
        return dict(
            user=self.user, freeze_no=no, case_info=f"并发案-{no}",
            authority="某区检察院", legal_doc="", action_type="freeze",
            effective_from=timezone.now() - timedelta(minutes=1),
            effective_to=None,
            items=[{'goods_id': self.goods.pk}],
        )

    def test_freeze_waits_behind_held_goods_lock(self):
        """放行事务持锁期间，建立冻结必须等待，不能抢先/并发提交。"""
        locked = threading.Event()
        release = threading.Event()
        freeze_done = threading.Event()
        freeze_error = []

        def approval_tx():
            try:
                with transaction.atomic():
                    services.lock_goods([self.goods.pk])
                    locked.set()
                    release.wait(10)
                    # 持锁期间的复查：冻结尚未提交，查不到阻断依据
                    self.assertEqual(
                        get_blocking_items([self.goods.pk], 'stock_out'), {}
                    )
            finally:
                connection.close()

        def freeze_tx():
            try:
                services.create_freeze(**self._freeze_kwargs("FZ-C1"))
                freeze_done.set()
            except Exception as exc:  # 记录但不让线程静默吞掉
                freeze_error.append(exc)
            finally:
                connection.close()

        t_approval = threading.Thread(target=approval_tx)
        t_approval.start()
        self.assertTrue(locked.wait(5), "放行事务未能在预期时间内取得物资锁")

        t_freeze = threading.Thread(target=freeze_tx)
        t_freeze.start()
        # 放行事务持锁 0.6 秒：冻结事务必须阻塞等待，不得完成提交
        time.sleep(0.6)
        self.assertFalse(
            freeze_done.is_set(),
            "建立冻结抢在持锁的放行事务之前/同时提交，存在并发空档"
        )
        self.assertEqual(freeze_error, [])

        release.set()
        t_approval.join(5)
        self.assertTrue(freeze_done.wait(10), "放行事务释放锁后冻结仍未完成")
        t_freeze.join(5)
        self.assertEqual(freeze_error, [])

        # 冻结既已提交，此后任何新的放行判定都必须读到冻结并被阻断
        with self.assertRaises(services.FreezeBlockedError):
            services.review_stock_out(
                self.stock_out.pk, approver=self.user, approved=True
            )
        self.stock_out.refresh_from_db()
        self.assertEqual(self.stock_out.status, "pending")

    def test_approval_loses_race_when_freeze_commits_first(self):
        """冻结先持锁提交：等待中的审批在获锁后复查，必须被阻断。"""
        locked = threading.Event()
        release = threading.Event()
        result = {}
        done = threading.Event()

        def freeze_tx():
            try:
                with transaction.atomic():
                    services.lock_goods([self.goods.pk])
                    locked.set()
                    release.wait(10)
                    freeze = LegalFreeze.objects.create(
                        freeze_no="FZ-C2", case_info="并发案-2",
                        authority="某区检察院", action_type="freeze",
                        effective_from=timezone.now() - timedelta(minutes=1),
                        status=LegalFreeze.STATUS_ACTIVE,
                        created_by=self.user,
                    )
                    FreezeItem.objects.create(freeze=freeze, goods=self.goods)
            finally:
                connection.close()

        def approval_tx():
            try:
                services.review_stock_out(
                    self.stock_out.pk, approver=self.user, approved=True
                )
                result['outcome'] = 'approved'
            except services.FreezeBlockedError:
                result['outcome'] = 'blocked'
            except Exception as exc:
                result['outcome'] = f'error: {exc!r}'
            finally:
                done.set()
                connection.close()

        t_freeze = threading.Thread(target=freeze_tx)
        t_freeze.start()
        self.assertTrue(locked.wait(5))

        t_approval = threading.Thread(target=approval_tx)
        t_approval.start()
        # 冻结持锁期间审批无法完成（先获锁复查这一步被挡住）
        time.sleep(0.6)
        self.assertFalse(done.is_set(), "审批在冻结持锁期间完成，锁协议失效")

        release.set()
        t_freeze.join(5)
        self.assertTrue(done.wait(10))
        t_approval.join(5)

        self.assertEqual(result['outcome'], 'blocked')
        self.stock_out.refresh_from_db()
        self.assertEqual(self.stock_out.status, "pending")
        self.assertTrue(LegalFreeze.objects.filter(freeze_no="FZ-C2").exists())

"""
法律冻结功能测试：范围快照、三类业务阻断、重叠解除、历史保留、并发竞态。
"""
import threading
import time
from datetime import timedelta
from decimal import Decimal

from django.db import connection, OperationalError
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User

from .models import (
    Approval, Category, DestructionPlan, FreezeBlockLog, Goods,
    LegalFreeze, LegalFreezeItem, StockOut, StockTransfer, Unit, Variety,
    FreezeViolation,
)
from . import freeze as freeze_service


def with_lock_retry(fn, *, attempts=50):
    """SQLite 写锁升级冲突会立即返回 SQLITE_BUSY（不像服务器数据库由
    SELECT ... FOR UPDATE 排队），客户端正确行为是整体重试整个事务；
    重试时必然观察到对方已提交的状态，业务结果不受影响。"""
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except OperationalError as exc:
            if 'locked' not in str(exc):
                raise
            last = exc
            time.sleep(0.02)
    raise last


class FreezeFixture(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user("freeze-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(
            name="受控器材", unit=self.unit, created_by=self.user)
        self.category2 = Category.objects.create(
            name="文书载体", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(
            name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety, name="执法记录终端", code="DEV-001",
            quantity=Decimal("12"), warning_threshold=Decimal("5"))
        self.goods2 = Goods.objects.create(
            variety=self.variety, name="备用终端", code="DEV-002",
            quantity=Decimal("3"), warning_threshold=Decimal("1"))

    def register_freeze(self, **overrides):
        params = dict(
            case_no="A2026-01", document_no="冻字001号", authority="监察委调查部门",
            scope_type=LegalFreeze.SCOPE_GOODS, scope_targets=[self.goods.id],
            created_by=self.user,
        )
        params.update(overrides)
        return freeze_service.register_freeze(**params)


class FreezeRegisterTest(FreezeFixture):
    def test_register_snapshots_goods_scope(self):
        freeze = self.register_freeze()
        self.assertEqual(freeze.items.count(), 1)
        item = freeze.items.get()
        self.assertEqual(item.goods_id, self.goods.id)
        self.assertEqual(item.goods_code_snapshot, "DEV-001")
        self.assertTrue(freeze.is_active)

    def test_register_variety_scope_expands_all_goods(self):
        freeze = self.register_freeze(
            scope_type=LegalFreeze.SCOPE_VARIETY, scope_targets=[self.variety.id])
        self.assertEqual(set(freeze.items.values_list("goods_id", flat=True)),
                         {self.goods.id, self.goods2.id})

    def test_register_category_scope_expands(self):
        other_variety = Variety.objects.create(
            name="存储介质", category=self.category2, created_by=self.user)
        other_goods = Goods.objects.create(
            variety=other_variety, name="封存硬盘", code="DISK-001", quantity=Decimal("5"))
        freeze = self.register_freeze(
            scope_type=LegalFreeze.SCOPE_CATEGORY, scope_targets=[self.category2.id])
        self.assertEqual(list(freeze.items.values_list("goods_id", flat=True)),
                         [other_goods.id])

    def test_snapshot_survives_later_category_change(self):
        freeze = self.register_freeze(
            scope_type=LegalFreeze.SCOPE_VARIETY, scope_targets=[self.variety.id])
        # 冻结后货物被调整到其他品类：快照范围不变
        self.goods2.variety = Variety.objects.create(
            name="划转品种", category=self.category2, created_by=self.user)
        self.goods2.save()
        self.assertEqual(set(freeze.items.values_list("goods_id", flat=True)),
                         {self.goods.id, self.goods2.id})

    def test_empty_scope_rejected_and_rolled_back(self):
        with self.assertRaises(ValueError):
            self.register_freeze(
                scope_type=LegalFreeze.SCOPE_VARIETY,
                scope_targets=[Variety.objects.create(
                    name="空品种", category=self.category2, created_by=self.user).id])
        self.assertEqual(LegalFreeze.objects.count(), 0)

    def test_expire_window(self):
        # 未生效
        future = self.register_freeze(effective_at=timezone.now() + timedelta(days=1))
        self.assertFalse(future.is_active)
        self.assertEqual(freeze_service.current_blocks(self.goods.id), [])
        # 已过期
        self.register_freeze(
            document_no="冻字002号", case_no="A2026-02",
            effective_at=timezone.now() - timedelta(days=2),
            expire_at=timezone.now() - timedelta(days=1))
        self.assertEqual(freeze_service.current_blocks(self.goods.id), [])


class FreezeBlockBusinessTest(FreezeFixture):
    def test_approve_and_complete_stock_out_blocked(self):
        # 冻结前已提交、已审批的出库申请
        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="李四",
            quantity=Decimal("2"))
        out.status = "approved"
        out.save()
        self.register_freeze()

        with self.assertRaises(FreezeViolation):
            freeze_service.complete_stock_out(out, operator=self.user)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))  # 库存未动
        # 阻断有留痕
        log = FreezeBlockLog.objects.get(action="stock_out")
        self.assertEqual(log.freeze.document_no, "冻字001号")
        self.assertIn("冻字001号", log.message)

    def test_approve_pending_stock_out_blocked(self):
        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="李四",
            quantity=Decimal("2"))
        self.register_freeze()
        with self.assertRaises(FreezeViolation):
            freeze_service.approve_stock_out(out, approver=self.user)
        out.refresh_from_db()
        self.assertEqual(out.status, "pending")

    def test_transfer_blocked_at_approve_and_complete(self):
        transfer = StockTransfer.objects.create(
            goods=self.goods, operator=self.user, quantity=Decimal("1"),
            to_location="二号库")
        self.register_freeze()
        with self.assertRaises(FreezeViolation):
            freeze_service.approve_transfer(transfer, approver=self.user)

        transfer.status = "approved"
        transfer.save()
        with self.assertRaises(FreezeViolation):
            freeze_service.complete_transfer(transfer, operator=self.user)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.location, "")

    def test_destruction_blocked(self):
        plan = DestructionPlan.objects.create(
            goods=self.goods, operator=self.user, quantity=Decimal("1"))
        self.register_freeze()
        with self.assertRaises(FreezeViolation):
            freeze_service.approve_destruction(plan, approver=self.user)

        plan.status = "approved"
        plan.save()
        with self.assertRaises(FreezeViolation):
            freeze_service.complete_destruction(plan, operator=self.user)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))

    def test_unfrozen_goods_unaffected(self):
        self.register_freeze()  # 只冻结 goods
        out = StockOut.objects.create(
            goods=self.goods2, operator=self.user, receiver="王五",
            quantity=Decimal("1"))
        freeze_service.approve_stock_out(out, approver=self.user)
        freeze_service.complete_stock_out(out, operator=self.user)
        self.goods2.refresh_from_db()
        self.assertEqual(self.goods2.quantity, Decimal("2"))

    def test_lift_restores_business(self):
        freeze = self.register_freeze()
        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="李四",
            quantity=Decimal("2"))
        with self.assertRaises(FreezeViolation):
            freeze_service.approve_stock_out(out, approver=self.user)
        freeze_service.lift_freeze(freeze, lifted_by=self.user, remark="案件撤销")
        freeze_service.approve_stock_out(out, approver=self.user)
        freeze_service.complete_stock_out(out, operator=self.user)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("10"))

    def test_overlapping_freezes_lift_one_keeps_other(self):
        f1 = self.register_freeze(document_no="冻字001号", case_no="A-1")
        f2 = self.register_freeze(document_no="冻字002号", case_no="A-2")
        self.assertEqual(len(freeze_service.current_blocks(self.goods.id)), 2)

        freeze_service.lift_freeze(f1, lifted_by=self.user)
        blocks = freeze_service.current_blocks(self.goods.id)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].freeze_id, f2.id)

        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="李四",
            quantity=Decimal("1"))
        with self.assertRaises(FreezeViolation) as ctx:
            freeze_service.approve_stock_out(out, approver=self.user)
        # 阻断依据指向仍有效的第二份冻结
        self.assertIn("冻字002号", str(ctx.exception))

        freeze_service.lift_freeze(f2, lifted_by=self.user)
        freeze_service.approve_stock_out(out, approver=self.user)

    def test_cannot_lift_twice(self):
        freeze = self.register_freeze()
        freeze_service.lift_freeze(freeze, lifted_by=self.user)
        with self.assertRaises(ValueError):
            freeze_service.lift_freeze(freeze, lifted_by=self.user)

    def test_history_preserved_after_freeze(self):
        # 冻结前的入库、出库历史
        from .models import StockIn
        StockIn.objects.create(goods=self.goods, operator=self.user,
                               quantity=Decimal("4"))
        old_out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="历史领用",
            quantity=Decimal("1"), status="completed",
            stock_out_time=timezone.now() - timedelta(days=2))
        Approval.objects.create(stock_out=old_out, approver=self.user,
                                status="approved")
        self.register_freeze()

        timeline = freeze_service.goods_timeline(self.goods.id)
        titles = [e["title"] for e in timeline]
        self.assertTrue(any("入库" in t for t in titles))
        self.assertTrue(any("历史领用" in t or "出库" in t for t in titles))
        self.assertTrue(any("冻结登记" in t for t in titles))
        self.assertTrue(any("冻结生效" in t for t in titles))
        # 历史记录未被修改
        self.assertEqual(old_out.status, "completed")


class FreezeAPITest(FreezeFixture):
    def test_api_register_and_query_status(self):
        resp = self.client.post("/api/freezes/", {
            "case_no": "A2026-09", "document_no": "冻字009号",
            "authority": "调查部门", "scope_type": "goods",
            "scope_targets": [self.goods.id],
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        freeze_id = resp.json()["data"]["id"]

        status_resp = self.client.get(f"/api/goods/{self.goods.id}/freeze-status/")
        self.assertEqual(status_resp.status_code, 200)
        body = status_resp.json()["data"]
        self.assertTrue(body["is_frozen"])
        self.assertEqual(body["current_blocks"][0]["document_no"], "冻字009号")
        self.assertTrue(any(e["freeze_id"] == freeze_id for e in body["timeline"]))

    def test_api_apply_stock_out_rejected_while_frozen(self):
        self.register_freeze()
        resp = self.client.post("/api/stock-out/", {
            "goods": self.goods.id, "receiver": "李四", "quantity": "2",
        }, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("冻结", resp.json()["message"])
        self.assertEqual(StockOut.objects.count(), 0)

    def test_api_complete_stock_out_conflict(self):
        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="李四",
            quantity=Decimal("2"), status="approved")
        self.register_freeze()
        resp = self.client.post(f"/api/stock-out/{out.id}/complete/", {}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_api_lift_does_not_touch_other_freeze(self):
        f1 = self.register_freeze(document_no="冻字001号", case_no="A-1")
        self.register_freeze(document_no="冻字002号", case_no="A-2")
        resp = self.client.post(f"/api/freezes/{f1.id}/lift/",
                                {"remark": "部分解除"}, format="json")
        self.assertEqual(resp.status_code, 200)
        status = self.client.get(
            f"/api/goods/{self.goods.id}/freeze-status/").json()["data"]
        self.assertTrue(status["is_frozen"])
        self.assertEqual(len(status["current_blocks"]), 1)

    def test_api_register_validates_scope(self):
        resp = self.client.post("/api/freezes/", {
            "case_no": "A2026-10", "document_no": "冻字010号",
            "authority": "调查部门", "scope_type": "goods",
            "scope_targets": [99999],
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_api_freeze_detail_timeline_and_blocks(self):
        freeze = self.register_freeze()
        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="李四",
            quantity=Decimal("1"))
        with self.assertRaises(FreezeViolation):
            freeze_service.approve_stock_out(out, approver=self.user)
        resp = self.client.get(f"/api/freezes/{freeze.id}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(any(e["category"] == "block" for e in data["timeline"]))
        self.assertEqual(data["items"][0]["current_blocks"][0]["document_no"],
                         "冻字001号")


class FreezeConcurrencyTest(FreezeFixture):
    """冻结登记与出库放行并发时，不得出现先放行后补冻结。"""

    def test_freeze_wins_against_approve_race(self):
        outcomes = []

        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="竞态",
            quantity=Decimal("1"))

        barrier = threading.Barrier(2)
        errors = []

        def thread_approve():
            barrier.wait()
            try:
                def work():
                    pending = StockOut.objects.get(pk=out.pk)
                    freeze_service.approve_stock_out(pending, approver=self.user)
                    outcomes.append("approved")
                with_lock_retry(work)
            except FreezeViolation:
                outcomes.append("blocked")
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                connection.close()

        def thread_freeze():
            barrier.wait()
            try:
                with_lock_retry(self.register_freeze)
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_approve)
        t2 = threading.Thread(target=thread_freeze)
        t1.start(); t2.start()
        t1.join(timeout=30); t2.join(timeout=30)

        self.assertFalse(t1.is_alive() or t2.is_alive(), "并发线程死锁")
        self.assertEqual(errors, [])
        out.refresh_from_db()

        # 不变量：冻结生效后货物绝不能实际出库。
        # 顺序 A：冻结先提交，审批必须被阻断，申请保持待审批。
        # 顺序 B：审批先提交，申请变为已通过，但执行出库仍须被冻结拦下。
        if out.status == "pending":
            self.assertEqual(outcomes, ["blocked"])
        else:
            self.assertEqual(out.status, "approved")
            self.assertEqual(outcomes, ["approved"])
            with self.assertRaises(FreezeViolation):
                freeze_service.complete_stock_out(out, operator=self.user)
            out.refresh_from_db()
            self.assertEqual(out.status, "approved")
            self.goods.refresh_from_db()
            self.assertEqual(self.goods.quantity, Decimal("12"))

    def test_freeze_against_complete_race_serialized(self):
        # 已审批通过、尚未出库
        out = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="竞态",
            quantity=Decimal("1"), status="approved")

        barrier = threading.Barrier(2)
        results = {"complete": None, "freeze_error": None}

        def thread_complete():
            barrier.wait()
            try:
                def work():
                    freeze_service.complete_stock_out(out, operator=self.user)
                    results["complete"] = "done"
                with_lock_retry(work)
            except FreezeViolation:
                results["complete"] = "blocked"
            except Exception as exc:
                results["complete"] = repr(exc)
            finally:
                connection.close()

        def thread_freeze():
            barrier.wait()
            try:
                with_lock_retry(self.register_freeze)
            except Exception as exc:
                results["freeze_error"] = repr(exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_complete)
        t2 = threading.Thread(target=thread_freeze)
        t1.start(); t2.start()
        t1.join(timeout=30); t2.join(timeout=30)
        self.assertFalse(t1.is_alive() or t2.is_alive())
        self.assertIsNone(results["freeze_error"], results)

        out.refresh_from_db()
        self.goods.refresh_from_db()
        if results["complete"] == "done":
            # 出库先提交：必须真实扣减库存
            self.assertEqual(out.status, "completed")
            self.assertEqual(self.goods.quantity, Decimal("11"))
        else:
            # 冻结先提交：出库被阻断，库存与状态都不变
            self.assertEqual(results["complete"], "blocked")
            self.assertEqual(out.status, "approved")
            self.assertEqual(self.goods.quantity, Decimal("12"))

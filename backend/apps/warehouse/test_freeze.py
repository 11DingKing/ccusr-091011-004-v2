"""
法律冻结功能测试：阻断点、重叠解除独立性、时间窗、历史保留与时间线。
"""
import time
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.core.exceptions import BusinessException
from apps.warehouse.models import (
    Approval, DisposalPlan, FreezeEvent, FreezeItem, Goods,
    LegalFreeze, StockOut, TransferOrder,
)
from apps.warehouse.services import (
    FreezeBlockedError, create_freeze, lift_freeze,
    create_stock_out, review_stock_out, complete_stock_out,
    create_transfer, review_transfer, complete_transfer,
    create_disposal, review_disposal, destroy_disposal,
    OP_STOCK_OUT, OP_TRANSFER, OP_DESTROY,
)
from apps.warehouse.tests import WarehouseFixture


def make_freeze(freeze_no, goods, user, *, operations=None,
                effective_from=None, effective_to=None, case_info=None):
    return create_freeze(
        user=user,
        freeze_no=freeze_no,
        case_info=case_info or f"案件-{freeze_no}",
        authority="某区人民检察院",
        legal_doc=f"文书-{freeze_no}",
        action_type=LegalFreeze.ACTION_FREEZE,
        effective_from=effective_from or (timezone.now() - timedelta(minutes=1)),
        effective_to=effective_to,
        items=[{
            'goods_id': goods.pk,
            'operations': operations or FreezeItem.ALL_OPERATIONS,
        }],
    )


class FreezeBlockingServiceTest(WarehouseFixture):
    """服务层：各放行点均被生效冻结阻断"""

    def test_freeze_blocks_stock_out_application(self):
        make_freeze("FZ-001", self.goods, self.user)
        with self.assertRaises(FreezeBlockedError) as ctx:
            create_stock_out(
                user=self.user, goods=self.goods, quantity=Decimal("1"),
                receiver="领用员",
            )
        self.assertEqual(ctx.exception.code, 409)
        self.assertIn("FZ-001", ctx.exception.message)
        self.assertEqual(StockOut.objects.count(), 0)
        # 拦截事件进入时间线
        self.assertTrue(FreezeEvent.objects.filter(
            freeze__freeze_no="FZ-001", type=FreezeEvent.TYPE_BLOCKED,
            operation=OP_STOCK_OUT,
        ).exists())

    def test_freeze_blocks_pending_approval(self):
        """核心场景：冻结下达时申请已在领用审批流程中，审批通过必须被挡住"""
        stock_out = create_stock_out(
            user=self.user, goods=self.goods, quantity=Decimal("2"),
            receiver="领用员",
        )
        self.assertEqual(stock_out.status, "pending")

        make_freeze("FZ-002", self.goods, self.user)

        with self.assertRaises(FreezeBlockedError):
            review_stock_out(stock_out.pk, approver=self.user, approved=True)

        stock_out.refresh_from_db()
        self.assertEqual(stock_out.status, "pending")  # 未被放行
        self.assertEqual(Approval.objects.count(), 0)  # 未产生通过记录

    def test_freeze_blocks_complete_after_approval(self):
        """已审批通过、尚未执行的出库，执行时仍需复查冻结"""
        stock_out = create_stock_out(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            receiver="领用员",
        )
        review_stock_out(stock_out.pk, approver=self.user, approved=True)
        make_freeze("FZ-003", self.goods, self.user)

        with self.assertRaises(FreezeBlockedError):
            complete_stock_out(stock_out.pk, user=self.user)
        stock_out.refresh_from_db()
        self.assertEqual(stock_out.status, "approved")
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))  # 库存未动

    def test_freeze_blocks_transfer_flow(self):
        order = create_transfer(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            target_location="二号库房",
        )
        make_freeze("FZ-004", self.goods, self.user, case_info="转移案")

        with self.assertRaises(FreezeBlockedError):
            review_transfer(order.pk, approver=self.user, approved=True)
        order.refresh_from_db()
        self.assertEqual(order.status, "pending")

        # 直接构造已通过的转移单，执行环节同样阻断
        order.status = "approved"
        order.save(update_fields=["status"])
        with self.assertRaises(FreezeBlockedError):
            complete_transfer(order.pk, user=self.user)
        order.refresh_from_db()
        self.assertEqual(order.status, "approved")

    def test_freeze_blocks_disposal_flow(self):
        plan = create_disposal(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            reason="过期销毁",
        )
        make_freeze("FZ-005", self.goods, self.user)

        with self.assertRaises(FreezeBlockedError):
            review_disposal(plan.pk, approver=self.user, approved=True)

        plan.status = "approved"
        plan.save(update_fields=["status"])
        with self.assertRaises(FreezeBlockedError):
            destroy_disposal(plan.pk, user=self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "approved")
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))

    def test_partial_operation_scope(self):
        """冻结只阻断文书列明的操作：仅冻结销毁时，出库/转移仍可办理"""
        make_freeze("FZ-006", self.goods, self.user, operations=[OP_DESTROY])

        stock_out = create_stock_out(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            receiver="领用员",
        )
        review_stock_out(stock_out.pk, approver=self.user, approved=True)
        complete_stock_out(stock_out.pk, user=self.user)
        self.assertEqual(StockOut.objects.get(pk=stock_out.pk).status, "completed")

        order = create_transfer(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            target_location="二号库房",
        )
        review_transfer(order.pk, approver=self.user, approved=True)
        complete_transfer(order.pk, user=self.user)
        self.assertEqual(TransferOrder.objects.get(pk=order.pk).status, "completed")

        with self.assertRaises(FreezeBlockedError):
            create_disposal(
                user=self.user, goods=self.goods, quantity=Decimal("1"),
                reason="过期销毁",
            )


class FreezeWindowTest(WarehouseFixture):
    """生效时间窗：未生效 / 已过期的冻结不产生阻断"""

    def test_future_freeze_does_not_block(self):
        make_freeze(
            "FZ-FUTURE", self.goods, self.user,
            effective_from=timezone.now() + timedelta(hours=2),
        )
        stock_out = create_stock_out(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            receiver="领用员",
        )
        self.assertEqual(stock_out.status, "pending")

    def test_expired_freeze_does_not_block(self):
        make_freeze(
            "FZ-PAST", self.goods, self.user,
            effective_from=timezone.now() - timedelta(days=10),
            effective_to=timezone.now() - timedelta(days=1),
        )
        stock_out = create_stock_out(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            receiver="领用员",
        )
        review_stock_out(stock_out.pk, approver=self.user, approved=True)
        self.assertEqual(StockOut.objects.get(pk=stock_out.pk).status, "approved")

    def test_invalid_time_window_rejected(self):
        with self.assertRaises(Exception):
            create_freeze(
                user=self.user, freeze_no="FZ-BAD", case_info="x",
                authority="机关", legal_doc="", action_type="freeze",
                effective_from=timezone.now(),
                effective_to=timezone.now() - timedelta(hours=1),
                items=[{'goods_id': self.goods.pk}],
            )


class OverlappingFreezeTest(WarehouseFixture):
    """多份冻结重叠：解除其中一份不得误解开其他有效限制"""

    def test_lift_one_leaves_others_in_force(self):
        freeze_a = make_freeze(
            "FZ-A", self.goods, self.user, operations=[OP_DESTROY]
        )
        freeze_b = make_freeze("FZ-B", self.goods, self.user)

        # 两份并存：出库被 B 阻断
        with self.assertRaises(FreezeBlockedError):
            create_stock_out(
                user=self.user, goods=self.goods, quantity=Decimal("1"),
                receiver="领用员",
            )

        lift_freeze(freeze_b.pk, user=self.user, lift_doc="解-B", lift_reason="案件撤销")

        # B 解除后：出库放行（B 不再有效）
        stock_out = create_stock_out(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            receiver="领用员",
        )
        review_stock_out(stock_out.pk, approver=self.user, approved=True)
        self.assertEqual(StockOut.objects.get(pk=stock_out.pk).status, "approved")

        # A 仍然有效：销毁继续被阻断
        with self.assertRaises(FreezeBlockedError):
            create_disposal(
                user=self.user, goods=self.goods, quantity=Decimal("1"),
                reason="过期销毁",
            )

        # 解除 A 后，销毁也可办理
        lift_freeze(freeze_a.pk, user=self.user, lift_doc="解-A")
        plan = create_disposal(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            reason="过期销毁",
        )
        review_disposal(plan.pk, approver=self.user, approved=True)
        destroy_disposal(plan.pk, user=self.user)
        self.assertEqual(DisposalPlan.objects.get(pk=plan.pk).status, "destroyed")

    def test_cannot_lift_twice(self):
        freeze = make_freeze("FZ-ONCE", self.goods, self.user)
        lift_freeze(freeze.pk, user=self.user)
        with self.assertRaises(BusinessException):
            lift_freeze(freeze.pk, user=self.user)

    def test_overlap_both_recorded_as_basis(self):
        make_freeze("FZ-X", self.goods, self.user)
        make_freeze("FZ-Y", self.goods, self.user)
        try:
            create_stock_out(
                user=self.user, goods=self.goods, quantity=Decimal("1"),
                receiver="领用员",
            )
            self.fail("应当被冻结阻断")
        except FreezeBlockedError as ctx:
            self.assertIn("FZ-X", ctx.exception.message)
            self.assertIn("FZ-Y", ctx.exception.message)
        # 每份冻结各留一条拦截事件
        self.assertEqual(FreezeEvent.objects.filter(
            type=FreezeEvent.TYPE_BLOCKED, operation=OP_STOCK_OUT
        ).count(), 2)


class HistoryPreservedTest(WarehouseFixture):
    """冻结不溯及既往：冻结前已完成的业务与库存状态原样保留"""

    def test_history_before_freeze_untouched(self):
        stock_out = create_stock_out(
            user=self.user, goods=self.goods, quantity=Decimal("3"),
            receiver="领用员",
        )
        review_stock_out(stock_out.pk, approver=self.user, approved=True)
        complete_stock_out(stock_out.pk, user=self.user)

        make_freeze("FZ-HIST", self.goods, self.user)

        # 历史出库仍是已完成，库存扣减保留
        self.assertEqual(StockOut.objects.get(pk=stock_out.pk).status, "completed")
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("9"))

        # 该物资冻结时间线只包含本次冻结相关事件，不含冻结前的出库
        ops = set(FreezeEvent.objects.filter(
            goods=self.goods
        ).values_list("operation", flat=True))
        self.assertEqual(ops, {""})  # 只有建立事件（无业务操作字段）

    def test_freeze_lift_then_new_operations_allowed(self):
        freeze = make_freeze("FZ-REV", self.goods, self.user)
        with self.assertRaises(FreezeBlockedError):
            create_transfer(
                user=self.user, goods=self.goods, quantity=Decimal("1"),
                target_location="二号库房",
            )
        lift_freeze(freeze.pk, user=self.user)
        order = create_transfer(
            user=self.user, goods=self.goods, quantity=Decimal("1"),
            target_location="二号库房",
        )
        self.assertEqual(order.status, "pending")


class FreezeTimelineTest(WarehouseFixture):
    """承办人可查看完整时间线：建立 → 拦截 → 解除"""

    def test_full_timeline_order(self):
        freeze = make_freeze("FZ-TL", self.goods, self.user)
        blocked_at = None
        try:
            create_stock_out(
                user=self.user, goods=self.goods, quantity=Decimal("1"),
                receiver="领用员",
            )
        except FreezeBlockedError:
            blocked_at = timezone.now()
        self.assertIsNotNone(blocked_at)

        time.sleep(0.01)
        lift_freeze(freeze.pk, user=self.user, lift_reason="核查完毕")

        events = list(FreezeEvent.objects.filter(
            freeze=freeze
        ).order_by("occurred_at", "id"))
        types = [e.type for e in events]
        self.assertEqual(types[0], FreezeEvent.TYPE_CREATED)
        self.assertIn(FreezeEvent.TYPE_BLOCKED, types)
        self.assertEqual(types[-1], FreezeEvent.TYPE_LIFTED)
        self.assertTrue(all(e.occurred_at <= timezone.now() for e in events))


class FreezeAPITest(WarehouseFixture):
    """接口层验收"""

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")

    def _create_freeze(self, freeze_no="FZ-API", operations=None, goods=None):
        payload = {
            "freeze_no": freeze_no,
            "case_info": f"案件 {freeze_no}",
            "authority": "某区公安分局",
            "legal_doc": f"法字〔2026〕{freeze_no}号",
            "action_type": "freeze",
            "effective_from": (timezone.now() - timedelta(minutes=5)).isoformat(),
            "items": [{
                "goods": (goods or self.goods).pk,
                "operations": operations or ["stock_out", "transfer", "destroy"],
            }],
        }
        return self.api.post("/api/freezes/", payload, format="json")

    def test_create_list_detail_freeze(self):
        created = self._create_freeze()
        self.assertEqual(created.status_code, 200, created.content)
        freeze_id = created.json()["data"]["id"]
        self.assertTrue(created.json()["data"]["is_effective"])

        listing = self.api.get("/api/freezes/")
        self.assertEqual(listing.json()["data"]["total"], 1)

        detail = self.api.get(f"/api/freezes/{freeze_id}/")
        self.assertEqual(detail.status_code, 200)
        data = detail.json()["data"]
        self.assertEqual(len(data["current_restrictions"]), 1)
        self.assertEqual(
            data["current_restrictions"][0]["operations_display"],
            ["出库", "转移", "销毁"],
        )
        timeline_types = [e["type"] for e in data["timeline"]]
        self.assertEqual(timeline_types, ["created"])

    def test_duplicate_freeze_no_rejected(self):
        self._create_freeze("FZ-DUP")
        dup = self._create_freeze("FZ-DUP")
        self.assertEqual(dup.status_code, 400)

    def test_create_freeze_validates_items(self):
        resp = self.api.post("/api/freezes/", {
            "freeze_no": "FZ-EMPTY",
            "case_info": "案件",
            "authority": "机关",
            "effective_from": timezone.now().isoformat(),
            "items": [],
        }, format="json")
        self.assertEqual(resp.status_code, 400)

        resp = self.api.post("/api/freezes/", {
            "freeze_no": "FZ-MISSING",
            "case_info": "案件",
            "authority": "机关",
            "effective_from": timezone.now().isoformat(),
            "items": [{"goods": 99999}],
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_stock_out_blocked_by_freeze_api(self):
        self._create_freeze("FZ-BLOCK")
        resp = self.api.post("/api/stock-out/", {
            "goods": self.goods.pk, "quantity": "1", "receiver": "领用员",
        }, format="json")
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertIn("FZ-BLOCK", body["message"])

    def test_approval_in_flight_blocked_api(self):
        application = self.api.post("/api/stock-out/", {
            "goods": self.goods.pk, "quantity": "2", "receiver": "领用员",
        }, format="json")
        stock_out_id = application.json()["data"]["id"]

        self._create_freeze("FZ-MID")
        review = self.api.post(
            f"/api/stock-out/{stock_out_id}/review/",
            {"approved": True}, format="json",
        )
        self.assertEqual(review.status_code, 409)
        self.assertEqual(StockOut.objects.get(pk=stock_out_id).status, "pending")

    def test_transfer_and_disposal_blocked_api(self):
        self._create_freeze("FZ-TD")
        transfer = self.api.post("/api/transfers/", {
            "goods": self.goods.pk, "quantity": "1", "target_location": "二号库",
        }, format="json")
        self.assertEqual(transfer.status_code, 409)

        disposal = self.api.post("/api/disposals/", {
            "goods": self.goods.pk, "quantity": "1", "reason": "过期",
        }, format="json")
        self.assertEqual(disposal.status_code, 409)

    def test_lift_freeze_api(self):
        self._create_freeze("FZ-LIFT")
        freeze_id = LegalFreeze.objects.get(freeze_no="FZ-LIFT").pk

        lifted = self.api.post(f"/api/freezes/{freeze_id}/lift/", {
            "lift_doc": "解-2026-1", "lift_reason": "案件撤销",
        }, format="json")
        self.assertEqual(lifted.status_code, 200)
        self.assertEqual(lifted.json()["data"]["status"], "lifted")

        again = self.api.post(f"/api/freezes/{freeze_id}/lift/", {}, format="json")
        self.assertEqual(again.status_code, 409)

        # 解除后可正常申请
        ok = self.api.post("/api/stock-out/", {
            "goods": self.goods.pk, "quantity": "1", "receiver": "领用员",
        }, format="json")
        self.assertEqual(ok.status_code, 200)

    def test_lift_one_overlap_keeps_other_api(self):
        self._create_freeze("FZ-OA", operations=["destroy"])
        self._create_freeze("FZ-OB")
        id_a = LegalFreeze.objects.get(freeze_no="FZ-OA").pk
        id_b = LegalFreeze.objects.get(freeze_no="FZ-OB").pk

        self.api.post(f"/api/freezes/{id_b}/lift/", {}, format="json")

        stock_out = self.api.post("/api/stock-out/", {
            "goods": self.goods.pk, "quantity": "1", "receiver": "领用员",
        }, format="json")
        self.assertEqual(stock_out.status_code, 200)

        disposal = self.api.post("/api/disposals/", {
            "goods": self.goods.pk, "quantity": "1", "reason": "过期",
        }, format="json")
        self.assertEqual(disposal.status_code, 409)
        self.assertIn("FZ-OA", disposal.json()["message"])

        self.api.post(f"/api/freezes/{id_a}/lift/", {}, format="json")

    def test_goods_freeze_status_api(self):
        self._create_freeze("FZ-STATUS")
        # 触发一次拦截，丰富时间线
        self.api.post("/api/stock-out/", {
            "goods": self.goods.pk, "quantity": "1", "receiver": "领用员",
        }, format="json")

        resp = self.api.get(f"/api/goods/{self.goods.pk}/freeze-status/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["is_frozen"])
        self.assertTrue(data["restrictions"]["stock_out"]["blocked"])
        self.assertTrue(data["restrictions"]["transfer"]["blocked"])
        self.assertTrue(data["restrictions"]["destroy"]["blocked"])
        self.assertEqual(data["restrictions"]["stock_out"]["basis"][0]["freeze_no"], "FZ-STATUS")
        self.assertEqual(len(data["freezes"]), 1)
        self.assertTrue(data["freezes"][0]["is_effective"])
        timeline_types = {e["type"] for e in data["timeline"]}
        self.assertEqual(timeline_types, {"created", "blocked"})

    def test_goods_list_has_freeze_basis(self):
        self._create_freeze("FZ-LIST")
        resp = self.api.get("/api/goods/")
        self.assertEqual(resp.status_code, 200)
        row = resp.json()["data"]["list"][0]
        self.assertTrue(row["is_frozen"])
        self.assertEqual(row["freeze_basis"][0]["freeze_no"], "FZ-LIST")

    def test_filter_freezes_by_goods_and_case(self):
        other_goods = Goods.objects.create(
            variety=self.variety, name="其他物资", code="DEV-002",
            quantity=Decimal("5"),
        )
        self._create_freeze("FZ-F1")
        self._create_freeze("FZ-F2", goods=other_goods)

        resp = self.api.get(f"/api/freezes/?goods={self.goods.pk}")
        nos = [f["freeze_no"] for f in resp.json()["data"]["list"]]
        self.assertEqual(nos, ["FZ-F1"])

        resp = self.api.get("/api/freezes/?case_info=F2")
        nos = [f["freeze_no"] for f in resp.json()["data"]["list"]]
        self.assertEqual(nos, ["FZ-F2"])

"""
法律冻结阻断与受监管业务操作的领域服务。

并发协议（为什么不会出现"先放行、后补冻结"的空档）
----------------------------------------------------
冻结的建立（写入冻结物资范围）与受冻结约束的放行操作（审批通过、执行
出库 / 转移 / 销毁）触及同一物资时，都在数据库事务内先对该物资行获取
写锁，再做判定或写入：

1. 冻结建立事务先拿到锁：范围明细先落库，后到的放行操作必须等待，
   拿到锁后复查时一定能读到该冻结，遂被阻断；
2. 放行操作先拿到锁：它在冻结范围写入之前已完成判定并提交，冻结
   建立只能发生在其后，属于对新状态的冻结，不影响已经合法完成的
   历史操作（冻结前历史状态原样保留）。

因此对同一件物资，"建立冻结"与"放行"在数据库层面全序串行，判定
依据在加锁后读取，不存在两者之间的时间差窗口。

锁的实现采用按主键升序的条件空更新（UPDATE ... SET updated_at=
自身）：在 MySQL / PostgreSQL 上等价于对命中行加行级写锁；在 SQLite
上写事务在第一条写语句时开启并取得 RESERVED 写锁，使所有写入方互斥
串行。所有路径均按相同顺序（主键升序）取锁，避免多物资场景下的交叉
死锁。

关键细节是 write-first：事务在任何业务读取之前先取物资写锁，物资 id
的解析放在事务外的 autocommit 短读中完成。否则在可重复读快照隔离下，
若事务先读取了业务单（建立旧快照）再等待物资锁，获锁后仍读不到对方
刚刚提交的冻结，会错误放行。快照必须在获锁那一刻建立，才能保证判定
依据包含所有先提交的冻结。
"""
import functools
import logging
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from apps.core.exceptions import BusinessException
from .models import (
    Approval, DisposalPlan, FreezeEvent, FreezeItem, Goods,
    LegalFreeze, StockOut, TransferOrder,
)

logger = logging.getLogger('apps')

OP_STOCK_OUT = FreezeItem.OP_STOCK_OUT
OP_TRANSFER = FreezeItem.OP_TRANSFER
OP_DESTROY = FreezeItem.OP_DESTROY
OPERATION_LABELS = {
    OP_STOCK_OUT: '出库',
    OP_TRANSFER: '转移',
    OP_DESTROY: '销毁',
}


class FreezeBlockedError(BusinessException):
    """业务操作被生效中的法律冻结阻断"""

    def __init__(self, items, operation, *, goods_id=None, user=None, context=''):
        self.items = items
        self.operation = operation
        self.goods_id = goods_id
        self.user = user
        basis = '；'.join(
            f"{item.freeze.freeze_no}（案件：{item.freeze.case_info}，"
            f"机关：{item.freeze.authority}）"
            for item in items
        )
        label = OPERATION_LABELS.get(operation, operation)
        message = f"该物资已被依法冻结，{label}已被阻断。依据：{basis}"
        if context:
            message = f"{context}{message}"
        super().__init__(message, code=409)


def freeze_aware(func):
    """装饰器：业务事务因冻结回滚后，将拦截事件独立提交到时间线。

    阻断判定发生在持锁事务内（保证并发正确），但事件落库必须独立于
    被回滚的业务事务——因此等内层事务回滚完毕后，另开事务写入，
    再把原异常抛给调用方。
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FreezeBlockedError as exc:
            if exc.items and exc.goods_id is not None:
                now = timezone.now()
                with transaction.atomic():
                    FreezeEvent.objects.bulk_create([
                        FreezeEvent(
                            freeze=item.freeze,
                            type=FreezeEvent.TYPE_BLOCKED,
                            operator=exc.user,
                            goods_id=exc.goods_id,
                            operation=exc.operation,
                            detail=exc.__dict__.get('_context', '')[:500],
                            occurred_at=now,
                        )
                        for item in exc.items
                    ])
            raise
    return wrapper


# ==================== 加锁与阻断判定 ====================

def _sorted_goods_ids(goods_ids):
    return sorted({int(gid) for gid in goods_ids})


def lock_goods(goods_ids):
    """在当前事务内锁定给定物资行，返回主键升序的 Goods 列表。

    必须在 transaction.atomic() 块内调用。
    """
    ids = _sorted_goods_ids(goods_ids)
    if not ids:
        return []
    # 条件恒真、值不变的写操作：仅用于在各数据库后端稳定获取行级/库级写锁。
    # QuerySet.update 绕过 auto_now，updated_at 取自身，数据内容不发生变化。
    Goods.objects.filter(pk__in=ids).update(updated_at=F('updated_at'))
    return list(Goods.objects.filter(pk__in=ids).order_by('pk'))


def _active_blocking_items(goods_id, operation, at=None):
    """加锁后的当前读：当前对该物资、该操作有阻断效力的全部冻结明细。

    必须在已持有物资写锁的事务内调用。在支持 SELECT ... FOR UPDATE 的
    后端（PostgreSQL/MySQL）使用当前读，确保可重复读隔离下也能看到对方
    刚刚提交的冻结；SQLite 不支持该子句，但其写锁在同一时刻只允许一个
    写事务，获锁后普通读即为最新已提交状态。
    """
    at = at or timezone.now()
    qs = FreezeItem.objects.filter(
        goods_id=goods_id
    ).select_related('freeze').filter(
        restrict_operations__contains=operation
    )
    if connection.features.supports_select_for_update:
        qs = qs.select_for_update()
    return [item for item in qs if item.freeze.is_effective_at(at)]


def assert_not_frozen(goods_id, operation, *, user=None, context=''):
    """阻断判定（必须在持锁事务内调用）：若物资被任一有效冻结限制则抛异常。

    多份冻结重叠时，异常携带每一份生效冻结，拦截事件由 freeze_aware
    在业务事务回滚后逐份写入，解除其中任何一份都不影响其余冻结继续阻断。
    """
    items = _active_blocking_items(goods_id, operation)
    if not items:
        return
    exc = FreezeBlockedError(
        items, operation, goods_id=goods_id, user=user, context=context
    )
    exc._context = context
    raise exc


# ==================== 法律冻结建立 / 解除 ====================

@transaction.atomic
def create_freeze(*, user, freeze_no, case_info, authority, legal_doc,
                  action_type, effective_from, effective_to=None, items):
    """建立一份法律冻结并写入物资范围。

    items: [{'goods_id': int,
             'operations': ['stock_out','transfer','destroy'],
             'quantity': Decimal|None}, ...]
    至少包含一项物资；与同物资上的放行操作经由同一把物资写锁互斥。
    """
    if not items:
        raise BusinessException('冻结物资范围不能为空')

    goods_ids = [int(item['goods_id']) for item in items]
    locked = {g.id: g for g in lock_goods(goods_ids)}
    missing = sorted(set(goods_ids) - set(locked.keys()))
    if missing:
        raise BusinessException(f'物资不存在：{missing[0]}')

    if LegalFreeze.objects.filter(freeze_no=freeze_no).exists():
        raise BusinessException('冻结编号已存在')

    if effective_to and effective_to <= effective_from:
        raise BusinessException('到期时间必须晚于生效时间')

    freeze = LegalFreeze.objects.create(
        freeze_no=freeze_no,
        case_info=case_info,
        authority=authority,
        legal_doc=legal_doc or '',
        action_type=action_type or LegalFreeze.ACTION_FREEZE,
        effective_from=effective_from,
        effective_to=effective_to,
        status=LegalFreeze.STATUS_ACTIVE,
        created_by=user,
    )

    freeze_items, events = [], []
    now = timezone.now()
    for raw in items:
        operations = raw.get('operations') or FreezeItem.ALL_OPERATIONS
        invalid = set(operations) - set(FreezeItem.ALL_OPERATIONS)
        if invalid:
            raise BusinessException(f"未知的限制操作：{','.join(sorted(invalid))}")
        quantity = raw.get('quantity')
        if quantity is not None and quantity < 0:
            raise BusinessException('冻结数量不能为负数')
        freeze_items.append(FreezeItem(
            freeze=freeze,
            goods_id=int(raw['goods_id']),
            restrict_operations=','.join(operations),
            quantity=quantity,
        ))
        goods = locked[int(raw['goods_id'])]
        events.append(FreezeEvent(
            freeze=freeze,
            type=FreezeEvent.TYPE_CREATED,
            operator=user,
            goods_id=int(raw['goods_id']),
            detail=f"冻结建立：{goods.name}（{goods.code}），"
                   f"限制：{','.join(OPERATION_LABELS[o] for o in operations)}",
            occurred_at=now,
        ))
    FreezeItem.objects.bulk_create(freeze_items)
    FreezeEvent.objects.bulk_create(events)

    logger.info(
        "User %s created legal freeze %s for case %s, %d goods",
        getattr(user, 'username', None), freeze_no, case_info, len(freeze_items)
    )
    return freeze


@transaction.atomic
def lift_freeze(freeze_id, *, user, lift_doc='', lift_reason=''):
    """解除一份冻结。

    只翻转本份冻结的状态，不触碰任何其他冻结记录；
    对同一物资仍有效的其他冻结继续阻断。冻结已解除则拒绝重复解除。
    """
    # 单条条件更新完成"加锁 + 状态判定 + 翻转"：谓词 status=active 由数据库
    # 在写锁下求值，即使在可重复读隔离下也是原子的，且兼容不支持
    # SELECT FOR UPDATE 的 SQLite。影响行数 0 时区分"不存在"与"已解除"。
    now = timezone.now()
    updated = LegalFreeze.objects.filter(
        pk=freeze_id, status=LegalFreeze.STATUS_ACTIVE
    ).update(
        status=LegalFreeze.STATUS_LIFTED,
        lifted_by=user,
        lift_doc=lift_doc or '',
        lift_reason=lift_reason or '',
        lifted_at=now,
    )
    if not updated:
        if LegalFreeze.objects.filter(pk=freeze_id).exists():
            raise BusinessException('该冻结已解除，请勿重复操作', code=409)
        raise BusinessException('冻结记录不存在', code=404)
    freeze = LegalFreeze.objects.filter(pk=freeze_id).first()
    events = [
        FreezeEvent(
            freeze=freeze,
            type=FreezeEvent.TYPE_LIFTED,
            operator=user,
            goods_id=item.goods_id,
            detail=f"冻结解除：{lift_reason or '依据解除文书办理'}",
            occurred_at=now,
        )
        for item in freeze.items.all()
    ]
    if not events:
        events.append(FreezeEvent(
            freeze=freeze,
            type=FreezeEvent.TYPE_LIFTED,
            operator=user,
            detail=f"冻结解除：{lift_reason or '依据解除文书办理'}",
            occurred_at=now,
        ))
    FreezeEvent.objects.bulk_create(events)

    logger.info(
        "User %s lifted freeze %s (other overlapping freezes unaffected)",
        getattr(user, 'username', None), freeze.freeze_no
    )
    return freeze



# ==================== 出库 / 转移 / 销毁 受监管业务流程 ====================
#
# 统一的 write-first 事务结构（隔离级别安全）
# ------------------------------------------------
# 公开函数在 autocommit 下仅解析出 goods_id（短读），随后进入内层事务；
# 内层事务的第一条语句必定是物资行写锁，业务单读取全部发生在获锁之后。
# 这样即使底层是可重复读（SQLite WAL / MySQL RR / PG 均同理），事务的
# 读快照也在获锁时刻建立，一定能看到对方先提交的冻结，杜绝"先放行后
# 补冻结"。

def _goods_id(goods):
    return goods.pk if hasattr(goods, 'pk') else int(goods)


def _get_for_update(model, pk):
    """持物资锁后读取业务单：支持时用 SELECT FOR UPDATE（当前读+行锁），
    不支持的 SQLite 退化为普通读（写锁已保证互斥，读到的即最新已提交值）。"""
    qs = model.objects.filter(pk=pk)
    if connection.features.supports_select_for_update:
        qs = qs.select_for_update()
    return qs.first()


def _check_positive_quantity(quantity):
    if quantity is None or quantity <= Decimal('0'):
        raise BusinessException('数量必须大于0')


def _enough_stock(goods, quantity):
    if quantity > goods.quantity:
        raise BusinessException('数量不能超过库存数量')


# ---------------- 出库（领用） ----------------

def create_stock_out(*, user, goods, quantity, receiver, receiver_dept='', remark=''):
    _check_positive_quantity(quantity)
    return _stock_out_create_tx(
        user=user, goods_id=_goods_id(goods), quantity=quantity,
        receiver=receiver, receiver_dept=receiver_dept or '', remark=remark or '',
    )


@freeze_aware
@transaction.atomic
def _stock_out_create_tx(*, user, goods_id, quantity, receiver, receiver_dept, remark):
    goods = lock_goods([goods_id])
    if not goods:
        raise BusinessException('物资不存在', code=404)
    goods = goods[0]
    _enough_stock(goods, quantity)
    assert_not_frozen(goods.pk, OP_STOCK_OUT, user=user, context='出库申请被拦截：')
    return StockOut.objects.create(
        goods=goods, operator=user, receiver=receiver,
        receiver_dept=receiver_dept, quantity=quantity,
        status='pending', remark=remark,
    )


def review_stock_out(stock_out_id, *, approver, approved, remark=''):
    goods_id = StockOut.objects.filter(pk=stock_out_id).values_list('goods_id', flat=True).first()
    if goods_id is None:
        raise BusinessException('出库记录不存在', code=404)
    return _stock_out_review_tx(
        stock_out_id=stock_out_id, goods_id=goods_id,
        approver=approver, approved=approved, remark=remark or '',
    )


@freeze_aware
@transaction.atomic
def _stock_out_review_tx(*, stock_out_id, goods_id, approver, approved, remark):
    # 第一条语句：物资写锁（审批通过的并发判定与冻结建立在此串行）
    lock_goods([goods_id])
    stock_out = _get_for_update(StockOut, stock_out_id)
    if stock_out is None:
        raise BusinessException('出库记录不存在', code=404)
    if stock_out.status != 'pending':
        raise BusinessException('该出库申请已审批，请勿重复操作', code=409)

    approval_status = 'approved' if approved else 'rejected'
    if approved:
        assert_not_frozen(
            goods_id, OP_STOCK_OUT, user=approver,
            context=f"出库审批（领用人：{stock_out.receiver}）被拦截："
        )
    stock_out.status = approval_status
    stock_out.save(update_fields=['status'])
    approval = Approval.objects.create(
        stock_out=stock_out, approver=approver,
        status=approval_status, remark=remark,
    )
    return stock_out, approval


def complete_stock_out(stock_out_id, *, user):
    goods_id = StockOut.objects.filter(pk=stock_out_id).values_list('goods_id', flat=True).first()
    if goods_id is None:
        raise BusinessException('出库记录不存在', code=404)
    return _stock_out_complete_tx(stock_out_id=stock_out_id, goods_id=goods_id, user=user)


@freeze_aware
@transaction.atomic
def _stock_out_complete_tx(*, stock_out_id, goods_id, user):
    goods = lock_goods([goods_id])[0]
    stock_out = _get_for_update(StockOut, stock_out_id)
    if stock_out is None:
        raise BusinessException('出库记录不存在', code=404)
    if stock_out.status != 'approved':
        raise BusinessException('仅审批通过的出库申请可以执行出库', code=409)
    assert_not_frozen(goods.pk, OP_STOCK_OUT, user=user, context='执行出库被拦截：')
    if stock_out.quantity > goods.quantity:
        raise BusinessException('库存不足，无法完成出库')

    goods.quantity -= stock_out.quantity
    goods.save(update_fields=['quantity', 'updated_at'])
    stock_out.status = 'completed'
    stock_out.stock_out_time = timezone.now()
    stock_out.save(update_fields=['status', 'stock_out_time'])
    return stock_out


# ---------------- 转移 ----------------

def create_transfer(*, user, goods, quantity, target_location, target_keeper='', remark=''):
    _check_positive_quantity(quantity)
    return _transfer_create_tx(
        user=user, goods_id=_goods_id(goods), quantity=quantity,
        target_location=target_location, target_keeper=target_keeper or '', remark=remark or '',
    )


@freeze_aware
@transaction.atomic
def _transfer_create_tx(*, user, goods_id, quantity, target_location, target_keeper, remark):
    goods_list = lock_goods([goods_id])
    if not goods_list:
        raise BusinessException('物资不存在', code=404)
    goods = goods_list[0]
    _enough_stock(goods, quantity)
    assert_not_frozen(goods.pk, OP_TRANSFER, user=user, context='转移申请被拦截：')
    return TransferOrder.objects.create(
        goods=goods, operator=user, quantity=quantity,
        target_location=target_location, target_keeper=target_keeper,
        status='pending', remark=remark,
    )


def review_transfer(transfer_id, *, approver, approved, remark=''):
    goods_id = TransferOrder.objects.filter(pk=transfer_id).values_list('goods_id', flat=True).first()
    if goods_id is None:
        raise BusinessException('转移记录不存在', code=404)
    return _transfer_review_tx(
        transfer_id=transfer_id, goods_id=goods_id,
        approver=approver, approved=approved, remark=remark or '',
    )


@freeze_aware
@transaction.atomic
def _transfer_review_tx(*, transfer_id, goods_id, approver, approved, remark):
    lock_goods([goods_id])
    order = _get_for_update(TransferOrder, transfer_id)
    if order is None:
        raise BusinessException('转移记录不存在', code=404)
    if order.status != 'pending':
        raise BusinessException('该转移申请已审批，请勿重复操作', code=409)
    if approved:
        assert_not_frozen(
            goods_id, OP_TRANSFER, user=approver,
            context=f"转移审批（目标位置：{order.target_location}）被拦截："
        )
        order.status = 'approved'
    else:
        order.status = 'rejected'
    if remark:
        order.remark = ((order.remark + '\n') if order.remark else '') + remark
    order.save(update_fields=['status', 'remark'])
    return order


def complete_transfer(transfer_id, *, user):
    goods_id = TransferOrder.objects.filter(pk=transfer_id).values_list('goods_id', flat=True).first()
    if goods_id is None:
        raise BusinessException('转移记录不存在', code=404)
    return _transfer_complete_tx(transfer_id=transfer_id, goods_id=goods_id, user=user)


@freeze_aware
@transaction.atomic
def _transfer_complete_tx(*, transfer_id, goods_id, user):
    goods = lock_goods([goods_id])[0]
    order = _get_for_update(TransferOrder, transfer_id)
    if order is None:
        raise BusinessException('转移记录不存在', code=404)
    if order.status != 'approved':
        raise BusinessException('仅审批通过的转移申请可以执行', code=409)
    assert_not_frozen(goods.pk, OP_TRANSFER, user=user, context='执行转移被拦截：')

    goods.location = order.target_location
    goods.save(update_fields=['location', 'updated_at'])
    order.status = 'completed'
    order.transfer_time = timezone.now()
    order.save(update_fields=['status', 'transfer_time'])
    return order


# ---------------- 销毁 ----------------

def create_disposal(*, user, goods, quantity, reason, planned_time=None, remark=''):
    _check_positive_quantity(quantity)
    return _disposal_create_tx(
        user=user, goods_id=_goods_id(goods), quantity=quantity,
        reason=reason, planned_time=planned_time, remark=remark or '',
    )


@freeze_aware
@transaction.atomic
def _disposal_create_tx(*, user, goods_id, quantity, reason, planned_time, remark):
    goods_list = lock_goods([goods_id])
    if not goods_list:
        raise BusinessException('物资不存在', code=404)
    goods = goods_list[0]
    _enough_stock(goods, quantity)
    assert_not_frozen(goods.pk, OP_DESTROY, user=user, context='销毁计划被拦截：')
    return DisposalPlan.objects.create(
        goods=goods, operator=user, quantity=quantity, reason=reason,
        planned_time=planned_time, status='pending', remark=remark,
    )


def review_disposal(disposal_id, *, approver, approved, remark=''):
    goods_id = DisposalPlan.objects.filter(pk=disposal_id).values_list('goods_id', flat=True).first()
    if goods_id is None:
        raise BusinessException('销毁计划不存在', code=404)
    return _disposal_review_tx(
        disposal_id=disposal_id, goods_id=goods_id,
        approver=approver, approved=approved, remark=remark or '',
    )


@freeze_aware
@transaction.atomic
def _disposal_review_tx(*, disposal_id, goods_id, approver, approved, remark):
    lock_goods([goods_id])
    plan = _get_for_update(DisposalPlan, disposal_id)
    if plan is None:
        raise BusinessException('销毁计划不存在', code=404)
    if plan.status != 'pending':
        raise BusinessException('该销毁计划已审批，请勿重复操作', code=409)
    if approved:
        assert_not_frozen(
            goods_id, OP_DESTROY, user=approver,
            context=f"销毁审批（事由：{plan.reason}）被拦截："
        )
        plan.status = 'approved'
    else:
        plan.status = 'rejected'
    if remark:
        plan.remark = ((plan.remark + '\n') if plan.remark else '') + remark
    plan.save(update_fields=['status', 'remark'])
    return plan


def destroy_disposal(disposal_id, *, user):
    goods_id = DisposalPlan.objects.filter(pk=disposal_id).values_list('goods_id', flat=True).first()
    if goods_id is None:
        raise BusinessException('销毁计划不存在', code=404)
    return _disposal_destroy_tx(disposal_id=disposal_id, goods_id=goods_id, user=user)


@freeze_aware
@transaction.atomic
def _disposal_destroy_tx(*, disposal_id, goods_id, user):
    goods = lock_goods([goods_id])[0]
    plan = _get_for_update(DisposalPlan, disposal_id)
    if plan is None:
        raise BusinessException('销毁计划不存在', code=404)
    if plan.status != 'approved':
        raise BusinessException('仅审批通过的销毁计划可以执行销毁', code=409)
    assert_not_frozen(goods.pk, OP_DESTROY, user=user, context='执行销毁被拦截：')
    if plan.quantity > goods.quantity:
        raise BusinessException('库存不足，无法完成销毁')

    goods.quantity -= plan.quantity
    goods.save(update_fields=['quantity', 'updated_at'])
    plan.status = 'destroyed'
    plan.destroyed_time = timezone.now()
    plan.save(update_fields=['status', 'destroyed_time'])
    return plan

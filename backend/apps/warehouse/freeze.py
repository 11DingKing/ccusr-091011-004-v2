"""
法律冻结业务服务。

所有会改变货物占有状态的操作（出库、转移、销毁）与冻结登记共用同一套
加锁 + 判定流程：

    with transaction.atomic():
        lock_goods_for_update([goods_id])
        assert_not_frozen([goods_id], action=..., operator=...)
        # 业务写入 ...

冻结登记同样先锁货再写入，因此两类事务在数据库层面串行化，
不会出现“业务先放行、冻结后补登”的空档。
"""
import functools

from django.db import transaction
from django.utils import timezone

from .models import (
    Goods, LegalFreeze, LegalFreezeItem, FreezeBlockLog,
    StockIn, StockOut, Approval, StockTransfer, DestructionPlan,
    lock_goods_for_update, active_freeze_items, assert_not_frozen,
    FreezeViolation,
)

ACTION_LABELS = dict(FreezeBlockLog.ACTION_CHOICES)


def guarded(fn):
    """业务事务回滚后，在独立事务中补写阻断留痕，再向上抛出。

    若在函数内部捕获异常，atomic 装饰器不会回滚（Django 仅在异常
    逃出 atomic 块时回滚），因此采用内层原子块 + 外层捕获的结构。
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            with transaction.atomic():
                return fn(*args, **kwargs)
        except FreezeViolation as exc:
            with transaction.atomic():
                exc.persist_logs()
            raise

    return wrapper


# ==================== 冻结登记 / 解除 ====================

@transaction.atomic
def register_freeze(*, case_no, document_no, authority, scope_type, scope_targets,
                    created_by, effective_at=None, expire_at=None,
                    case_name='', remark=''):
    """登记一份法律冻结，并把物资范围快照为冻结明细。

    effective_at 允许早于当前时间（文书先送达、后补录系统），
    补录的冻结立即产生阻断效力。
    """
    effective_at = effective_at or timezone.now()
    if expire_at and expire_at <= effective_at:
        raise ValueError('到期时间必须晚于生效时间')

    freeze = LegalFreeze.objects.create(
        case_no=case_no,
        case_name=case_name,
        document_no=document_no,
        authority=authority,
        scope_type=scope_type,
        scope_targets=list(scope_targets),
        effective_at=effective_at,
        expire_at=expire_at,
        remark=remark,
        created_by=created_by,
    )

    # 先锁住候选货物，防止展开快照期间发生出库/转移，保证快照与锁定判定一致。
    candidate_ids = list(_candidate_goods_ids(scope_type, scope_targets))
    lock_goods_for_update(candidate_ids)
    goods_list = list(freeze.expand_goods())
    if not goods_list:
        # 空范围冻结没有法律意义，直接回滚整个登记事务。
        raise ValueError('冻结范围内没有在库货物，无法登记冻结')

    LegalFreezeItem.objects.bulk_create([
        LegalFreezeItem(
            freeze=freeze,
            goods=goods,
            goods_name_snapshot=goods.name,
            goods_code_snapshot=goods.code,
        )
        for goods in goods_list
    ])
    return freeze


def _candidate_goods_ids(scope_type, targets):
    qs = Goods.objects.filter(is_active=True)
    if scope_type == LegalFreeze.SCOPE_GOODS:
        return qs.filter(pk__in=targets).values_list('id', flat=True)
    if scope_type == LegalFreeze.SCOPE_VARIETY:
        return qs.filter(variety_id__in=targets).values_list('id', flat=True)
    if scope_type == LegalFreeze.SCOPE_CATEGORY:
        return qs.filter(variety__category_id__in=targets).values_list('id', flat=True)
    return qs.none().values_list('id', flat=True)


@transaction.atomic
def lift_freeze(freeze, *, lifted_by, remark=''):
    """解除一份冻结。

    多份冻结重叠时，解除只改变本份记录的状态；对货物的阻断查询始终
    实时汇总所有有效冻结，因此不会误解开其他限制。
    """
    freeze = LegalFreeze.objects.select_for_update().get(pk=freeze.pk)
    if freeze.status != LegalFreeze.STATUS_ACTIVE:
        raise ValueError('该冻结已解除，不能重复解除')
    freeze.status = LegalFreeze.STATUS_LIFTED
    freeze.lifted_at = timezone.now()
    freeze.lifted_by = lifted_by
    freeze.lift_remark = remark
    freeze.save(update_fields=['status', 'lifted_at', 'lifted_by', 'lift_remark'])
    return freeze


# ==================== 出库 ====================

@guarded
def approve_stock_out(stock_out, *, approver, remark=''):
    """审批通过出库申请：货物被冻结时禁止放行。"""
    stock_out = StockOut.objects.select_for_update().get(pk=stock_out.pk)
    if stock_out.status != 'pending':
        raise ValueError('该申请已审批，不能重复审批')
    lock_goods_for_update([stock_out.goods_id])
    assert_not_frozen(
        [stock_out.goods_id], action='stock_out',
        operator=approver, detail=f'出库申请#{stock_out.pk}（{stock_out.receiver}）',
    )
    stock_out.status = 'approved'
    stock_out.save(update_fields=['status'])
    Approval.objects.create(stock_out=stock_out, approver=approver,
                            status='approved', remark=remark)
    return stock_out


@guarded
def complete_stock_out(stock_out, *, operator):
    """实际出库：冻结期间一律阻断，即便申请在冻结前已审批通过。"""
    stock_out = StockOut.objects.select_for_update().get(pk=stock_out.pk)
    if stock_out.status != 'approved':
        raise ValueError('只有审批通过的出库申请可以出库')
    goods = Goods.objects.select_for_update().get(pk=stock_out.goods_id)
    lock_goods_for_update([goods.id])
    assert_not_frozen(
        [goods.id], action='stock_out',
        operator=operator, detail=f'出库申请#{stock_out.pk}（{stock_out.receiver}）',
    )
    if goods.quantity < stock_out.quantity:
        raise ValueError('库存数量不足')
    goods.quantity = goods.quantity - stock_out.quantity
    goods.save(update_fields=['quantity', 'updated_at'])
    stock_out.status = 'completed'
    stock_out.stock_out_time = timezone.now()
    stock_out.save(update_fields=['status', 'stock_out_time'])
    return stock_out


@transaction.atomic
def reject_stock_out(stock_out, *, approver, remark=''):
    stock_out = StockOut.objects.select_for_update().get(pk=stock_out.pk)
    if stock_out.status != 'pending':
        raise ValueError('该申请已审批，不能重复审批')
    stock_out.status = 'rejected'
    stock_out.save(update_fields=['status'])
    Approval.objects.create(stock_out=stock_out, approver=approver,
                            status='rejected', remark=remark)
    return stock_out


# ==================== 转移 ====================

@guarded
def approve_transfer(transfer, *, approver, remark=''):
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
    if transfer.status != 'pending':
        raise ValueError('该转移申请已审批')
    lock_goods_for_update([transfer.goods_id])
    assert_not_frozen(
        [transfer.goods_id], action='transfer',
        operator=approver, detail=f'转移申请#{transfer.pk}',
    )
    transfer.status = 'approved'
    transfer.save(update_fields=['status'])
    return transfer


@guarded
def complete_transfer(transfer, *, operator):
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
    if transfer.status != 'approved':
        raise ValueError('只有审批通过的转移可以执行')
    goods = Goods.objects.select_for_update().get(pk=transfer.goods_id)
    lock_goods_for_update([goods.id])
    assert_not_frozen(
        [goods.id], action='transfer',
        operator=operator, detail=f'转移申请#{transfer.pk}',
    )
    goods.location = transfer.to_location
    goods.save(update_fields=['location', 'updated_at'])
    transfer.status = 'completed'
    transfer.transfer_time = timezone.now()
    transfer.save(update_fields=['status', 'transfer_time'])
    return transfer


# ==================== 销毁 ====================

@guarded
def approve_destruction(plan, *, approver, remark=''):
    plan = DestructionPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != 'pending':
        raise ValueError('该销毁计划已审批')
    lock_goods_for_update([plan.goods_id])
    assert_not_frozen(
        [plan.goods_id], action='destruction',
        operator=approver, detail=f'销毁计划#{plan.pk}',
    )
    plan.status = 'approved'
    plan.save(update_fields=['status'])
    return plan


@guarded
def complete_destruction(plan, *, operator):
    plan = DestructionPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != 'approved':
        raise ValueError('只有审批通过的销毁计划可以执行销毁')
    goods = Goods.objects.select_for_update().get(pk=plan.goods_id)
    lock_goods_for_update([goods.id])
    assert_not_frozen(
        [goods.id], action='destruction',
        operator=operator, detail=f'销毁计划#{plan.pk}',
    )
    if goods.quantity < plan.quantity:
        raise ValueError('库存数量不足')
    goods.quantity = goods.quantity - plan.quantity
    goods.save(update_fields=['quantity', 'updated_at'])
    plan.status = 'completed'
    plan.destroyed_at = timezone.now()
    plan.save(update_fields=['status', 'destroyed_at'])
    return plan


# ==================== 查询：阻断依据与时间线 ====================

def current_blocks(goods_id):
    """货物当前受到的全部有效冻结（重叠冻结全部列出）。"""
    return list(active_freeze_items([goods_id]).distinct())


def freeze_timeline(freeze):
    """冻结决定自身的生命周期时间线，并附被阻断业务记录。"""
    events = []

    def add(ts, title, **extra):
        events.append({'time': ts, 'category': 'freeze', 'title': title, **extra})

    add(freeze.created_at, f'冻结登记：{freeze.document_no}（{freeze.case_no}）',
        operator_name=freeze.created_by.username if freeze.created_by else '',
        authority=freeze.authority, remark=freeze.remark)
    add(freeze.effective_at, f'冻结生效：{freeze.document_no}')
    if freeze.status == LegalFreeze.STATUS_LIFTED and freeze.lifted_at:
        add(freeze.lifted_at,
            f'冻结解除：{freeze.document_no}'
            + (f'（{freeze.lift_remark}）' if freeze.lift_remark else ''),
            operator_name=freeze.lifted_by.username if freeze.lifted_by else '')
    elif freeze.expire_at:
        add(freeze.expire_at, f'冻结期限届满：{freeze.document_no}')

    for block in (
        FreezeBlockLog.objects.filter(freeze=freeze)
        .select_related('operator', 'goods')
        .order_by('created_at')
    ):
        events.append({
            'time': block.created_at, 'category': 'block',
            'title': f'{ACTION_LABELS.get(block.action, block.action)}被阻断：{block.message}',
            'goods': block.goods_id,
            'goods_code': block.goods.code,
            'operator_name': block.operator.username if block.operator else '',
            'detail': block.detail,
        })

    events.sort(key=lambda e: (e['time'] is None, e['time'] or timezone.now()))
    return events


def goods_timeline(goods_id):
    """构造货物的完整时间线：冻结前历史、冻结生命周期与业务操作合并展示。

    冻结不会修改或删除任何历史业务记录，历史状态原样保留在时间线上。
    """
    events = []

    def add(ts, category, title, **extra):
        events.append({'time': ts, 'category': category, 'title': title, **extra})

    for note in StockIn.objects.filter(goods_id=goods_id):
        add(note.stock_in_time, 'stock_in', f'入库 +{note.quantity}',
            operator_name=note.operator.username if note.operator else '',
            remark=note.remark)

    for out in StockOut.objects.filter(goods_id=goods_id).select_related('operator'):
        add(out.created_at, 'stock_out', f'出库申请提交（{out.receiver}，{out.quantity}）',
            status=out.status, ref=out.pk,
            operator_name=out.operator.username if out.operator else '')
        for ap in out.approvals.select_related('approver').order_by('created_at'):
            add(ap.created_at, 'approval',
                f'出库审批：{ap.get_status_display()}',
                status=ap.status, ref=out.pk,
                operator_name=ap.approver.username if ap.approver else '',
                remark=ap.remark)
        if out.status == 'completed' and out.stock_out_time:
            add(out.stock_out_time, 'stock_out', f'实际出库 -{out.quantity}',
                status=out.status, ref=out.pk)

    for tr in StockTransfer.objects.filter(goods_id=goods_id).select_related('operator'):
        add(tr.created_at, 'transfer', f'转移申请提交（{tr.to_location}，{tr.quantity}）',
            status=tr.status, ref=tr.pk)
        if tr.status == 'completed' and tr.transfer_time:
            add(tr.transfer_time, 'transfer',
                f'完成转移至 {tr.to_location}', status=tr.status, ref=tr.pk)

    for plan in DestructionPlan.objects.filter(goods_id=goods_id).select_related('operator'):
        add(plan.created_at, 'destruction', f'销毁计划提交（{plan.quantity}）',
            status=plan.status, ref=plan.pk)
        if plan.status == 'completed' and plan.destroyed_at:
            add(plan.destroyed_at, 'destruction', f'完成销毁 -{plan.quantity}',
                status=plan.status, ref=plan.pk)

    freeze_items = (
        LegalFreezeItem.objects.filter(goods_id=goods_id)
        .select_related('freeze', 'freeze__created_by', 'freeze__lifted_by')
    )
    for item in freeze_items:
        fz = item.freeze
        add(fz.created_at, 'freeze',
            f'冻结登记：{fz.document_no}（{fz.case_no}）',
            freeze_id=fz.id, status=fz.status,
            operator_name=fz.created_by.username if fz.created_by else '',
            authority=fz.authority, remark=fz.remark)
        add(fz.effective_at, 'freeze', f'冻结生效：{fz.document_no}',
            freeze_id=fz.id, status=fz.status)
        if fz.status == LegalFreeze.STATUS_LIFTED and fz.lifted_at:
            add(fz.lifted_at, 'freeze',
                f'冻结解除：{fz.document_no}'
                + (f'（{fz.lift_remark}）' if fz.lift_remark else ''),
                freeze_id=fz.id, status=fz.status,
                operator_name=fz.lifted_by.username if fz.lifted_by else '')
        elif fz.expire_at:
            add(fz.expire_at, 'freeze', f'冻结期限届满：{fz.document_no}',
                freeze_id=fz.id, status=fz.status)

    for block in (
        FreezeBlockLog.objects.filter(goods_id=goods_id)
        .select_related('freeze', 'operator')
        .order_by('created_at')
    ):
        add(block.created_at, 'block',
            f'{ACTION_LABELS.get(block.action, block.action)}被阻断：{block.message}',
            freeze_id=block.freeze_id,
            operator_name=block.operator.username if block.operator else '',
            detail=block.detail)

    events.sort(key=lambda e: (e['time'] is None, e['time'] or timezone.now()))
    return events

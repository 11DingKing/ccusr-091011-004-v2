"""
库房管理模型
"""
from django.db import models, connection
from django.db.models import F
from apps.authentication.models import User


class Unit(models.Model):
    """单位模型"""
    name = models.CharField('单位名称', max_length=5, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_units', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_unit'
        verbose_name = '单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品类"""
        return self.categories.exists()


class Category(models.Model):
    """品类模型"""
    name = models.CharField('品类名称', max_length=10, unique=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT,
        related_name='categories', verbose_name='单位'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_categories', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_category'
        verbose_name = '品类'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品种"""
        return self.varieties.exists()


class Variety(models.Model):
    """品种模型"""
    name = models.CharField('品种名称', max_length=20)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='varieties', verbose_name='所属品类'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_varieties', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_variety'
        verbose_name = '品种'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        unique_together = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    @property
    def is_in_stock(self):
        """是否已入库"""
        return self.goods.exists()
    
    @property
    def unit_name(self):
        """获取单位名称"""
        return self.category.unit.name if self.category and self.category.unit else ''


class Goods(models.Model):
    """货物模型"""
    variety = models.ForeignKey(
        Variety, on_delete=models.CASCADE,
        related_name='goods', verbose_name='所属品种'
    )
    name = models.CharField('货物名称', max_length=200)
    code = models.CharField('货物编码', max_length=50, unique=True)
    specification = models.CharField('规格型号', max_length=200, blank=True)
    quantity = models.DecimalField('库存数量', max_digits=12, decimal_places=2, default=0)
    warning_threshold = models.DecimalField('预警阈值', max_digits=12, decimal_places=2, default=10)
    location = models.CharField('存放位置', max_length=100, blank=True)
    remark = models.TextField('备注', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_goods'
        verbose_name = '货物'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_warning(self):
        """是否预警"""
        return self.quantity <= self.warning_threshold


class StockIn(models.Model):
    """入库记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_ins', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    stock_in_time = models.DateTimeField('入库时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    
    class Meta:
        db_table = 'wh_stock_in'
        verbose_name = '入库记录'
        verbose_name_plural = verbose_name
        ordering = ['-stock_in_time']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class StockOut(models.Model):
    """出库记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_outs', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_out_operations', verbose_name='操作人'
    )
    receiver = models.CharField('领用人', max_length=100)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('出库数量', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    stock_out_time = models.DateTimeField('出库时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_stock_out'
        verbose_name = '出库记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class Warning(models.Model):
    """预警记录模型"""
    TYPE_CHOICES = [
        ('low_stock', '库存不足'),
        ('expiring', '即将过期'),
        ('expired', '已过期'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='warnings', verbose_name='货物'
    )
    type = models.CharField('预警类型', max_length=20, choices=TYPE_CHOICES)
    message = models.TextField('预警信息')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_warning'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.get_type_display()}"


class Approval(models.Model):
    """审批记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    
    stock_out = models.ForeignKey(
        StockOut, on_delete=models.CASCADE,
        related_name='approvals', verbose_name='出库记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approvals', verbose_name='审批人'
    )
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_approval'
        verbose_name = '审批记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.stock_out} - {self.get_status_display()}"


# ==================== 法律冻结 ====================

class LegalFreeze(models.Model):
    """法律冻结决定。

    一份冻结对应调查部门出具的一份法律文书，按物资范围冻结；
    范围在下达时展开为具体货物快照（LegalFreezeItem），此后即使
    货物归属的品种/品类调整，冻结范围也保持稳定。多份冻结可以
    重叠覆盖同一货物，各自独立解除，互不影响。
    """
    SCOPE_GOODS = 'goods'
    SCOPE_VARIETY = 'variety'
    SCOPE_CATEGORY = 'category'
    SCOPE_CHOICES = [
        (SCOPE_GOODS, '指定货物'),
        (SCOPE_VARIETY, '指定品种（冻结时在库货物）'),
        (SCOPE_CATEGORY, '指定品类（冻结时在库货物）'),
    ]
    STATUS_ACTIVE = 'active'
    STATUS_LIFTED = 'lifted'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, '冻结中'),
        (STATUS_LIFTED, '已解除'),
    ]

    case_no = models.CharField('案件编号', max_length=100)
    case_name = models.CharField('案件名称', max_length=200, blank=True)
    document_no = models.CharField('法律文书编号', max_length=100)
    authority = models.CharField('作出机关', max_length=200)
    scope_type = models.CharField('范围类型', max_length=20, choices=SCOPE_CHOICES)
    scope_targets = models.JSONField('范围标识（货物/品种/品类ID）', default=list)
    effective_at = models.DateTimeField('生效时间')
    expire_at = models.DateTimeField('到期时间', null=True, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    remark = models.TextField('备注', blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_freezes', verbose_name='登记人'
    )
    created_at = models.DateTimeField('登记时间', auto_now_add=True)
    lifted_at = models.DateTimeField('解除时间', null=True, blank=True)
    lifted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lifted_freezes', verbose_name='解除人'
    )
    lift_remark = models.TextField('解除说明', blank=True)

    class Meta:
        db_table = 'wh_legal_freeze'
        verbose_name = '法律冻结'
        verbose_name_plural = verbose_name
        ordering = ['-effective_at', '-created_at']

    def __str__(self):
        return f"冻结 {self.document_no}（{self.case_no}）"

    @property
    def is_active(self):
        """逻辑有效：状态为冻结中，且已生效未到期。"""
        from django.utils import timezone
        if self.status != self.STATUS_ACTIVE:
            return False
        now = timezone.now()
        if self.effective_at > now:
            return False
        if self.expire_at and self.expire_at <= now:
            return False
        return True

    def expand_goods(self):
        """将范围标识展开为具体货物（登记时调用，结果作为冻结快照）。"""
        qs = Goods.objects.filter(is_active=True)
        if self.scope_type == self.SCOPE_GOODS:
            return list(qs.filter(pk__in=self.scope_targets or []))
        if self.scope_type == self.SCOPE_VARIETY:
            return list(qs.filter(variety_id__in=self.scope_targets or []))
        if self.scope_type == self.SCOPE_CATEGORY:
            return list(qs.filter(variety__category_id__in=self.scope_targets or []))
        return []


class LegalFreezeItem(models.Model):
    """冻结范围明细：冻结下达时物资范围的货物快照。"""
    freeze = models.ForeignKey(
        LegalFreeze, on_delete=models.CASCADE,
        related_name='items', verbose_name='冻结决定'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='freeze_items', verbose_name='货物'
    )
    goods_name_snapshot = models.CharField('货物名称（冻结时）', max_length=200)
    goods_code_snapshot = models.CharField('货物编码（冻结时）', max_length=50)
    created_at = models.DateTimeField('加入冻结时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_legal_freeze_item'
        verbose_name = '冻结范围明细'
        verbose_name_plural = verbose_name
        unique_together = [('freeze', 'goods')]
        ordering = ['goods_id']

    def __str__(self):
        return f"{self.freeze_id}:{self.goods_code_snapshot}"


class StockTransfer(models.Model):
    """库间转移记录。"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='transfers', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='transfer_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('转移数量', max_digits=12, decimal_places=2)
    from_location = models.CharField('调出位置', max_length=100, blank=True)
    to_location = models.CharField('调入位置', max_length=100)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    transfer_time = models.DateTimeField('转移时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_stock_transfer'
        verbose_name = '库间转移'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.goods.name} -> {self.to_location}"


class DestructionPlan(models.Model):
    """销毁计划。执行前须经审批，受冻结约束。"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已销毁'),
    ]
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='destruction_plans', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='destruction_operations', verbose_name='经办人'
    )
    quantity = models.DecimalField('销毁数量', max_digits=12, decimal_places=2)
    reason = models.CharField('销毁事由', max_length=200, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    destroyed_at = models.DateTimeField('销毁时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_destruction_plan'
        verbose_name = '销毁计划'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"销毁 {self.goods.name} {self.quantity}"


class FreezeBlockLog(models.Model):
    """冻结阻断记录：出账业务被冻结拦下时留痕，作为承办人看到的依据之一。"""
    ACTION_CHOICES = [
        ('stock_out', '出库'),
        ('transfer', '转移'),
        ('destruction', '销毁'),
    ]
    freeze = models.ForeignKey(
        LegalFreeze, on_delete=models.CASCADE,
        related_name='block_logs', verbose_name='冻结决定'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='freeze_block_logs', verbose_name='货物'
    )
    action = models.CharField('业务类型', max_length=20, choices=ACTION_CHOICES)
    detail = models.CharField('业务标识', max_length=200, blank=True)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='freeze_blocks', verbose_name='操作人'
    )
    message = models.CharField('阻断说明', max_length=300)
    created_at = models.DateTimeField('阻断时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_freeze_block_log'
        verbose_name = '冻结阻断记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_action_display()}被冻结{self.freeze_id}阻断"


# ==================== 冻结校验 ====================

def lock_goods_for_update(goods_ids):
    """对货物行加写锁，直到外层事务提交/回滚。

    冻结登记与出库/转移/销毁必须先取同一批货物的锁再做冻结判定，
    使两类操作在数据库层面串行化，避免“先放行、后补冻结”的空档。
    SQLite 不支持 SELECT ... FOR UPDATE，但同一保留写锁（对行做
    无实际变化的 UPDATE）在整个事务内阻塞其他写事务，效果等价。
    """
    ids = [g for g in dict.fromkeys(goods_ids) if g is not None]
    if not ids:
        return
    if connection.vendor == 'sqlite':
        Goods.objects.filter(pk__in=ids).update(updated_at=F('updated_at'))
    else:
        list(Goods.objects.filter(pk__in=ids).select_for_update())


def active_freeze_items(goods_ids, at=None):
    """返回货物当前受哪些有效冻结明细约束（已按冻结/货物去重）。"""
    from django.utils import timezone
    at = at or timezone.now()
    return (
        LegalFreezeItem.objects
        .filter(goods_id__in=goods_ids)
        .filter(freeze__status=LegalFreeze.STATUS_ACTIVE)
        .filter(freeze__effective_at__lte=at)
        .filter(
            models.Q(freeze__expire_at__isnull=True)
            | models.Q(freeze__expire_at__gt=at)
        )
        .select_related('freeze')
        .order_by('freeze__effective_at', 'freeze_id')
    )


class FreezeViolation(Exception):
    """业务被有效法律冻结阻断。"""

    def __init__(self, items, action, operator=None, detail=''):
        self.items = list(items)
        self.action = action
        self.operator = operator
        self.detail = detail
        first = self.items[0].freeze
        super().__init__(
            f"物资处于法律冻结期间，阻断依据：{first.document_no}（{first.case_no}），"
            f"共 {len(self.items)} 项冻结限制，须先解除后方可办理。"
        )

    def persist_logs(self):
        """在业务事务回滚后调用：阻断留痕独立提交，不随回滚丢失。

        幂等：服务层与视图层都可能在异常链上调用，只写一次。
        """
        if getattr(self, '_logs_persisted', False):
            return []
        self._logs_persisted = True
        label = dict(FreezeBlockLog.ACTION_CHOICES).get(self.action, self.action)
        return FreezeBlockLog.objects.bulk_create([
            FreezeBlockLog(
                freeze=item.freeze,
                goods=item.goods,
                action=self.action,
                detail=self.detail or '',
                operator=self.operator,
                message=(
                    f"{label}被冻结决定 {item.freeze.document_no}"
                    f"（{item.freeze.case_no}）阻断"
                ),
            )
            for item in self.items
        ])


def assert_not_frozen(goods_ids, action, operator=None, detail='', at=None):
    """断言货物未被冻结，否则抛出携带全部阻断依据的 FreezeViolation。

    调用方必须已在事务中并先通过 lock_goods_for_update 锁住货物。
    阻断留痕由上层在业务事务回滚后调用 persist_logs() 独立写入，
    以保证“业务没办成、留痕还在”。
    """
    items = list(active_freeze_items(goods_ids, at=at))
    if items:
        raise FreezeViolation(items, action, operator=operator, detail=detail)
    return items

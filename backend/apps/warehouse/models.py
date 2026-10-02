"""
库房管理模型
"""
from django.db import models
from django.utils import timezone
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


class TransferOrder(models.Model):
    """转移记录模型（物资在保管点/保管人之间转移）"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]

    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='transfer_orders', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='transfer_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('转移数量', max_digits=12, decimal_places=2)
    target_location = models.CharField('目标存放位置', max_length=100)
    target_keeper = models.CharField('目标保管人', max_length=100, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    transfer_time = models.DateTimeField('转移时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_transfer_order'
        verbose_name = '转移记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.goods.name} - {self.quantity} - {self.target_location}"


class DisposalPlan(models.Model):
    """销毁计划模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('destroyed', '已销毁'),
    ]

    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='disposal_plans', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='disposal_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('销毁数量', max_digits=12, decimal_places=2)
    reason = models.CharField('销毁事由', max_length=200)
    planned_time = models.DateTimeField('计划销毁时间', null=True, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    destroyed_time = models.DateTimeField('实际销毁时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_disposal_plan'
        verbose_name = '销毁计划'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.goods.name} - {self.quantity} - {self.get_status_display()}"


# ==================== 法律冻结 ====================

class LegalFreeze(models.Model):
    """法律冻结记录：办案机关依法对涉案物资下达的冻结/查封/扣押指令。

    多份冻结可对同一批物资重叠生效；每份冻结独立建立、独立解除，
    解除其中一份不会影响其他仍然有效的冻结。
    """
    ACTION_FREEZE = 'freeze'
    ACTION_SEAL = 'seal'
    ACTION_DISTRAIN = 'distrain'
    ACTION_CHOICES = [
        (ACTION_FREEZE, '冻结'),
        (ACTION_SEAL, '查封'),
        (ACTION_DISTRAIN, '扣押'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_LIFTED = 'lifted'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, '生效中'),
        (STATUS_LIFTED, '已解除'),
    ]

    freeze_no = models.CharField('冻结编号', max_length=50, unique=True)
    case_info = models.CharField('案件名称/编号', max_length=200)
    authority = models.CharField('办案机关', max_length=200)
    legal_doc = models.CharField('法律文书号', max_length=100, blank=True)
    action_type = models.CharField(
        '冻结方式', max_length=20, choices=ACTION_CHOICES, default=ACTION_FREEZE
    )
    effective_from = models.DateTimeField('生效时间')
    effective_to = models.DateTimeField('到期时间', null=True, blank=True)
    status = models.CharField(
        '状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_freezes', verbose_name='承办人'
    )
    lifted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lifted_freezes', verbose_name='解除人'
    )
    lift_doc = models.CharField('解除文书号', max_length=100, blank=True)
    lift_reason = models.CharField('解除事由', max_length=200, blank=True)
    lifted_at = models.DateTimeField('解除时间', null=True, blank=True)
    created_at = models.DateTimeField('建立时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_legal_freeze'
        verbose_name = '法律冻结记录'
        verbose_name_plural = verbose_name
        ordering = ['-effective_from', '-created_at']

    def __str__(self):
        return f"{self.freeze_no} - {self.case_info}"

    def is_effective_at(self, at=None):
        """该份冻结在指定时刻（默认当前）是否产生阻断效力。

        必须同时满足：状态为生效中、已到生效时间、未到期。
        解除后即使时间窗仍覆盖该时刻也不再有效。
        """
        at = at or timezone.now()
        if self.status != self.STATUS_ACTIVE:
            return False
        if at < self.effective_from:
            return False
        if self.effective_to and at >= self.effective_to:
            return False
        return True

    @property
    def is_effective(self):
        """当前是否生效中（供序列化与列表展示）"""
        return self.is_effective_at()


class FreezeItem(models.Model):
    """冻结物资范围：一份冻结与一件物资的关联明细。"""
    OP_STOCK_OUT = 'stock_out'
    OP_TRANSFER = 'transfer'
    OP_DESTROY = 'destroy'
    OP_CHOICES = [
        (OP_STOCK_OUT, '出库'),
        (OP_TRANSFER, '转移'),
        (OP_DESTROY, '销毁'),
    ]
    ALL_OPERATIONS = [OP_STOCK_OUT, OP_TRANSFER, OP_DESTROY]

    freeze = models.ForeignKey(
        LegalFreeze, on_delete=models.CASCADE,
        related_name='items', verbose_name='冻结记录'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='freeze_items', verbose_name='货物'
    )
    restrict_operations = models.CharField(
        '限制操作', max_length=60,
        default=','.join(ALL_OPERATIONS)
    )
    quantity = models.DecimalField(
        '冻结数量', max_digits=12, decimal_places=2, null=True, blank=True
    )
    created_at = models.DateTimeField('加入时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_freeze_item'
        verbose_name = '冻结物资范围'
        verbose_name_plural = verbose_name
        unique_together = ['freeze', 'goods']

    def __str__(self):
        return f"{self.freeze.freeze_no} - {self.goods.name}"

    @property
    def operations_list(self):
        return [op for op in self.restrict_operations.split(',') if op]

    def restricts(self, operation):
        """该明细是否限制指定操作"""
        return operation in self.operations_list


def get_blocking_items(goods_ids, operation, at=None):
    """查询在指定时刻对给定物资、指定操作仍有阻断效力的冻结明细。

    - 逐份冻结独立判定（状态 + 生效时间窗），多份重叠时全部返回；
    - goods_ids 支持单个 id 或可迭代 id 集合；
    - 返回 dict: goods_id -> list[FreezeItem]，仅含有阻断依据的物资。
    只读查询，不加锁；放行路径必须使用 services.assert_not_frozen。
    """
    if isinstance(goods_ids, int):
        goods_ids = [goods_ids]
    goods_ids = list(goods_ids)
    at = at or timezone.now()

    items = FreezeItem.objects.filter(
        goods_id__in=goods_ids
    ).select_related('freeze')

    # __contains 对逗号分隔串做子串匹配即可命中操作名；
    # 各操作名互不构成前缀/子串，不会误匹配。
    items = items.filter(restrict_operations__contains=operation)

    blocked = {}
    for item in items:
        if item.freeze.is_effective_at(at):
            blocked.setdefault(item.goods_id, []).append(item)
    return blocked


class FreezeEvent(models.Model):
    """冻结生命周期事件：建立、解除、被拦截的业务操作，构成完整时间线。"""
    TYPE_CREATED = 'created'
    TYPE_LIFTED = 'lifted'
    TYPE_BLOCKED = 'blocked'
    TYPE_CHOICES = [
        (TYPE_CREATED, '冻结建立'),
        (TYPE_LIFTED, '冻结解除'),
        (TYPE_BLOCKED, '操作拦截'),
    ]

    freeze = models.ForeignKey(
        LegalFreeze, on_delete=models.CASCADE,
        related_name='events', verbose_name='冻结记录'
    )
    type = models.CharField('事件类型', max_length=20, choices=TYPE_CHOICES)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='freeze_events', verbose_name='操作人'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='freeze_events', verbose_name='关联物资'
    )
    operation = models.CharField('被拦截操作', max_length=20, blank=True, default='')
    detail = models.CharField('说明', max_length=500, blank=True)
    occurred_at = models.DateTimeField('发生时间', default=timezone.now)

    class Meta:
        db_table = 'wh_freeze_event'
        verbose_name = '冻结事件'
        verbose_name_plural = verbose_name
        ordering = ['occurred_at', 'id']

    def __str__(self):
        return f"{self.freeze.freeze_no} - {self.get_type_display()}"


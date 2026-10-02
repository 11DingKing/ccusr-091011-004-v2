"""
仓库管理序列化器
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    LegalFreeze, LegalFreezeItem, StockTransfer, DestructionPlan, FreezeBlockLog,
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    
    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'stock_in_time', 'remark'
        ]


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 法律冻结 ====================

class FreezeItemSerializer(serializers.ModelSerializer):
    """冻结范围明细序列化器"""
    class Meta:
        model = LegalFreezeItem
        fields = ['id', 'goods', 'goods_name_snapshot', 'goods_code_snapshot', 'created_at']


class LegalFreezeListSerializer(serializers.ModelSerializer):
    """冻结列表/详情序列化器"""
    scope_type_display = serializers.CharField(source='get_scope_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    lifted_by_name = serializers.CharField(source='lifted_by.username', read_only=True)
    items = FreezeItemSerializer(many=True, read_only=True)
    goods_count = serializers.SerializerMethodField()

    class Meta:
        model = LegalFreeze
        fields = [
            'id', 'case_no', 'case_name', 'document_no', 'authority',
            'scope_type', 'scope_type_display', 'scope_targets',
            'effective_at', 'expire_at', 'status', 'status_display', 'is_active',
            'remark', 'created_by', 'created_by_name', 'created_at',
            'lifted_at', 'lifted_by', 'lifted_by_name', 'lift_remark',
            'items', 'goods_count',
        ]

    def get_goods_count(self, obj):
        return obj.items.count()


class LegalFreezeCreateSerializer(serializers.Serializer):
    """冻结登记序列化器"""
    case_no = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请输入案件编号', 'blank': '案件编号不能为空'})
    case_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    document_no = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请输入法律文书编号', 'blank': '法律文书编号不能为空'})
    authority = serializers.CharField(max_length=200, required=True, error_messages={
        'required': '请输入作出冻结决定的机关', 'blank': '作出机关不能为空'})
    scope_type = serializers.ChoiceField(
        choices=[LegalFreeze.SCOPE_GOODS, LegalFreeze.SCOPE_VARIETY, LegalFreeze.SCOPE_CATEGORY],
        required=True, error_messages={'required': '请选择冻结范围类型'})
    scope_targets = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=True, allow_empty=False,
        error_messages={'required': '请选择冻结范围', 'empty': '冻结范围不能为空',
                        'not_a_list': '冻结范围格式不正确'})
    effective_at = serializers.DateTimeField(required=False)
    expire_at = serializers.DateTimeField(required=False, allow_null=True)
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        effective_at = data.get('effective_at') or timezone.now()
        data['effective_at'] = effective_at
        expire_at = data.get('expire_at')
        if expire_at and expire_at <= effective_at:
            raise serializers.ValidationError('到期时间必须晚于生效时间')

        scope_type = data['scope_type']
        targets = data['scope_targets']
        if scope_type == LegalFreeze.SCOPE_GOODS:
            existing = set(Goods.objects.filter(pk__in=targets).values_list('pk', flat=True))
            label = '货物'
        elif scope_type == LegalFreeze.SCOPE_VARIETY:
            existing = set(Variety.objects.filter(pk__in=targets).values_list('pk', flat=True))
            label = '品种'
        else:
            existing = set(Category.objects.filter(pk__in=targets).values_list('pk', flat=True))
            label = '品类'
        missing = sorted(set(targets) - existing)
        if missing:
            raise serializers.ValidationError(f'以下{label}不存在：{missing}')
        return data


class FreezeLiftSerializer(serializers.Serializer):
    """解除冻结序列化器"""
    remark = serializers.CharField(required=False, allow_blank=True, default='')


class StockOutApplySerializer(serializers.Serializer):
    """出库申请序列化器（沿用 StockOut 模型，受理阶段即做冻结预检）"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    receiver = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请输入领用人', 'blank': '领用人不能为空'})
    receiver_dept = serializers.CharField(max_length=100, required=False,
                                          allow_blank=True, default='')
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
                                        required=True, error_messages={'required': '请输入数量'})
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value


class ApprovalActionSerializer(serializers.Serializer):
    """审批动作序列化器"""
    remark = serializers.CharField(required=False, allow_blank=True, default='')


class StockTransferSerializer(serializers.ModelSerializer):
    """转移记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'from_location', 'to_location',
            'status', 'status_display', 'transfer_time', 'remark', 'created_at',
        ]
        read_only_fields = ['status', 'transfer_time', 'created_at']


class StockTransferCreateSerializer(serializers.Serializer):
    """转移申请序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
                                        required=True, error_messages={'required': '请输入数量'})
    from_location = serializers.CharField(max_length=100, required=False,
                                          allow_blank=True, default='')
    to_location = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请输入调入位置', 'blank': '调入位置不能为空'})
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value


class DestructionPlanSerializer(serializers.ModelSerializer):
    """销毁计划序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DestructionPlan
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'reason', 'status', 'status_display',
            'destroyed_at', 'remark', 'created_at',
        ]
        read_only_fields = ['status', 'destroyed_at', 'created_at']


class DestructionPlanCreateSerializer(serializers.Serializer):
    """销毁计划创建序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
                                        required=True, error_messages={'required': '请输入数量'})
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value


class FreezeBlockLogSerializer(serializers.ModelSerializer):
    """冻结阻断记录序列化器"""
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    freeze_document_no = serializers.CharField(source='freeze.document_no', read_only=True)
    case_no = serializers.CharField(source='freeze.case_no', read_only=True)

    class Meta:
        model = FreezeBlockLog
        fields = [
            'id', 'freeze', 'freeze_document_no', 'case_no',
            'goods', 'action', 'action_display', 'detail',
            'operator', 'operator_name', 'message', 'created_at',
        ]

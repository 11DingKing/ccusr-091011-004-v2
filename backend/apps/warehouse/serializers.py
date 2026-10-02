"""
仓库管理序列化器
"""
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    TransferOrder, DisposalPlan, LegalFreeze, FreezeItem, FreezeEvent,
)
from .services import OPERATION_LABELS


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


class TransferOrderSerializer(serializers.ModelSerializer):
    """转移记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = TransferOrder
        fields = [
            'id', 'goods', 'goods_name', 'goods_code', 'operator', 'operator_name',
            'quantity', 'target_location', 'target_keeper',
            'status', 'status_display', 'transfer_time', 'remark', 'created_at'
        ]


class DisposalPlanSerializer(serializers.ModelSerializer):
    """销毁计划序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DisposalPlan
        fields = [
            'id', 'goods', 'goods_name', 'goods_code', 'operator', 'operator_name',
            'quantity', 'reason', 'planned_time',
            'status', 'status_display', 'destroyed_time', 'remark', 'created_at'
        ]


# ==================== 法律冻结 ====================

class FreezeItemSerializer(serializers.ModelSerializer):
    """冻结物资范围序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    operations = serializers.ListField(
        child=serializers.CharField(), source='operations_list', read_only=True
    )
    operations_display = serializers.SerializerMethodField()

    class Meta:
        model = FreezeItem
        fields = [
            'id', 'goods', 'goods_name', 'goods_code',
            'operations', 'operations_display', 'quantity', 'created_at'
        ]

    def get_operations_display(self, obj):
        return [OPERATION_LABELS.get(op, op) for op in obj.operations_list]


class FreezeEventSerializer(serializers.ModelSerializer):
    """冻结事件时间线序列化器"""
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operation_display = serializers.SerializerMethodField()

    class Meta:
        model = FreezeEvent
        fields = [
            'id', 'freeze', 'type', 'type_display',
            'operator', 'operator_name',
            'goods', 'goods_name',
            'operation', 'operation_display', 'detail', 'occurred_at'
        ]

    def get_operation_display(self, obj):
        return OPERATION_LABELS.get(obj.operation, obj.operation)


class LegalFreezeSerializer(serializers.ModelSerializer):
    """法律冻结记录序列化器"""
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    lifted_by_name = serializers.CharField(source='lifted_by.username', read_only=True)
    items = FreezeItemSerializer(many=True, read_only=True)
    is_effective = serializers.BooleanField(read_only=True)

    class Meta:
        model = LegalFreeze
        fields = [
            'id', 'freeze_no', 'case_info', 'authority', 'legal_doc',
            'action_type', 'action_type_display',
            'effective_from', 'effective_to',
            'status', 'status_display', 'is_effective',
            'created_by', 'created_by_name',
            'lifted_by', 'lifted_by_name',
            'lift_doc', 'lift_reason', 'lifted_at',
            'items', 'created_at', 'updated_at'
        ]


class FreezeItemInputSerializer(serializers.Serializer):
    """冻结物资范围入参"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择冻结物资'})
    operations = serializers.ListField(
        child=serializers.CharField(), required=False,
    )
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )

    def validate_operations(self, value):
        if value is None:
            return None
        valid = dict(FreezeItem.OP_CHOICES).keys()
        for op in value:
            if op not in valid:
                raise serializers.ValidationError(f'不支持的限制操作：{op}')
        if not value:
            raise serializers.ValidationError('限制操作不能为空')
        # 去重并保持固定顺序
        ordered = [op for op in FreezeItem.ALL_OPERATIONS if op in value]
        return ordered


class LegalFreezeCreateSerializer(serializers.Serializer):
    """建立冻结入参"""
    freeze_no = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入冻结编号', 'blank': '冻结编号不能为空'
    })
    case_info = serializers.CharField(max_length=200, required=True, error_messages={
        'required': '请输入案件名称/编号', 'blank': '案件名称/编号不能为空'
    })
    authority = serializers.CharField(max_length=200, required=True, error_messages={
        'required': '请输入办案机关', 'blank': '办案机关不能为空'
    })
    legal_doc = serializers.CharField(max_length=100, required=False, allow_blank=True)
    action_type = serializers.ChoiceField(
        choices=LegalFreeze.ACTION_CHOICES, required=False
    )
    effective_from = serializers.DateTimeField(required=True, error_messages={
        'required': '请输入生效时间', 'invalid': '生效时间格式错误'
    })
    effective_to = serializers.DateTimeField(required=False, allow_null=True)
    items = FreezeItemInputSerializer(many=True, required=True, error_messages={
        'required': '请选择冻结物资范围'
    })

    def validate_freeze_no(self, value):
        value = value.strip()
        if LegalFreeze.objects.filter(freeze_no=value).exists():
            raise serializers.ValidationError('冻结编号已存在')
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('冻结物资范围不能为空')
        goods_ids = [item['goods'] for item in value]
        if len(set(goods_ids)) != len(goods_ids):
            raise serializers.ValidationError('同一物资在冻结范围内出现多次')
        exists_ids = set(Goods.objects.filter(
            pk__in=goods_ids
        ).values_list('pk', flat=True))
        missing = sorted(set(goods_ids) - exists_ids)
        if missing:
            raise serializers.ValidationError(f'物资不存在：{missing[0]}')
        return value

    def validate(self, data):
        effective_from = data.get('effective_from')
        effective_to = data.get('effective_to')
        if effective_from and effective_to and effective_to <= effective_from:
            raise serializers.ValidationError('到期时间必须晚于生效时间')
        return data


class LegalFreezeLiftSerializer(serializers.Serializer):
    """解除冻结入参"""
    lift_doc = serializers.CharField(max_length=100, required=False, allow_blank=True)
    lift_reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

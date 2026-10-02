"""
仓库管理视图
"""
import logging
import io
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from apps.core.response import success_response, error_response
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    LegalFreeze, StockTransfer, DestructionPlan, FreezeBlockLog,
    lock_goods_for_update, assert_not_frozen, active_freeze_items, FreezeViolation,
)
from . import freeze as freeze_service
from .serializers import (
    UnitSerializer, UnitCreateSerializer,
    CategorySerializer, CategoryCreateSerializer,
    VarietySerializer, VarietyCreateSerializer,
    GoodsSerializer, StockInSerializer, StockOutSerializer,
    WarningSerializer, ApprovalSerializer,
    LegalFreezeListSerializer, LegalFreezeCreateSerializer, FreezeLiftSerializer,
    StockOutApplySerializer, ApprovalActionSerializer,
    StockTransferSerializer, StockTransferCreateSerializer,
    DestructionPlanSerializer, DestructionPlanCreateSerializer,
    FreezeBlockLogSerializer,
)

logger = logging.getLogger('apps')


# ==================== 单位管理 ====================

class UnitListView(APIView):
    """单位列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = Unit.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        units = queryset[start:end]
        
        serializer = UnitSerializer(units, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建单位"""
        serializer = UnitCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        unit = Unit.objects.create(
            name=serializer.validated_data['name'],
            created_by=request.user
        )
        
        logger.info(f"User {request.user.username} created unit {unit.name}")
        
        return success_response(data=UnitSerializer(unit).data, message='创建成功')


class UnitDetailView(APIView):
    """单位详情视图"""
    permission_classes = [IsAuthenticated]
    
    def put(self, request, pk):
        """更新单位"""
        try:
            unit = Unit.objects.get(pk=pk)
        except Unit.DoesNotExist:
            return error_response(message='单位不存在', code=404)
        
        serializer = UnitCreateSerializer(data=request.data, context={'instance': unit})
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        unit.name = serializer.validated_data['name']
        unit.save()
        
        logger.info(f"User {request.user.username} updated unit {unit.name}")
        
        return success_response(data=UnitSerializer(unit).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除单位"""
        try:
            unit = Unit.objects.get(pk=pk)
        except Unit.DoesNotExist:
            return error_response(message='单位不存在', code=404)
        
        if unit.is_linked:
            return error_response(message='该单位已被关联，无法删除')
        
        name = unit.name
        unit.delete()
        
        logger.info(f"User {request.user.username} deleted unit {name}")
        
        return success_response(message='删除成功')


class UnitBatchDeleteView(APIView):
    """单位批量删除视图"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return error_response(message='请选择要删除的单位')
        
        # 只删除未关联的单位
        units = Unit.objects.filter(pk__in=ids)
        deleted_count = 0
        for unit in units:
            if not unit.is_linked:
                unit.delete()
                deleted_count += 1
        
        logger.info(f"User {request.user.username} batch deleted {deleted_count} units")
        
        return success_response(message=f'成功删除 {deleted_count} 个单位')


class UnitAllView(APIView):
    """获取所有单位（用于下拉选择）"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        units = Unit.objects.filter(is_active=True).order_by('name')
        serializer = UnitSerializer(units, many=True)
        return success_response(data=serializer.data)


# ==================== 品类管理 ====================

class CategoryListView(APIView):
    """品类列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = Category.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        categories = queryset[start:end]
        
        serializer = CategorySerializer(categories, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建品类"""
        serializer = CategoryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        unit = Unit.objects.get(pk=serializer.validated_data['unit'])
        category = Category.objects.create(
            name=serializer.validated_data['name'],
            unit=unit,
            created_by=request.user
        )
        
        logger.info(f"User {request.user.username} created category {category.name}")
        
        return success_response(data=CategorySerializer(category).data, message='创建成功')


class CategoryDetailView(APIView):
    """品类详情视图"""
    permission_classes = [IsAuthenticated]
    
    def put(self, request, pk):
        """更新品类"""
        try:
            category = Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            return error_response(message='品类不存在', code=404)
        
        serializer = CategoryCreateSerializer(data=request.data, context={'instance': category})
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        category.name = serializer.validated_data['name']
        category.unit = Unit.objects.get(pk=serializer.validated_data['unit'])
        category.save()
        
        logger.info(f"User {request.user.username} updated category {category.name}")
        
        return success_response(data=CategorySerializer(category).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除品类"""
        try:
            category = Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            return error_response(message='品类不存在', code=404)
        
        if category.is_linked:
            return error_response(message='该品类已被关联，无法删除')
        
        name = category.name
        category.delete()
        
        logger.info(f"User {request.user.username} deleted category {name}")
        
        return success_response(message='删除成功')


class CategoryBatchDeleteView(APIView):
    """品类批量删除视图"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return error_response(message='请选择要删除的品类')
        
        categories = Category.objects.filter(pk__in=ids)
        deleted_count = 0
        for category in categories:
            if not category.is_linked:
                category.delete()
                deleted_count += 1
        
        logger.info(f"User {request.user.username} batch deleted {deleted_count} categories")
        
        return success_response(message=f'成功删除 {deleted_count} 个品类')


class CategoryAllView(APIView):
    """获取所有品类（用于下拉选择）"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        categories = Category.objects.filter(is_active=True).order_by('name')
        serializer = CategorySerializer(categories, many=True)
        return success_response(data=serializer.data)


# ==================== 品种管理 ====================

class VarietyListView(APIView):
    """品种列表视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = Variety.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        varieties = queryset[start:end]
        
        serializer = VarietySerializer(varieties, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建品种"""
        serializer = VarietyCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0]
            if isinstance(first_error, list):
                first_error = first_error[0]
            return error_response(message=str(first_error))
        
        category = Category.objects.get(pk=serializer.validated_data['category'])
        variety = Variety.objects.create(
            name=serializer.validated_data['name'],
            category=category,
            created_by=request.user
        )
        
        logger.info(f"User {request.user.username} created variety {variety.name}")
        
        return success_response(data=VarietySerializer(variety).data, message='创建成功')


class VarietyDetailView(APIView):
    """品种详情视图"""
    permission_classes = [IsAuthenticated]
    
    def put(self, request, pk):
        """更新品种"""
        try:
            variety = Variety.objects.get(pk=pk)
        except Variety.DoesNotExist:
            return error_response(message='品种不存在', code=404)
        
        serializer = VarietyCreateSerializer(data=request.data, context={'instance': variety})
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0]
            if isinstance(first_error, list):
                first_error = first_error[0]
            return error_response(message=str(first_error))
        
        variety.name = serializer.validated_data['name']
        variety.category = Category.objects.get(pk=serializer.validated_data['category'])
        variety.save()
        
        logger.info(f"User {request.user.username} updated variety {variety.name}")
        
        return success_response(data=VarietySerializer(variety).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除品种"""
        try:
            variety = Variety.objects.get(pk=pk)
        except Variety.DoesNotExist:
            return error_response(message='品种不存在', code=404)
        
        if variety.is_in_stock:
            return error_response(message='该品种已入库，无法删除')
        
        name = variety.name
        variety.delete()
        
        logger.info(f"User {request.user.username} deleted variety {name}")
        
        return success_response(message='删除成功')


class VarietyBatchDeleteView(APIView):
    """品种批量删除视图"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return error_response(message='请选择要删除的品种')
        
        varieties = Variety.objects.filter(pk__in=ids)
        deleted_count = 0
        for variety in varieties:
            if not variety.is_in_stock:
                variety.delete()
                deleted_count += 1
        
        logger.info(f"User {request.user.username} batch deleted {deleted_count} varieties")
        
        return success_response(message=f'成功删除 {deleted_count} 个品种')


class VarietyTemplateView(APIView):
    """品种导入模板下载"""
    permission_classes = []  # 允许匿名访问，通过token参数验证
    
    def get(self, request):
        # 从URL参数获取token进行验证
        from apps.authentication.backends import decode_token
        from apps.authentication.models import User
        
        token = request.query_params.get('token')
        if not token:
            return error_response(message='缺少认证信息', code=401)
        
        payload = decode_token(token)
        if not payload:
            return error_response(message='认证信息无效或已过期', code=401)
        
        try:
            user = User.objects.get(pk=payload['user_id'])
        except User.DoesNotExist:
            return error_response(message='用户不存在', code=401)
        
        wb = Workbook()
        
        # 第一个表格 - 导入模板
        ws1 = wb.active
        ws1.title = '品种导入'
        
        # 设置表头样式
        header_font = Font(bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='4F46E5', end_color='4F46E5', fill_type='solid')
        header_alignment = Alignment(horizontal='center', vertical='center')
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        headers = ['品种', '品类', '单位']
        for col, header in enumerate(headers, 1):
            cell = ws1.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # 设置列宽
        ws1.column_dimensions['A'].width = 25
        ws1.column_dimensions['B'].width = 20
        ws1.column_dimensions['C'].width = 15
        
        # 第二个表格 - 品类参考
        ws2 = wb.create_sheet(title='品类参考')
        
        headers2 = ['品类', '单位']
        for col, header in enumerate(headers2, 1):
            cell = ws2.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        
        # 填充品类数据
        categories = Category.objects.filter(is_active=True).select_related('unit')
        for row, category in enumerate(categories, 2):
            ws2.cell(row=row, column=1, value=category.name).border = thin_border
            ws2.cell(row=row, column=2, value=category.unit.name).border = thin_border
        
        ws2.column_dimensions['A'].width = 20
        ws2.column_dimensions['B'].width = 15
        
        # 返回Excel文件
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=variety_import_template.xlsx'
        
        return response


class VarietyImportView(APIView):
    """品种导入视图"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        if 'file' not in request.FILES:
            return error_response(message='请上传文件')
        
        file = request.FILES['file']
        
        try:
            wb = load_workbook(file)
            ws = wb.active
        except Exception as e:
            return error_response(message='文件格式错误，请上传Excel文件')
        
        # 获取所有品类及其单位
        categories = {c.name: c for c in Category.objects.filter(is_active=True).select_related('unit')}
        
        can_import = []
        cannot_import = []
        
        for row in range(2, ws.max_row + 1):
            variety_name = ws.cell(row=row, column=1).value
            category_name = ws.cell(row=row, column=2).value
            unit_name = ws.cell(row=row, column=3).value
            
            if not variety_name:
                continue
            
            variety_name = str(variety_name).strip()
            category_name = str(category_name).strip() if category_name else ''
            unit_name = str(unit_name).strip() if unit_name else ''
            
            # 验证
            error_msg = None
            
            if not variety_name:
                error_msg = '品种名称不能为空'
            elif len(variety_name) > 20:
                error_msg = '品种名称最多20个字'
            elif not category_name:
                error_msg = '品类不能为空'
            elif category_name not in categories:
                error_msg = f'品类"{category_name}"不存在'
            elif not unit_name:
                error_msg = '单位不能为空'
            elif categories.get(category_name) and categories[category_name].unit.name != unit_name:
                error_msg = f'单位与品类不匹配，应为"{categories[category_name].unit.name}"'
            elif Variety.objects.filter(name=variety_name, category__name=category_name).exists():
                error_msg = '该品种已存在'
            
            if error_msg:
                cannot_import.append({
                    'row': row,
                    'variety': variety_name,
                    'category': category_name,
                    'unit': unit_name,
                    'reason': error_msg
                })
            else:
                can_import.append({
                    'row': row,
                    'variety': variety_name,
                    'category': category_name,
                    'unit': unit_name
                })
        
        # 如果是预览请求
        if request.data.get('preview') == 'true':
            return success_response(data={
                'can_import': can_import,
                'cannot_import': cannot_import,
                'can_import_count': len(can_import),
                'cannot_import_count': len(cannot_import)
            })
        
        # 执行导入
        imported_count = 0
        for item in can_import:
            category = categories[item['category']]
            Variety.objects.create(
                name=item['variety'],
                category=category,
                created_by=request.user
            )
            imported_count += 1
        
        logger.info(f"User {request.user.username} imported {imported_count} varieties")
        
        return success_response(
            data={
                'imported_count': imported_count,
                'failed_count': len(cannot_import),
                'failed_items': cannot_import
            },
            message=f'成功导入 {imported_count} 个品种'
        )


# ==================== 货物管理 ====================

class GoodsListView(APIView):
    """货物列表（携带当前冻结状态）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Goods.objects.select_related(
            'variety__category__unit').order_by('-created_at')

        keyword = request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(
                Q(name__icontains=keyword) | Q(code__icontains=keyword)
            )

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        goods = queryset[(page - 1) * page_size:page * page_size]
        serializer = GoodsSerializer(goods, many=True)

        # 一次性汇总本页货物当前的阻断依据，避免逐条查询
        blocked = {}
        items = active_freeze_items([g.id for g in goods]).select_related('freeze')
        for item in items:
            blocked.setdefault(item.goods_id, []).append(
                FreezeBasisBrief(item.freeze))

        data = serializer.data
        for row in data:
            row['freeze_blocks'] = blocked.get(row['id'], [])
            row['is_frozen'] = bool(blocked.get(row['id']))

        return success_response(data={
            'list': data, 'total': total, 'page': page, 'page_size': page_size,
        })


def FreezeBasisBrief(freeze):
    """查询结果中展示的当前阻断依据摘要。"""
    return {
        'freeze_id': freeze.id,
        'document_no': freeze.document_no,
        'case_no': freeze.case_no,
        'case_name': freeze.case_name,
        'authority': freeze.authority,
        'effective_at': freeze.effective_at,
        'expire_at': freeze.expire_at,
    }


# ==================== 入库记录 ====================

class StockInListView(APIView):
    """入库记录列表"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = StockIn.objects.select_related('goods', 'operator').order_by('-stock_in_time')
        goods_id = request.query_params.get('goods')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        records = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': StockInSerializer(records, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })


# ==================== 出库管理 ====================

class StockOutListView(APIView):
    """出库申请列表/提交申请。

    受理阶段即对已生效冻结做预检并拒绝，防止冻结物资进入审批流；
    审批和实际出库环节还会在持锁事务中再次强校验。
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = StockOut.objects.select_related('goods', 'operator').order_by('-created_at')
        goods_id = request.query_params.get('goods')
        status = request.query_params.get('status')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        if status:
            queryset = queryset.filter(status=status)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        records = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': StockOutSerializer(records, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = StockOutApplySerializer(data=request.data)
        if not serializer.is_valid():
            first_error = list(serializer.errors.values())[0][0]
            return error_response(message=str(first_error))
        vd = serializer.validated_data

        try:
            with transaction.atomic():
                lock_goods_for_update([vd['goods']])
                assert_not_frozen(
                    [vd['goods']], action='stock_out', operator=request.user,
                    detail=f'出库申请受理（{vd["receiver"]}）',
                )
                stock_out = StockOut.objects.create(
                    goods_id=vd['goods'], operator=request.user,
                    receiver=vd['receiver'], receiver_dept=vd.get('receiver_dept', ''),
                    quantity=vd['quantity'], remark=vd.get('remark', ''),
                )
        except FreezeViolation as exc:
            with transaction.atomic():
                exc.persist_logs()
            return error_response(message=str(exc), code=409)

        logger.info(f"User {request.user.username} applied stock-out {stock_out.id}")
        return success_response(data=StockOutSerializer(stock_out).data, message='申请已提交')


class StockOutDetailView(APIView):
    """出库审批/执行"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            stock_out = StockOut.objects.select_related('goods').get(pk=pk)
        except StockOut.DoesNotExist:
            return error_response(message='出库记录不存在', code=404)
        data = StockOutSerializer(stock_out).data
        data['freeze_blocks'] = [
            FreezeBasisBrief(item.freeze)
            for item in active_freeze_items([stock_out.goods_id]).select_related('freeze')
        ]
        return success_response(data=data)

    def post(self, request, pk, action):
        try:
            stock_out = StockOut.objects.get(pk=pk)
        except StockOut.DoesNotExist:
            return error_response(message='出库记录不存在', code=404)

        serializer = ApprovalActionSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=str(list(serializer.errors.values())[0][0]))
        remark = serializer.validated_data.get('remark', '')

        try:
            if action == 'approve':
                freeze_service.approve_stock_out(
                    stock_out, approver=request.user, remark=remark)
            elif action == 'reject':
                freeze_service.reject_stock_out(
                    stock_out, approver=request.user, remark=remark)
            elif action == 'complete':
                freeze_service.complete_stock_out(stock_out, operator=request.user)
            else:
                return error_response(message='不支持的操作', code=404)
        except FreezeViolation as exc:
            with transaction.atomic():
                exc.persist_logs()
            return error_response(message=str(exc), code=409)
        except ValueError as exc:
            return error_response(message=str(exc))

        stock_out.refresh_from_db()
        return success_response(data=StockOutSerializer(stock_out).data, message='操作成功')


# ==================== 转移管理 ====================

class StockTransferListView(APIView):
    """库间转移列表/申请"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = StockTransfer.objects.select_related('goods', 'operator').order_by('-created_at')
        goods_id = request.query_params.get('goods')
        status = request.query_params.get('status')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        if status:
            queryset = queryset.filter(status=status)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        records = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': StockTransferSerializer(records, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = StockTransferCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=str(list(serializer.errors.values())[0][0]))
        vd = serializer.validated_data
        try:
            with transaction.atomic():
                lock_goods_for_update([vd['goods']])
                assert_not_frozen(
                    [vd['goods']], action='transfer', operator=request.user,
                    detail='转移申请受理',
                )
                transfer = StockTransfer.objects.create(
                    goods_id=vd['goods'], operator=request.user,
                    quantity=vd['quantity'],
                    from_location=vd.get('from_location', ''),
                    to_location=vd['to_location'], remark=vd.get('remark', ''),
                )
        except FreezeViolation as exc:
            with transaction.atomic():
                exc.persist_logs()
            return error_response(message=str(exc), code=409)
        return success_response(data=StockTransferSerializer(transfer).data, message='申请已提交')


class StockTransferDetailView(APIView):
    """转移审批/执行"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        try:
            transfer = StockTransfer.objects.get(pk=pk)
        except StockTransfer.DoesNotExist:
            return error_response(message='转移记录不存在', code=404)
        try:
            if action == 'approve':
                freeze_service.approve_transfer(transfer, approver=request.user)
            elif action == 'complete':
                freeze_service.complete_transfer(transfer, operator=request.user)
            else:
                return error_response(message='不支持的操作', code=404)
        except FreezeViolation as exc:
            with transaction.atomic():
                exc.persist_logs()
            return error_response(message=str(exc), code=409)
        except ValueError as exc:
            return error_response(message=str(exc))
        transfer.refresh_from_db()
        return success_response(data=StockTransferSerializer(transfer).data, message='操作成功')


# ==================== 销毁管理 ====================

class DestructionPlanListView(APIView):
    """销毁计划列表/立项"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = DestructionPlan.objects.select_related('goods', 'operator').order_by('-created_at')
        goods_id = request.query_params.get('goods')
        status = request.query_params.get('status')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        if status:
            queryset = queryset.filter(status=status)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        records = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': DestructionPlanSerializer(records, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = DestructionPlanCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=str(list(serializer.errors.values())[0][0]))
        vd = serializer.validated_data
        try:
            with transaction.atomic():
                lock_goods_for_update([vd['goods']])
                assert_not_frozen(
                    [vd['goods']], action='destruction', operator=request.user,
                    detail='销毁计划立项',
                )
                plan = DestructionPlan.objects.create(
                    goods_id=vd['goods'], operator=request.user,
                    quantity=vd['quantity'],
                    reason=vd.get('reason', ''), remark=vd.get('remark', ''),
                )
        except FreezeViolation as exc:
            with transaction.atomic():
                exc.persist_logs()
            return error_response(message=str(exc), code=409)
        return success_response(data=DestructionPlanSerializer(plan).data, message='计划已提交')


class DestructionPlanDetailView(APIView):
    """销毁审批/执行"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        try:
            plan = DestructionPlan.objects.get(pk=pk)
        except DestructionPlan.DoesNotExist:
            return error_response(message='销毁计划不存在', code=404)
        try:
            if action == 'approve':
                freeze_service.approve_destruction(plan, approver=request.user)
            elif action == 'complete':
                freeze_service.complete_destruction(plan, operator=request.user)
            else:
                return error_response(message='不支持的操作', code=404)
        except FreezeViolation as exc:
            with transaction.atomic():
                exc.persist_logs()
            return error_response(message=str(exc), code=409)
        except ValueError as exc:
            return error_response(message=str(exc))
        plan.refresh_from_db()
        return success_response(data=DestructionPlanSerializer(plan).data, message='操作成功')


# ==================== 法律冻结 ====================

class LegalFreezeListView(APIView):
    """冻结列表/登记"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = LegalFreeze.objects.prefetch_related('items').order_by('-created_at')
        case_no = request.query_params.get('case_no')
        status = request.query_params.get('status')
        goods_id = request.query_params.get('goods')
        if case_no:
            queryset = queryset.filter(case_no__icontains=case_no)
        if status:
            queryset = queryset.filter(status=status)
        if goods_id:
            queryset = queryset.filter(items__goods_id=goods_id).distinct()

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        freezes = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': LegalFreezeListSerializer(freezes, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = LegalFreezeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_field = list(errors.values())[0]
            first_error = first_field[0] if isinstance(first_field, list) else first_field
            return error_response(message=str(first_error))
        try:
            freeze = freeze_service.register_freeze(
                created_by=request.user, **serializer.validated_data)
        except ValueError as exc:
            return error_response(message=str(exc))
        logger.info(
            f"User {request.user.username} registered freeze {freeze.id} "
            f"case {freeze.case_no}"
        )
        return success_response(
            data=LegalFreezeListSerializer(freeze).data, message='冻结已登记并生效')


class LegalFreezeDetailView(APIView):
    """冻结详情：含完整时间线和当前覆盖物资的阻断依据"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            freeze = LegalFreeze.objects.prefetch_related('items').get(pk=pk)
        except LegalFreeze.DoesNotExist:
            return error_response(message='冻结记录不存在', code=404)
        data = LegalFreezeListSerializer(freeze).data

        # 每个被覆盖货物当前的有效冻结（可能包含其他重叠冻结）
        goods_ids = list(freeze.items.values_list('goods_id', flat=True))
        blocks = {}
        for item in active_freeze_items(goods_ids).select_related('freeze'):
            blocks.setdefault(item.goods_id, []).append(FreezeBasisBrief(item.freeze))
        for item in data['items']:
            item['current_blocks'] = blocks.get(item['goods'], [])

        data['timeline'] = freeze_service.freeze_timeline(freeze)
        return success_response(data=data)


class LegalFreezeLiftView(APIView):
    """解除一份冻结（不影响其他重叠冻结）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            freeze = LegalFreeze.objects.get(pk=pk)
        except LegalFreeze.DoesNotExist:
            return error_response(message='冻结记录不存在', code=404)
        serializer = FreezeLiftSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=str(list(serializer.errors.values())[0][0]))
        try:
            freeze = freeze_service.lift_freeze(
                freeze, lifted_by=request.user,
                remark=serializer.validated_data.get('remark', ''))
        except ValueError as exc:
            return error_response(message=str(exc))
        logger.info(f"User {request.user.username} lifted freeze {freeze.id}")
        return success_response(
            data=LegalFreezeListSerializer(freeze).data, message='冻结已解除')


class FreezeBlockLogListView(APIView):
    """阻断记录查询"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = FreezeBlockLog.objects.select_related(
            'freeze', 'operator', 'goods').order_by('-created_at')
        goods_id = request.query_params.get('goods')
        freeze_id = request.query_params.get('freeze')
        action = request.query_params.get('action')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        if freeze_id:
            queryset = queryset.filter(freeze_id=freeze_id)
        if action:
            queryset = queryset.filter(action=action)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        records = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': FreezeBlockLogSerializer(records, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })


class GoodsFreezeStatusView(APIView):
    """货物冻结状态查询：当前阻断依据 + 完整时间线（承办人主入口）"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not Goods.objects.filter(pk=pk).exists():
            return error_response(message='货物不存在', code=404)
        blocks = [
            FreezeBasisBrief(item.freeze)
            for item in active_freeze_items([pk]).select_related('freeze')
        ]
        return success_response(data={
            'goods': pk,
            'is_frozen': bool(blocks),
            'current_blocks': blocks,
            'timeline': freeze_service.goods_timeline(pk),
        })


# ==================== 预警与审批记录 ====================

class WarningListView(APIView):
    """预警记录列表"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Warning.objects.select_related('goods').order_by('-created_at')
        goods_id = request.query_params.get('goods')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        records = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': WarningSerializer(records, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })


class ApprovalListView(APIView):
    """审批记录列表"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Approval.objects.select_related('stock_out', 'approver').order_by('-created_at')
        stock_out_id = request.query_params.get('stock_out')
        if stock_out_id:
            queryset = queryset.filter(stock_out_id=stock_out_id)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        records = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': ApprovalSerializer(records, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

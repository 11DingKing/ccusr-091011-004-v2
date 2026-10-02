"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    GoodsListView, GoodsFreezeStatusView,
    StockInListView, StockOutListView, StockOutDetailView,
    StockTransferListView, StockTransferDetailView,
    DestructionPlanListView, DestructionPlanDetailView,
    WarningListView, ApprovalListView,
    LegalFreezeListView, LegalFreezeDetailView, LegalFreezeLiftView,
    FreezeBlockLogListView,
)

urlpatterns = [
    # 单位管理
    path('units/', UnitListView.as_view(), name='unit-list'),
    path('units/all/', UnitAllView.as_view(), name='unit-all'),
    path('units/batch-delete/', UnitBatchDeleteView.as_view(), name='unit-batch-delete'),
    path('units/<int:pk>/', UnitDetailView.as_view(), name='unit-detail'),

    # 品类管理
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/all/', CategoryAllView.as_view(), name='category-all'),
    path('categories/batch-delete/', CategoryBatchDeleteView.as_view(), name='category-batch-delete'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),

    # 品种管理
    path('varieties/', VarietyListView.as_view(), name='variety-list'),
    path('varieties/batch-delete/', VarietyBatchDeleteView.as_view(), name='variety-batch-delete'),
    path('varieties/template/', VarietyTemplateView.as_view(), name='variety-template'),
    path('varieties/import/', VarietyImportView.as_view(), name='variety-import'),
    path('varieties/<int:pk>/', VarietyDetailView.as_view(), name='variety-detail'),

    # 货物管理
    path('goods/', GoodsListView.as_view(), name='goods-list'),
    path('goods/<int:pk>/freeze-status/', GoodsFreezeStatusView.as_view(),
         name='goods-freeze-status'),

    # 入库管理
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),

    # 出库管理
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),
    path('stock-out/<int:pk>/', StockOutDetailView.as_view(),
         name='stock-out-detail'),
    path('stock-out/<int:pk>/<str:action>/', StockOutDetailView.as_view(),
         name='stock-out-action'),

    # 库间转移
    path('transfers/', StockTransferListView.as_view(), name='transfer-list'),
    path('transfers/<int:pk>/<str:action>/', StockTransferDetailView.as_view(),
         name='transfer-action'),

    # 销毁计划
    path('destructions/', DestructionPlanListView.as_view(), name='destruction-list'),
    path('destructions/<int:pk>/<str:action>/', DestructionPlanDetailView.as_view(),
         name='destruction-action'),

    # 法律冻结
    path('freezes/', LegalFreezeListView.as_view(), name='freeze-list'),
    path('freezes/<int:pk>/', LegalFreezeDetailView.as_view(), name='freeze-detail'),
    path('freezes/<int:pk>/lift/', LegalFreezeLiftView.as_view(), name='freeze-lift'),
    path('freeze-blocks/', FreezeBlockLogListView.as_view(), name='freeze-block-list'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),
]

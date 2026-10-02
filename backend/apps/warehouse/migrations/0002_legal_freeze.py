# Generated for 法律冻结与转移/销毁业务

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('warehouse', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LegalFreeze',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('freeze_no', models.CharField(max_length=50, unique=True, verbose_name='冻结编号')),
                ('case_info', models.CharField(max_length=200, verbose_name='案件名称/编号')),
                ('authority', models.CharField(max_length=200, verbose_name='办案机关')),
                ('legal_doc', models.CharField(blank=True, max_length=100, verbose_name='法律文书号')),
                ('action_type', models.CharField(
                    choices=[('freeze', '冻结'), ('seal', '查封'), ('distrain', '扣押')],
                    default='freeze', max_length=20, verbose_name='冻结方式')),
                ('effective_from', models.DateTimeField(verbose_name='生效时间')),
                ('effective_to', models.DateTimeField(blank=True, null=True, verbose_name='到期时间')),
                ('status', models.CharField(
                    choices=[('active', '生效中'), ('lifted', '已解除')],
                    default='active', max_length=20, verbose_name='状态')),
                ('lift_doc', models.CharField(blank=True, max_length=100, verbose_name='解除文书号')),
                ('lift_reason', models.CharField(blank=True, max_length=200, verbose_name='解除事由')),
                ('lifted_at', models.DateTimeField(blank=True, null=True, verbose_name='解除时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='建立时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_freezes', to=settings.AUTH_USER_MODEL,
                    verbose_name='承办人')),
                ('lifted_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='lifted_freezes', to=settings.AUTH_USER_MODEL,
                    verbose_name='解除人')),
            ],
            options={
                'verbose_name': '法律冻结记录',
                'verbose_name_plural': '法律冻结记录',
                'db_table': 'wh_legal_freeze',
                'ordering': ['-effective_from', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TransferOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='转移数量')),
                ('target_location', models.CharField(max_length=100, verbose_name='目标存放位置')),
                ('target_keeper', models.CharField(blank=True, max_length=100, verbose_name='目标保管人')),
                ('status', models.CharField(
                    choices=[('pending', '待审批'), ('approved', '已通过'),
                             ('rejected', '已拒绝'), ('completed', '已完成')],
                    default='pending', max_length=20, verbose_name='状态')),
                ('transfer_time', models.DateTimeField(blank=True, null=True, verbose_name='转移时间')),
                ('remark', models.TextField(blank=True, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('goods', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transfer_orders', to='warehouse.goods', verbose_name='货物')),
                ('operator', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='transfer_operations', to=settings.AUTH_USER_MODEL,
                    verbose_name='操作人')),
            ],
            options={
                'verbose_name': '转移记录',
                'verbose_name_plural': '转移记录',
                'db_table': 'wh_transfer_order',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='DisposalPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='销毁数量')),
                ('reason', models.CharField(max_length=200, verbose_name='销毁事由')),
                ('planned_time', models.DateTimeField(blank=True, null=True, verbose_name='计划销毁时间')),
                ('status', models.CharField(
                    choices=[('pending', '待审批'), ('approved', '已通过'),
                             ('rejected', '已拒绝'), ('destroyed', '已销毁')],
                    default='pending', max_length=20, verbose_name='状态')),
                ('destroyed_time', models.DateTimeField(blank=True, null=True, verbose_name='实际销毁时间')),
                ('remark', models.TextField(blank=True, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('goods', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='disposal_plans', to='warehouse.goods', verbose_name='货物')),
                ('operator', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='disposal_operations', to=settings.AUTH_USER_MODEL,
                    verbose_name='操作人')),
            ],
            options={
                'verbose_name': '销毁计划',
                'verbose_name_plural': '销毁计划',
                'db_table': 'wh_disposal_plan',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='FreezeItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('restrict_operations', models.CharField(
                    default='stock_out,transfer,destroy', max_length=60, verbose_name='限制操作')),
                ('quantity', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='冻结数量')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='加入时间')),
                ('freeze', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items', to='warehouse.legalfreeze', verbose_name='冻结记录')),
                ('goods', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='freeze_items', to='warehouse.goods', verbose_name='货物')),
            ],
            options={
                'verbose_name': '冻结物资范围',
                'verbose_name_plural': '冻结物资范围',
                'db_table': 'wh_freeze_item',
                'unique_together': {('freeze', 'goods')},
            },
        ),
        migrations.CreateModel(
            name='FreezeEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(
                    choices=[('created', '冻结建立'), ('lifted', '冻结解除'), ('blocked', '操作拦截')],
                    max_length=20, verbose_name='事件类型')),
                ('operation', models.CharField(
                    blank=True, default='', max_length=20, verbose_name='被拦截操作')),
                ('detail', models.CharField(blank=True, max_length=500, verbose_name='说明')),
                ('occurred_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='发生时间')),
                ('freeze', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='events', to='warehouse.legalfreeze', verbose_name='冻结记录')),
                ('goods', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='freeze_events', to='warehouse.goods', verbose_name='关联物资')),
                ('operator', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='freeze_events', to=settings.AUTH_USER_MODEL, verbose_name='操作人')),
            ],
            options={
                'verbose_name': '冻结事件',
                'verbose_name_plural': '冻结事件',
                'db_table': 'wh_freeze_event',
                'ordering': ['occurred_at', 'id'],
            },
        ),
    ]

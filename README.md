# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```

## 法律冻结

办案机关下达冻结通知后，系统以冻结记录为准绳，按案件、物资范围和生效时间
阻断出库、转移、销毁，不再依赖人工备注。

### 数据模型

- `LegalFreeze`：冻结记录（冻结编号、案件、办案机关、法律文书号、生效/到期
  时间窗、状态、承办人/解除人）。
- `FreezeItem`：冻结物资范围明细，每件物资可单独配置限制操作
  （出库 `stock_out` / 转移 `transfer` / 销毁 `destroy`）与冻结数量。
- `FreezeEvent`：冻结生命周期事件流（建立 `created` / 解除 `lifted` /
  业务操作被拦截 `blocked`），构成完整时间线。

### 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/freezes/` | 建立冻结（含物资范围、限制操作、生效时间窗） |
| GET | `/api/freezes/` | 冻结列表（支持 `status`、`case_info`、`freeze_no`、`goods` 过滤） |
| GET | `/api/freezes/<id>/` | 冻结详情：当前阻断依据 + 完整时间线 |
| POST | `/api/freezes/<id>/lift/` | 解除本份冻结 |
| GET | `/api/goods/<id>/freeze-status/` | 物资视角：当前各操作阻断依据、全部冻结与时间线 |
| GET | `/api/goods/` | 物资列表带 `is_frozen` 与 `freeze_basis` |
| POST | `/api/stock-out/`、`/<id>/review/`、`/<id>/complete/` | 领用申请 / 审批 / 执行 |
| POST | `/api/transfers/`、`/<id>/review/`、`/<id>/complete/` | 转移申请 / 审批 / 执行 |
| POST | `/api/disposals/`、`/<id>/review/`、`/<id>/destroy/` | 销毁计划 / 审批 / 执行 |

被冻结阻断时接口返回 HTTP 409，`message` 中列明全部阻断依据（冻结编号、
案件、机关），并为每份生效冻结写入一条 `blocked` 时间线事件。

### 关键规则

- **逐份独立、允许重叠**：同一物资可被多份冻结同时限制；解除只翻转本份
  冻结，其他生效冻结继续阻断。
- **生效时间窗**：仅当状态为生效中、当前时间晚于生效时间且未到期时产生
  阻断；支持预先录入未来生效的冻结。
- **历史不溯及**：冻结前已完成的出库/转移/销毁及库存状态原样保留，冻结
  不回写历史。
- **全放行点复查**：申请提交、审批通过、实际执行三个环节均在数据库事务内
  先锁定物资行再读取冻结状态。冻结建立走同一把物资锁，因此"放行"与"补
  冻结"在同一物资上全序串行，不存在先放行后补冻结的空档。


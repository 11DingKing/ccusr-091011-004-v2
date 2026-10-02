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

调查部门下达冻结通知后，在系统中登记冻结决定；系统按案件、物资范围和生效时间
阻断出库、转移和销毁，并保留冻结前的历史状态。多份冻结可以重叠，各自独立解除。

### 数据模型

| 模型 | 说明 |
| --- | --- |
| `LegalFreeze` | 冻结决定（案号、法律文书编号、作出机关、生效/到期时间、状态） |
| `LegalFreezeItem` | 冻结范围在下达时展开的货物快照（货物随后调整品类不影响冻结范围） |
| `StockTransfer` | 库间转移记录（与出库、销毁同为受冻结约束的出账业务） |
| `DestructionPlan` | 销毁计划 |
| `FreezeBlockLog` | 每次阻断的依据留痕（业务回滚后独立事务写入，不随回滚丢失） |

### 并发安全

冻结登记与出库/转移/销毁在同一事务中对相关货物行加写锁后再做冻结判定
（生产库使用 `SELECT … FOR UPDATE`；SQLite 用同事务写锁等价串行化），
保证两类操作在数据库层面串行：不会出现业务先放行、冻结后补登的空档。
出库在**审批**和**实际出库**两个环节都持锁校验，冻结前已审批通过的申请
也无法在冻结生效后出库。

### 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/freezes/` | 登记冻结（`scope_type` 取 `goods`/`variety`/`category`，`scope_targets` 为 ID 列表；可补录 `effective_at`） |
| GET | `/api/freezes/?case_no=&status=&goods=` | 冻结列表 |
| GET | `/api/freezes/{id}/` | 冻结详情：范围货物当前的全部阻断依据（含重叠冻结）+ 完整时间线 |
| POST | `/api/freezes/{id}/lift/` | 解除本份冻结（不影响其他重叠冻结） |
| GET | `/api/goods/{id}/freeze-status/` | 承办人入口：货物当前阻断依据 + 完整时间线（入库/申请/审批/转移/销毁/冻结/阻断） |
| POST/GET | `/api/stock-out/` | 出库申请受理阶段即预检冻结，冻结时返回 409 |
| POST | `/api/stock-out/{id}/approve/`、`/reject/`、`/complete/` | 出库审批与执行 |
| POST/GET | `/api/transfers/`、`/api/destructions/` | 转移、销毁申请（同样受冻结约束） |
| GET | `/api/freeze-blocks/?goods=&freeze=&action=` | 阻断记录查询 |

被冻结阻断时返回 `409`，响应消息给出文书编号与案号；每次阻断均写入
`FreezeBlockLog`，可在货物/冻结时间线上查看。

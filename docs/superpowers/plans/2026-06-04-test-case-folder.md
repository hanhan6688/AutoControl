# 测试用例文档层级 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AutoGLM 测试计划与测试用例之间增加"测试用例文档"层级，使测试计划=版本，文档=功能模块，用例=具体条目。

**Architecture:** 后端新增 TestCaseFolder 模型作为 TestPlanProject 和 ImportedTestCase 的中间层。前端在 TestCaseManager.vue 右侧内容区上方增加文档列表卡片，下方用例表格增加"所属文档"列和筛选功能。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (后端), Vue 3 + Element Plus (前端), SQLite (数据库)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `backend/app/models/test_case_folder.py` | TestCaseFolder 模型定义 |
| Modify | `backend/app/models/__init__.py` | 导出 TestCaseFolder |
| Modify | `backend/app/models.py` | ImportedTestCase 增加 folder_id, TestPlanProject 增加 folders 关系 |
| Create | `backend/app/schemas/test_case_folder.py` | 文档相关 schema |
| Modify | `backend/app/schemas.py` | 用例 schema 增加 folder_id, 计划 schema 增加 folders |
| Create | `backend/app/routers/folders.py` | 文档 CRUD API |
| Modify | `backend/app/routers/test_plans.py` | 修改现有接口返回 folders 信息 |
| Create | `backend/alembic/versions/xxxx_add_test_case_folder.py` | 数据库迁移 |
| Modify | `frontend/src/api.ts` | 新增文档相关 API 函数 |
| Modify | `frontend/src/views/TestCaseManager.vue` | UI 改造 |

---

### Task 1: 后端 - 新增 TestCaseFolder 模型

**Files:**
- Create: `backend/app/models/test_case_folder.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models.py`

- [ ] **Step 1: 创建 TestCaseFolder 模型文件**

创建 `backend/app/models/test_case_folder.py`:

```python
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class TestCaseFolder(Base):
    """测试用例文档 - 测试计划与用例之间的中间层级

    一个测试计划包含多个文档，每个文档对应一个功能/需求。
    """
    __tablename__ = "test_case_folder"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("test_plan_project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, comment="文档名称，如'登录功能'")
    requirement_summary = Column(Text, nullable=True, comment="需求摘要/功能描述")
    source_type = Column(String(64), nullable=True, comment="来源: manual/ai_generated/import_grouped")
    source_filename = Column(String(255), nullable=True, comment="来源文件名")
    sequence = Column(Integer, default=0, comment="排序序号")
    total_cases = Column(Integer, default=0, comment="用例数量")
    created_at = Column(DateTime, default=datetime.now)

    # 关系
    plan = relationship("TestPlanProject", back_populates="folders")
    cases = relationship("ImportedTestCase", back_populates="folder", cascade="all, delete-orphan")
```

- [ ] **Step 2: 修改 models/__init__.py 导出新模型**

在 `backend/app/models/__init__.py` 中增加:

```python
from .test_case_folder import TestCaseFolder
```

- [ ] **Step 3: 修改 models.py - ImportedTestCase 增加 folder_id**

在 `backend/app/models.py` 的 `ImportedTestCase` 类中:
- 新增字段: `folder_id = Column(Integer, ForeignKey("test_case_folder.id", ondelete="SET NULL"), nullable=True, index=True)`
- 新增关系: `folder = relationship("TestCaseFolder", back_populates="cases")`

- [ ] **Step 4: 修改 models.py - TestPlanProject 增加 folders 关系**

在 `backend/app/models.py` 的 `TestPlanProject` 类中:
- 新增关系: `folders = relationship("TestCaseFolder", back_populates="plan", cascade="all, delete-orphan", order_by="TestCaseFolder.sequence")`

- [ ] **Step 5: 验证模型无语法错误**

Run: `cd D:/Mobile-AI-TestOps/backend && python -c "from app.models import TestCaseFolder, ImportedTestCase, TestPlanProject; print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/
git commit -m "feat: add TestCaseFolder model for document-level hierarchy"
```

---

### Task 2: 后端 - Schemas 变更

**Files:**
- Create: `backend/app/schemas/test_case_folder.py`
- Modify: `backend/app/schemas.py`

- [ ] **Step 1: 创建文档相关 Schema**

创建 `backend/app/schemas/test_case_folder.py`:

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TestCaseFolderCreate(BaseModel):
    """创建测试用例文档"""
    name: str
    requirement_summary: Optional[str] = None
    source_type: Optional[str] = "manual"
    source_filename: Optional[str] = None


class TestCaseFolderUpdate(BaseModel):
    """更新测试用例文档"""
    name: Optional[str] = None
    requirement_summary: Optional[str] = None


class TestCaseFolderResponse(BaseModel):
    """测试用例文档响应"""
    id: int
    plan_id: int
    name: str
    requirement_summary: Optional[str] = None
    source_type: Optional[str] = None
    source_filename: Optional[str] = None
    sequence: int
    total_cases: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TestCaseFolderWithCases(TestCaseFolderResponse):
    """带用例列表的文档响应"""
    cases: list = []  # list[ImportedTestCaseResponse] 避免循环引用用 list
```

- [ ] **Step 2: 修改 schemas.py - ImportedTestCaseResponse 增加 folder_id**

在 `backend/app/schemas.py` 的 `ImportedTestCaseResponse` 中增加字段:
```python
folder_id: Optional[int] = None
folder_name: Optional[str] = None
```

- [ ] **Step 3: 修改 schemas.py - TestPlanProjectResponse 增加 folders**

在 `backend/app/schemas.py` 的 `TestPlanProjectResponse` (或对应的详细响应schema) 中增加字段:
```python
folders: list[TestCaseFolderResponse] = []
```

在文件顶部增加导入:
```python
from .test_case_folder import TestCaseFolderResponse, TestCaseFolderCreate, TestCaseFolderUpdate, TestCaseFolderWithCases
```

- [ ] **Step 4: 验证 Schema 无语法错误**

Run: `cd D:/Mobile-AI-TestOps/backend && python -c "from app.schemas import TestCaseFolderResponse, ImportedTestCaseResponse; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/
git commit -m "feat: add TestCaseFolder schemas and extend existing schemas"
```

---

### Task 3: 后端 - 文档 CRUD API

**Files:**
- Create: `backend/app/routers/folders.py`
- Modify: `backend/app/main.py` (注册路由)

- [ ] **Step 1: 创建 folders 路由**

创建 `backend/app/routers/folders.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models import TestCaseFolder, TestPlanProject, ImportedTestCase
from ..schemas.test_case_folder import (
    TestCaseFolderCreate,
    TestCaseFolderUpdate,
    TestCaseFolderResponse,
)

router = APIRouter(prefix="/api/folders", tags=["test-case-folders"])


@router.post("/plans/{plan_id}/folders", response_model=TestCaseFolderResponse)
def create_folder(plan_id: int, folder_data: TestCaseFolderCreate, db: Session = Depends(get_db)):
    """在指定测试计划下创建文档"""
    plan = db.query(TestPlanProject).filter(TestPlanProject.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    # 获取当前最大 sequence
    max_seq = db.query(TestCaseFolder).filter(
        TestCaseFolder.plan_id == plan_id
    ).count()

    folder = TestCaseFolder(
        plan_id=plan_id,
        name=folder_data.name,
        requirement_summary=folder_data.requirement_summary,
        source_type=folder_data.source_type or "manual",
        source_filename=folder_data.source_filename,
        sequence=max_seq,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.get("/plans/{plan_id}/folders", response_model=List[TestCaseFolderResponse])
def list_folders(plan_id: int, db: Session = Depends(get_db)):
    """获取测试计划下的所有文档"""
    folders = db.query(TestCaseFolder).filter(
        TestCaseFolder.plan_id == plan_id
    ).order_by(TestCaseFolder.sequence).all()
    return folders


@router.put("/folders/{folder_id}", response_model=TestCaseFolderResponse)
def update_folder(folder_id: int, folder_data: TestCaseFolderUpdate, db: Session = Depends(get_db)):
    """更新文档"""
    folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="文档不存在")

    if folder_data.name is not None:
        folder.name = folder_data.name
    if folder_data.requirement_summary is not None:
        folder.requirement_summary = folder_data.requirement_summary

    db.commit()
    db.refresh(folder)
    return folder


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, db: Session = Depends(get_db)):
    """删除文档（连同其下所有用例）"""
    folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 更新计划的用例计数
    plan = db.query(TestPlanProject).filter(TestPlanProject.id == folder.plan_id).first()
    if plan and plan.total_cases is not None:
        plan.total_cases = max(0, (plan.total_cases or 0) - (folder.total_cases or 0))

    db.delete(folder)
    db.commit()
    return {"message": "删除成功"}


@router.post("/cases/batch-move")
def batch_move_cases(data: dict, db: Session = Depends(get_db)):
    """批量移动用例到其他文档"""
    case_ids = data.get("case_ids", [])
    target_folder_id = data.get("target_folder_id")

    if not case_ids or target_folder_id is None:
        raise HTTPException(status_code=400, detail="参数不完整")

    target_folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == target_folder_id).first()
    if not target_folder:
        raise HTTPException(status_code=404, detail="目标文档不存在")

    # 获取要移动的用例
    cases = db.query(ImportedTestCase).filter(ImportedTestCase.id.in_(case_ids)).all()

    # 记录源文档ID，用于更新计数
    source_folder_ids = set()
    for case in cases:
        if case.folder_id and case.folder_id != target_folder_id:
            source_folder_ids.add(case.folder_id)
        case.folder_id = target_folder_id

    # 更新源文档的用例计数
    for src_id in source_folder_ids:
        src_folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == src_id).first()
        if src_folder:
            src_folder.total_cases = db.query(ImportedTestCase).filter(
                ImportedTestCase.folder_id == src_id
            ).count()

    # 更新目标文档的用例计数
    target_folder.total_cases = db.query(ImportedTestCase).filter(
        ImportedTestCase.folder_id == target_folder_id
    ).count()

    db.commit()
    return {"message": f"已移动 {len(cases)} 条用例"}
```

- [ ] **Step 2: 注册路由到 main.py**

在 `backend/app/main.py` 中增加:

```python
from .routers.folders import router as folders_router
app.include_router(folders_router)
```

- [ ] **Step 3: 验证路由注册成功**

Run: `cd D:/Mobile-AI-TestOps/backend && python -c "from app.main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'folder' in r])"`
Expected: 包含 folders 相关路由

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/folders.py backend/app/main.py
git commit -m "feat: add TestCaseFolder CRUD API routes"
```

---

### Task 4: 后端 - 修改现有接口返回 folders 信息

**Files:**
- Modify: `backend/app/routers/test_plans.py`

- [ ] **Step 1: 修改获取测试计划详情接口**

在 `test_plans.py` 中，找到返回测试计划详情的接口（通常是 `GET /api/test-plans/{plan_id}`），确保:
1. 查询时 joinedload folders
2. 返回的数据包含 folders 列表
3. 每个 folder 包含 total_cases
4. 用例列表包含 folder_id 和 folder_name

关键修改点:
```python
from sqlalchemy.orm import joinedload

# 在查询计划时 eager load folders
plan = db.query(TestPlanProject).options(
    joinedload(TestPlanProject.folders)
).filter(TestPlanProject.id == plan_id).first()

# 用例查询时加载 folder 信息
cases = db.query(ImportedTestCase).filter(
    ImportedTestCase.plan_id == plan_id
).all()

# 在返回数据中补充 folder_name
for case in cases:
    if case.folder:
        case.folder_name = case.folder.name
```

- [ ] **Step 2: 修改导入接口 - 支持按字段分组创建文档**

在导入测试用例的逻辑中（`test_plan_import_service.py` 或 `test_plans.py` 中的导入路由），修改:
1. 导入时检查是否有 `system_name` 或 `module` 字段
2. 如果有，按该字段分组自动创建 TestCaseFolder
3. 每个分组创建一个文档，名称取自分组字段值
4. 用例导入时自动关联到对应文档
5. 如果没有分组字段，创建一个"默认文档"

- [ ] **Step 3: 修改 AI 生成接口 - 自动创建文档**

在 AI 生成用例的逻辑中，修改:
1. 生成完成后，如果需求中包含多个功能模块，按模块创建多个文档
2. 用例自动归入对应文档
3. 如果只有一个功能，创建一个以功能命名的文档

- [ ] **Step 4: 验证接口返回正确数据**

Run: `cd D:/Mobile-AI-TestOps/backend && python -c "from app.routers.test_plans import router; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/test_plans.py backend/app/services/
git commit -m "feat: extend test plan APIs to return folder info and auto-create folders on import/generate"
```

---

### Task 5: 后端 - 数据库迁移

**Files:**
- Create: `backend/alembic/versions/xxxx_add_test_case_folder.py`

- [ ] **Step 1: 生成迁移文件**

Run: `cd D:/Mobile-AI-TestOps/backend && alembic revision --autogenerate -m "add test_case_folder table"`

- [ ] **Step 2: 检查生成的迁移文件**

打开生成的迁移文件，确认:
1. 创建 `test_case_folder` 表，包含所有字段
2. 在 `imported_test_case` 表增加 `folder_id` 列（nullable=True）
3. 创建外键约束

- [ ] **Step 3: 添加数据迁移逻辑**

在迁移文件的 `upgrade()` 函数中，创建表之后增加:

```python
from sqlalchemy import text

# 为现有测试计划创建默认文档
conn = op.get_bind()
plans = conn.execute(text("SELECT id, project_name FROM test_plan_project")).fetchall()

for plan in plans:
    # 创建默认文档
    result = conn.execute(text(
        "INSERT INTO test_case_folder (plan_id, name, source_type, sequence, total_cases, created_at) "
        "VALUES (:plan_id, '默认文档', 'import_grouped', 0, 0, datetime('now'))"
    ), {"plan_id": plan.id})
    folder_id = result.lastrowid

    # 将该计划下所有无 folder_id 的用例归入默认文档
    conn.execute(text(
        "UPDATE imported_test_case SET folder_id = :folder_id WHERE plan_id = :plan_id"
    ), {"folder_id": folder_id, "plan_id": plan.id})

    # 更新文档的用例计数
    count = conn.execute(text(
        "SELECT COUNT(*) FROM imported_test_case WHERE folder_id = :folder_id"
    ), {"folder_id": folder_id}).scalar()
    conn.execute(text(
        "UPDATE test_case_folder SET total_cases = :count WHERE id = :folder_id"
    ), {"count": count, "folder_id": folder_id})
```

- [ ] **Step 4: 执行迁移**

Run: `cd D:/Mobile-AI-TestOps/backend && alembic upgrade head`
Expected: 运行成功

- [ ] **Step 5: 验证数据库结构**

Run: `cd D:/Mobile-AI-TestOps/backend && python -c "from app.database import engine; from sqlalchemy import inspect; insp = inspect(engine); print('test_case_folder columns:', [c['name'] for c in insp.get_columns('test_case_folder')]); print('imported_test_case has folder_id:', 'folder_id' in [c['name'] for c in insp.get_columns('imported_test_case')])"`
Expected: test_case_folder 表存在且有正确列，imported_test_case 包含 folder_id

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/
git commit -m "feat: add alembic migration for test_case_folder with data migration"
```

---

### Task 6: 前端 - API 类型和接口函数

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: 新增 TestCaseFolder 类型定义**

在 `frontend/src/api.ts` 中增加:

```typescript
// 测试用例文档
export interface TestCaseFolder {
  id: number
  plan_id: number
  name: string
  requirement_summary?: string
  source_type?: string
  source_filename?: string
  sequence: number
  total_cases: number
  created_at?: string
}

export interface TestCaseFolderCreate {
  name: string
  requirement_summary?: string
  source_type?: string
  source_filename?: string
}

export interface TestCaseFolderUpdate {
  name?: string
  requirement_summary?: string
}
```

- [ ] **Step 2: 修改 ImportedTestCase 类型**

在 `ImportedTestCase` 接口中增加:
```typescript
folder_id?: number
folder_name?: string
```

- [ ] **Step 3: 修改 TestPlanProject 类型**

在 `TestPlanProject` 接口中增加:
```typescript
folders?: TestCaseFolder[]
```

- [ ] **Step 4: 新增 API 函数**

```typescript
// 文档管理
export async function createFolder(planId: number, data: TestCaseFolderCreate): Promise<TestCaseFolder> {
  const res = await fetch(`/api/folders/plans/${planId}/folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('创建文档失败')
  return res.json()
}

export async function listFolders(planId: number): Promise<TestCaseFolder[]> {
  const res = await fetch(`/api/folders/plans/${planId}/folders`)
  if (!res.ok) throw new Error('获取文档列表失败')
  return res.json()
}

export async function updateFolder(folderId: number, data: TestCaseFolderUpdate): Promise<TestCaseFolder> {
  const res = await fetch(`/api/folders/folders/${folderId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('更新文档失败')
  return res.json()
}

export async function deleteFolder(folderId: number): Promise<void> {
  const res = await fetch(`/api/folders/folders/${folderId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('删除文档失败')
}

export async function batchMoveCases(caseIds: number[], targetFolderId: number): Promise<void> {
  const res = await fetch('/api/folders/cases/batch-move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ case_ids: caseIds, target_folder_id: targetFolderId }),
  })
  if (!res.ok) throw new Error('移动用例失败')
}
```

- [ ] **Step 5: 验证 TypeScript 编译**

Run: `cd D:/Mobile-AI-TestOps/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: 无新增错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: add TestCaseFolder types and API functions"
```

---

### Task 7: 前端 - UI 改造 TestCaseManager.vue

**Files:**
- Modify: `frontend/src/views/TestCaseManager.vue`

- [ ] **Step 1: 新增文档相关响应式状态**

在 `<script setup>` 中增加:

```typescript
import { TestCaseFolder, createFolder, listFolders, updateFolder, deleteFolder, batchMoveCases } from '../api'

// 文档相关状态
const folders = ref<TestCaseFolder[]>([])
const selectedFolderId = ref<number | null>(null)  // null = 显示全部
const showCreateFolderDialog = ref(false)
const newFolderName = ref('')
const newFolderSummary = ref('')
const showMoveDialog = ref(false)
const moveTargetFolderId = ref<number | null>(null)
```

- [ ] **Step 2: 新增文档加载和操作方法**

```typescript
// 加载文档列表
async function loadFolders() {
  if (!selectedPlan.value) return
  try {
    folders.value = await listFolders(selectedPlan.value.id)
  } catch (e) {
    ElMessage.error('加载文档列表失败')
  }
}

// 创建文档
async function handleCreateFolder() {
  if (!selectedPlan.value || !newFolderName.value.trim()) return
  try {
    await createFolder(selectedPlan.value.id, {
      name: newFolderName.value.trim(),
      requirement_summary: newFolderSummary.value.trim() || undefined,
    })
    ElMessage.success('创建文档成功')
    showCreateFolderDialog.value = false
    newFolderName.value = ''
    newFolderSummary.value = ''
    await loadFolders()
  } catch (e) {
    ElMessage.error('创建文档失败')
  }
}

// 删除文档
async function handleDeleteFolder(folder: TestCaseFolder) {
  try {
    await ElMessageBox.confirm(
      `确定要删除文档"${folder.name}"及其下所有用例吗？`,
      '确认删除',
      { type: 'warning' }
    )
    await deleteFolder(folder.id)
    ElMessage.success('删除成功')
    if (selectedFolderId.value === folder.id) {
      selectedFolderId.value = null
    }
    await loadFolders()
    await loadTestCases()  // 刷新用例列表
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// 选择文档筛选
function selectFolder(folderId: number | null) {
  selectedFolderId.value = folderId
}

// 批量移动用例
async function handleBatchMove() {
  if (!moveTargetFolderId.value || selectedCaseIds.value.length === 0) return
  try {
    await batchMoveCases(selectedCaseIds.value, moveTargetFolderId.value)
    ElMessage.success('移动成功')
    showMoveDialog.value = false
    await loadFolders()
    await loadTestCases()
  } catch (e) {
    ElMessage.error('移动用例失败')
  }
}
```

- [ ] **Step 3: 修改 loadTestCases - 加载文档信息**

在 `loadTestCases()` 函数中，加载用例后同步加载文档:
```typescript
async function loadTestCases() {
  // ... 现有加载逻辑保持不变 ...
  // 加载完成后也加载文档
  await loadFolders()
}
```

- [ ] **Step 4: 修改用例表格 computed - 按文档筛选**

```typescript
const filteredTestCases = computed(() => {
  let cases = testCases.value
  if (selectedFolderId.value !== null) {
    cases = cases.filter(c => c.folder_id === selectedFolderId.value)
  }
  return cases
})
```

将模板中引用 `testCases` 的表格改为使用 `filteredTestCases`。

- [ ] **Step 5: 在模板中添加文档列表区域**

在右侧内容区，测试计划标题和用例表格之间，增加文档列表:

```html
<!-- 文档列表 -->
<div class="folder-section" v-if="selectedPlan">
  <div class="folder-header">
    <span class="folder-title">测试用例文档</span>
    <el-button size="small" type="primary" @click="showCreateFolderDialog = true">
      <el-icon><Plus /></el-icon> 新建文档
    </el-button>
  </div>
  <div class="folder-list">
    <div
      class="folder-card"
      :class="{ active: selectedFolderId === null }"
      @click="selectFolder(null)"
    >
      <span class="folder-card-name">全部</span>
      <span class="folder-card-count">{{ testCases.length }}条</span>
    </div>
    <div
      v-for="folder in folders"
      :key="folder.id"
      class="folder-card"
      :class="{ active: selectedFolderId === folder.id }"
      @click="selectFolder(folder.id)"
    >
      <span class="folder-card-name">{{ folder.name }}</span>
      <span class="folder-card-count">{{ folder.total_cases }}条</span>
      <el-tag v-if="folder.source_type === 'ai_generated'" size="small" type="success">AI</el-tag>
      <el-dropdown trigger="click" @command="(cmd: string) => {
        if (cmd === 'delete') handleDeleteFolder(folder)
      }">
        <el-icon class="folder-card-more"><MoreFilled /></el-icon>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="delete">删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</div>
```

- [ ] **Step 6: 在用例表格中增加"所属文档"列**

在用例表格的 `<el-table-column>` 中增加:

```html
<el-table-column prop="folder_name" label="所属文档" width="140">
  <template #default="{ row }">
    <el-tag size="small" v-if="row.folder_name">{{ row.folder_name }}</el-tag>
    <span v-else class="text-gray">未分类</span>
  </template>
</el-table-column>
```

- [ ] **Step 7: 新建文档对话框**

在模板末尾增加:

```html
<!-- 新建文档对话框 -->
<el-dialog v-model="showCreateFolderDialog" title="新建测试用例文档" width="480px">
  <el-form label-width="100px">
    <el-form-item label="文档名称">
      <el-input v-model="newFolderName" placeholder="如：登录功能" />
    </el-form-item>
    <el-form-item label="需求摘要">
      <el-input v-model="newFolderSummary" type="textarea" :rows="3" placeholder="可选，描述该文档对应的功能需求" />
    </el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="showCreateFolderDialog = false">取消</el-button>
    <el-button type="primary" @click="handleCreateFolder" :disabled="!newFolderName.trim()">确定</el-button>
  </template>
</el-dialog>

<!-- 批量移动对话框 -->
<el-dialog v-model="showMoveDialog" title="移动用例到文档" width="480px">
  <el-form label-width="100px">
    <el-form-item label="目标文档">
      <el-select v-model="moveTargetFolderId" placeholder="选择目标文档" style="width: 100%">
        <el-option
          v-for="folder in folders"
          :key="folder.id"
          :label="folder.name"
          :value="folder.id"
        />
      </el-select>
    </el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="showMoveDialog = false">取消</el-button>
    <el-button type="primary" @click="handleBatchMove" :disabled="!moveTargetFolderId">确定</el-button>
  </template>
</el-dialog>
```

- [ ] **Step 8: 添加文档区域样式**

```css
.folder-section {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--el-bg-color);
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}

.folder-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.folder-title {
  font-weight: 600;
  font-size: 14px;
}

.folder-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.folder-card {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 13px;
}

.folder-card:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.folder-card.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.folder-card-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-card-count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.folder-card-more {
  cursor: pointer;
  color: var(--el-text-color-secondary);
}

.folder-card-more:hover {
  color: var(--el-color-primary);
}
```

- [ ] **Step 9: 在批量操作按钮区增加"移动到文档"按钮**

在现有的批量操作区域增加:
```html
<el-button size="small" @click="showMoveDialog = true" :disabled="selectedCaseIds.length === 0">
  移动到文档
</el-button>
```

- [ ] **Step 10: 验证前端编译**

Run: `cd D:/Mobile-AI-TestOps/frontend && npm run build 2>&1 | tail -5`
Expected: 构建成功

- [ ] **Step 11: Commit**

```bash
git add frontend/src/views/TestCaseManager.vue
git commit -m "feat: add folder list UI and case folder filtering to TestCaseManager"
```

---

### Task 8: 修改后端导入和AI生成逻辑 - 自动创建文档

**Files:**
- Modify: `backend/app/services/test_plan_import_service.py`
- Modify: `backend/app/services/requirement_analysis_service.py`

- [ ] **Step 1: 修改导入服务 - 按字段分组创建文档**

在 `test_plan_import_service.py` 的导入逻辑中:
1. 导入用例时，检查数据中是否有 `system_name` / `module` / `功能模块` 字段
2. 如果有分组字段，按字段值分组:
   - 每个分组值创建一个 TestCaseFolder（name=分组值, source_type="import_grouped"）
   - 用例的 folder_id 设为对应文档
3. 如果没有分组字段，创建一个"默认文档"

- [ ] **Step 2: 修改 AI 生成服务 - 按功能创建文档**

在 `requirement_analysis_service.py` 的生成逻辑中:
1. 生成用例时，如果需求包含多个功能模块:
   - 每个功能模块创建一个 TestCaseFolder（name=功能名, source_type="ai_generated"）
   - 用例的 folder_id 设为对应文档
2. 如果只涉及一个功能，创建一个以功能命名的文档

- [ ] **Step 3: 验证导入功能**

手动测试: 导入包含"功能模块"列的 Excel 文件，确认自动创建多个文档。

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/
git commit -m "feat: auto-create folders on import and AI generation"
```

---

### Task 9: 端到端测试

**Files:** 无新文件

- [ ] **Step 1: 启动后端服务**

Run: `cd D:/Mobile-AI-TestOps/backend && python -m uvicorn app.main:app --reload --port 8000`

- [ ] **Step 2: 启动前端服务**

Run: `cd D:/Mobile-AI-TestOps/frontend && npm run dev`

- [ ] **Step 3: 验证文档 CRUD**

1. 打开页面，选择一个测试计划
2. 确认自动创建了"默认文档"
3. 点击"+新建文档"，创建新文档
4. 确认文档列表显示正确
5. 删除文档，确认删除成功

- [ ] **Step 4: 验证用例筛选**

1. 点击"全部"，确认显示所有用例
2. 点击某个文档，确认只显示该文档下的用例
3. 确认用例表格"所属文档"列显示正确

- [ ] **Step 5: 验证批量移动**

1. 选择多条用例
2. 点击"移动到文档"
3. 选择目标文档，确认移动成功
4. 验证文档的用例计数更新

- [ ] **Step 6: 验证导入自动分组**

1. 导入包含"功能模块"列的 Excel
2. 确认自动创建了对应文档
3. 确认用例归入正确文档

- [ ] **Step 7: Final Commit**

```bash
git add -A
git commit -m "feat: complete test case folder hierarchy implementation"
```

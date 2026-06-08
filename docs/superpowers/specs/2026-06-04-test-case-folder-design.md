# 测试用例文档层级设计

## 背景

当前 AutoGLM 管理页面的数据层级为：测试计划 → 测试用例（扁平列表）。
用户需要增加中间层级"测试用例文档"，使得：

- **测试计划** = 一个版本（如 "v2.5.0 回归测试"）
- **测试用例文档** = 按功能/需求划分（如 "登录功能"、"搜索功能"）
- **测试用例** = 具体用例条目

## 数据模型

### 新增模型：TestCaseFolder（测试用例文档）

| 字段 | 类型 | 说明 |
|-----|------|-----|
| id | int | 主键 |
| plan_id | int | 外键 → TestPlanProject |
| name | String(255) | 文档名称（如"登录功能"） |
| requirement_summary | Text | 需求摘要/功能描述 |
| source_type | String(64) | 来源：manual / ai_generated / import_grouped |
| source_filename | String(255) | 来源文件名 |
| sequence | int | 排序序号 |
| total_cases | int | 用例数量（冗余计数，default=0） |
| created_at | datetime | 创建时间 |

关系：
- `plan: TestPlanProject` → back_populates="folders"
- `cases: list[ImportedTestCase]` → back_populates="folder", cascade="all, delete-orphan"

### 修改模型：ImportedTestCase

新增字段：
- `folder_id: int | None` → ForeignKey("test_case_folder.id"), nullable（兼容迁移）

新增关系：
- `folder: TestCaseFolder` → back_populates="cases"

### 修改模型：TestPlanProject

新增关系：
- `folders: list[TestCaseFolder]` → back_populates="plan", cascade="all, delete-orphan"

### 数据迁移策略

每个现有 TestPlanProject 自动创建一个默认文档（name="默认文档"，source_type="import_grouped"），
将所有无 folder_id 的 ImportedTestCase 归入该文档。

## API 变更

### 新增接口

| 接口 | 说明 |
|-----|------|
| POST /api/test-plans/{plan_id}/folders | 创建文档 |
| GET /api/test-plans/{plan_id}/folders | 获取文档列表 |
| PUT /api/folders/{folder_id} | 更新文档 |
| DELETE /api/folders/{folder_id} | 删除文档（连同其下用例） |
| POST /api/folders/{folder_id}/generate | AI从需求文档生成用例到该文档 |
| POST /api/cases/batch-move | 批量移动用例到其他文档 |

### 修改接口

| 接口 | 变更 |
|-----|------|
| GET /api/test-plans/{plan_id} | 返回 folders + cases（cases 带 folder_id） |
| POST /api/test-plans/import | 支持按 module/system_name 字段自动分组创建文档 |
| POST /api/test-plans/generate-from-requirement | AI生成时按功能自动创建文档 |
| POST /api/test-plans/{plan_id}/cases | 创建用例时指定 folder_id |
| DELETE /api/test-plans/{plan_id} | cascade 删除 folders |

## Schemas 变更

### 新增

- TestCaseFolderResponse（id, plan_id, name, requirement_summary, source_type, source_filename, sequence, total_cases, created_at, cases）
- TestCaseFolderCreateRequest（name, requirement_summary?）
- TestCaseFolderUpdateRequest（name, requirement_summary?）

### 修改

- ImportedTestCaseResponse → 新增 folder_id
- ImportedTestCaseCreateRequest → 新增 folder_id (optional)
- TestPlanProjectResponse → 新增 folders
- TestPlanListItem → 无变更

## UI 变更

### 左侧侧边栏

保持现有结构：导入、AI生成、测试计划列表。

### 右侧内容区

选择测试计划后：

1. **文档列表区**（上方）：
   - 紧凑卡片式展示所有文档
   - 每个卡片显示：名称、用例数量、来源标签
   - 点击卡片筛选下方表格只显示该文档用例
   - "全部"按钮取消筛选
   - "+新建文档"按钮
   - 支持删除文档

2. **用例表格区**（下方）：
   - 增加"所属文档"列
   - 支持按文档筛选
   - 批量编辑增加"移动到文档"功能
   - 新增用例时可选择目标文档

### 新增用例对话框

增加"所属文档"选择器。

### 批量编辑对话框

增加"移动到文档"选项。

### AI生成流程

生成完成后自动按功能创建多个文档，用例自动归入对应文档。

## 实现顺序

1. 后端：模型 + migration + schemas
2. 后端：API 接口（CRUD + 修改现有接口）
3. 前端：API ts 类型 + 接口函数
4. 前端：UI 文档列表组件 + 用例表格改造
5. 前端：新增/编辑/批量移动对话框改造
6. 数据迁移：alembic migration + 自动迁移脚本
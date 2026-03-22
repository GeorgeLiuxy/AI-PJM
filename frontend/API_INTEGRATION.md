# 前端数据接入文档

## 配置步骤

### 1. 配置后端 API 地址

编辑 `.env` 文件（已创建），设置后端 API 地址：

```env
VITE_API_BASE_URL=http://localhost:8000
```

如果后端运行在其他地址，请相应修改。

### 2. 启动后端服务

确保后端服务正在运行：

```bash
cd "D:\projects\AI PJM\backend"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 安装前端依赖（首次运行）

```bash
cd "D:\projects\AI PJM\frontend"
npm install
# 或
pnpm install
```

### 4. 启动前端开发服务器

```bash
cd "D:\projects\AI PJM\frontend"
npm run dev
# 或
pnpm dev
```

前端将运行在 `http://localhost:5173`（Vite 默认端口）

## 已接入的页面

### 1. 首页 (/)

**接口**: `GET /api/v1/workbench/home`

**接入内容**:
- ✓ Summary 四张卡片（待确认事项、待复核分析、待确认输出、已完成事项）
- ✓ 待办列表（todo_queue）
- ✓ 最近事项（recent_items）
- ✓ 最近 AI 生成结果（recent_outputs）

**状态处理**:
- ✓ Loading 状态（骨架屏）
- ✓ Error 状态（错误提示）
- ✓ Empty 状态（暂无数据）

### 2. 事项详情页 (/items/{id})

**接口**: `GET /api/v1/items/{id}/timeline`

**接入内容**:
- ✓ 完整时间线（包含 item + analysis + output 的所有 action_logs）
- ✓ 事件类型中文映射
- ✓ 操作者类型（用户/AI/系统）
- ✓ 状态变更展示
- ✓ 时间格式化

**状态处理**:
- ✓ Loading 状态
- ✓ Error 状态
- ✓ Empty 状态

## 已创建的文件

### API 调用层
- `src/app/lib/api.ts` - 统一的 API 调用封装
- `src/app/types/index.ts` - 类型定义和映射

### React Hooks
- `src/app/hooks/index.ts` - 数据获取 Hooks
  - `useWorkbenchHome()`
  - `useWorkbenchTodos()`
  - `useItemTimeline()`

### 组件
- `src/app/components/workbench.tsx` - Summary Cards 组件
- `src/app/components/todo.tsx` - Todo 列表组件
- `src/app/components/recent.tsx` - Recent Items/Outputs 组件
- `src/app/components/loading.tsx` - 加载状态组件

### 页面
- `src/app/pages/HomePage.tsx` - 首页（已修改，接入真实数据）
- `src/app/pages/ItemDetailPage.tsx` - 事项详情页（新建）
- `src/app/routes.tsx` - 路由配置（已更新）

### 配置
- `.env` - 环境变量（已创建）
- `.env.example` - 环境变量模板

## 类型映射

### Todo 类型中文映射
- `pending_item_confirm` → 待确认事项
- `pending_analysis_review` → 待复核分析
- `pending_output_confirm` → 待确认输出
- `pending_output_adopt` → 待采用输出

### Action Type 中文映射（部分）
- `item_created` → 创建事项
- `item_understood` → AI 理解事项
- `item_confirmed` → 确认事项
- `analysis_created` → 创建分析
- `analysis_started` → 开始分析
- `analysis_completed` → 完成分析
- `analysis_confirmed` → 确认分析
- `output_generated` → 生成输出物
- `output_confirmed` → 确认输出物
- `output_adopted` → 采用输出物
- `item_status_changed_to_done` → 事项完成

## 待办列表跳转

点击任何待办项，统一跳转到 `/items/{item_id}`

## 未接入的页面/区块

以下页面仍使用 mock 数据或静态内容：

1. **统一输入页** (`/input`) - 未接入
2. **任务处理页** (`/process`) - 未接入
3. **影响分析页** (`/impact`) - 未接入
4. **结果工作台页** (`/results`) - 未接入

这些页面的接入需要在后续阶段完成。

## 验证步骤

1. **启动后端服务**
   ```bash
   cd backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **启动前端服务**
   ```bash
   cd frontend
   npm run dev
   ```

3. **访问首页**
   - 打开 `http://localhost:5173`
   - 检查四张卡片是否显示正确数据
   - 检查待办列表是否显示真实数据
   - 检查最近事项/输出是否显示

4. **访问事项详情页**
   - 点击任意待办项
   - 或直接访问 `http://localhost:5173/items/1`
   - 检查时间线是否完整显示

5. **检查网络请求**
   - 打开浏览器开发者工具 (F12)
   - 切换到 Network 标签
   - 检查 API 请求是否成功：
     - `GET /api/v1/workbench/home`
     - `GET /api/v1/items/1/timeline`

## 已知限制

1. **错误处理**: 当前错误处理较为简单，只显示错误消息
2. **重试机制**: 未实现自动重试
3. **缓存**: 未实现数据缓存
4. **刷新机制**: 未实现手动刷新或自动刷新

这些功能可以在后续阶段根据需要添加。

## 页面与接口字段差异

目前未发现字段不匹配的情况。前端类型定义与后端响应结构完全一致。

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Loader2, Plus, RefreshCw, ShieldCheck, UserPlus } from 'lucide-react';
import { authApi } from '../lib/api';
import type { AuthManagedUser, AuthProject } from '../types';

const globalRoles = ['admin', 'operator', 'reviewer', 'viewer'];
const projectRoles = ['owner', 'operator', 'reviewer', 'viewer'];

export default function AdminAccessPage() {
  const [projects, setProjects] = useState<AuthProject[]>([]);
  const [users, setUsers] = useState<AuthManagedUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [savingUser, setSavingUser] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [projectForm, setProjectForm] = useState({
    key: '',
    name: '',
    repository_root: '',
    default_branch: 'main',
  });
  const [userForm, setUserForm] = useState({
    username: '',
    password: '',
    display_name: '',
    email: '',
    role: 'operator',
    project_id: '',
    project_role: 'operator',
  });

  const firstProjectId = useMemo(() => projects[0]?.id, [projects]);

  const loadAccessData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectResponse, userResponse] = await Promise.all([
        authApi.listProjects(),
        authApi.listUsers(),
      ]);
      setProjects(projectResponse.data);
      setUsers(userResponse.data);
      setUserForm((current) => ({
        ...current,
        project_id: current.project_id || (projectResponse.data[0]?.id ? String(projectResponse.data[0].id) : ''),
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载权限配置失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAccessData();
  }, []);

  const submitProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSavingProject(true);
    setError(null);
    setNotice(null);
    try {
      const project = (await authApi.createProject({
        key: projectForm.key.trim(),
        name: projectForm.name.trim(),
        repository_root: projectForm.repository_root.trim() || null,
        default_branch: projectForm.default_branch.trim() || 'main',
      })).data;
      setProjectForm({ key: '', name: '', repository_root: '', default_branch: 'main' });
      setNotice(`项目已创建：${project.name}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '创建项目失败';
      setError(message);
    } finally {
      setSavingProject(false);
    }
  };

  const submitUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSavingUser(true);
    setError(null);
    setNotice(null);
    try {
      const user = (await authApi.createUser({
        username: userForm.username.trim(),
        password: userForm.password,
        display_name: userForm.display_name.trim(),
        email: userForm.email.trim() || null,
        role: userForm.role,
        project_id: userForm.project_id ? Number(userForm.project_id) : firstProjectId || null,
        project_role: userForm.project_role,
      })).data;
      setUserForm((current) => ({
        ...current,
        username: '',
        password: '',
        display_name: '',
        email: '',
      }));
      setNotice(`用户已创建：${user.username}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '创建用户失败';
      setError(message);
    } finally {
      setSavingUser(false);
    }
  };

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-4">
      <section className="mb-3 rounded border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-blue-700">
              <ShieldCheck className="h-4 w-4" />
              权限管理
            </div>
            <h1 className="mt-1 text-lg font-semibold text-slate-950">项目、用户和角色</h1>
          </div>
          <button
            type="button"
            onClick={() => void loadAccessData()}
            disabled={loading}
            className="inline-flex h-9 items-center gap-2 rounded border border-slate-200 bg-white px-3 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
        {(error || notice) && (
          <div className="border-b border-slate-200 px-4 py-2">
            {error ? <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
            {notice ? <div className="rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div> : null}
          </div>
        )}
        <div className="grid gap-3 p-4 lg:grid-cols-2">
          <ProjectForm
            value={projectForm}
            saving={savingProject}
            onChange={setProjectForm}
            onSubmit={submitProject}
          />
          <UserForm
            value={userForm}
            projects={projects}
            saving={savingUser}
            onChange={setUserForm}
            onSubmit={submitUser}
          />
        </div>
      </section>

      <section className="grid gap-3 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <ProjectTable projects={projects} loading={loading} />
        <UserTable users={users} loading={loading} />
      </section>
    </main>
  );
}

function ProjectForm({
  value,
  saving,
  onChange,
  onSubmit,
}: {
  value: { key: string; name: string; repository_root: string; default_branch: string };
  saving: boolean;
  onChange: (value: { key: string; name: string; repository_root: string; default_branch: string }) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="rounded border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
        <Plus className="h-4 w-4 text-blue-600" />
        创建项目
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <TextInput label="项目标识" value={value.key} onChange={(key) => onChange({ ...value, key })} required />
        <TextInput label="项目名称" value={value.name} onChange={(name) => onChange({ ...value, name })} required />
        <TextInput
          label="默认分支"
          value={value.default_branch}
          onChange={(default_branch) => onChange({ ...value, default_branch })}
        />
        <TextInput
          label="仓库路径"
          value={value.repository_root}
          onChange={(repository_root) => onChange({ ...value, repository_root })}
        />
      </div>
      <SubmitButton label="创建项目" saving={saving} disabled={!value.key.trim() || !value.name.trim()} />
    </form>
  );
}

function UserForm({
  value,
  projects,
  saving,
  onChange,
  onSubmit,
}: {
  value: {
    username: string;
    password: string;
    display_name: string;
    email: string;
    role: string;
    project_id: string;
    project_role: string;
  };
  projects: AuthProject[];
  saving: boolean;
  onChange: (value: UserFormValue) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="rounded border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
        <UserPlus className="h-4 w-4 text-blue-600" />
        创建用户
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <TextInput label="用户名" value={value.username} onChange={(username) => onChange({ ...value, username })} required />
        <TextInput
          label="显示名称"
          value={value.display_name}
          onChange={(display_name) => onChange({ ...value, display_name })}
          required
        />
        <TextInput
          label="初始密码"
          value={value.password}
          onChange={(password) => onChange({ ...value, password })}
          type="password"
          required
        />
        <TextInput label="邮箱" value={value.email} onChange={(email) => onChange({ ...value, email })} />
        <SelectInput label="全局角色" value={value.role} options={globalRoles} onChange={(role) => onChange({ ...value, role })} />
        <SelectInput
          label="项目"
          value={value.project_id}
          options={projects.map((project) => ({ label: project.name, value: String(project.id) }))}
          onChange={(project_id) => onChange({ ...value, project_id })}
        />
        <SelectInput
          label="项目角色"
          value={value.project_role}
          options={projectRoles}
          onChange={(project_role) => onChange({ ...value, project_role })}
        />
      </div>
      <SubmitButton
        label="创建用户"
        saving={saving}
        disabled={!value.username.trim() || !value.display_name.trim() || value.password.length < 8}
      />
    </form>
  );
}

type UserFormValue = {
  username: string;
  password: string;
  display_name: string;
  email: string;
  role: string;
  project_id: string;
  project_role: string;
};

function TextInput({
  label,
  value,
  onChange,
  required = false,
  type = 'text',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
}) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        type={type}
        required={required}
        className="mt-1 h-9 w-full rounded border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      />
    </label>
  );
}

function SelectInput({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<string | { label: string; value: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 h-9 w-full rounded border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      >
        {options.length === 0 ? <option value="">暂无项目</option> : null}
        {options.map((option) => {
          const labelValue = typeof option === 'string' ? option : option.label;
          const optionValue = typeof option === 'string' ? option : option.value;
          return (
            <option key={optionValue} value={optionValue}>
              {formatRoleLabel(labelValue)}
            </option>
          );
        })}
      </select>
    </label>
  );
}

function SubmitButton({ label, saving, disabled }: { label: string; saving: boolean; disabled: boolean }) {
  return (
    <button
      type="submit"
      disabled={saving || disabled}
      className="mt-3 inline-flex h-9 items-center gap-2 rounded bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
    >
      {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {label}
    </button>
  );
}

function ProjectTable({ projects, loading }: { projects: AuthProject[]; loading: boolean }) {
  return (
    <div className="overflow-hidden rounded border border-slate-200 bg-white">
      <TableHeader title="项目" count={projects.length} loading={loading} />
      <div className="max-h-[520px] overflow-auto">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
            <tr>
              <th className="w-[28%] px-3 py-2">项目</th>
              <th className="w-[18%] px-3 py-2">标识</th>
              <th className="w-[18%] px-3 py-2">分支</th>
              <th className="w-[18%] px-3 py-2">状态</th>
              <th className="w-[18%] px-3 py-2">创建时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {projects.length > 0 ? (
              projects.map((project) => (
                <tr key={project.id}>
                  <td className="break-words px-3 py-2 font-medium text-slate-900">{project.name}</td>
                  <td className="break-words px-3 py-2 font-mono text-xs text-slate-700">{project.key}</td>
                  <td className="break-words px-3 py-2 text-slate-700">{project.default_branch}</td>
                  <td className="px-3 py-2">
                    <Badge>{formatStatus(project.status)}</Badge>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{formatDate(project.created_at)}</td>
                </tr>
              ))
            ) : (
              <EmptyRow colSpan={5} loading={loading} label="暂无项目" />
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UserTable({ users, loading }: { users: AuthManagedUser[]; loading: boolean }) {
  return (
    <div className="overflow-hidden rounded border border-slate-200 bg-white">
      <TableHeader title="用户" count={users.length} loading={loading} />
      <div className="max-h-[520px] overflow-auto">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
            <tr>
              <th className="w-[22%] px-3 py-2">用户</th>
              <th className="w-[16%] px-3 py-2">全局角色</th>
              <th className="w-[30%] px-3 py-2">项目角色</th>
              <th className="w-[14%] px-3 py-2">状态</th>
              <th className="w-[18%] px-3 py-2">创建时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.length > 0 ? (
              users.map((user) => (
                <tr key={user.id || user.username}>
                  <td className="break-words px-3 py-2">
                    <div className="font-medium text-slate-900">{user.display_name}</div>
                    <div className="text-xs text-slate-500">{user.username}</div>
                  </td>
                  <td className="px-3 py-2">
                    <Badge>{formatRoleLabel(user.role)}</Badge>
                  </td>
                  <td className="break-words px-3 py-2 text-slate-700">
                    {user.projects.length > 0
                      ? user.projects.map((project) => `${project.name}/${formatRoleLabel(project.role)}`).join('，')
                      : '未分配项目'}
                  </td>
                  <td className="px-3 py-2">
                    <Badge>{formatStatus(user.status)}</Badge>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{formatDate(user.created_at)}</td>
                </tr>
              ))
            ) : (
              <EmptyRow colSpan={5} loading={loading} label="暂无用户" />
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TableHeader({ title, count, loading }: { title: string; count: number; loading: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
      <div className="text-sm font-medium text-slate-900">{title}</div>
      <Badge>{loading ? '加载中' : `${count} 条`}</Badge>
    </div>
  );
}

function EmptyRow({ colSpan, loading, label }: { colSpan: number; loading: boolean; label: string }) {
  return (
    <tr>
      <td className="px-3 py-6 text-sm text-slate-400" colSpan={colSpan}>
        {loading ? '正在加载' : label}
      </td>
    </tr>
  );
}

function Badge({ children }: { children: string }) {
  return (
    <span className="inline-flex max-w-[12rem] rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-700">
      <span className="truncate">{children}</span>
    </span>
  );
}

function formatRoleLabel(value: string) {
  const labels: Record<string, string> = {
    admin: '管理员',
    owner: '项目负责人',
    operator: '操作员',
    reviewer: '评审员',
    viewer: '只读',
  };
  return labels[value] || value;
}

function formatStatus(value: string) {
  const labels: Record<string, string> = {
    active: '启用',
    disabled: '停用',
  };
  return labels[value] || value;
}

function formatDate(value?: string | null) {
  if (!value) {
    return '暂无';
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}


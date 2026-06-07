import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router';
import { KeyRound, Loader2, Plus, RefreshCw, Rocket, ShieldCheck, Trash2, UserCog, UserPlus } from 'lucide-react';
import { authApi, deliveryApi } from '../lib/api';
import { canAdmin } from '../lib/permissions';
import type { AuthManagedUser, AuthProject, ProjectDeploymentEnvironmentConfig, SecretRecord } from '../types';
import type { AppOutletContext } from '../Root';

const globalRoles = ['admin', 'operator', 'reviewer', 'viewer'];
const projectRoles = ['owner', 'operator', 'reviewer', 'viewer'];
const secretProviders = ['dify', 'gitlab', 'github', 'openai', 'codex', 'custom'];
const userStatuses = ['active', 'disabled'];

export default function AdminAccessPage() {
  const { user } = useOutletContext<AppOutletContext>();
  const [projects, setProjects] = useState<AuthProject[]>([]);
  const [users, setUsers] = useState<AuthManagedUser[]>([]);
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [savingUser, setSavingUser] = useState(false);
  const [savingSecret, setSavingSecret] = useState(false);
  const [savingSecretRotate, setSavingSecretRotate] = useState(false);
  const [loadingDeploymentEnv, setLoadingDeploymentEnv] = useState(false);
  const [savingDeploymentEnv, setSavingDeploymentEnv] = useState(false);
  const [savingAccessAction, setSavingAccessAction] = useState<string | null>(null);
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
  const [secretForm, setSecretForm] = useState({
    project_id: '',
    name: '',
    provider: 'dify',
    value: '',
    description: '',
    expires_at: '',
  });
  const [secretRotateForm, setSecretRotateForm] = useState<SecretRotateFormValue>({
    secret_id: '',
    value: '',
    description: '',
    expires_at: '',
  });
  const [deploymentEnvironments, setDeploymentEnvironments] = useState<ProjectDeploymentEnvironmentConfig['environments']>({});
  const [deploymentEnvForm, setDeploymentEnvForm] = useState<DeploymentEnvironmentFormValue>({
    project_id: '',
    environment: 'test',
    url: '',
    log_url: '',
    description: '',
    environment_name: '',
  });
  const [maintenanceForm, setMaintenanceForm] = useState<MaintenanceFormValue>({
    user_id: '',
    display_name: '',
    email: '',
    role: 'operator',
    status: 'active',
    password: '',
    project_id: '',
    project_role: 'operator',
  });

  const firstProjectId = useMemo(() => projects[0]?.id, [projects]);
  const projectNameById = useMemo(() => {
    return new Map(projects.map((project) => [project.id, project.name]));
  }, [projects]);
  const selectedMaintenanceUser = useMemo(() => {
    return users.find((managedUser) => String(managedUser.id) === maintenanceForm.user_id) || null;
  }, [maintenanceForm.user_id, users]);
  const hasAdminAccess = canAdmin(user);

  const loadProjectDeploymentEnvironment = async (projectId: string, environmentName = 'test') => {
    if (!projectId) {
      setDeploymentEnvironments({});
      setDeploymentEnvForm((current) => ({ ...current, project_id: '', environment: environmentName || 'test' }));
      return;
    }
    const environment = environmentName.trim() || 'test';
    setLoadingDeploymentEnv(true);
    try {
      const response = await deliveryApi.getProjectDeploymentEnvironments(Number(projectId));
      const environments = response.data.environments || {};
      const selected = environments[environment] || {};
      setDeploymentEnvironments(environments);
      setDeploymentEnvForm((current) => ({
        ...current,
        project_id: projectId,
        environment,
        url: selected.url || '',
        log_url: selected.log_url || '',
        description: selected.description || '',
        environment_name: selected.environment_name || '',
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载测试环境配置失败';
      setError(message);
    } finally {
      setLoadingDeploymentEnv(false);
    }
  };

  const loadAccessData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectResponse, userResponse, secretResponse] = await Promise.all([
        authApi.listProjects(),
        authApi.listUsers(),
        authApi.listSecrets(),
      ]);
      const projectIds = new Set(projectResponse.data.map((project) => String(project.id)));
      const secretIds = new Set(secretResponse.data.map((secret) => String(secret.id)));
      const defaultProjectId = projectResponse.data[0]?.id ? String(projectResponse.data[0].id) : '';
      const defaultSecretId = secretResponse.data[0]?.id ? String(secretResponse.data[0].id) : '';
      setProjects(projectResponse.data);
      setUsers(userResponse.data);
      setSecrets(secretResponse.data);
      setUserForm((current) => ({
        ...current,
        project_id: current.project_id && projectIds.has(current.project_id) ? current.project_id : defaultProjectId,
      }));
      setSecretForm((current) => ({
        ...current,
        project_id: current.project_id && projectIds.has(current.project_id) ? current.project_id : defaultProjectId,
      }));
      setSecretRotateForm((current) => {
        const keepsCurrent = Boolean(current.secret_id && secretIds.has(current.secret_id));
        const selectedSecretId = keepsCurrent ? current.secret_id : defaultSecretId;
        const selectedSecret = secretResponse.data.find((secret) => String(secret.id) === selectedSecretId);
        return {
          ...current,
          secret_id: selectedSecretId,
          description: keepsCurrent ? current.description : selectedSecret?.description || '',
          expires_at: keepsCurrent ? current.expires_at : toDateTimeLocal(selectedSecret?.expires_at),
        };
      });
      const deploymentProjectId =
        deploymentEnvForm.project_id && projectIds.has(deploymentEnvForm.project_id)
          ? deploymentEnvForm.project_id
          : defaultProjectId;
      setDeploymentEnvForm((current) => ({ ...current, project_id: deploymentProjectId }));
      setMaintenanceForm((current) => {
        const selectedUser = userResponse.data.find((user) => String(user.id) === current.user_id) || userResponse.data[0];
        if (!selectedUser) {
          return { ...current, user_id: '', project_id: defaultProjectId };
        }
        const selectedMembership =
          selectedUser.projects.find((project) => String(project.id) === current.project_id) || selectedUser.projects[0];
        return {
          ...current,
          user_id: String(selectedUser.id || ''),
          display_name: selectedUser.display_name,
          email: selectedUser.email || '',
          role: selectedUser.role,
          status: selectedUser.status,
          project_id: selectedMembership?.id
            ? String(selectedMembership.id)
            : current.project_id && projectIds.has(current.project_id)
              ? current.project_id
              : defaultProjectId,
          project_role: selectedMembership?.role || current.project_role || 'operator',
          password: '',
        };
      });
      await loadProjectDeploymentEnvironment(deploymentProjectId, deploymentEnvForm.environment || 'test');
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载权限配置失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (hasAdminAccess) {
      void loadAccessData();
    }
  }, [hasAdminAccess]);

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

  const submitSecret = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSavingSecret(true);
    setError(null);
    setNotice(null);
    try {
      const secret = (await authApi.createSecret({
        project_id: Number(secretForm.project_id || firstProjectId),
        name: secretForm.name.trim(),
        provider: secretForm.provider.trim(),
        value: secretForm.value,
        description: secretForm.description.trim() || null,
        expires_at: secretForm.expires_at ? new Date(secretForm.expires_at).toISOString() : null,
      })).data;
      setSecretForm((current) => ({
        ...current,
        name: '',
        value: '',
        description: '',
        expires_at: '',
      }));
      setNotice(`密钥已保存：${secret.name}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '保存密钥失败';
      setError(message);
    } finally {
      setSavingSecret(false);
    }
  };

  const submitDeploymentEnvironment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!deploymentEnvForm.project_id) {
      return;
    }
    const environment = deploymentEnvForm.environment.trim();
    if (!environment) {
      setError('环境名不能为空');
      return;
    }
    setSavingDeploymentEnv(true);
    setError(null);
    setNotice(null);
    try {
      const config = {
        url: deploymentEnvForm.url.trim() || null,
        log_url: deploymentEnvForm.log_url.trim() || null,
        description: deploymentEnvForm.description.trim() || null,
        environment_name: deploymentEnvForm.environment_name.trim() || null,
      };
      const response = await deliveryApi.updateProjectDeploymentEnvironments(Number(deploymentEnvForm.project_id), {
        environments: {
          ...deploymentEnvironments,
          [environment]: config,
        },
      });
      const environments = response.data.environments || {};
      setDeploymentEnvironments(environments);
      setDeploymentEnvForm((current) => ({
        ...current,
        environment,
        url: environments[environment]?.url || '',
        log_url: environments[environment]?.log_url || '',
        description: environments[environment]?.description || '',
        environment_name: environments[environment]?.environment_name || '',
      }));
      setNotice(`测试环境配置已保存：${environment}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : '保存测试环境配置失败';
      setError(message);
    } finally {
      setSavingDeploymentEnv(false);
    }
  };

  const selectDeploymentEnvironmentProject = (projectId: string) => {
    setDeploymentEnvForm((current) => ({ ...current, project_id: projectId }));
    void loadProjectDeploymentEnvironment(projectId, deploymentEnvForm.environment || 'test');
  };

  const reloadDeploymentEnvironment = () => {
    void loadProjectDeploymentEnvironment(deploymentEnvForm.project_id, deploymentEnvForm.environment || 'test');
  };

  const selectSecretForRotate = (secretId: string) => {
    const selectedSecret = secrets.find((secret) => String(secret.id) === secretId);
    setSecretRotateForm((current) => ({
      ...current,
      secret_id: secretId,
      value: '',
      description: selectedSecret?.description || '',
      expires_at: toDateTimeLocal(selectedSecret?.expires_at),
    }));
  };

  const submitSecretRotate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!secretRotateForm.secret_id) {
      return;
    }
    setSavingSecretRotate(true);
    setError(null);
    setNotice(null);
    try {
      const secret = (await authApi.rotateSecret(Number(secretRotateForm.secret_id), {
        value: secretRotateForm.value,
        description: secretRotateForm.description.trim() || null,
        expires_at: secretRotateForm.expires_at ? new Date(secretRotateForm.expires_at).toISOString() : null,
      })).data;
      setSecretRotateForm((current) => ({
        ...current,
        value: '',
        description: secret.description || '',
        expires_at: toDateTimeLocal(secret.expires_at),
      }));
      setNotice(`密钥已轮换：${secret.name}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '轮换密钥失败';
      setError(message);
    } finally {
      setSavingSecretRotate(false);
    }
  };

  const checkSecretHealth = async (secret: SecretRecord) => {
    setSavingAccessAction(`secret-health-${secret.id}`);
    setError(null);
    setNotice(null);
    try {
      const checked = (await authApi.checkSecretHealth(secret.id)).data;
      setNotice(`密钥健康检查完成：${checked.name}，${formatSecretHealth(checked.health_status)}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '密钥健康检查失败';
      setError(message);
    } finally {
      setSavingAccessAction(null);
    }
  };

  const updateSecretStatus = async (secret: SecretRecord, status: 'active' | 'disabled') => {
    const actionLabel = status === 'disabled' ? '停用' : '启用';
    if (
      status === 'disabled'
      && !confirmDangerousAction({
        title: '停用密钥',
        target: secret.name,
        description: '相关 Provider 将无法继续使用该凭证。',
      })
    ) {
      return;
    }
    setSavingAccessAction(`secret-status-${secret.id}`);
    setError(null);
    setNotice(null);
    try {
      const updated = (await authApi.updateSecretStatus(secret.id, {
        status,
        reason: status === 'disabled' ? 'access management disabled' : 'access management enabled',
      })).data;
      setNotice(`密钥已${actionLabel}：${updated.name}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : `${actionLabel}密钥失败`;
      setError(message);
    } finally {
      setSavingAccessAction(null);
    }
  };

  const selectManagedUser = (userId: string) => {
    const selectedUser = users.find((user) => String(user.id) === userId);
    if (!selectedUser) {
      setMaintenanceForm((current) => ({ ...current, user_id: userId }));
      return;
    }
    const selectedMembership = selectedUser.projects[0];
    setMaintenanceForm((current) => ({
      ...current,
      user_id: String(selectedUser.id || ''),
      display_name: selectedUser.display_name,
      email: selectedUser.email || '',
      role: selectedUser.role,
      status: selectedUser.status,
      project_id: selectedMembership?.id ? String(selectedMembership.id) : projects[0]?.id ? String(projects[0].id) : '',
      project_role: selectedMembership?.role || 'operator',
      password: '',
    }));
  };

  const submitUserUpdate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!maintenanceForm.user_id) {
      return;
    }
    if (
      maintenanceForm.status === 'disabled'
      && selectedMaintenanceUser?.status !== 'disabled'
      && !confirmDangerousAction({
        title: '停用用户',
        target: selectedMaintenanceUser?.username || maintenanceForm.display_name,
        description: '该用户将无法继续登录和执行平台操作。',
      })
    ) {
      return;
    }
    setSavingAccessAction('update-user');
    setError(null);
    setNotice(null);
    try {
      const user = (await authApi.updateUser(Number(maintenanceForm.user_id), {
        display_name: maintenanceForm.display_name.trim(),
        email: maintenanceForm.email.trim() || null,
        role: maintenanceForm.role,
        status: maintenanceForm.status,
      })).data;
      setNotice(`用户已更新：${user.username}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '更新用户失败';
      setError(message);
    } finally {
      setSavingAccessAction(null);
    }
  };

  const resetManagedUserPassword = async () => {
    if (!maintenanceForm.user_id || maintenanceForm.password.length < 8) {
      return;
    }
    if (
      !confirmDangerousAction({
        title: '重置密码',
        target: selectedMaintenanceUser?.username || maintenanceForm.display_name,
        description: '原密码会立即失效，请确认已和用户完成交接。',
      })
    ) {
      return;
    }
    setSavingAccessAction('reset-password');
    setError(null);
    setNotice(null);
    try {
      const user = (await authApi.resetUserPassword(Number(maintenanceForm.user_id), {
        password: maintenanceForm.password,
      })).data;
      setMaintenanceForm((current) => ({ ...current, password: '' }));
      setNotice(`密码已重置：${user.username}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '重置密码失败';
      setError(message);
    } finally {
      setSavingAccessAction(null);
    }
  };

  const saveManagedUserMembership = async () => {
    if (!maintenanceForm.user_id || !maintenanceForm.project_id) {
      return;
    }
    setSavingAccessAction('save-membership');
    setError(null);
    setNotice(null);
    try {
      const user = (await authApi.upsertUserMembership(Number(maintenanceForm.user_id), {
        project_id: Number(maintenanceForm.project_id),
        role: maintenanceForm.project_role,
      })).data;
      setNotice(`项目角色已保存：${user.username}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '保存项目角色失败';
      setError(message);
    } finally {
      setSavingAccessAction(null);
    }
  };

  const removeManagedUserMembership = async () => {
    if (!maintenanceForm.user_id || !maintenanceForm.project_id) {
      return;
    }
    const projectName = projectNameById.get(Number(maintenanceForm.project_id)) || `项目 ${maintenanceForm.project_id}`;
    if (
      !confirmDangerousAction({
        title: '移除项目角色',
        target: selectedMaintenanceUser?.username || maintenanceForm.display_name,
        description: `用户将失去「${projectName}」下的项目权限。`,
      })
    ) {
      return;
    }
    setSavingAccessAction('remove-membership');
    setError(null);
    setNotice(null);
    try {
      const user = (await authApi.removeUserMembership(Number(maintenanceForm.user_id), Number(maintenanceForm.project_id))).data;
      setNotice(`项目角色已移除：${user.username}`);
      await loadAccessData();
    } catch (err) {
      const message = err instanceof Error ? err.message : '移除项目角色失败';
      setError(message);
    } finally {
      setSavingAccessAction(null);
    }
  };

  if (!hasAdminAccess) {
    return (
      <main className="mx-auto max-w-[960px] px-4 py-6">
        <section className="rounded border border-slate-200 bg-white p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded bg-slate-100 text-slate-600">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-slate-950">没有权限访问权限管理</h1>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                当前账号不能维护项目、用户、角色和密钥。需要平台管理员账号执行该操作。
              </p>
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-4">
      <section className="mb-3 rounded border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-blue-700">
              <ShieldCheck className="h-4 w-4" />
              权限管理
            </div>
            <h1 className="mt-1 text-lg font-semibold text-slate-950">项目、用户、角色和密钥</h1>
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
        <div className="grid gap-3 p-4 xl:grid-cols-2 2xl:grid-cols-4">
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
          <SecretForm
            value={secretForm}
            projects={projects}
            saving={savingSecret}
            onChange={setSecretForm}
            onSubmit={submitSecret}
          />
          <SecretRotateForm
            value={secretRotateForm}
            secrets={secrets}
            projectNameById={projectNameById}
            saving={savingSecretRotate}
            onChange={setSecretRotateForm}
            onSelectSecret={selectSecretForRotate}
            onSubmit={submitSecretRotate}
          />
          <DeploymentEnvironmentForm
            value={deploymentEnvForm}
            projects={projects}
            loading={loadingDeploymentEnv}
            saving={savingDeploymentEnv}
            onChange={setDeploymentEnvForm}
            onSelectProject={selectDeploymentEnvironmentProject}
            onReload={reloadDeploymentEnvironment}
            onSubmit={submitDeploymentEnvironment}
          />
          <UserMaintenanceForm
            value={maintenanceForm}
            users={users}
            projects={projects}
            savingAction={savingAccessAction}
            onChange={setMaintenanceForm}
            onSelectUser={selectManagedUser}
            onSubmitUser={submitUserUpdate}
            onResetPassword={resetManagedUserPassword}
            onSaveMembership={saveManagedUserMembership}
            onRemoveMembership={removeManagedUserMembership}
          />
        </div>
      </section>

      <section className="grid gap-3 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <ProjectTable projects={projects} loading={loading} />
        <UserTable users={users} loading={loading} />
        <div className="xl:col-span-2">
          <SecretTable
            secrets={secrets}
            projectNameById={projectNameById}
            loading={loading}
            savingAction={savingAccessAction}
            onCheckHealth={checkSecretHealth}
            onUpdateStatus={updateSecretStatus}
          />
        </div>
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

function SecretForm({
  value,
  projects,
  saving,
  onChange,
  onSubmit,
}: {
  value: SecretFormValue;
  projects: AuthProject[];
  saving: boolean;
  onChange: (value: SecretFormValue) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="rounded border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
        <KeyRound className="h-4 w-4 text-blue-600" />
        保存项目密钥
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <SelectInput
          label="项目"
          value={value.project_id}
          options={projects.map((project) => ({ label: project.name, value: String(project.id) }))}
          onChange={(project_id) => onChange({ ...value, project_id })}
        />
        <SelectInput
          label="类型"
          value={value.provider}
          options={secretProviders}
          onChange={(provider) => onChange({ ...value, provider })}
          formatter={formatProviderLabel}
        />
        <TextInput
          label="密钥名称"
          value={value.name}
          onChange={(name) => onChange({ ...value, name })}
          required
        />
        <TextInput
          label="密钥值"
          value={value.value}
          onChange={(secretValue) => onChange({ ...value, value: secretValue })}
          type="password"
          required
        />
        <TextInput
          label="过期时间"
          value={value.expires_at}
          onChange={(expires_at) => onChange({ ...value, expires_at })}
          type="datetime-local"
        />
        <div className="md:col-span-2 xl:col-span-1 2xl:col-span-2">
          <TextInput
            label="说明"
            value={value.description}
            onChange={(description) => onChange({ ...value, description })}
          />
        </div>
      </div>
      <SubmitButton
        label="保存密钥"
        saving={saving}
        disabled={!value.project_id || !value.name.trim() || !value.provider.trim() || !value.value.trim()}
      />
    </form>
  );
}

function SecretRotateForm({
  value,
  secrets,
  projectNameById,
  saving,
  onChange,
  onSelectSecret,
  onSubmit,
}: {
  value: SecretRotateFormValue;
  secrets: SecretRecord[];
  projectNameById: Map<number, string>;
  saving: boolean;
  onChange: (value: SecretRotateFormValue) => void;
  onSelectSecret: (secretId: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="rounded border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
        <RefreshCw className="h-4 w-4 text-blue-600" />
        轮换项目密钥
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <SelectInput
          label="选择密钥"
          value={value.secret_id}
          options={secrets.map((secret) => ({
            label: `${secret.name} / ${formatProviderLabel(secret.provider)} / ${
              projectNameById.get(secret.project_id) || `#${secret.project_id}`
            }`,
            value: String(secret.id),
          }))}
          onChange={onSelectSecret}
          formatter={identityLabel}
          emptyLabel="暂无密钥"
        />
        <TextInput
          label="新密钥值"
          value={value.value}
          onChange={(secretValue) => onChange({ ...value, value: secretValue })}
          type="password"
          required
        />
        <TextInput
          label="新过期时间"
          value={value.expires_at}
          onChange={(expires_at) => onChange({ ...value, expires_at })}
          type="datetime-local"
        />
        <TextInput
          label="轮换说明"
          value={value.description}
          onChange={(description) => onChange({ ...value, description })}
        />
      </div>
      <SubmitButton
        label="轮换密钥"
        saving={saving}
        disabled={!value.secret_id || !value.value.trim()}
      />
    </form>
  );
}

function DeploymentEnvironmentForm({
  value,
  projects,
  loading,
  saving,
  onChange,
  onSelectProject,
  onReload,
  onSubmit,
}: {
  value: DeploymentEnvironmentFormValue;
  projects: AuthProject[];
  loading: boolean;
  saving: boolean;
  onChange: (value: DeploymentEnvironmentFormValue) => void;
  onSelectProject: (projectId: string) => void;
  onReload: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="rounded border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <Rocket className="h-4 w-4 text-blue-600" />
          测试环境配置
        </div>
        <button
          type="button"
          onClick={onReload}
          disabled={loading || !value.project_id}
          className="inline-flex h-8 items-center gap-1 rounded border border-slate-200 bg-white px-2 text-xs text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          读取
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <SelectInput
          label="项目"
          value={value.project_id}
          options={projects.map((project) => ({ label: project.name, value: String(project.id) }))}
          onChange={onSelectProject}
          formatter={identityLabel}
        />
        <TextInput
          label="环境名"
          value={value.environment}
          onChange={(environment) => onChange({ ...value, environment })}
          required
        />
        <TextInput
          label="访问地址"
          value={value.url}
          onChange={(url) => onChange({ ...value, url })}
        />
        <TextInput
          label="日志地址"
          value={value.log_url}
          onChange={(log_url) => onChange({ ...value, log_url })}
        />
        <TextInput
          label="显示名称"
          value={value.environment_name}
          onChange={(environment_name) => onChange({ ...value, environment_name })}
        />
        <TextInput
          label="说明"
          value={value.description}
          onChange={(description) => onChange({ ...value, description })}
        />
      </div>
      <SubmitButton
        label="保存环境"
        saving={saving}
        disabled={!value.project_id || !value.environment.trim() || (!value.url.trim() && !value.log_url.trim())}
      />
    </form>
  );
}

function UserMaintenanceForm({
  value,
  users,
  projects,
  savingAction,
  onChange,
  onSelectUser,
  onSubmitUser,
  onResetPassword,
  onSaveMembership,
  onRemoveMembership,
}: {
  value: MaintenanceFormValue;
  users: AuthManagedUser[];
  projects: AuthProject[];
  savingAction: string | null;
  onChange: (value: MaintenanceFormValue) => void;
  onSelectUser: (userId: string) => void;
  onSubmitUser: (event: FormEvent<HTMLFormElement>) => void;
  onResetPassword: () => void;
  onSaveMembership: () => void;
  onRemoveMembership: () => void;
}) {
  const selectedUser = users.find((user) => String(user.id) === value.user_id);
  const hasSelectedMembership = Boolean(
    selectedUser?.projects.some((project) => String(project.id) === value.project_id),
  );
  return (
    <form onSubmit={onSubmitUser} className="rounded border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
        <UserCog className="h-4 w-4 text-blue-600" />
        维护用户权限
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <SelectInput
          label="用户"
          value={value.user_id}
          options={users.map((user) => ({
            label: `${user.display_name} / ${user.username}`,
            value: String(user.id || ''),
          }))}
          onChange={onSelectUser}
          formatter={identityLabel}
        />
        <SelectInput
          label="状态"
          value={value.status}
          options={userStatuses}
          onChange={(status) => onChange({ ...value, status })}
          formatter={formatStatus}
        />
        <TextInput
          label="显示名称"
          value={value.display_name}
          onChange={(display_name) => onChange({ ...value, display_name })}
          required
        />
        <TextInput label="邮箱" value={value.email} onChange={(email) => onChange({ ...value, email })} />
        <SelectInput
          label="全局角色"
          value={value.role}
          options={globalRoles}
          onChange={(role) => onChange({ ...value, role })}
        />
        <TextInput
          label="新密码"
          value={value.password}
          onChange={(password) => onChange({ ...value, password })}
          type="password"
        />
        <SelectInput
          label="项目"
          value={value.project_id}
          options={projects.map((project) => ({ label: project.name, value: String(project.id) }))}
          onChange={(project_id) => {
            const existingRole = selectedUser?.projects.find((project) => String(project.id) === project_id)?.role;
            onChange({ ...value, project_id, project_role: existingRole || value.project_role });
          }}
          formatter={identityLabel}
        />
        <SelectInput
          label="项目角色"
          value={value.project_role}
          options={projectRoles}
          onChange={(project_role) => onChange({ ...value, project_role })}
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton
          label="更新用户"
          saving={savingAction === 'update-user'}
          disabled={!value.user_id || !value.display_name.trim()}
        />
        <ActionButton
          label="重置密码"
          type="button"
          saving={savingAction === 'reset-password'}
          disabled={!value.user_id || value.password.length < 8}
          onClick={onResetPassword}
        />
        <ActionButton
          label="保存项目角色"
          type="button"
          saving={savingAction === 'save-membership'}
          disabled={!value.user_id || !value.project_id}
          onClick={onSaveMembership}
        />
        <button
          type="button"
          disabled={!value.user_id || !value.project_id || !hasSelectedMembership || savingAction === 'remove-membership'}
          onClick={onRemoveMembership}
          className="inline-flex h-9 items-center gap-2 rounded border border-red-200 bg-white px-3 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-300"
        >
          {savingAction === 'remove-membership' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
          移除项目角色
        </button>
      </div>
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

type SecretFormValue = {
  project_id: string;
  name: string;
  provider: string;
  value: string;
  description: string;
  expires_at: string;
};

type SecretRotateFormValue = {
  secret_id: string;
  value: string;
  description: string;
  expires_at: string;
};

type DeploymentEnvironmentFormValue = {
  project_id: string;
  environment: string;
  url: string;
  log_url: string;
  description: string;
  environment_name: string;
};

type MaintenanceFormValue = {
  user_id: string;
  display_name: string;
  email: string;
  role: string;
  status: string;
  password: string;
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
  formatter = formatRoleLabel,
  emptyLabel = '暂无项目',
}: {
  label: string;
  value: string;
  options: Array<string | { label: string; value: string }>;
  onChange: (value: string) => void;
  formatter?: (value: string) => string;
  emptyLabel?: string;
}) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 h-9 w-full rounded border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      >
        {options.length === 0 ? <option value="">{emptyLabel}</option> : null}
        {options.map((option) => {
          const labelValue = typeof option === 'string' ? option : option.label;
          const optionValue = typeof option === 'string' ? option : option.value;
          return (
            <option key={optionValue} value={optionValue}>
              {formatter(labelValue)}
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

function ActionButton({
  label,
  saving,
  disabled,
  type = 'submit',
  onClick,
}: {
  label: string;
  saving: boolean;
  disabled: boolean;
  type?: 'submit' | 'button';
  onClick?: () => void;
}) {
  return (
    <button
      type={type}
      disabled={saving || disabled}
      onClick={onClick}
      className="inline-flex h-9 items-center gap-2 rounded bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
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

function SecretTable({
  secrets,
  projectNameById,
  loading,
  savingAction,
  onCheckHealth,
  onUpdateStatus,
}: {
  secrets: SecretRecord[];
  projectNameById: Map<number, string>;
  loading: boolean;
  savingAction: string | null;
  onCheckHealth: (secret: SecretRecord) => void;
  onUpdateStatus: (secret: SecretRecord, status: 'active' | 'disabled') => void;
}) {
  return (
    <div className="overflow-hidden rounded border border-slate-200 bg-white">
      <TableHeader title="项目密钥" count={secrets.length} loading={loading} />
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full min-w-[1040px] table-fixed text-left text-sm">
          <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
            <tr>
              <th className="w-[16%] px-3 py-2">项目</th>
              <th className="w-[17%] px-3 py-2">名称</th>
              <th className="w-[10%] px-3 py-2">类型</th>
              <th className="w-[14%] px-3 py-2">掩码</th>
              <th className="w-[13%] px-3 py-2">健康</th>
              <th className="w-[14%] px-3 py-2">使用/过期</th>
              <th className="w-[8%] px-3 py-2">状态</th>
              <th className="w-[8%] px-3 py-2">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {secrets.length > 0 ? (
              secrets.map((secret) => (
                <tr key={secret.id}>
                  <td className="break-words px-3 py-2 text-slate-700">
                    {projectNameById.get(secret.project_id) || `#${secret.project_id}`}
                  </td>
                  <td className="break-words px-3 py-2">
                    <div className="font-medium text-slate-900">{secret.name}</div>
                    {secret.description ? <div className="text-xs text-slate-500">{secret.description}</div> : null}
                  </td>
                  <td className="px-3 py-2">
                    <Badge>{formatProviderLabel(secret.provider)}</Badge>
                  </td>
                  <td className="break-words px-3 py-2 font-mono text-xs text-slate-700">{secret.value_mask}</td>
                  <td className="px-3 py-2">
                    <Badge>{formatSecretHealth(secret.health_status)}</Badge>
                    {secret.health_reason ? <div className="mt-1 text-xs text-slate-500">{secret.health_reason}</div> : null}
                    <ProviderHealthNote secret={secret} />
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">
                    <div>最近：{formatDate(secret.last_used_at)}</div>
                    <div>过期：{formatDate(secret.expires_at)}</div>
                  </td>
                  <td className="px-3 py-2">
                    <Badge>{formatStatus(secret.status)}</Badge>
                  </td>
                  <td className="space-y-1 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => onCheckHealth(secret)}
                      disabled={savingAction === `secret-health-${secret.id}`}
                      className="inline-flex h-8 items-center gap-1 rounded border border-slate-200 bg-white px-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <RefreshCw
                        className={`h-3.5 w-3.5 ${savingAction === `secret-health-${secret.id}` ? 'animate-spin' : ''}`}
                      />
                      检查
                    </button>
                    <button
                      type="button"
                      onClick={() => onUpdateStatus(secret, secret.status === 'active' ? 'disabled' : 'active')}
                      disabled={savingAction === `secret-status-${secret.id}`}
                      className={`inline-flex h-8 items-center gap-1 rounded border bg-white px-2 text-xs disabled:cursor-not-allowed disabled:opacity-50 ${
                        secret.status === 'active'
                          ? 'border-red-200 text-red-700 hover:bg-red-50'
                          : 'border-emerald-200 text-emerald-700 hover:bg-emerald-50'
                      }`}
                    >
                      <RefreshCw
                        className={`h-3.5 w-3.5 ${savingAction === `secret-status-${secret.id}` ? 'animate-spin' : ''}`}
                      />
                      {secret.status === 'active' ? '停用' : '启用'}
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <EmptyRow colSpan={8} loading={loading} label="暂无项目密钥" />
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

function formatProviderLabel(value: string) {
  const labels: Record<string, string> = {
    dify: 'Dify',
    gitlab: 'GitLab',
    github: 'GitHub',
    openai: 'OpenAI',
    codex: 'Codex',
    custom: '自定义',
  };
  return labels[value] || value;
}

function identityLabel(value: string) {
  return value;
}

function confirmDangerousAction({
  title,
  target,
  description,
}: {
  title: string;
  target: string;
  description: string;
}) {
  const normalizedTarget = target.trim();
  if (!normalizedTarget) {
    return false;
  }
  const answer = window.prompt(`${title}\n${description}\n\n请输入「${normalizedTarget}」确认继续。`);
  return answer?.trim() === normalizedTarget;
}

function formatStatus(value: string) {
  const labels: Record<string, string> = {
    active: '启用',
    disabled: '停用',
  };
  return labels[value] || value;
}

function formatSecretHealth(value: string) {
  const labels: Record<string, string> = {
    healthy: '正常',
    expiring_soon: '即将过期',
    expired: '已过期',
    invalid: '不可用',
    disabled: '已停用',
    unknown: '未检查',
  };
  return labels[value] || value;
}

function ProviderHealthNote({ secret }: { secret: SecretRecord }) {
  const health = providerHealth(secret);
  if (!health) {
    return null;
  }
  return (
    <div className="mt-1 text-xs text-slate-500">
      远端：{formatSecretHealth(health.status)}
      {health.reason ? `，${health.reason}` : ''}
    </div>
  );
}

function providerHealth(secret: SecretRecord): { status: string; reason: string | null } | null {
  const raw = secret.metadata_json?.last_provider_health;
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const health = raw as Record<string, unknown>;
  const status = typeof health.status === 'string' ? health.status : '';
  if (!status) {
    return null;
  }
  return {
    status,
    reason: typeof health.reason === 'string' ? health.reason : null,
  };
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

function toDateTimeLocal(value?: string | null) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localDate.toISOString().slice(0, 16);
}

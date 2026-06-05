import { FormEvent, useEffect, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router';
import { GitBranch, Loader2, LogOut, Sparkles, UserRound } from 'lucide-react';
import { authApi, setAuthToken } from './lib/api';
import { canAdmin } from './lib/permissions';
import type { AuthUser } from './types';

const navItems = [
  { to: '/', label: '交付工作台' },
  { to: '/admin/access', label: '权限管理', adminOnly: true },
];

export type AppOutletContext = {
  user: AuthUser | null;
};

export default function Root() {
  const location = useLocation();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [loginRequired, setLoginRequired] = useState(false);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);

  const loadCurrentUser = async () => {
    setAuthLoading(true);
    try {
      const current = (await authApi.me()).data;
      setUser(current);
      setLoginRequired(false);
      setLoginError(null);
    } catch (err) {
      setUser(null);
      setLoginRequired(true);
      const message = err instanceof Error ? err.message : '需要登录后继续';
      setLoginError(message);
    } finally {
      setAuthLoading(false);
    }
  };

  useEffect(() => {
    void loadCurrentUser();
  }, []);

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginBusy(true);
    try {
      const response = (await authApi.login({ username, password })).data;
      setAuthToken(response.access_token);
      setUser(response.user);
      setLoginRequired(false);
      setLoginError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : '登录失败';
      setLoginError(message);
    } finally {
      setLoginBusy(false);
    }
  };

  const handleLogout = () => {
    setAuthToken(null);
    setUser(null);
    setLoginRequired(true);
  };

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-600">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        正在检查登录状态
      </div>
    );
  }

  if (loginRequired && !user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <form
          onSubmit={handleLogin}
          className="w-full max-w-sm rounded border border-slate-200 bg-white p-6 shadow-sm"
        >
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded bg-blue-600">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-slate-950">AI PJM</h1>
              <p className="text-sm text-slate-500">登录交付编排工作台</p>
            </div>
          </div>
          <label className="mb-4 block text-sm font-medium text-slate-700">
            用户名
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="mt-2 h-10 w-full rounded border border-slate-200 px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              autoComplete="username"
            />
          </label>
          <label className="mb-4 block text-sm font-medium text-slate-700">
            密码
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-2 h-10 w-full rounded border border-slate-200 px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              type="password"
              autoComplete="current-password"
            />
          </label>
          {loginError ? <div className="mb-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{loginError}</div> : null}
          <button
            type="submit"
            disabled={loginBusy || !username.trim() || !password}
            className="flex h-10 w-full items-center justify-center rounded bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {loginBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            登录
          </button>
        </form>
      </main>
    );
  }

  const outletContext: AppOutletContext = { user };

  return (
    <div className="min-h-screen overflow-x-hidden bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-3 py-3 sm:px-4 lg:flex-nowrap lg:px-8 lg:py-4">
          <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-6">
            <Link to="/" className="flex shrink-0 items-center gap-3 hover:opacity-85">
              <div className="flex h-8 w-8 items-center justify-center rounded bg-blue-600">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-950">AI PJM</div>
                <div className="text-xs text-slate-500">交付编排工作台</div>
              </div>
            </Link>
            <nav className="flex flex-wrap items-center gap-1">
              {navItems.filter((item) => !item.adminOnly || canAdmin(user)).map((item) => {
                const active = item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to);
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={`rounded px-3 py-2 text-sm transition-colors ${
                      active
                        ? 'bg-blue-50 font-medium text-blue-700'
                        : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950'
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {user ? (
              <div className="hidden items-center gap-2 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 md:flex">
                <UserRound className="h-4 w-4" />
                <span>{user.display_name}</span>
                <span className="text-slate-400">/</span>
                <span>{user.role}</span>
              </div>
            ) : null}
            <a
              href="http://localhost:8010/docs"
              target="_blank"
              rel="noreferrer"
              className="hidden items-center gap-2 rounded border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 md:inline-flex"
            >
              <GitBranch className="h-4 w-4" />
              接口文档
            </a>
            {user?.auth_enabled ? (
              <button
                type="button"
                onClick={handleLogout}
                className="inline-flex items-center gap-2 rounded border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                <LogOut className="h-4 w-4" />
                退出
              </button>
            ) : null}
          </div>
        </div>
      </header>
      <Outlet context={outletContext} />
    </div>
  );
}

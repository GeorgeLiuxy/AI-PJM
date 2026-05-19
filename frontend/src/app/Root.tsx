import { Link, Outlet, useLocation } from 'react-router';
import { GitBranch, Sparkles } from 'lucide-react';

const navItems = [
  { to: '/', label: 'Delivery' },
];

export default function Root() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-6 px-8 py-4">
          <div className="flex min-w-0 items-center gap-6">
            <Link to="/" className="flex shrink-0 items-center gap-3 hover:opacity-85">
              <div className="flex h-8 w-8 items-center justify-center rounded bg-blue-600">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-950">AI PJM</div>
                <div className="text-xs text-slate-500">Delivery orchestration</div>
              </div>
            </Link>
            <nav className="flex flex-wrap items-center gap-1">
              {navItems.map((item) => {
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
          <a
            href="http://localhost:8010/docs"
            target="_blank"
            rel="noreferrer"
            className="hidden items-center gap-2 rounded border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 md:inline-flex"
          >
            <GitBranch className="h-4 w-4" />
            API docs
          </a>
        </div>
      </header>
      <Outlet />
    </div>
  );
}

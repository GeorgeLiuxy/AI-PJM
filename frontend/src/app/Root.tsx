import { Outlet, Link, useLocation } from "react-router";
import { Sparkles } from "lucide-react";

export default function Root() {
  const location = useLocation();
  
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1400px] mx-auto px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
              <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-blue-600 rounded-lg flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <h1 className="text-lg font-medium text-gray-900">安全型团队提效 AI 工作台</h1>
            </Link>
            <nav className="flex items-center gap-1">
              <Link
                to="/"
                className={`px-3 py-2 text-sm rounded-lg transition-colors ${
                  location.pathname === "/" 
                    ? "bg-blue-50 text-blue-700 font-medium" 
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                工作台
              </Link>
              <Link
                to="/input"
                className={`px-3 py-2 text-sm rounded-lg transition-colors ${
                  location.pathname === "/input" 
                    ? "bg-blue-50 text-blue-700 font-medium" 
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                统一输入
              </Link>
              <Link
                to="/process"
                className={`px-3 py-2 text-sm rounded-lg transition-colors ${
                  location.pathname === "/process" 
                    ? "bg-blue-50 text-blue-700 font-medium" 
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                事项处理
              </Link>
              <Link
                to="/impact"
                className={`px-3 py-2 text-sm rounded-lg transition-colors ${
                  location.pathname === "/impact" 
                    ? "bg-blue-50 text-blue-700 font-medium" 
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                影响分析
              </Link>
              <Link
                to="/results"
                className={`px-3 py-2 text-sm rounded-lg transition-colors ${
                  location.pathname === "/results" 
                    ? "bg-blue-50 text-blue-700 font-medium" 
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                AI 结果
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <button className="text-sm text-gray-600 hover:text-gray-900">帮助</button>
            <div className="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center">
              <span className="text-sm font-medium text-gray-700">张</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <Outlet />
    </div>
  );
}
import React from "react";
import { NavLink, useNavigate, Outlet } from "react-router-dom";
import {
    LayoutDashboard, Boxes, ClipboardList, Bell, FileText,
    History, Users, Building2, LogOut, Stethoscope, Package, ShieldCheck
} from "lucide-react";
import { useAuth, hasRole } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/api";
import { Button } from "@/components/ui/button";

const NAV = [
    { to: "/", label: "لوحة المؤشرات", icon: LayoutDashboard, testid: "nav-dashboard",
      roles: null },
    { to: "/stock", label: "إدخال الرصيد", icon: Package, testid: "nav-stock",
      roles: ["super_admin","digital_health_manager","department_stock_officer","department_head","supply_officer","auditor","hospital_manager","quality"] },
    { to: "/items", label: "الأصناف", icon: Boxes, testid: "nav-items",
      roles: null },
    { to: "/requests", label: "الطلبات", icon: ClipboardList, testid: "nav-requests",
      roles: null },
    { to: "/alerts", label: "التنبيهات", icon: Bell, testid: "nav-alerts",
      roles: null },
    { to: "/reports", label: "التقارير", icon: FileText, testid: "nav-reports",
      roles: null },
    { to: "/audit-logs", label: "سجل التدقيق", icon: History, testid: "nav-audit",
      roles: ["super_admin","digital_health_manager","auditor"] },
    { to: "/users", label: "المستخدمون", icon: Users, testid: "nav-users",
      roles: ["super_admin","digital_health_manager"] },
    { to: "/departments", label: "الأقسام", icon: Building2, testid: "nav-departments",
      roles: ["super_admin","digital_health_manager"] },
];

export default function Layout() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();

    async function onLogout() {
        await logout();
        navigate("/login");
    }

    return (
        <div className="min-h-screen flex bg-[#F8FAFC]" dir="rtl">
            {/* Sidebar */}
            <aside className="w-64 bg-slate-900 text-slate-100 flex flex-col"
                   data-testid="app-sidebar">
                <div className="px-5 py-5 border-b border-slate-800">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-md bg-sky-600 flex items-center justify-center">
                            <Stethoscope className="w-6 h-6 text-white" />
                        </div>
                        <div>
                            <div className="font-heading font-bold text-base leading-tight">المخزون الطبي الحرج</div>
                            <div className="text-xs text-slate-400">Critical Stock Monitor</div>
                        </div>
                    </div>
                </div>

                <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
                    {NAV.filter((n) => !n.roles || hasRole(user, ...n.roles)).map((n) => (
                        <NavLink
                            key={n.to}
                            to={n.to}
                            end={n.to === "/"}
                            data-testid={n.testid}
                            className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                        >
                            <n.icon className="w-5 h-5" />
                            {n.label}
                        </NavLink>
                    ))}
                </nav>

                <div className="border-t border-slate-800 p-3">
                    <div className="px-2 pb-2">
                        <div className="text-sm font-bold text-white truncate" data-testid="current-user-name">
                            {user?.full_name}
                        </div>
                        <div className="text-xs text-slate-400">{ROLE_LABELS[user?.role] || user?.role}</div>
                    </div>
                    <Button
                        onClick={onLogout}
                        variant="ghost"
                        className="w-full justify-start text-slate-200 hover:bg-slate-800 hover:text-white"
                        data-testid="logout-button"
                    >
                        <LogOut className="w-4 h-4 ms-0 me-2" />
                        تسجيل الخروج
                    </Button>
                </div>
            </aside>

            {/* Main */}
            <main className="flex-1 min-w-0">
                <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-slate-700">
                        <ShieldCheck className="w-4 h-4 text-sky-600" />
                        <span className="text-xs font-bold tracking-wider uppercase text-slate-500">
                            نظام مراقبة المخزون الطبي الحرج
                        </span>
                    </div>
                    <div className="text-xs text-slate-500" dir="ltr">
                        {new Date().toLocaleString("ar-SA")}
                    </div>
                </header>
                <div className="p-6">
                    <Outlet />
                </div>
            </main>
        </div>
    );
}

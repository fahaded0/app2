import React from "react";
import { NavLink, useNavigate, Outlet } from "react-router-dom";
import {
    LayoutDashboard, Boxes, ClipboardList, Bell, FileText,
    History, Users, Building2, LogOut, Stethoscope, Package, ShieldCheck,
    FileSpreadsheet, Sliders
} from "lucide-react";
import { useAuth, hasRole } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/api";
import { Button } from "@/components/ui/button";

const NAV = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard",
      roles: null },
    { to: "/stock", label: "Stock Entry", icon: Package, testid: "nav-stock",
      roles: ["super_admin","digital_health_manager","department_stock_officer","department_head","supply_officer","auditor","hospital_manager","quality"] },
    { to: "/items", label: "Items", icon: Boxes, testid: "nav-items",
      roles: null },
    { to: "/items/import", label: "Excel Import", icon: FileSpreadsheet, testid: "nav-import",
      roles: ["super_admin","digital_health_manager","supply_officer"] },
    { to: "/requests", label: "Requests", icon: ClipboardList, testid: "nav-requests",
      roles: null },
    { to: "/alerts", label: "Alerts", icon: Bell, testid: "nav-alerts",
      roles: null },
    { to: "/reports", label: "Reports", icon: FileText, testid: "nav-reports",
      roles: null },
    { to: "/settings", label: "Settings", icon: Sliders, testid: "nav-settings",
      roles: ["super_admin","digital_health_manager","hospital_manager","auditor"] },
    { to: "/audit-logs", label: "Audit Log", icon: History, testid: "nav-audit",
      roles: ["super_admin","digital_health_manager","auditor"] },
    { to: "/users", label: "Users", icon: Users, testid: "nav-users",
      roles: ["super_admin","digital_health_manager"] },
    { to: "/departments", label: "Departments", icon: Building2, testid: "nav-departments",
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
        <div className="min-h-screen flex bg-[#F8FAFC]">
            {/* Sidebar */}
            <aside className="w-64 bg-slate-900 text-slate-100 flex flex-col"
                   data-testid="app-sidebar">
                <div className="px-5 py-5 border-b border-slate-800">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-md bg-sky-600 flex items-center justify-center shrink-0">
                            <Stethoscope className="w-6 h-6 text-white" />
                        </div>
                        <div className="min-w-0">
                            <div className="font-heading font-bold text-base leading-tight">Critical Stock</div>
                            <div className="text-xs text-slate-400">Monitor &amp; Alert System</div>
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
                        <LogOut className="w-4 h-4 mr-2" />
                        Logout
                    </Button>
                </div>
            </aside>

            {/* Main */}
            <main className="flex-1 min-w-0">
                <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-slate-700">
                        <ShieldCheck className="w-4 h-4 text-sky-600" />
                        <span className="text-xs font-bold tracking-wider uppercase text-slate-500">
                            Critical Medical Stock Monitoring System
                        </span>
                    </div>
                    <div className="text-xs text-slate-500 font-mono">
                        {new Date().toLocaleString("en-GB", { hour12: false })}
                    </div>
                </header>
                <div className="p-6">
                    <Outlet />
                </div>
            </main>
        </div>
    );
}

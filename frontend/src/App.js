import React from "react";
import {
    BrowserRouter, Routes, Route, Navigate, useLocation
} from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import RoleGuard from "@/components/RoleGuard";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Items from "@/pages/Items";
import ImportItems from "@/pages/ImportItems";
import Stock from "@/pages/Stock";
import Requests from "@/pages/Requests";
import Alerts from "@/pages/Alerts";
import Reports from "@/pages/Reports";
import AuditLog from "@/pages/AuditLog";
import Users from "@/pages/Users";
import Departments from "@/pages/Departments";
import Settings from "@/pages/Settings";

function ProtectedRoute({ children }) {
    const { user, ready } = useAuth();
    const location = useLocation();
    if (!ready) {
        return (
            <div className="min-h-screen flex items-center justify-center text-slate-500">
                جاري التحميل...
            </div>
        );
    }
    if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
    return children;
}

function App() {
    return (
        <AuthProvider>
            <BrowserRouter>
                <Routes>
                    <Route path="/login" element={<Login />} />
                    <Route
                        element={
                            <ProtectedRoute>
                                <Layout />
                            </ProtectedRoute>
                        }
                    >
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/items" element={<Items />} />
                        <Route path="/items/import" element={
                            <RoleGuard roles={["super_admin","digital_health_manager","supply_officer"]}>
                                <ImportItems />
                            </RoleGuard>
                        } />
                        <Route path="/stock" element={<Stock />} />
                        <Route path="/requests" element={<Requests />} />
                        <Route path="/alerts" element={<Alerts />} />
                        <Route path="/reports" element={<Reports />} />
                        <Route path="/settings" element={
                            <RoleGuard roles={["super_admin","digital_health_manager","hospital_manager","auditor"]}>
                                <Settings />
                            </RoleGuard>
                        } />
                        <Route path="/audit-logs" element={
                            <RoleGuard roles={["super_admin","digital_health_manager","auditor"]}>
                                <AuditLog />
                            </RoleGuard>
                        } />
                        <Route path="/users" element={
                            <RoleGuard roles={["super_admin","digital_health_manager"]}>
                                <Users />
                            </RoleGuard>
                        } />
                        <Route path="/departments" element={
                            <RoleGuard roles={["super_admin","digital_health_manager"]}>
                                <Departments />
                            </RoleGuard>
                        } />
                    </Route>
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
            <Toaster position="top-center" richColors />
        </AuthProvider>
    );
}

export default App;

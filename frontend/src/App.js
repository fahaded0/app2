import React from "react";
import {
    BrowserRouter, Routes, Route, Navigate, useLocation
} from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Items from "@/pages/Items";
import Stock from "@/pages/Stock";
import Requests from "@/pages/Requests";
import Alerts from "@/pages/Alerts";
import Reports from "@/pages/Reports";
import AuditLog from "@/pages/AuditLog";
import Users from "@/pages/Users";
import Departments from "@/pages/Departments";

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
                        <Route path="/stock" element={<Stock />} />
                        <Route path="/requests" element={<Requests />} />
                        <Route path="/alerts" element={<Alerts />} />
                        <Route path="/reports" element={<Reports />} />
                        <Route path="/audit-logs" element={<AuditLog />} />
                        <Route path="/users" element={<Users />} />
                        <Route path="/departments" element={<Departments />} />
                    </Route>
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
            <Toaster position="top-center" richColors />
        </AuthProvider>
    );
}

export default App;

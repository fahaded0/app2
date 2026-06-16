import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);     // null = checking
    const [ready, setReady] = useState(false);

    useEffect(() => {
        const token = localStorage.getItem("access_token");
        if (!token) {
            setUser(false);
            setReady(true);
            return;
        }
        api.get("/auth/me")
            .then((r) => setUser(r.data))
            .catch(() => {
                localStorage.removeItem("access_token");
                setUser(false);
            })
            .finally(() => setReady(true));
    }, []);

    async function login(email, password) {
        const { data } = await api.post("/auth/login", { email, password });
        localStorage.setItem("access_token", data.access_token);
        setUser(data.user);
        return data.user;
    }

    async function logout() {
        try { await api.post("/auth/logout"); } catch (_) {}
        localStorage.removeItem("access_token");
        setUser(false);
    }

    return (
        <AuthContext.Provider value={{ user, login, logout, ready }}>
            {children}
        </AuthContext.Provider>
    );
}

export const useAuth = () => useContext(AuthContext);

export function hasRole(user, ...roles) {
    if (!user) return false;
    if (user.role === "super_admin") return true;
    return roles.includes(user.role);
}

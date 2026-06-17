import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Stethoscope, Lock, Mail } from "lucide-react";

export default function Login() {
    const { user, login } = useAuth();
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    if (user) return <Navigate to="/" replace />;

    async function onSubmit(e) {
        e.preventDefault();
        setLoading(true);
        setError("");
        try {
            await login(email, password);
            navigate("/");
        } catch (err) {
            setError(formatApiError(err));
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="min-h-screen flex bg-slate-50">
            {/* Left side - image panel */}
            <div className="hidden lg:block w-1/2 relative overflow-hidden">
                <img
                    src="https://customer-assets.emergentagent.com/job_reverent-galois-8/artifacts/ii1jbr7e_unnamed.jpg"
                    alt="Makkah Health Cluster"
                    className="absolute inset-0 w-full h-full object-cover"
                />
                <div className="absolute inset-0 bg-gradient-to-b from-slate-900/50 to-sky-900/70" />
                <div className="absolute inset-0 flex flex-col justify-end p-10 text-white">
                    <h2 className="font-heading text-3xl font-black leading-tight mb-3">
                        From spreadsheet to real-time operational system
                    </h2>
                    <p className="text-sm text-slate-100/90 leading-relaxed max-w-md">
                        Track zero-stock, critical-stock, and backorder items across every
                        department with automated alerts, escalation, and a full audit trail to
                        protect patient safety.
                    </p>
                </div>
            </div>

            {/* Right side - form */}
            <div className="flex-1 flex items-center justify-center p-6">
                <div className="w-full max-w-md">
                    <div className="flex items-center gap-3 mb-8">
                        <div className="w-12 h-12 rounded-md bg-sky-600 flex items-center justify-center">
                            <Stethoscope className="w-7 h-7 text-white" />
                        </div>
                        <div>
                            <h1 className="font-heading font-bold text-xl text-slate-900 leading-tight">
                                Critical Medical Stock
                            </h1>
                            <p className="text-xs text-slate-500">Monitoring &amp; Alerting System</p>
                        </div>
                    </div>

                    <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm">
                        <h2 className="font-heading text-2xl font-bold mb-2">Sign in</h2>
                        <p className="text-sm text-slate-500 mb-6">Use your authorised credentials to access the system.</p>

                        <form onSubmit={onSubmit} className="space-y-4">
                            <div>
                                <Label htmlFor="email" className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-600">Email</Label>
                                <div className="relative">
                                    <Mail className="w-4 h-4 absolute top-1/2 -translate-y-1/2 left-3 text-slate-400 pointer-events-none" />
                                    <Input
                                        id="email" type="email" required
                                        data-testid="login-email-input"
                                        className="pl-9"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        placeholder="name@medstock.sa"
                                    />
                                </div>
                            </div>

                            <div>
                                <Label htmlFor="password" className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-600">Password</Label>
                                <div className="relative">
                                    <Lock className="w-4 h-4 absolute top-1/2 -translate-y-1/2 left-3 text-slate-400 pointer-events-none" />
                                    <Input
                                        id="password" type="password" required
                                        data-testid="login-password-input"
                                        className="pl-9"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                    />
                                </div>
                            </div>

                            {error && (
                                <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-3"
                                     data-testid="login-error">
                                    {error}
                                </div>
                            )}

                            <Button
                                type="submit"
                                disabled={loading}
                                className="w-full bg-sky-600 hover:bg-sky-700 text-white font-bold py-2.5"
                                data-testid="login-submit-button"
                            >
                                {loading ? "Signing in..." : "Sign in"}
                            </Button>
                        </form>

                        <div className="mt-6 pt-5 border-t border-slate-200 text-xs text-slate-500">
                            <div className="font-bold mb-1 text-slate-700">Demo accounts:</div>
                            <ul className="space-y-1 font-mono">
                                <li>admin@medstock.sa / Admin@12345</li>
                                <li>head.er@medstock.sa / Head@12345</li>
                                <li>officer.er@medstock.sa / Officer@12345</li>
                                <li>supply@medstock.sa / Supply@12345</li>
                            </ul>
                        </div>
                    </div>

                    <p className="text-center text-xs text-slate-400 mt-6">
                        Secured with JWT + RBAC · Aligned with OWASP ASVS
                    </p>
                </div>
            </div>
        </div>
    );
}

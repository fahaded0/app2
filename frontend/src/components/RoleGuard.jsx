import React from "react";
import { ShieldX } from "lucide-react";
import { useAuth, hasRole } from "@/lib/auth";

/**
 * Route-level role guard. If user lacks any of `roles`, shows a forbidden
 * message instead of letting the page mount (and produce 403s).
 */
export default function RoleGuard({ roles, children }) {
    const { user } = useAuth();
    if (!user) return null;
    if (!roles || roles.length === 0) return children;
    if (!hasRole(user, ...roles)) {
        return (
            <div className="flex flex-col items-center justify-center py-24 text-center"
                 data-testid="forbidden-message">
                <div className="w-16 h-16 rounded-full bg-red-50 border border-red-200 flex items-center justify-center mb-4">
                    <ShieldX className="w-8 h-8 text-red-600" />
                </div>
                <h2 className="font-heading text-2xl font-black text-slate-900 mb-2">
                    Access Denied
                </h2>
                <p className="text-sm text-slate-500 max-w-md">
                    This screen is reserved for specific roles. If you believe this is an
                    error, please contact your system administrator to request the appropriate
                    permission.
                </p>
            </div>
        );
    }
    return children;
}

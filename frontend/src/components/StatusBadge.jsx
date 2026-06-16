import React from "react";
import { STATUS_LABELS, REQ_STATUS_LABELS } from "@/lib/api";
import { AlertCircle, AlertTriangle, CheckCircle2, RefreshCw, Clock } from "lucide-react";

export function StatusBadge({ status, size = "md" }) {
    const label = STATUS_LABELS[status] || status;
    let cls = "status-pill ";
    let Icon = CheckCircle2;
    switch (status) {
        case "zero_level":     cls += "status-zero"; Icon = AlertCircle; break;
        case "critical_level": cls += "status-critical"; Icon = AlertTriangle; break;
        case "available":      cls += "status-available"; Icon = CheckCircle2; break;
        case "back_in_stock":  cls += "status-back"; Icon = RefreshCw; break;
        case "backorder":      cls += "status-backorder"; Icon = Clock; break;
        default: cls += "status-available";
    }
    return (
        <span className={cls} data-testid={`status-badge-${status}`}>
            <Icon className={size === "sm" ? "w-3 h-3" : "w-3.5 h-3.5"} />
            {label}
        </span>
    );
}

export function RequestStatusBadge({ status }) {
    const label = REQ_STATUS_LABELS[status] || status;
    let color = "bg-slate-100 text-slate-700 border-slate-200";
    switch (status) {
        case "pending_approval": color = "bg-amber-50 text-amber-700 border-amber-200"; break;
        case "approved":         color = "bg-sky-50 text-sky-700 border-sky-200"; break;
        case "rejected":         color = "bg-red-50 text-red-700 border-red-200"; break;
        case "dispatched":       color = "bg-indigo-50 text-indigo-700 border-indigo-200"; break;
        case "partially_received": color = "bg-cyan-50 text-cyan-700 border-cyan-200"; break;
        case "received":         color = "bg-teal-50 text-teal-700 border-teal-200"; break;
        case "closed":           color = "bg-slate-100 text-slate-700 border-slate-200"; break;
        case "backorder":        color = "bg-purple-50 text-purple-700 border-purple-200"; break;
        default: break;
    }
    return (
        <span className={`inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-bold whitespace-nowrap ${color}`}>
            {label}
        </span>
    );
}

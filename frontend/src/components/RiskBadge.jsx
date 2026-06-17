import React from "react";
import {
    AlertCircle, AlertTriangle, CheckCircle2, ShieldAlert, Siren, Ban,
} from "lucide-react";

const STYLES = {
    normal:             { bg: "bg-emerald-50",  text: "text-emerald-800",  border: "border-emerald-200",
                          Icon: CheckCircle2, label: "Normal" },
    below_minimum:      { bg: "bg-amber-50",    text: "text-amber-800",    border: "border-amber-200",
                          Icon: AlertCircle,  label: "Below Minimum" },
    below_critical:     { bg: "bg-orange-50",   text: "text-orange-800",   border: "border-orange-200",
                          Icon: AlertTriangle,label: "Critical Level" },
    blocked_no_issue:   { bg: "bg-red-50",      text: "text-red-800",      border: "border-red-200",
                          Icon: Ban,          label: "Blocked — No Issue" },
    emergency_override: { bg: "bg-rose-50",     text: "text-rose-800",     border: "border-rose-200",
                          Icon: Siren,        label: "Emergency Override" },
    insufficient:       { bg: "bg-slate-100",   text: "text-slate-700",    border: "border-slate-300",
                          Icon: ShieldAlert,  label: "Insufficient Stock" },
};

export default function RiskBadge({ rule, size = "md", insufficient = false }) {
    const key = insufficient ? "insufficient" : (rule || "normal");
    const s = STYLES[key] || STYLES.normal;
    const pad = size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-3 py-1 text-xs";
    const iconSize = size === "sm" ? "w-3 h-3" : "w-3.5 h-3.5";
    return (
        <span className={`inline-flex items-center gap-1.5 rounded-md border font-bold uppercase tracking-wider ${pad} ${s.bg} ${s.text} ${s.border}`}
              data-testid={`risk-badge-${key}`}>
            <s.Icon className={iconSize} />
            {s.label}
        </span>
    );
}

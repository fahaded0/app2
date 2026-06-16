import React, { useEffect, useState } from "react";
import { api, formatApiError, fmtDate, ROLE_LABELS } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from "@/components/ui/dialog";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select";
import {
    AlertCircle, AlertTriangle, Bell, Clock, Heart, ShieldCheck, PlayCircle,
    CheckCircle2, Archive, ArrowUpRight
} from "lucide-react";
import { toast } from "sonner";
import { useAuth, hasRole } from "@/lib/auth";

const SEVERITY_BG = {
    critical: "border-red-400 bg-red-50",
    danger:   "border-red-300 bg-red-50/70",
    warning:  "border-amber-300 bg-amber-50/70",
    info:     "border-sky-300 bg-sky-50/70",
};
const SEVERITY_ICON = {
    critical: AlertCircle, danger: AlertCircle, warning: AlertTriangle, info: Bell,
};
const SEVERITY_LABEL = {
    critical: "Critical", danger: "Danger", warning: "Warning", info: "Info",
};
const STATUS_LABEL = {
    open: "Open", acknowledged: "Acknowledged", in_progress: "In Progress",
    resolved: "Resolved", closed: "Closed",
};
const STATUS_COLOR = {
    open: "bg-red-100 text-red-700 border-red-200",
    acknowledged: "bg-sky-100 text-sky-700 border-sky-200",
    in_progress: "bg-amber-100 text-amber-700 border-amber-200",
    resolved: "bg-emerald-100 text-emerald-700 border-emerald-200",
    closed: "bg-slate-100 text-slate-700 border-slate-200",
};

export default function Alerts() {
    const { user } = useAuth();
    const canClose = hasRole(user, "super_admin", "digital_health_manager", "hospital_manager");

    const [alerts, setAlerts] = useState([]);
    const [statusFilter, setStatusFilter] = useState("open");
    const [severityFilter, setSeverityFilter] = useState("all");
    const [resolveDialog, setResolveDialog] = useState(null);
    const [resolveNote, setResolveNote] = useState("");

    function load() {
        const params = {};
        if (statusFilter && statusFilter !== "all") params.status = statusFilter;
        if (severityFilter !== "all") params.severity = severityFilter;
        api.get("/alerts", { params }).then((r) => setAlerts(r.data));
    }
    useEffect(load, [statusFilter, severityFilter]);

    async function doAction(id, path, body) {
        try {
            await api.post(`/alerts/${id}/${path}`, body || {});
            toast.success("Updated");
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }

    async function submitResolve() {
        if (!resolveDialog) return;
        await doAction(resolveDialog.id, "resolve", { note: resolveNote || null });
        setResolveDialog(null);
        setResolveNote("");
    }

    return (
        <div className="space-y-5" data-testid="alerts-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">Alerts</h1>
                <div className="flex items-center gap-3">
                    <Select value={severityFilter} onValueChange={setSeverityFilter}>
                        <SelectTrigger className="w-44" data-testid="alerts-severity-filter">
                            <SelectValue placeholder="All Severities" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">All Severities</SelectItem>
                            <SelectItem value="critical">Critical</SelectItem>
                            <SelectItem value="danger">Danger</SelectItem>
                            <SelectItem value="warning">Warning</SelectItem>
                            <SelectItem value="info">Info</SelectItem>
                        </SelectContent>
                    </Select>
                    <Select value={statusFilter} onValueChange={setStatusFilter}>
                        <SelectTrigger className="w-44" data-testid="alerts-status-filter">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="open">Open (active)</SelectItem>
                            <SelectItem value="acknowledged">Acknowledged</SelectItem>
                            <SelectItem value="in_progress">In Progress</SelectItem>
                            <SelectItem value="resolved">Resolved</SelectItem>
                            <SelectItem value="closed">Closed</SelectItem>
                            <SelectItem value="all">All</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>

            {alerts.length === 0 ? (
                <div className="bg-white border border-slate-200 rounded-lg p-10 text-center">
                    <ShieldCheck className="w-12 h-12 mx-auto text-emerald-500 mb-2" />
                    <div className="font-bold">No alerts in this view</div>
                    <div className="text-sm text-slate-500">Try changing the status filter.</div>
                </div>
            ) : (
                <div className="space-y-3">
                    {alerts.map((a) => {
                        const Icon = SEVERITY_ICON[a.severity] || Bell;
                        const status = a.status || (a.acknowledged ? "acknowledged" : "open");
                        const level = a.escalation_level || 0;
                        return (
                            <div key={a.id}
                                 data-testid={`alert-card-${a.id}`}
                                 className={`border rounded-lg p-4 transition-all ${
                                    SEVERITY_BG[a.severity] || "border-slate-200 bg-white"
                                 } ${status === "closed" || status === "resolved" ? "opacity-70" : ""}`}>
                                <div className="flex items-start gap-4">
                                    <div className={`shrink-0 w-10 h-10 rounded-md flex items-center justify-center ${
                                        a.severity === "critical" || a.severity === "danger" ? "bg-red-100 text-red-700" :
                                        a.severity === "warning" ? "bg-amber-100 text-amber-700" :
                                        "bg-sky-100 text-sky-700"
                                    }`}>
                                        <Icon className="w-5 h-5" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap mb-1">
                                            <div className="font-bold text-base">{a.title}</div>
                                            <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${STATUS_COLOR[status]}`}>
                                                {STATUS_LABEL[status]}
                                            </span>
                                            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                                                {SEVERITY_LABEL[a.severity]}
                                            </span>
                                            {a.item?.is_life_saving && (
                                                <span className="status-pill status-zero text-[10px]">
                                                    <Heart className="w-3 h-3" />Life-Saving
                                                </span>
                                            )}
                                            {level > 0 && (
                                                <span className="inline-flex items-center gap-1 rounded-md border border-purple-300 bg-purple-100 text-purple-700 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider">
                                                    <ArrowUpRight className="w-3 h-3" /> Escalation L{level}
                                                </span>
                                            )}
                                        </div>
                                        <div className="text-sm text-slate-700 mb-2">{a.message}</div>
                                        <div className="flex flex-wrap gap-4 text-xs text-slate-500">
                                            {a.department && (
                                                <span>Department: <b>{a.department.name_en} ({a.department.code})</b></span>
                                            )}
                                            {a.item && (
                                                <span>Item: <b>{a.item.name_en}</b></span>
                                            )}
                                            <span className="inline-flex items-center gap-1 font-mono">
                                                <Clock className="w-3 h-3" />
                                                {fmtDate(a.created_at)}
                                            </span>
                                        </div>
                                        {a.escalations && a.escalations.length > 0 && (
                                            <div className="mt-2 text-xs text-slate-600 bg-white/60 border border-slate-200 rounded-md p-2">
                                                <div className="font-bold mb-1 text-slate-700">Escalation trail:</div>
                                                <ul className="space-y-0.5">
                                                    {a.escalations.map((e, i) => (
                                                        <li key={i} className="font-mono">
                                                            L{e.level} → <b>{ROLE_LABELS[e.escalated_to] || e.escalated_to}</b> · {fmtDate(e.at)} — {e.reason}
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}
                                        {a.resolution_note && (
                                            <div className="mt-2 text-xs bg-emerald-50 border border-emerald-200 rounded-md p-2 text-emerald-900">
                                                <b>Resolution:</b> {a.resolution_note}
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex flex-col items-stretch gap-1 shrink-0">
                                        {status === "open" && (
                                            <Button onClick={() => doAction(a.id, "acknowledge")} size="sm" variant="outline"
                                                    data-testid={`acknowledge-alert-${a.id}`}>
                                                <ShieldCheck className="w-4 h-4 mr-1" /> Acknowledge
                                            </Button>
                                        )}
                                        {(status === "open" || status === "acknowledged") && (
                                            <Button onClick={() => doAction(a.id, "start")} size="sm" variant="outline"
                                                    className="text-amber-700 border-amber-300"
                                                    data-testid={`start-alert-${a.id}`}>
                                                <PlayCircle className="w-4 h-4 mr-1" /> Start
                                            </Button>
                                        )}
                                        {(status === "open" || status === "acknowledged" || status === "in_progress") && (
                                            <Button onClick={() => { setResolveDialog(a); setResolveNote(""); }}
                                                    size="sm" variant="outline"
                                                    className="text-emerald-700 border-emerald-300"
                                                    data-testid={`resolve-alert-${a.id}`}>
                                                <CheckCircle2 className="w-4 h-4 mr-1" /> Resolve
                                            </Button>
                                        )}
                                        {status === "resolved" && canClose && (
                                            <Button onClick={() => doAction(a.id, "close")} size="sm" variant="outline"
                                                    data-testid={`close-alert-${a.id}`}>
                                                <Archive className="w-4 h-4 mr-1" /> Close
                                            </Button>
                                        )}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            <Dialog open={!!resolveDialog} onOpenChange={(o) => !o && setResolveDialog(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Resolve Alert</DialogTitle>
                    </DialogHeader>
                    {resolveDialog && (
                        <div className="space-y-3">
                            <div className="bg-slate-50 border border-slate-200 rounded-md p-3 text-sm">
                                <div className="font-bold">{resolveDialog.title}</div>
                                <div className="text-xs text-slate-500">{resolveDialog.message}</div>
                            </div>
                            <div>
                                <Label className="text-xs font-bold">Resolution Note</Label>
                                <Input value={resolveNote} placeholder="What action was taken to resolve this?"
                                       data-testid="resolve-note-input"
                                       onChange={(e) => setResolveNote(e.target.value)} />
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setResolveDialog(null)}>Cancel</Button>
                        <Button onClick={submitResolve} className="bg-emerald-600 hover:bg-emerald-700"
                                data-testid="submit-resolve-button">Resolve</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

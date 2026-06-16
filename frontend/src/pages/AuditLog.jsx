import React, { useEffect, useState } from "react";
import { api, ROLE_LABELS, fmtDate } from "@/lib/api";
import {
    Table, TableHeader, TableBody, TableRow, TableHead, TableCell
} from "@/components/ui/table";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select";

export default function AuditLog() {
    const [logs, setLogs] = useState([]);
    const [filter, setFilter] = useState("all");

    function load() {
        const params = {};
        if (filter !== "all") params.entity = filter;
        api.get("/audit-logs", { params }).then((r) => setLogs(r.data));
    }
    useEffect(load, [filter]);

    return (
        <div className="space-y-5" data-testid="audit-page">
            <h1 className="font-heading text-3xl font-black tracking-tight">Audit Log</h1>

            <div className="flex items-center gap-3 bg-white border border-slate-200 rounded-lg p-3">
                <Select value={filter} onValueChange={setFilter}>
                    <SelectTrigger className="w-56" data-testid="audit-filter">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All Activities</SelectItem>
                        <SelectItem value="auth">Authentication</SelectItem>
                        <SelectItem value="users">Users</SelectItem>
                        <SelectItem value="items">Items</SelectItem>
                        <SelectItem value="stock_entries">Stock</SelectItem>
                        <SelectItem value="requests">Requests</SelectItem>
                        <SelectItem value="alerts">Alerts</SelectItem>
                    </SelectContent>
                </Select>
                <div className="text-sm text-slate-500">Events: <b className="tabular-nums">{logs.length}</b></div>
                <div className="text-xs text-slate-400 ml-auto">Tamper-proof log</div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="w-44">Timestamp</TableHead>
                            <TableHead>User</TableHead>
                            <TableHead className="w-44">Role</TableHead>
                            <TableHead className="w-44">Action</TableHead>
                            <TableHead className="w-32">Entity</TableHead>
                            <TableHead className="w-28">Entity ID</TableHead>
                            <TableHead className="w-32">IP</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {logs.map((l, i) => (
                            <TableRow key={l.id || i} className="hover:bg-slate-50" data-testid={`audit-row-${l.id || i}`}>
                                <TableCell className="text-xs text-slate-500 font-mono">{fmtDate(l.created_at)}</TableCell>
                                <TableCell className="text-sm font-mono">{l.user_email || "—"}</TableCell>
                                <TableCell className="text-xs">{ROLE_LABELS[l.user_role] || l.user_role || "—"}</TableCell>
                                <TableCell><span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">{l.action}</span></TableCell>
                                <TableCell className="text-xs">{l.entity}</TableCell>
                                <TableCell className="code-cell text-slate-500">
                                    {l.entity_id ? l.entity_id.slice(0, 8) : "—"}
                                </TableCell>
                                <TableCell className="code-cell text-slate-500">{l.ip || "—"}</TableCell>
                            </TableRow>
                        ))}
                        {logs.length === 0 && (
                            <TableRow><TableCell colSpan={7} className="text-center py-10 text-slate-500">No events</TableCell></TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}

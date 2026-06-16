import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
    Table, TableHeader, TableBody, TableRow, TableHead, TableCell
} from "@/components/ui/table";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select";
import { ROLE_LABELS } from "@/lib/api";

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
            <h1 className="font-heading text-3xl font-black tracking-tight">سجل التدقيق</h1>

            <div className="flex items-center gap-3 bg-white border border-slate-200 rounded-lg p-3">
                <Select value={filter} onValueChange={setFilter}>
                    <SelectTrigger className="w-56" data-testid="audit-filter">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">كل الأنشطة</SelectItem>
                        <SelectItem value="auth">المصادقة</SelectItem>
                        <SelectItem value="users">المستخدمون</SelectItem>
                        <SelectItem value="items">الأصناف</SelectItem>
                        <SelectItem value="stock_entries">الرصيد</SelectItem>
                        <SelectItem value="requests">الطلبات</SelectItem>
                        <SelectItem value="alerts">التنبيهات</SelectItem>
                    </SelectContent>
                </Select>
                <div className="text-sm text-slate-500">الأحداث: <b>{logs.length}</b></div>
                <div className="text-xs text-slate-400 ms-auto">سجل لا يقبل التعديل</div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="text-start">التاريخ</TableHead>
                            <TableHead className="text-start">المستخدم</TableHead>
                            <TableHead className="text-start">الدور</TableHead>
                            <TableHead className="text-start">الإجراء</TableHead>
                            <TableHead className="text-start">الكيان</TableHead>
                            <TableHead className="text-start">المعرف</TableHead>
                            <TableHead className="text-start">IP</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {logs.map((l, i) => (
                            <TableRow key={l.id || i} className="hover:bg-slate-50" data-testid={`audit-row-${l.id || i}`}>
                                <TableCell className="text-xs text-slate-500" dir="ltr">
                                    {new Date(l.created_at).toLocaleString("ar-SA")}
                                </TableCell>
                                <TableCell className="text-xs" dir="ltr">{l.user_email || "—"}</TableCell>
                                <TableCell className="text-xs">{ROLE_LABELS[l.user_role] || l.user_role || "—"}</TableCell>
                                <TableCell><span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">{l.action}</span></TableCell>
                                <TableCell className="text-xs">{l.entity}</TableCell>
                                <TableCell className="text-xs font-mono text-slate-500" dir="ltr">
                                    {l.entity_id ? l.entity_id.slice(0, 8) : "—"}
                                </TableCell>
                                <TableCell className="text-xs font-mono text-slate-500" dir="ltr">{l.ip || "—"}</TableCell>
                            </TableRow>
                        ))}
                        {logs.length === 0 && (
                            <TableRow><TableCell colSpan={7} className="text-center py-10 text-slate-500">لا توجد أحداث</TableCell></TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}

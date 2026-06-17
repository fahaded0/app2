import React, { useEffect, useState } from "react";
import { api, formatApiError, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import {
    Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";
import {
    History, Heart, Siren, ArrowRight, Filter, Download,
} from "lucide-react";
import { toast } from "sonner";

const ENTRY_TYPE_LABELS = {
    issue: "Issue",
    receive: "Receive",
    adjustment: "Adjustment",
    opening_balance: "Opening",
    physical_count: "Count",
    transfer_in: "Transfer In",
    transfer_out: "Transfer Out",
    return: "Return",
};

function TypePill({ type, override }) {
    const t = type || "issue";
    const color =
        t === "issue" ? "bg-orange-50 text-orange-700 border-orange-200"
      : t === "receive" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : t === "adjustment" ? "bg-amber-50 text-amber-700 border-amber-200"
      : "bg-slate-100 text-slate-700 border-slate-200";
    return (
        <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ${color}`}>
            {ENTRY_TYPE_LABELS[t] || t}
            {override && (
                <span title="Override" className="inline-flex items-center text-rose-600">
                    <Siren className="w-3 h-3 ml-0.5" />
                </span>
            )}
        </span>
    );
}

const isDeptStaff = (role) =>
    ["department_stock_officer", "department_head"].includes(role);

export default function StockTransactions() {
    const { user } = useAuth();
    const lockedDept = isDeptStaff(user.role);

    const [departments, setDepartments] = useState([]);
    const [items, setItems] = useState([]);
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(false);

    const [departmentId, setDepartmentId] = useState(lockedDept ? user.department_id || "all" : "all");
    const [itemId, setItemId] = useState("all");
    const [entryType, setEntryType] = useState("all");
    const [overrideOnly, setOverrideOnly] = useState(false);
    const [dateFrom, setDateFrom] = useState("");
    const [dateTo, setDateTo] = useState("");

    useEffect(() => {
        api.get("/departments").then((r) => setDepartments(r.data));
        api.get("/items").then((r) => setItems(r.data));
    }, []);

    function load() {
        setLoading(true);
        const params = {};
        if (departmentId && departmentId !== "all") params.department_id = departmentId;
        if (itemId && itemId !== "all") params.item_id = itemId;
        if (entryType && entryType !== "all") params.entry_type = entryType;
        if (overrideOnly) params.override_only = true;
        if (dateFrom) params.date_from = new Date(dateFrom).toISOString();
        if (dateTo) {
            const d = new Date(dateTo);
            d.setHours(23, 59, 59, 999);
            params.date_to = d.toISOString();
        }
        api.get("/stock/transactions", { params })
            .then((r) => setRows(r.data || []))
            .catch((e) => toast.error(formatApiError(e)))
            .finally(() => setLoading(false));
    }

    useEffect(load, [departmentId, itemId, entryType, overrideOnly, dateFrom, dateTo]);

    function exportCsv() {
        const headers = [
            "created_at", "department", "item_code", "item_name",
            "entry_type", "previous_balance", "new_balance", "delta",
            "override_flag", "decision_rule", "reference_no", "user_name", "notes",
        ];
        const lines = [headers.join(",")];
        for (const r of rows) {
            const cells = [
                r.created_at, r.department?.code || "", r.item?.internal_code || "",
                `"${(r.item?.name_en || "").replace(/"/g, '""')}"`,
                r.entry_type || "", r.previous_balance ?? "", r.new_balance ?? "",
                r.delta ?? "", r.override_flag ? "1" : "0",
                r.decision_rule || "", r.reference_no || "", r.user_name || "",
                `"${(r.reason || "").replace(/"/g, '""')}"`,
            ];
            lines.push(cells.join(","));
        }
        const blob = new Blob([lines.join("\n")], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `stock_transactions_${new Date().toISOString().slice(0,10)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }

    return (
        <div className="space-y-5" data-testid="stock-transactions-page">
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h1 className="font-heading text-3xl font-black tracking-tight flex items-center gap-2">
                        <History className="w-7 h-7 text-sky-600" />
                        Stock Transactions
                    </h1>
                    <p className="text-sm text-slate-500 mt-1">
                        Immutable audit trail of every issue, receive and adjustment — including emergency overrides.
                    </p>
                </div>
                <Button variant="outline" onClick={exportCsv} data-testid="export-transactions-csv-button">
                    <Download className="w-4 h-4 mr-2" /> Export CSV
                </Button>
            </div>

            {/* Filters */}
            <Card className="border-slate-200">
                <CardContent className="p-4">
                    <div className="flex items-center gap-2 mb-3 text-xs uppercase tracking-wider font-bold text-slate-500">
                        <Filter className="w-3.5 h-3.5" /> Filters
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
                        <div>
                            <Label className="text-xs font-bold">Department</Label>
                            <Select value={departmentId} onValueChange={setDepartmentId} disabled={lockedDept}>
                                <SelectTrigger data-testid="txn-dept-filter"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All</SelectItem>
                                    {departments.map((d) =>
                                        <SelectItem key={d.id} value={d.id}>{d.code} — {d.name_en}</SelectItem>)}
                                </SelectContent>
                            </Select>
                        </div>
                        <div>
                            <Label className="text-xs font-bold">Item</Label>
                            <Select value={itemId} onValueChange={setItemId}>
                                <SelectTrigger data-testid="txn-item-filter"><SelectValue /></SelectTrigger>
                                <SelectContent className="max-h-72">
                                    <SelectItem value="all">All</SelectItem>
                                    {items.map((i) =>
                                        <SelectItem key={i.id} value={i.id}>{i.internal_code} — {i.name_en}</SelectItem>)}
                                </SelectContent>
                            </Select>
                        </div>
                        <div>
                            <Label className="text-xs font-bold">Type</Label>
                            <Select value={entryType} onValueChange={setEntryType}>
                                <SelectTrigger data-testid="txn-type-filter"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">All</SelectItem>
                                    <SelectItem value="issue">Issue</SelectItem>
                                    <SelectItem value="receive">Receive</SelectItem>
                                    <SelectItem value="adjustment">Adjustment</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div>
                            <Label className="text-xs font-bold">From</Label>
                            <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                                   data-testid="txn-date-from" />
                        </div>
                        <div>
                            <Label className="text-xs font-bold">To</Label>
                            <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                                   data-testid="txn-date-to" />
                        </div>
                        <label className="flex items-end gap-2 pb-1 cursor-pointer">
                            <input type="checkbox" className="w-4 h-4 accent-rose-600"
                                   checked={overrideOnly}
                                   onChange={(e) => setOverrideOnly(e.target.checked)}
                                   data-testid="txn-override-only" />
                            <span className="text-xs font-bold text-rose-700">Overrides only</span>
                        </label>
                    </div>
                </CardContent>
            </Card>

            {/* Table */}
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="w-44">Time</TableHead>
                            <TableHead className="w-32">Type</TableHead>
                            <TableHead className="w-28">Dept</TableHead>
                            <TableHead>Item</TableHead>
                            <TableHead className="w-44 text-right">Balance</TableHead>
                            <TableHead className="w-20 text-right">Δ</TableHead>
                            <TableHead className="w-32">User</TableHead>
                            <TableHead className="w-40">Reference / Notes</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {rows.map((r) => (
                            <TableRow key={r.id} data-testid={`txn-row-${r.id}`} className="hover:bg-slate-50">
                                <TableCell className="text-xs font-mono text-slate-600">{fmtDate(r.created_at)}</TableCell>
                                <TableCell><TypePill type={r.entry_type} override={r.override_flag} /></TableCell>
                                <TableCell className="text-xs font-bold">{r.department?.code || "—"}</TableCell>
                                <TableCell>
                                    <div className="font-semibold text-sm flex items-center gap-2">
                                        {r.item?.name_en || r.item_id}
                                        {r.item?.is_life_saving && <Heart className="w-3 h-3 text-red-500" />}
                                    </div>
                                    <div className="text-xs text-slate-500 font-mono">{r.item?.internal_code}</div>
                                </TableCell>
                                <TableCell className="num-cell">
                                    <span className="tabular-nums text-slate-500">{r.previous_balance}</span>
                                    <ArrowRight className="inline w-3 h-3 mx-1 text-slate-400" />
                                    <span className="tabular-nums font-bold">{r.new_balance}</span>
                                </TableCell>
                                <TableCell className="num-cell tabular-nums">
                                    <span className={r.delta < 0 ? "text-orange-600 font-bold" : "text-emerald-700 font-bold"}>
                                        {r.delta > 0 ? `+${r.delta}` : r.delta}
                                    </span>
                                </TableCell>
                                <TableCell className="text-xs">{r.user_name || "—"}</TableCell>
                                <TableCell className="text-xs">
                                    {r.reference_no && <div className="font-mono text-slate-600">{r.reference_no}</div>}
                                    {r.override_reason && (
                                        <div className="text-rose-700 italic mt-0.5">override: {r.override_reason}</div>
                                    )}
                                    {r.reason && <div className="text-slate-500">{r.reason}</div>}
                                </TableCell>
                            </TableRow>
                        ))}
                        {rows.length === 0 && (
                            <TableRow>
                                <TableCell colSpan={8} className="text-center py-10 text-slate-500">
                                    {loading ? "Loading transactions..." : "No transactions found for these filters"}
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>

            <div className="text-xs text-slate-500">Showing {rows.length} transactions (limited to 500 most recent).</div>
        </div>
    );
}

import React, { useEffect, useState } from "react";
import { api, fmtDate, STATUS_LABELS, REQ_STATUS_LABELS } from "@/lib/api";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription
} from "@/components/ui/dialog";
import { StatusBadge, RequestStatusBadge } from "@/components/StatusBadge";
import { Heart, Barcode, Loader2 } from "lucide-react";

/**
 * Click-to-drill detail dialog for dashboard KPI tiles.
 * Fetches /api/dashboard/drill/{metric} and renders the appropriate table.
 */
export default function KpiDetailDialog({ metric, onClose }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (!metric) return;
        setLoading(true);
        setData(null);
        api.get(`/dashboard/drill/${metric}`)
            .then((r) => setData(r.data))
            .finally(() => setLoading(false));
    }, [metric]);

    return (
        <Dialog open={!!metric} onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col"
                           data-testid="kpi-detail-dialog">
                <DialogHeader>
                    <DialogTitle data-testid="kpi-detail-title">
                        {data?.title || "Details"}
                        {data?.count != null && (
                            <span className="ml-2 text-sm font-normal text-slate-500 tabular-nums">
                                ({data.count} {data.count === 1 ? "record" : "records"})
                            </span>
                        )}
                    </DialogTitle>
                    <DialogDescription>
                        Click-to-drill view of the underlying records behind this KPI tile.
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-auto" data-testid="kpi-detail-body">
                    {loading && (
                        <div className="py-12 flex items-center justify-center text-slate-500">
                            <Loader2 className="w-5 h-5 mr-2 animate-spin" /> Loading...
                        </div>
                    )}

                    {!loading && data && data.kind === "summary" && (
                        <SummaryView rows={data.rows} />
                    )}

                    {!loading && data && data.kind === "stock" && (
                        <StockTable rows={data.rows} showDaysOut={metric === "avg_days_out"} />
                    )}

                    {!loading && data && data.kind === "request" && (
                        <RequestTable rows={data.rows} />
                    )}

                    {!loading && data && data.kind === "alert" && (
                        <AlertTable rows={data.rows} />
                    )}

                    {!loading && data && data.kind === "item" && (
                        <ItemTable rows={data.rows} />
                    )}

                    {!loading && data && (!data.rows || data.rows.length === 0) && (
                        <div className="py-12 text-center text-slate-500 text-sm">
                            No records to display.
                        </div>
                    )}
                </div>
            </DialogContent>
        </Dialog>
    );
}

// ---------- Summary breakdown (availability / fulfillment) ----------
function SummaryView({ rows }) {
    const total = rows.reduce((s, r) => s + r.count, 0);
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-1">
            {rows.map((r) => {
                const pct = total ? Math.round((r.count / total) * 1000) / 10 : 0;
                const label =
                    STATUS_LABELS[r.status] ||
                    REQ_STATUS_LABELS[r.status] ||
                    r.status;
                return (
                    <div key={r.status}
                         className="bg-slate-50 border border-slate-200 rounded-lg p-4">
                        <div className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">
                            {label}
                        </div>
                        <div className="flex items-baseline gap-3">
                            <div className="font-heading text-3xl font-black tabular-nums">{r.count}</div>
                            <div className="text-sm text-slate-500 tabular-nums">{pct}%</div>
                        </div>
                        <div className="mt-2 h-1.5 rounded-full bg-slate-200 overflow-hidden">
                            <div className="h-full bg-sky-600" style={{ width: `${pct}%` }} />
                        </div>
                    </div>
                );
            })}
            <div className="bg-sky-50 border border-sky-200 rounded-lg p-4 md:col-span-2">
                <div className="text-xs font-bold uppercase tracking-wider text-sky-700 mb-1">Total</div>
                <div className="font-heading text-3xl font-black tabular-nums text-sky-700">{total}</div>
            </div>
        </div>
    );
}

// ---------- Stock entries (zero / critical / life-saving / stale / avg-days-out) ----------
function StockTable({ rows, showDaysOut }) {
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-sm table-dense">
                <thead className="bg-slate-50 sticky top-0">
                    <tr>
                        <th className="w-28">Department</th>
                        <th>Item</th>
                        <th className="w-24 text-right">Balance</th>
                        <th className="w-32 text-right">Min / Critical</th>
                        <th className="w-36">Status</th>
                        {showDaysOut && <th className="w-24 text-right">Days Out</th>}
                        <th className="w-44">Last Updated</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((r) => (
                        <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50">
                            <td>
                                <div className="font-semibold text-sm">{r.department?.code}</div>
                                <div className="text-xs text-slate-500">{r.department?.name_en}</div>
                            </td>
                            <td>
                                <div className="font-semibold text-sm flex items-center gap-2">
                                    {r.item?.name_en}
                                    {r.item?.is_life_saving && <Heart className="w-3.5 h-3.5 text-red-500" />}
                                </div>
                                <div className="text-xs text-slate-500 font-mono">{r.item?.internal_code}</div>
                            </td>
                            <td className="num-cell">
                                <span className="font-heading text-base font-black">{r.balance}</span>
                                <span className="text-xs text-slate-500 ml-1">{r.item?.unit}</span>
                            </td>
                            <td className="num-cell text-slate-600">
                                {r.item?.min_level} / {r.item?.critical_threshold}
                            </td>
                            <td><StatusBadge status={r.status} size="sm" /></td>
                            {showDaysOut && (
                                <td className="num-cell">
                                    <span className={`font-mono font-bold ${
                                        (r.days_out || 0) >= 7 ? "text-red-600" :
                                        (r.days_out || 0) >= 2 ? "text-amber-600" : "text-slate-700"
                                    }`}>{r.days_out ?? "—"}d</span>
                                </td>
                            )}
                            <td className="text-xs text-slate-500 font-mono">{fmtDate(r.last_updated_at)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ---------- Requests (pending / dispatched / backorder) ----------
function RequestTable({ rows }) {
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-sm table-dense">
                <thead className="bg-slate-50 sticky top-0">
                    <tr>
                        <th className="w-44">Request #</th>
                        <th className="w-24">Dept</th>
                        <th>Item</th>
                        <th className="w-36 text-right">Req / Disp / Rec</th>
                        <th className="w-36">Status</th>
                        <th className="w-44">Created</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((r) => (
                        <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50">
                            <td className="code-cell">{r.request_number}</td>
                            <td className="text-sm font-mono">{r.department?.code}</td>
                            <td>
                                <div className="font-semibold text-sm">{r.item?.name_en}</div>
                                <div className="text-xs text-slate-500 font-mono">{r.item?.internal_code}</div>
                            </td>
                            <td className="num-cell text-xs">
                                {r.requested_qty} / {r.dispatched_qty} / {r.received_qty}
                            </td>
                            <td><RequestStatusBadge status={r.status} /></td>
                            <td className="text-xs text-slate-500 font-mono">{fmtDate(r.created_at)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ---------- Open Alerts ----------
function AlertTable({ rows }) {
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-sm table-dense">
                <thead className="bg-slate-50 sticky top-0">
                    <tr>
                        <th className="w-32">Type</th>
                        <th className="w-28">Severity</th>
                        <th>Title</th>
                        <th className="w-32">Status</th>
                        <th className="w-20 text-right">Esc.</th>
                        <th className="w-44">Created</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((a) => (
                        <tr key={a.id} className="border-t border-slate-100 hover:bg-slate-50">
                            <td className="text-xs font-mono">{a.type}</td>
                            <td>
                                <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase ${
                                    a.severity === "critical" ? "bg-red-100 text-red-700 border-red-200" :
                                    a.severity === "danger" ? "bg-red-50 text-red-700 border-red-200" :
                                    a.severity === "warning" ? "bg-amber-100 text-amber-700 border-amber-200" :
                                    "bg-sky-50 text-sky-700 border-sky-200"
                                }`}>{a.severity}</span>
                            </td>
                            <td className="font-semibold text-sm">{a.title}</td>
                            <td>
                                <span className="inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase bg-slate-100 text-slate-700 border-slate-200">
                                    {a.status || "open"}
                                </span>
                            </td>
                            <td className="num-cell font-bold">L{a.escalation_level || 0}</td>
                            <td className="text-xs text-slate-500 font-mono">{fmtDate(a.created_at)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ---------- Items (no-barcode) ----------
function ItemTable({ rows }) {
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-sm table-dense">
                <thead className="bg-slate-50 sticky top-0">
                    <tr>
                        <th className="w-32">Code</th>
                        <th>Name</th>
                        <th className="w-28">Category</th>
                        <th className="w-20">Unit</th>
                        <th className="w-28">Barcode</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((it) => (
                        <tr key={it.id} className="border-t border-slate-100 hover:bg-slate-50">
                            <td className="code-cell">{it.internal_code}</td>
                            <td className="font-semibold text-sm">{it.name_en}</td>
                            <td className="text-xs">{it.category}</td>
                            <td className="text-xs font-mono">{it.unit}</td>
                            <td>
                                <span className="inline-flex items-center gap-1 text-amber-600 text-xs">
                                    <Barcode className="w-3.5 h-3.5" /> Missing
                                </span>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

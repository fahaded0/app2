import React, { useState } from "react";
import { api, API, fmtDate } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Download, AlertCircle, AlertTriangle, Clock, Heart, Barcode, ClipboardList } from "lucide-react";
import { StatusBadge, RequestStatusBadge } from "@/components/StatusBadge";

const REPORTS = [
    { key: "zero_level",    title: "Zero Stock Items",          icon: AlertCircle,   color: "text-red-600" },
    { key: "critical_level", title: "Critical Stock Items",     icon: AlertTriangle, color: "text-amber-600" },
    { key: "backorder",     title: "Backorder Report",          icon: Clock,         color: "text-purple-600" },
    { key: "open_requests", title: "Open Requests",             icon: ClipboardList, color: "text-sky-600" },
    { key: "no_barcode",    title: "Items Without Barcode",     icon: Barcode,       color: "text-slate-600" },
    { key: "life_saving",   title: "Life-Saving Items at Risk", icon: Heart,         color: "text-pink-600" },
];

export default function Reports() {
    const [selected, setSelected] = useState(null);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);

    async function loadReport(key) {
        setSelected(key);
        setLoading(true);
        try {
            const r = await api.get(`/reports/${key}`);
            setData(r.data);
        } finally {
            setLoading(false);
        }
    }

    function downloadCsv(key) {
        const token = localStorage.getItem("access_token");
        fetch(`${API}/reports/${key}/export.csv`, {
            headers: { Authorization: `Bearer ${token}` },
        }).then((r) => r.blob()).then((blob) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url; a.download = `${key}.csv`; a.click();
            URL.revokeObjectURL(url);
        });
    }

    return (
        <div className="space-y-5" data-testid="reports-page">
            <h1 className="font-heading text-3xl font-black tracking-tight">Reports</h1>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {REPORTS.map((r) => (
                    <Card key={r.key} className="border-slate-200 hover:shadow-md transition-all cursor-pointer"
                          onClick={() => loadReport(r.key)} data-testid={`report-card-${r.key}`}>
                        <CardContent className="p-5">
                            <div className="flex items-start justify-between mb-3">
                                <div className={`w-10 h-10 rounded-md bg-slate-50 border border-slate-200 flex items-center justify-center ${r.color}`}>
                                    <r.icon className="w-5 h-5" />
                                </div>
                                <Button size="sm" variant="ghost"
                                        onClick={(e) => { e.stopPropagation(); downloadCsv(r.key); }}
                                        data-testid={`download-${r.key}`}>
                                    <Download className="w-4 h-4" />
                                </Button>
                            </div>
                            <div className="font-heading font-bold text-base mb-1">{r.title}</div>
                            <div className="text-xs text-slate-500">Click to view, or download CSV</div>
                        </CardContent>
                    </Card>
                ))}
            </div>

            {selected && (
                <Card className="border-slate-200" data-testid="report-result">
                    <CardHeader className="flex flex-row items-center justify-between">
                        <CardTitle className="font-heading text-lg">
                            {REPORTS.find((x) => x.key === selected)?.title}
                            <span className="ml-2 text-sm font-normal text-slate-500 tabular-nums">({data?.count || 0} records)</span>
                        </CardTitle>
                        <Button onClick={() => downloadCsv(selected)} variant="outline"
                                data-testid="export-csv-button">
                            <Download className="w-4 h-4 mr-2" /> Export CSV
                        </Button>
                    </CardHeader>
                    <CardContent>
                        {loading ? (
                            <div className="text-center py-10 text-slate-500">Loading...</div>
                        ) : !data || data.rows.length === 0 ? (
                            <div className="text-center py-10 text-slate-500">No data</div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm table-dense">
                                    <thead className="bg-slate-50">
                                        <tr>
                                            <th className="w-24">Department</th>
                                            <th>Item</th>
                                            <th className="w-32 text-right">Balance/Qty</th>
                                            <th className="w-40">Status</th>
                                            <th className="w-44">Date</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.rows.map((r, i) => (
                                            <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                                                <td className="text-xs font-mono">{r.department?.code || "—"}</td>
                                                <td>
                                                    <div className="font-semibold text-sm">{r.item?.name_en || r.name_en || "—"}</div>
                                                    <div className="text-xs text-slate-500 font-mono">{r.item?.internal_code || r.internal_code || ""}</div>
                                                </td>
                                                <td className="num-cell">{r.balance ?? r.requested_qty ?? "—"}</td>
                                                <td>
                                                    {r.status && (selected === "open_requests" || selected === "backorder"
                                                        ? <RequestStatusBadge status={r.status} />
                                                        : <StatusBadge status={r.status} size="sm" />)}
                                                </td>
                                                <td className="text-xs text-slate-500 font-mono">
                                                    {fmtDate(r.last_updated_at || r.created_at)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}
        </div>
    );
}

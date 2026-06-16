import React, { useState } from "react";
import { api, API } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Download, FileText, AlertCircle, AlertTriangle, Clock, Heart, Barcode, ClipboardList } from "lucide-react";
import { StatusBadge, RequestStatusBadge } from "@/components/StatusBadge";

const REPORTS = [
    { key: "zero_level",   title: "تقرير البنود الصفرية", icon: AlertCircle, color: "text-red-600" },
    { key: "critical_level", title: "تقرير البنود الحرجة", icon: AlertTriangle, color: "text-amber-600" },
    { key: "backorder",    title: "تقرير Backorder",       icon: Clock,       color: "text-purple-600" },
    { key: "open_requests", title: "الطلبات المفتوحة",     icon: ClipboardList, color: "text-sky-600" },
    { key: "no_barcode",   title: "أصناف بدون باركود",     icon: Barcode,     color: "text-slate-600" },
    { key: "life_saving",  title: "أصناف منقذة للحياة في خطر", icon: Heart,  color: "text-pink-600" },
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
        // Open in new tab with token via header is not possible. Use fetch + blob.
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
            <h1 className="font-heading text-3xl font-black tracking-tight">التقارير</h1>

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
                            <div className="text-xs text-slate-500">اضغط للعرض، أو حمّل CSV</div>
                        </CardContent>
                    </Card>
                ))}
            </div>

            {selected && (
                <Card className="border-slate-200" data-testid="report-result">
                    <CardHeader className="flex flex-row items-center justify-between">
                        <CardTitle className="font-heading text-lg">
                            {REPORTS.find((x) => x.key === selected)?.title}
                            <span className="ms-2 text-sm font-normal text-slate-500">({data?.count || 0} سجل)</span>
                        </CardTitle>
                        <Button onClick={() => downloadCsv(selected)} variant="outline"
                                data-testid="export-csv-button">
                            <Download className="w-4 h-4 me-2" /> تصدير CSV
                        </Button>
                    </CardHeader>
                    <CardContent>
                        {loading ? (
                            <div className="text-center py-10 text-slate-500">جاري التحميل...</div>
                        ) : !data || data.rows.length === 0 ? (
                            <div className="text-center py-10 text-slate-500">لا توجد بيانات</div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead className="bg-slate-50">
                                        <tr className="text-start">
                                            <th className="p-2 text-start font-bold text-xs uppercase tracking-wider text-slate-600">القسم</th>
                                            <th className="p-2 text-start font-bold text-xs uppercase tracking-wider text-slate-600">الصنف</th>
                                            <th className="p-2 text-start font-bold text-xs uppercase tracking-wider text-slate-600">الرصيد/الكمية</th>
                                            <th className="p-2 text-start font-bold text-xs uppercase tracking-wider text-slate-600">الحالة</th>
                                            <th className="p-2 text-start font-bold text-xs uppercase tracking-wider text-slate-600">التاريخ</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.rows.map((r, i) => (
                                            <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                                                <td className="p-2 text-xs">{r.department?.code || "—"}</td>
                                                <td className="p-2">
                                                    <div className="font-bold text-sm">{r.item?.name_ar || r.name_ar || "—"}</div>
                                                    <div className="text-xs text-slate-500" dir="ltr">{r.item?.internal_code || r.internal_code || ""}</div>
                                                </td>
                                                <td className="p-2 font-mono text-sm">{r.balance ?? r.requested_qty ?? "—"}</td>
                                                <td className="p-2">
                                                    {r.status && (selected === "open_requests" || selected === "backorder"
                                                        ? <RequestStatusBadge status={r.status} />
                                                        : <StatusBadge status={r.status} size="sm" />)}
                                                </td>
                                                <td className="p-2 text-xs text-slate-500" dir="ltr">
                                                    {(r.last_updated_at || r.created_at) ? new Date(r.last_updated_at || r.created_at).toLocaleString("ar-SA") : ""}
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

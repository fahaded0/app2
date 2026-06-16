import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select";
import {
    AlertCircle, AlertTriangle, Bell, Clock, Heart, ShieldCheck
} from "lucide-react";
import { toast } from "sonner";

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
    critical: "حرج جداً", danger: "خطر", warning: "تحذير", info: "معلومة",
};

export default function Alerts() {
    const [alerts, setAlerts] = useState([]);
    const [filter, setFilter] = useState("unack");
    const [severityFilter, setSeverityFilter] = useState("all");

    function load() {
        const params = {};
        if (filter === "unack") params.acknowledged = false;
        if (filter === "ack") params.acknowledged = true;
        if (severityFilter !== "all") params.severity = severityFilter;
        api.get("/alerts", { params }).then((r) => setAlerts(r.data));
    }
    useEffect(load, [filter, severityFilter]);

    async function acknowledge(id) {
        await api.post(`/alerts/${id}/acknowledge`);
        toast.success("تم استلام التنبيه");
        load();
    }

    return (
        <div className="space-y-5" data-testid="alerts-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">التنبيهات</h1>
                <div className="flex items-center gap-3">
                    <Select value={severityFilter} onValueChange={setSeverityFilter}>
                        <SelectTrigger className="w-44" data-testid="alerts-severity-filter">
                            <SelectValue placeholder="كل الخطورات" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">كل الخطورات</SelectItem>
                            <SelectItem value="critical">حرج جداً</SelectItem>
                            <SelectItem value="danger">خطر</SelectItem>
                            <SelectItem value="warning">تحذير</SelectItem>
                            <SelectItem value="info">معلومة</SelectItem>
                        </SelectContent>
                    </Select>
                    <Select value={filter} onValueChange={setFilter}>
                        <SelectTrigger className="w-44" data-testid="alerts-status-filter">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="unack">غير مستلمة</SelectItem>
                            <SelectItem value="ack">مستلمة</SelectItem>
                            <SelectItem value="all">كل التنبيهات</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>

            {alerts.length === 0 ? (
                <div className="bg-white border border-slate-200 rounded-lg p-10 text-center">
                    <ShieldCheck className="w-12 h-12 mx-auto text-emerald-500 mb-2" />
                    <div className="font-bold">لا توجد تنبيهات حالياً</div>
                    <div className="text-sm text-slate-500">جميع البنود في وضع طبيعي</div>
                </div>
            ) : (
                <div className="space-y-3">
                    {alerts.map((a) => {
                        const Icon = SEVERITY_ICON[a.severity] || Bell;
                        return (
                            <div key={a.id}
                                 data-testid={`alert-card-${a.id}`}
                                 className={`border rounded-lg p-4 flex items-start gap-4 transition-all ${
                                    SEVERITY_BG[a.severity] || "border-slate-200 bg-white"
                                 } ${a.acknowledged ? "opacity-60" : ""}`}>
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
                                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                                            {SEVERITY_LABEL[a.severity]}
                                        </span>
                                        {a.item?.is_life_saving && (
                                            <span className="status-pill status-zero text-[10px]">
                                                <Heart className="w-3 h-3" />منقذ للحياة
                                            </span>
                                        )}
                                    </div>
                                    <div className="text-sm text-slate-700 mb-2">{a.message}</div>
                                    <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                                        {a.department && (
                                            <span>القسم: <b>{a.department.name_ar} ({a.department.code})</b></span>
                                        )}
                                        {a.item && (
                                            <span>الصنف: <b>{a.item.name_ar}</b></span>
                                        )}
                                        <span dir="ltr" className="inline-flex items-center gap-1">
                                            <Clock className="w-3 h-3" />
                                            {new Date(a.created_at).toLocaleString("ar-SA")}
                                        </span>
                                    </div>
                                </div>
                                {!a.acknowledged && (
                                    <Button onClick={() => acknowledge(a.id)} variant="outline" size="sm"
                                            data-testid={`acknowledge-alert-${a.id}`}>
                                        <ShieldCheck className="w-4 h-4 me-1" /> استلام
                                    </Button>
                                )}
                                {a.acknowledged && (
                                    <span className="text-xs text-slate-400 inline-flex items-center gap-1">
                                        <ShieldCheck className="w-3.5 h-3.5" /> مستلم
                                    </span>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

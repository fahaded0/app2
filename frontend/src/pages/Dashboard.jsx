import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
    AlertCircle, AlertTriangle, Boxes, Clock, ShieldAlert,
    Activity, Building2, Heart, Package, TrendingUp
} from "lucide-react";
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, Legend, PieChart, Pie, Cell
} from "recharts";

const KPI = ({ label, value, icon: Icon, color, sub, testid }) => (
    <div className={`bg-white border rounded-xl p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md ${color}`}
         data-testid={testid}>
        <div className="flex items-start justify-between mb-3">
            <div className="text-xs font-bold tracking-wider uppercase text-slate-500">{label}</div>
            <Icon className="w-7 h-7 opacity-80" />
        </div>
        <div className="font-heading text-3xl font-black tracking-tight">{value}</div>
        {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
);

export default function Dashboard() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        api.get("/dashboard/kpis")
            .then((r) => setData(r.data))
            .finally(() => setLoading(false));
    }, []);

    if (loading) {
        return (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {Array.from({ length: 8 }).map((_, i) => (
                    <Skeleton key={i} className="h-32 rounded-xl" />
                ))}
            </div>
        );
    }

    if (!data) return null;

    const chartData = data.by_department.map((d) => ({
        name: d.department?.code || "؟",
        "صفر": d.zero_level || 0,
        "حرج": d.critical_level || 0,
        "متوفر": d.available || 0,
        "عاد للمخزون": d.back_in_stock || 0,
    }));

    const distData = [
        { name: "صفر مخزون", value: data.zero_count, color: "#DC2626" },
        { name: "حرج", value: data.critical_count, color: "#D97706" },
        { name: "عاد للمخزون", value: data.back_in_stock_count, color: "#2563EB" },
        { name: "متوفر", value: data.available_count, color: "#0D9488" },
    ].filter((d) => d.value > 0);

    return (
        <div className="space-y-6" data-testid="dashboard-page">
            <div className="flex items-baseline justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight" data-testid="dashboard-title">
                    لوحة المؤشرات
                </h1>
                <div className="text-xs text-slate-500">
                    آخر تحديث: {new Date().toLocaleString("ar-SA")}
                </div>
            </div>

            {/* KPI grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <KPI label="صفر مخزون" value={data.zero_count} icon={AlertCircle}
                     color="text-red-700 border-red-200 bg-red-50/40" testid="kpi-zero" />
                <KPI label="مخزون حرج" value={data.critical_count} icon={AlertTriangle}
                     color="text-amber-700 border-amber-200 bg-amber-50/40" testid="kpi-critical" />
                <KPI label="Backorder" value={data.backorder_count} icon={Clock}
                     color="text-purple-700 border-purple-200 bg-purple-50/40" testid="kpi-backorder" />
                <KPI label="منقذ للحياة في خطر" value={data.life_saving_risk} icon={Heart}
                     color="text-pink-700 border-pink-200 bg-pink-50/40" testid="kpi-lifesaving" />

                <KPI label="طلبات بانتظار الاعتماد" value={data.pending_requests} icon={Activity}
                     color="text-sky-700 border-sky-200 bg-sky-50/40" testid="kpi-pending" />
                <KPI label="تم الصرف" value={data.dispatched_requests} icon={Package}
                     color="text-indigo-700 border-indigo-200 bg-indigo-50/40" testid="kpi-dispatched" />
                <KPI label="تنبيهات مفتوحة" value={data.open_alerts} icon={ShieldAlert}
                     color="text-orange-700 border-orange-200 bg-orange-50/40" testid="kpi-alerts" />
                <KPI label="لم يحدث منذ 24س" value={data.stale_count} icon={TrendingUp}
                     color="text-slate-700 border-slate-200" testid="kpi-stale" />
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <Card className="lg:col-span-2 border-slate-200" data-testid="chart-by-dept">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg">حالة المخزون حسب القسم</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <ResponsiveContainer width="100%" height={280}>
                            <BarChart data={chartData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                                <XAxis dataKey="name" tick={{ fontFamily: "Cairo", fontSize: 12 }} reversed />
                                <YAxis orientation="right" tick={{ fontFamily: "Cairo", fontSize: 12 }} />
                                <Tooltip contentStyle={{ fontFamily: "IBM Plex Sans Arabic", fontSize: 12 }} />
                                <Legend wrapperStyle={{ fontFamily: "IBM Plex Sans Arabic", fontSize: 12 }} />
                                <Bar dataKey="صفر" stackId="a" fill="#DC2626" />
                                <Bar dataKey="حرج" stackId="a" fill="#D97706" />
                                <Bar dataKey="متوفر" stackId="a" fill="#0D9488" />
                                <Bar dataKey="عاد للمخزون" stackId="a" fill="#2563EB" />
                            </BarChart>
                        </ResponsiveContainer>
                    </CardContent>
                </Card>

                <Card className="border-slate-200" data-testid="chart-distribution">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg">توزيع الحالات</CardTitle>
                    </CardHeader>
                    <CardContent>
                        {distData.length === 0 ? (
                            <div className="text-sm text-slate-500 py-8 text-center">لا توجد بيانات</div>
                        ) : (
                            <ResponsiveContainer width="100%" height={280}>
                                <PieChart>
                                    <Pie data={distData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                                         innerRadius={50} outerRadius={90}>
                                        {distData.map((d, i) => <Cell key={i} fill={d.color} />)}
                                    </Pie>
                                    <Tooltip contentStyle={{ fontFamily: "IBM Plex Sans Arabic", fontSize: 12 }} />
                                    <Legend wrapperStyle={{ fontFamily: "IBM Plex Sans Arabic", fontSize: 12 }} />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </CardContent>
                </Card>
            </div>

            {/* Recent alerts + top departments */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <Card className="lg:col-span-2 border-slate-200" data-testid="recent-alerts-card">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg flex items-center gap-2">
                            <ShieldAlert className="w-5 h-5 text-amber-600" /> آخر التنبيهات
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {data.recent_alerts.length === 0 ? (
                            <div className="text-sm text-slate-500 py-6 text-center">لا توجد تنبيهات</div>
                        ) : (
                            <ul className="divide-y divide-slate-200">
                                {data.recent_alerts.map((a) => (
                                    <li key={a.id} className="py-3 flex items-start gap-3"
                                        data-testid={`recent-alert-${a.id}`}>
                                        <div className={`w-2 h-2 mt-2 rounded-full ${
                                            a.severity === "critical" ? "bg-red-500 animate-pulse-slow" :
                                            a.severity === "danger" ? "bg-red-500" :
                                            a.severity === "warning" ? "bg-amber-500" : "bg-sky-500"
                                        }`} />
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <div className="font-bold text-sm text-slate-900 truncate">{a.title}</div>
                                                {a.item?.is_life_saving && (
                                                    <span className="status-pill status-zero text-[10px]">
                                                        <Heart className="w-3 h-3" />منقذ للحياة
                                                    </span>
                                                )}
                                            </div>
                                            <div className="text-xs text-slate-500">{a.message}</div>
                                        </div>
                                        <div className="text-xs text-slate-400 whitespace-nowrap" dir="ltr">
                                            {new Date(a.created_at).toLocaleString("ar-SA")}
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </CardContent>
                </Card>

                <Card className="border-slate-200" data-testid="top-departments-card">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg flex items-center gap-2">
                            <Building2 className="w-5 h-5 text-sky-600" /> أكثر الأقسام تأثراً
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {data.top_departments.length === 0 ? (
                            <div className="text-sm text-slate-500 py-6 text-center">لا توجد بيانات</div>
                        ) : (
                            <ul className="space-y-2">
                                {data.top_departments.map((d) => (
                                    <li key={d.department.id}
                                        className="flex items-center justify-between bg-slate-50 rounded-md px-3 py-2 border border-slate-100">
                                        <div>
                                            <div className="font-bold text-sm">{d.department.name_ar}</div>
                                            <div className="text-xs text-slate-500">{d.department.code}</div>
                                        </div>
                                        <div className="font-heading text-2xl font-black text-red-600">{d.count}</div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}

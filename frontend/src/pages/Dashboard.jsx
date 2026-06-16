import React, { useEffect, useState } from "react";
import { api, fmtDate } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
    AlertCircle, AlertTriangle, Clock, ShieldAlert,
    Activity, Building2, Heart, Package, TrendingUp, Barcode,
    PercentSquare, Repeat
} from "lucide-react";
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, Legend, PieChart, Pie, Cell
} from "recharts";

const KPI = ({ label, value, suffix, icon: Icon, color, sub, testid }) => (
    <div className={`bg-white border rounded-xl p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md ${color}`}
         data-testid={testid}>
        <div className="flex items-start justify-between mb-3">
            <div className="text-xs font-bold tracking-wider uppercase text-slate-500">{label}</div>
            <Icon className="w-7 h-7 opacity-80" />
        </div>
        <div className="font-heading text-3xl font-black tracking-tight tabular-nums">
            {value}{suffix && <span className="text-base font-bold text-slate-500 ml-1">{suffix}</span>}
        </div>
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
        name: d.department?.code || "?",
        Zero: d.zero_level || 0,
        Critical: d.critical_level || 0,
        Available: d.available || 0,
        "Back in Stock": d.back_in_stock || 0,
    }));

    const distData = [
        { name: "Zero Stock", value: data.zero_count, color: "#DC2626" },
        { name: "Critical", value: data.critical_count, color: "#D97706" },
        { name: "Back in Stock", value: data.back_in_stock_count, color: "#2563EB" },
        { name: "Available", value: data.available_count, color: "#0D9488" },
    ].filter((d) => d.value > 0);

    const agingData = Object.entries(data.backorder_aging || {}).map(([bucket, n]) => ({
        bucket, count: n,
    }));

    return (
        <div className="space-y-6" data-testid="dashboard-page">
            <div className="flex items-baseline justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight" data-testid="dashboard-title">
                    Operational Dashboard
                </h1>
                <div className="text-xs text-slate-500 font-mono">
                    Last updated: {fmtDate(new Date().toISOString())}
                </div>
            </div>

            {/* Hero risk KPIs */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <KPI label="Stock Availability" value={data.availability_pct} suffix="%" icon={PercentSquare}
                     color={`${data.availability_pct >= 90 ? "text-emerald-700 border-emerald-200 bg-emerald-50/40" :
                             data.availability_pct >= 70 ? "text-amber-700 border-amber-200 bg-amber-50/40" :
                             "text-red-700 border-red-200 bg-red-50/40"}`}
                     sub="Available + Back-in-Stock / total" testid="kpi-availability" />
                <KPI label="Life-Saving at Risk" value={data.life_saving_risk} icon={Heart}
                     color="text-pink-700 border-pink-200 bg-pink-50/40"
                     sub="Zero or Critical" testid="kpi-lifesaving" />
                <KPI label="Open Alerts" value={data.open_alerts} icon={ShieldAlert}
                     color="text-orange-700 border-orange-200 bg-orange-50/40"
                     sub="Open + Ack + In-Progress" testid="kpi-alerts" />
                <KPI label="Avg Days Out of Stock" value={data.avg_days_out_of_stock} suffix="d" icon={Clock}
                     color="text-purple-700 border-purple-200 bg-purple-50/40"
                     sub="Across active shortages" testid="kpi-avg-days-out" />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <KPI label="Zero Stock" value={data.zero_count} icon={AlertCircle}
                     color="text-red-700 border-red-200 bg-red-50/40" testid="kpi-zero" />
                <KPI label="Critical Stock" value={data.critical_count} icon={AlertTriangle}
                     color="text-amber-700 border-amber-200 bg-amber-50/40" testid="kpi-critical" />
                <KPI label="Backorder" value={data.backorder_count} icon={Clock}
                     color="text-purple-700 border-purple-200 bg-purple-50/40" testid="kpi-backorder" />
                <KPI label="Fulfillment Rate (30d)" value={data.fulfillment_rate} suffix="%" icon={TrendingUp}
                     color="text-teal-700 border-teal-200 bg-teal-50/40" testid="kpi-fulfillment" />

                <KPI label="Pending Approval" value={data.pending_requests} icon={Activity}
                     color="text-sky-700 border-sky-200 bg-sky-50/40" testid="kpi-pending" />
                <KPI label="Dispatched" value={data.dispatched_requests} icon={Package}
                     color="text-indigo-700 border-indigo-200 bg-indigo-50/40" testid="kpi-dispatched" />
                <KPI label="Stale (>24h)" value={data.stale_count} icon={TrendingUp}
                     color="text-slate-700 border-slate-200" sub="Data quality" testid="kpi-stale" />
                <KPI label="Items without Barcode" value={data.no_barcode_count} icon={Barcode}
                     color="text-slate-700 border-slate-200" sub="Data quality" testid="kpi-no-barcode" />
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <Card className="lg:col-span-2 border-slate-200" data-testid="chart-by-dept">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg">Stock Status by Department</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <ResponsiveContainer width="100%" height={280}>
                            <BarChart data={chartData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                                <XAxis dataKey="name" tick={{ fontFamily: "Inter", fontSize: 12 }} />
                                <YAxis tick={{ fontFamily: "Inter", fontSize: 12 }} />
                                <Tooltip contentStyle={{ fontFamily: "Inter", fontSize: 12 }} />
                                <Legend wrapperStyle={{ fontFamily: "Inter", fontSize: 12 }} />
                                <Bar dataKey="Zero" stackId="a" fill="#DC2626" />
                                <Bar dataKey="Critical" stackId="a" fill="#D97706" />
                                <Bar dataKey="Available" stackId="a" fill="#0D9488" />
                                <Bar dataKey="Back in Stock" stackId="a" fill="#2563EB" />
                            </BarChart>
                        </ResponsiveContainer>
                    </CardContent>
                </Card>

                <Card className="border-slate-200" data-testid="chart-distribution">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg">Status Distribution</CardTitle>
                    </CardHeader>
                    <CardContent>
                        {distData.length === 0 ? (
                            <div className="text-sm text-slate-500 py-8 text-center">No data</div>
                        ) : (
                            <ResponsiveContainer width="100%" height={280}>
                                <PieChart>
                                    <Pie data={distData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                                         innerRadius={50} outerRadius={90}>
                                        {distData.map((d, i) => <Cell key={i} fill={d.color} />)}
                                    </Pie>
                                    <Tooltip contentStyle={{ fontFamily: "Inter", fontSize: 12 }} />
                                    <Legend wrapperStyle={{ fontFamily: "Inter", fontSize: 12 }} />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </CardContent>
                </Card>
            </div>

            {/* Backorder aging + Repeated stockouts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Card className="border-slate-200" data-testid="backorder-aging-card">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg flex items-center gap-2">
                            <Clock className="w-5 h-5 text-purple-600" /> Backorder Aging
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {agingData.every((d) => d.count === 0) ? (
                            <div className="text-sm text-slate-500 py-8 text-center">No backorders</div>
                        ) : (
                            <ResponsiveContainer width="100%" height={220}>
                                <BarChart data={agingData}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                                    <XAxis dataKey="bucket" tick={{ fontFamily: "Inter", fontSize: 12 }} />
                                    <YAxis tick={{ fontFamily: "Inter", fontSize: 12 }} allowDecimals={false} />
                                    <Tooltip contentStyle={{ fontFamily: "Inter", fontSize: 12 }} />
                                    <Bar dataKey="count" fill="#9333EA" />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </CardContent>
                </Card>

                <Card className="border-slate-200" data-testid="top-repeated-card">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg flex items-center gap-2">
                            <Repeat className="w-5 h-5 text-red-600" /> Top Repeated Stockouts
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {(!data.top_repeated_stockouts || data.top_repeated_stockouts.length === 0) ? (
                            <div className="text-sm text-slate-500 py-8 text-center">No data</div>
                        ) : (
                            <ul className="space-y-2">
                                {data.top_repeated_stockouts.map((t) => (
                                    <li key={t.item.id}
                                        className="flex items-center justify-between bg-slate-50 rounded-md px-3 py-2 border border-slate-100">
                                        <div>
                                            <div className="font-bold text-sm">{t.item.name_en}</div>
                                            <div className="text-xs text-slate-500 font-mono">{t.item.internal_code}</div>
                                        </div>
                                        <div className="font-heading text-2xl font-black text-red-600 tabular-nums">{t.events}</div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </CardContent>
                </Card>
            </div>

            {/* Recent alerts + top departments */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <Card className="lg:col-span-2 border-slate-200" data-testid="recent-alerts-card">
                    <CardHeader className="pb-2">
                        <CardTitle className="font-heading text-lg flex items-center gap-2">
                            <ShieldAlert className="w-5 h-5 text-amber-600" /> Recent Alerts
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {data.recent_alerts.length === 0 ? (
                            <div className="text-sm text-slate-500 py-6 text-center">No alerts</div>
                        ) : (
                            <ul className="divide-y divide-slate-200">
                                {data.recent_alerts.map((a) => (
                                    <li key={a.id} className="py-3 flex items-start gap-3"
                                        data-testid={`recent-alert-${a.id}`}>
                                        <div className={`w-2 h-2 mt-2 rounded-full shrink-0 ${
                                            a.severity === "critical" ? "bg-red-500 animate-pulse-slow" :
                                            a.severity === "danger" ? "bg-red-500" :
                                            a.severity === "warning" ? "bg-amber-500" : "bg-sky-500"
                                        }`} />
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <div className="font-bold text-sm text-slate-900 truncate">{a.title}</div>
                                                {(a.escalation_level || 0) > 0 && (
                                                    <span className="rounded border border-purple-300 bg-purple-100 text-purple-700 px-1.5 text-[10px] font-bold uppercase">
                                                        L{a.escalation_level}
                                                    </span>
                                                )}
                                                {a.item?.is_life_saving && (
                                                    <span className="status-pill status-zero text-[10px]">
                                                        <Heart className="w-3 h-3" />Life-Saving
                                                    </span>
                                                )}
                                            </div>
                                            <div className="text-xs text-slate-500">{a.message}</div>
                                        </div>
                                        <div className="text-xs text-slate-400 whitespace-nowrap font-mono">
                                            {fmtDate(a.created_at)}
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
                            <Building2 className="w-5 h-5 text-sky-600" /> Most Affected Departments
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {data.top_departments.length === 0 ? (
                            <div className="text-sm text-slate-500 py-6 text-center">No data</div>
                        ) : (
                            <ul className="space-y-2">
                                {data.top_departments.map((d) => (
                                    <li key={d.department.id}
                                        className="flex items-center justify-between bg-slate-50 rounded-md px-3 py-2 border border-slate-100">
                                        <div>
                                            <div className="font-bold text-sm">{d.department.name_en}</div>
                                            <div className="text-xs text-slate-500 font-mono">{d.department.code}</div>
                                        </div>
                                        <div className="font-heading text-2xl font-black text-red-600 tabular-nums">{d.count}</div>
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

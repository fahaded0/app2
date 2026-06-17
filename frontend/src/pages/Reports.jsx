import React, { useEffect, useState } from "react";
import { api, API, fmtDate, formatApiError } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
    AlertCircle, AlertTriangle, Clock, Heart, Barcode, ClipboardList,
    FileSpreadsheet, FileText, History, BarChart3, Activity, Building2,
    Download, Mail, Send,
} from "lucide-react";
import { toast } from "sonner";

const REPORT_META = {
    zero_level:             { title: "Zero Stock Items",          icon: AlertCircle,   color: "text-red-600", bg: "bg-red-50",
                              desc: "Items currently at zero balance in any department." },
    critical_level:         { title: "Critical Stock Items",      icon: AlertTriangle, color: "text-amber-600", bg: "bg-amber-50",
                              desc: "Items below their critical threshold but not yet zero." },
    life_saving:            { title: "Life-Saving Items at Risk", icon: Heart,         color: "text-pink-600", bg: "bg-pink-50",
                              desc: "Life-saving items currently at zero or critical level." },
    backorder:              { title: "Backorder Report",          icon: Clock,         color: "text-purple-600", bg: "bg-purple-50",
                              desc: "Open requests blocked by central warehouse stockout." },
    open_requests:          { title: "Open Requests",             icon: ClipboardList, color: "text-sky-600", bg: "bg-sky-50",
                              desc: "All in-flight requests not yet received or closed." },
    data_quality:           { title: "Data Quality Report",       icon: Barcode,       color: "text-slate-600", bg: "bg-slate-50",
                              desc: "Missing barcodes, duplicates, and stale stock entries." },
    item_movement:          { title: "Item Movement Report",      icon: Activity,      color: "text-emerald-600", bg: "bg-emerald-50",
                              desc: "Last 1000 stock transactions with user attribution." },
    department_performance: { title: "Department Performance",    icon: Building2,     color: "text-indigo-600", bg: "bg-indigo-50",
                              desc: "Per-department snapshot + 30-day operational metrics." },
    monthly_management:     { title: "Monthly Management Report", icon: BarChart3,     color: "text-blue-600", bg: "bg-blue-50",
                              desc: "Executive KPIs for the last 30 days." },
    audit_trail:            { title: "Audit Trail Report",        icon: History,       color: "text-zinc-700", bg: "bg-zinc-50",
                              desc: "Tamper-proof log of last 2000 system events." },
};

export default function Reports() {
    const [catalog, setCatalog] = useState([]);
    const [selected, setSelected] = useState(null);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);

    // Email-PDF dialog state
    const [emailOpen, setEmailOpen] = useState(false);
    const [emailReportKey, setEmailReportKey] = useState(null);
    const [emailRecipients, setEmailRecipients] = useState("");
    const [emailMessage, setEmailMessage] = useState(
        "Please find the latest report attached for your review."
    );
    const [emailSending, setEmailSending] = useState(false);

    function openEmailDialog(key) {
        setEmailReportKey(key);
        setEmailRecipients("");
        setEmailMessage("Please find the latest report attached for your review.");
        setEmailOpen(true);
    }

    async function sendEmail() {
        const recips = emailRecipients
            .split(/[,\s;]+/)
            .map((s) => s.trim())
            .filter((s) => s && s.includes("@"));
        if (recips.length === 0) {
            toast.error("Add at least one recipient email");
            return;
        }
        setEmailSending(true);
        try {
            await api.post(`/reports/${emailReportKey}/email`, {
                recipients: recips,
                message: emailMessage || null,
            });
            toast.success(`Report queued for delivery to ${recips.length} recipient${recips.length > 1 ? "s" : ""}`);
            setEmailOpen(false);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setEmailSending(false);
        }
    }

    useEffect(() => {
        api.get("/reports").then((r) => setCatalog(r.data));
    }, []);

    async function loadReport(key) {
        setSelected(key);
        setLoading(true);
        try {
            const r = await api.get(`/reports/${key}`);
            setData(r.data);
        } catch (e) {
            toast.error("Failed to load report");
        } finally {
            setLoading(false);
        }
    }

    function download(key, fmt) {
        const token = localStorage.getItem("access_token");
        fetch(`${API}/reports/${key}/export.${fmt}`, {
            headers: { Authorization: `Bearer ${token}` },
        }).then((r) => {
            if (!r.ok) throw new Error("Download failed");
            return r.blob();
        }).then((blob) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${key}.${fmt}`;
            a.click();
            URL.revokeObjectURL(url);
            toast.success(`${fmt.toUpperCase()} downloaded`);
        }).catch(() => toast.error("Download failed"));
    }

    return (
        <div className="space-y-5" data-testid="reports-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">Formal Reports</h1>
                <div className="text-xs text-slate-500">
                    {catalog.length} report{catalog.length !== 1 ? "s" : ""} available
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {catalog.map((r) => {
                    const meta = REPORT_META[r.key] || { title: r.title, icon: FileText, color: "text-slate-600", bg: "bg-slate-50", desc: "" };
                    const Icon = meta.icon;
                    return (
                        <Card key={r.key}
                              className={`border-slate-200 hover:shadow-md transition-all`}
                              data-testid={`report-card-${r.key}`}>
                            <CardContent className="p-5">
                                <div className="flex items-start gap-3 mb-3">
                                    <div className={`w-11 h-11 rounded-md ${meta.bg} border border-slate-200 flex items-center justify-center ${meta.color} shrink-0`}>
                                        <Icon className="w-5 h-5" />
                                    </div>
                                    <div className="min-w-0 flex-1">
                                        <div className="font-heading font-bold text-base">{meta.title}</div>
                                        <div className="text-xs text-slate-500 leading-snug mt-0.5">{meta.desc}</div>
                                    </div>
                                </div>
                                <div className="flex items-center justify-between gap-1 pt-3 border-t border-slate-100">
                                    <Button onClick={() => loadReport(r.key)} variant="ghost" size="sm"
                                            data-testid={`view-${r.key}`} className="text-xs">
                                        View
                                    </Button>
                                    <div className="flex items-center gap-1">
                                        <Button onClick={() => download(r.key, "csv")} variant="outline" size="sm"
                                                data-testid={`download-csv-${r.key}`} title="Download CSV"
                                                className="h-8 px-2 text-xs">
                                            <Download className="w-3 h-3 mr-1" /> CSV
                                        </Button>
                                        <Button onClick={() => download(r.key, "xlsx")} variant="outline" size="sm"
                                                data-testid={`download-xlsx-${r.key}`} title="Download Excel"
                                                className="h-8 px-2 text-xs text-emerald-700 border-emerald-300">
                                            <FileSpreadsheet className="w-3 h-3 mr-1" /> XLSX
                                        </Button>
                                        <Button onClick={() => download(r.key, "pdf")} variant="outline" size="sm"
                                                data-testid={`download-pdf-${r.key}`} title="Download PDF"
                                                className="h-8 px-2 text-xs text-red-700 border-red-300">
                                            <FileText className="w-3 h-3 mr-1" /> PDF
                                        </Button>
                                        <Button onClick={() => openEmailDialog(r.key)} variant="outline" size="sm"
                                                data-testid={`email-pdf-${r.key}`} title="Email PDF to manager"
                                                className="h-8 px-2 text-xs text-sky-700 border-sky-300">
                                            <Mail className="w-3 h-3 mr-1" /> Email
                                        </Button>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    );
                })}
            </div>

            {selected && (
                <Card className="border-slate-200" data-testid="report-result">
                    <CardHeader className="flex flex-row items-center justify-between border-b border-slate-100 pb-3">
                        <div>
                            <CardTitle className="font-heading text-lg">{data?.title}</CardTitle>
                            {data && (
                                <div className="text-xs text-slate-500 mt-1 flex flex-wrap gap-x-4 gap-y-1 font-mono">
                                    <span>Period: <b>{data.meta?.period || "—"}</b></span>
                                    <span>Records: <b className="tabular-nums">{data.count}</b></span>
                                    <span>Extracted by: <b>{data.meta?.extracted_by || "—"}</b></span>
                                    <span>Issued: <b>{fmtDate(new Date().toISOString())}</b></span>
                                </div>
                            )}
                            {data?.meta?.notes && (
                                <div className="text-xs text-slate-500 mt-1 italic">{data.meta.notes}</div>
                            )}
                        </div>
                        <div className="flex gap-2 shrink-0">
                            <Button onClick={() => download(selected, "csv")} variant="outline" size="sm">
                                <Download className="w-3.5 h-3.5 mr-1.5" /> CSV
                            </Button>
                            <Button onClick={() => download(selected, "xlsx")} variant="outline" size="sm"
                                    className="text-emerald-700 border-emerald-300">
                                <FileSpreadsheet className="w-3.5 h-3.5 mr-1.5" /> Excel
                            </Button>
                            <Button onClick={() => download(selected, "pdf")} variant="outline" size="sm"
                                    className="text-red-700 border-red-300">
                                <FileText className="w-3.5 h-3.5 mr-1.5" /> PDF
                            </Button>
                            <Button onClick={() => openEmailDialog(selected)} variant="outline" size="sm"
                                    className="text-sky-700 border-sky-300"
                                    data-testid={`email-pdf-detail-${selected}`}>
                                <Mail className="w-3.5 h-3.5 mr-1.5" /> Email
                            </Button>
                        </div>
                    </CardHeader>
                    <CardContent className="p-0">
                        {loading ? (
                            <div className="text-center py-10 text-slate-500">Loading...</div>
                        ) : !data || data.rows.length === 0 ? (
                            <div className="text-center py-10 text-slate-500">No data</div>
                        ) : (
                            <div className="overflow-x-auto max-h-[60vh] overflow-y-auto">
                                <table className="w-full text-sm table-dense">
                                    <thead className="bg-slate-50 sticky top-0">
                                        <tr>
                                            {data.headers.map((h, i) => (
                                                <th key={i} className="text-left">{h}</th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.rows.map((row, ri) => (
                                            <tr key={ri} className="border-t border-slate-100 hover:bg-slate-50">
                                                {row.map((cell, ci) => (
                                                    <td key={ci} className={typeof cell === "number" ? "num-cell" : ""}>
                                                        {cell === null || cell === undefined ? "—" : String(cell)}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}

            {/* Email PDF dialog */}
            <Dialog open={emailOpen} onOpenChange={setEmailOpen}>
                <DialogContent className="max-w-md" data-testid="email-report-dialog">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <Mail className="w-5 h-5 text-sky-600" /> Email PDF Report
                        </DialogTitle>
                        <DialogDescription>
                            The report PDF will be generated server-side and emailed as an attachment via Resend.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div>
                            <Label className="text-xs font-bold">Recipients</Label>
                            <Input
                                placeholder="e.g. manager@hospital.sa, supply@hospital.sa"
                                value={emailRecipients}
                                onChange={(e) => setEmailRecipients(e.target.value)}
                                data-testid="email-recipients-input"
                            />
                            <p className="text-[11px] text-slate-500 mt-1">Separate multiple addresses with commas, spaces or semicolons.</p>
                        </div>
                        <div>
                            <Label className="text-xs font-bold">Message <span className="text-slate-400 font-normal">(optional)</span></Label>
                            <Textarea
                                rows={4}
                                value={emailMessage}
                                onChange={(e) => setEmailMessage(e.target.value)}
                                data-testid="email-message-input"
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEmailOpen(false)}>Cancel</Button>
                        <Button onClick={sendEmail} disabled={emailSending}
                                className="bg-sky-600 hover:bg-sky-700"
                                data-testid="send-email-report-button">
                            <Send className="w-4 h-4 mr-2" />
                            {emailSending ? "Sending..." : "Send"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

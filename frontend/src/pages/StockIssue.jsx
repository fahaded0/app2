import React, { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import IssuePreviewCard from "@/components/IssuePreviewCard";
import {
    Send, Eye, Siren, RotateCcw, PackageMinus, ShieldCheck, ClipboardList, Loader2,
} from "lucide-react";
import { toast } from "sonner";

const isDeptStaff = (role) =>
    ["department_stock_officer", "department_head"].includes(role);

export default function StockIssue() {
    const { user } = useAuth();
    const lockedDept = isDeptStaff(user.role);

    const [departments, setDepartments] = useState([]);
    const [items, setItems] = useState([]);
    const [departmentId, setDepartmentId] = useState(lockedDept ? user.department_id || "" : "");
    const [itemId, setItemId] = useState("");
    const [quantity, setQuantity] = useState("");
    const [referenceNo, setReferenceNo] = useState("");
    const [notes, setNotes] = useState("");
    const [overrideReason, setOverrideReason] = useState("");
    const [approvalId, setApprovalId] = useState("");

    const [balance, setBalance] = useState(null);
    const [preview, setPreview] = useState(null);
    const [loadingPreview, setLoadingPreview] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [lastResult, setLastResult] = useState(null);

    useEffect(() => {
        api.get("/departments").then((r) => setDepartments(r.data));
        api.get("/items").then((r) => setItems(r.data));
    }, []);

    // Fetch the current balance whenever item or department changes
    useEffect(() => {
        if (!itemId || !departmentId) { setBalance(null); return; }
        api.get(`/stock-balance/${departmentId}/${itemId}`)
            .then((r) => setBalance(r.data))
            .catch(() => setBalance(null));
        setPreview(null);
        setLastResult(null);
    }, [itemId, departmentId]);

    const selectedItem = useMemo(
        () => items.find((i) => i.id === itemId) || null,
        [items, itemId]
    );

    const canPreview = itemId && departmentId && Number(quantity) > 0;

    async function runPreview() {
        if (!canPreview) return;
        setLoadingPreview(true);
        try {
            const r = await api.post("/stock/issue/preview", {
                item_id: itemId,
                department_id: departmentId,
                quantity: Number(quantity),
                override_reason: overrideReason || null,
            });
            setPreview(r.data);
        } catch (e) {
            toast.error(formatApiError(e));
            setPreview(null);
        } finally {
            setLoadingPreview(false);
        }
    }

    async function execute(force = false) {
        if (!preview) return;
        const dec = preview.decision || {};
        const isOverride = dec.rule === "blocked_no_issue" && preview.is_life_saving;
        if (dec.block && !isOverride) {
            toast.error(dec.message || "Issue blocked");
            return;
        }
        if ((isOverride || force) && !overrideReason.trim()) {
            toast.error("Override reason is required for emergency issue");
            return;
        }
        setSubmitting(true);
        try {
            const payload = {
                item_id: itemId,
                department_id: departmentId,
                quantity: Number(quantity),
                reference_no: referenceNo || null,
                notes: notes || null,
                override_reason: isOverride || force ? overrideReason : null,
                approval_id: approvalId || null,
            };
            const r = await api.post("/stock/issue", payload);
            setLastResult(r.data);
            toast.success(
                r.data?.alert_severity === "critical"
                    ? "Emergency issue executed and escalated"
                    : "Issue executed"
            );
            // Refresh balance + clear inputs
            const b = await api.get(`/stock-balance/${departmentId}/${itemId}`);
            setBalance(b.data);
            setPreview(null);
            setQuantity("");
            setReferenceNo("");
            setOverrideReason("");
            setApprovalId("");
            setNotes("");
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSubmitting(false);
        }
    }

    function resetForm() {
        setItemId("");
        if (!lockedDept) setDepartmentId("");
        setQuantity("");
        setReferenceNo("");
        setNotes("");
        setOverrideReason("");
        setApprovalId("");
        setPreview(null);
        setBalance(null);
        setLastResult(null);
    }

    const decRule = preview?.decision?.rule;
    const showOverride = preview && decRule === "blocked_no_issue" && preview.is_life_saving;

    return (
        <div className="space-y-5" data-testid="stock-issue-page">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="font-heading text-3xl font-black tracking-tight">Stock Issue</h1>
                    <p className="text-sm text-slate-500 mt-1">
                        Issue stock with reserve control. The backend enforces minimum, critical and no-issue thresholds per department.
                    </p>
                </div>
                <Button variant="outline" onClick={resetForm} data-testid="reset-form-button">
                    <RotateCcw className="w-4 h-4 mr-2" /> Reset
                </Button>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                {/* LEFT — input form */}
                <Card className="lg:col-span-1 border-slate-200">
                    <CardHeader className="pb-3">
                        <CardTitle className="font-heading text-lg flex items-center gap-2">
                            <PackageMinus className="w-5 h-5 text-sky-600" />
                            Issue Details
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="space-y-1.5">
                            <Label className="text-xs uppercase tracking-wider font-bold text-slate-700">
                                Department
                            </Label>
                            <Select
                                value={departmentId}
                                onValueChange={setDepartmentId}
                                disabled={lockedDept}
                            >
                                <SelectTrigger data-testid="issue-department-select">
                                    <SelectValue placeholder="Choose department..." />
                                </SelectTrigger>
                                <SelectContent>
                                    {departments.map((d) => (
                                        <SelectItem key={d.id} value={d.id} data-testid={`dept-opt-${d.code}`}>
                                            {d.code} — {d.name_en}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="space-y-1.5">
                            <Label className="text-xs uppercase tracking-wider font-bold text-slate-700">Item</Label>
                            <Select value={itemId} onValueChange={setItemId}>
                                <SelectTrigger data-testid="issue-item-select">
                                    <SelectValue placeholder="Choose item..." />
                                </SelectTrigger>
                                <SelectContent>
                                    {items.map((i) => (
                                        <SelectItem key={i.id} value={i.id} data-testid={`item-opt-${i.internal_code}`}>
                                            {i.internal_code} — {i.name_en}
                                            {i.is_life_saving ? " ♥" : ""}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="space-y-1.5">
                            <Label className="text-xs uppercase tracking-wider font-bold text-slate-700">
                                Quantity to issue
                            </Label>
                            <Input
                                type="number" min="1"
                                value={quantity}
                                onChange={(e) => setQuantity(e.target.value)}
                                placeholder="e.g. 5"
                                data-testid="issue-quantity-input"
                                className="tabular-nums"
                            />
                        </div>

                        <div className="space-y-1.5">
                            <Label className="text-xs uppercase tracking-wider font-bold text-slate-700">
                                Reference No. <span className="text-slate-400 normal-case lowercase">(optional)</span>
                            </Label>
                            <Input
                                value={referenceNo}
                                onChange={(e) => setReferenceNo(e.target.value)}
                                placeholder="REQ-2026-0001"
                                data-testid="issue-reference-input"
                            />
                        </div>

                        <div className="space-y-1.5">
                            <Label className="text-xs uppercase tracking-wider font-bold text-slate-700">
                                Notes <span className="text-slate-400 normal-case lowercase">(optional)</span>
                            </Label>
                            <Textarea
                                rows={2}
                                value={notes}
                                onChange={(e) => setNotes(e.target.value)}
                                placeholder="e.g. consumption for shift A"
                                data-testid="issue-notes-input"
                            />
                        </div>

                        <Button
                            onClick={runPreview}
                            disabled={!canPreview || loadingPreview}
                            className="w-full bg-slate-800 hover:bg-slate-900"
                            data-testid="preview-issue-button"
                        >
                            {loadingPreview ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Eye className="w-4 h-4 mr-2" />}
                            Preview Issue
                        </Button>

                        {/* Current balance card */}
                        {balance && (
                            <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm" data-testid="current-balance-summary">
                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-slate-500 uppercase tracking-wider font-bold">Current balance</span>
                                    <span className="font-black text-slate-900 text-lg tabular-nums">{balance.current_balance}</span>
                                </div>
                                <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
                                    <div>
                                        <div className="text-slate-500">Min</div>
                                        <div className="font-bold text-slate-800 tabular-nums">{balance.minimum_level}</div>
                                    </div>
                                    <div>
                                        <div className="text-slate-500">Critical</div>
                                        <div className="font-bold text-slate-800 tabular-nums">{balance.critical_level}</div>
                                    </div>
                                    <div>
                                        <div className="text-slate-500">No-issue</div>
                                        <div className="font-bold text-slate-800 tabular-nums">{balance.no_issue_threshold}</div>
                                    </div>
                                </div>
                            </div>
                        )}
                        {!balance && (departmentId || itemId) && (
                            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50/60 p-3 text-xs text-slate-500"
                                 data-testid="balance-hint">
                                {!departmentId
                                    ? "Select a department to view the current balance."
                                    : "Select an item to view the current balance and thresholds."}
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* RIGHT — preview + execute */}
                <div className="lg:col-span-2 space-y-4">
                    {!preview && (
                        <Card className="border-dashed border-2 border-slate-200">
                            <CardContent className="py-16 flex flex-col items-center justify-center text-center">
                                <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mb-3">
                                    <ClipboardList className="w-8 h-8 text-slate-400" />
                                </div>
                                <div className="font-bold text-slate-700">No preview yet</div>
                                <p className="text-sm text-slate-500 mt-1 max-w-md">
                                    Pick a department, item and quantity, then press <span className="font-bold">Preview Issue</span> to evaluate the decision.
                                </p>
                            </CardContent>
                        </Card>
                    )}

                    {preview && (
                        <>
                            <IssuePreviewCard preview={preview} />

                            {/* Override panel (life-saving only) */}
                            {showOverride && (
                                <Card className="border-rose-200 bg-rose-50/30">
                                    <CardHeader className="pb-2">
                                        <CardTitle className="font-heading text-base flex items-center gap-2 text-rose-700">
                                            <Siren className="w-5 h-5" /> Emergency Override
                                        </CardTitle>
                                    </CardHeader>
                                    <CardContent className="space-y-3">
                                        <p className="text-xs text-rose-700 leading-relaxed">
                                            This issue will push the balance below the no-issue threshold. Because the item is life-saving and you have override authority, you may proceed with a documented justification. An immediate escalation will be sent to hospital management and supply.
                                        </p>
                                        <div className="space-y-1.5">
                                            <Label className="text-xs uppercase tracking-wider font-bold text-rose-800">
                                                Justification (required)
                                            </Label>
                                            <Textarea
                                                rows={3}
                                                value={overrideReason}
                                                onChange={(e) => setOverrideReason(e.target.value)}
                                                placeholder="e.g. Active resuscitation in ER bay 3 — patient code blue"
                                                data-testid="override-reason-input"
                                            />
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label className="text-xs uppercase tracking-wider font-bold text-rose-800">
                                                Approval reference <span className="normal-case lowercase font-normal text-rose-600">(optional)</span>
                                            </Label>
                                            <Input
                                                value={approvalId}
                                                onChange={(e) => setApprovalId(e.target.value)}
                                                placeholder="APR-2026-0001"
                                                data-testid="approval-id-input"
                                            />
                                        </div>
                                        <Button
                                            onClick={() => execute(true)}
                                            disabled={submitting || !overrideReason.trim()}
                                            className="w-full bg-rose-600 hover:bg-rose-700 text-white"
                                            data-testid="emergency-issue-button"
                                        >
                                            {submitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Siren className="w-4 h-4 mr-2" />}
                                            Execute Emergency Issue
                                        </Button>
                                    </CardContent>
                                </Card>
                            )}

                            {/* Confirm panel (non-blocked) */}
                            {!preview.decision?.block && (
                                <Card className="border-slate-200">
                                    <CardContent className="p-4 flex items-center justify-between gap-3">
                                        <div className="flex items-center gap-2 text-sm text-slate-700">
                                            <ShieldCheck className="w-5 h-5 text-emerald-600" />
                                            <span>The system will record the transaction, update the balance and create the relevant alert if needed.</span>
                                        </div>
                                        <Button
                                            onClick={() => execute(false)}
                                            disabled={submitting}
                                            className="bg-sky-600 hover:bg-sky-700"
                                            data-testid="confirm-issue-button"
                                        >
                                            {submitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
                                            Confirm Issue
                                        </Button>
                                    </CardContent>
                                </Card>
                            )}

                            {/* Blocked, non life-saving */}
                            {preview.decision?.block && !showOverride && (
                                <Card className="border-red-200 bg-red-50/30">
                                    <CardContent className="p-4 text-sm text-red-800" data-testid="blocked-issue-message">
                                        <div className="font-bold mb-1">Issue not allowed</div>
                                        Please raise a stock request or substitute with an alternative item.
                                    </CardContent>
                                </Card>
                            )}
                        </>
                    )}

                    {/* Last result */}
                    {lastResult && (
                        <Card className="border-emerald-200 bg-emerald-50/30" data-testid="issue-result-card">
                            <CardHeader className="pb-2">
                                <CardTitle className="font-heading text-base text-emerald-800">
                                    Issue Recorded
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="text-sm text-slate-800 space-y-1">
                                <div>Transaction: <span className="font-mono text-xs">{lastResult.transaction_id}</span></div>
                                <div>Balance: <span className="font-bold tabular-nums">{lastResult.previous_balance}</span> → <span className="font-bold tabular-nums">{lastResult.current_balance}</span></div>
                                <div>Rule applied: <span className="font-bold">{lastResult.decision?.rule}</span></div>
                                {lastResult.alert_id && (
                                    <div>Alert created with severity <span className="font-bold uppercase">{lastResult.alert_severity}</span></div>
                                )}
                            </CardContent>
                        </Card>
                    )}
                </div>
            </div>

            {/* Selected item meta footer */}
            {selectedItem && (
                <div className="text-xs text-slate-500 italic">
                    Selected item: <span className="font-mono">{selectedItem.internal_code}</span> • category {selectedItem.category} • unit {selectedItem.unit}
                </div>
            )}
        </div>
    );
}

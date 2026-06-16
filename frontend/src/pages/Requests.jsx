import React, { useEffect, useState } from "react";
import { api, formatApiError, PRIORITY_LABELS, fmtDate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select";
import {
    Table, TableHeader, TableBody, TableRow, TableHead, TableCell
} from "@/components/ui/table";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger
} from "@/components/ui/dialog";
import { RequestStatusBadge } from "@/components/StatusBadge";
import { Plus, Check, X, Truck, PackageCheck } from "lucide-react";
import { useAuth, hasRole } from "@/lib/auth";
import { toast } from "sonner";

export default function Requests() {
    const { user } = useAuth();
    const isDeptStaff = ["department_stock_officer", "department_head"].includes(user.role);
    const canCreate = hasRole(user, "super_admin","department_stock_officer","department_head");
    const canApprove = hasRole(user, "super_admin","department_head","supply_officer");
    const canDispatch = hasRole(user, "super_admin","supply_officer");
    const canReceive = hasRole(user, "super_admin","department_head","department_stock_officer","supply_officer");

    const [requests, setRequests] = useState([]);
    const [departments, setDepartments] = useState([]);
    const [items, setItems] = useState([]);
    const [statusFilter, setStatusFilter] = useState("all");
    const [createOpen, setCreateOpen] = useState(false);
    const [actionDialog, setActionDialog] = useState(null);
    const [form, setForm] = useState({});
    const [createForm, setCreateForm] = useState({
        department_id: isDeptStaff ? user.department_id : "",
        item_id: "", requested_qty: 1, priority: "routine", reason: "",
    });

    function load() {
        const params = {};
        if (statusFilter && statusFilter !== "all") params.status = statusFilter;
        api.get("/requests", { params }).then((r) => setRequests(r.data));
    }
    useEffect(() => {
        api.get("/departments").then((r) => setDepartments(r.data));
        api.get("/items").then((r) => setItems(r.data));
    }, []);
    useEffect(load, [statusFilter]);

    async function submitCreate() {
        try {
            await api.post("/requests", {
                ...createForm,
                requested_qty: Number(createForm.requested_qty) || 1,
                reason: createForm.reason || null,
            });
            toast.success("Request submitted");
            setCreateOpen(false);
            setCreateForm({ ...createForm, item_id: "", requested_qty: 1, reason: "" });
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }
    async function submitAction() {
        const { type, req } = actionDialog;
        try {
            if (type === "approve") {
                await api.post(`/requests/${req.id}/approve`, { approved_qty: Number(form.approved_qty) || req.requested_qty });
                toast.success("Request approved");
            } else if (type === "reject") {
                await api.post(`/requests/${req.id}/reject`, { reason: form.reason || "" });
                toast.success("Request rejected");
            } else if (type === "dispatch") {
                await api.post(`/requests/${req.id}/dispatch`, {
                    dispatched_qty: Number(form.dispatched_qty) || 0,
                    backorder: !!form.backorder,
                    expected_supply_date: form.expected_supply_date || null,
                });
                toast.success(form.backorder ? "Request placed on backorder" : "Dispatched");
            } else if (type === "receive") {
                await api.post(`/requests/${req.id}/receive`, {
                    received_qty: Number(form.received_qty) || 0,
                    note: form.note || null,
                });
                toast.success("Receipt recorded");
            }
            setActionDialog(null);
            setForm({});
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }

    return (
        <div className="space-y-5" data-testid="requests-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">Stock Requests</h1>
                {canCreate && (
                    <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                        <DialogTrigger asChild>
                            <Button className="bg-sky-600 hover:bg-sky-700" data-testid="new-request-button">
                                <Plus className="w-4 h-4 mr-2" /> New Request
                            </Button>
                        </DialogTrigger>
                        <DialogContent>
                            <DialogHeader><DialogTitle>New Stock Request</DialogTitle></DialogHeader>
                            <div className="space-y-3">
                                <div>
                                    <Label className="text-xs font-bold">Department</Label>
                                    <Select value={createForm.department_id}
                                            onValueChange={(v) => setCreateForm({ ...createForm, department_id: v })}
                                            disabled={isDeptStaff}>
                                        <SelectTrigger data-testid="req-dept-select"><SelectValue placeholder="Select department" /></SelectTrigger>
                                        <SelectContent>
                                            {departments.map((d) => <SelectItem key={d.id} value={d.id}>{d.name_en}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Item</Label>
                                    <Select value={createForm.item_id}
                                            onValueChange={(v) => setCreateForm({ ...createForm, item_id: v })}>
                                        <SelectTrigger data-testid="req-item-select"><SelectValue placeholder="Select item" /></SelectTrigger>
                                        <SelectContent className="max-h-72">
                                            {items.map((it) => <SelectItem key={it.id} value={it.id}>{it.name_en} ({it.internal_code})</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <div>
                                        <Label className="text-xs font-bold">Quantity</Label>
                                        <Input type="number" value={createForm.requested_qty}
                                               data-testid="req-qty-input"
                                               onChange={(e) => setCreateForm({ ...createForm, requested_qty: e.target.value })} />
                                    </div>
                                    <div>
                                        <Label className="text-xs font-bold">Priority</Label>
                                        <Select value={createForm.priority}
                                                onValueChange={(v) => setCreateForm({ ...createForm, priority: v })}>
                                            <SelectTrigger><SelectValue /></SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="routine">Routine</SelectItem>
                                                <SelectItem value="urgent">Urgent</SelectItem>
                                                <SelectItem value="stat">STAT</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Reason / Notes</Label>
                                    <Input value={createForm.reason}
                                           onChange={(e) => setCreateForm({ ...createForm, reason: e.target.value })} />
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
                                <Button onClick={submitCreate} className="bg-sky-600 hover:bg-sky-700"
                                        data-testid="submit-request-button">Submit Request</Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                )}
            </div>

            <div className="flex items-center gap-3 bg-white border border-slate-200 rounded-lg p-3">
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                    <SelectTrigger className="w-56" data-testid="requests-status-filter">
                        <SelectValue placeholder="All Statuses" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All Statuses</SelectItem>
                        <SelectItem value="pending_approval">Pending Approval</SelectItem>
                        <SelectItem value="approved">Approved</SelectItem>
                        <SelectItem value="dispatched">Dispatched</SelectItem>
                        <SelectItem value="partially_received">Partially Received</SelectItem>
                        <SelectItem value="received">Received</SelectItem>
                        <SelectItem value="backorder">Backorder</SelectItem>
                        <SelectItem value="rejected">Rejected</SelectItem>
                    </SelectContent>
                </Select>
                <div className="text-sm text-slate-500">Total: <b className="tabular-nums">{requests.length}</b></div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="w-44">Request #</TableHead>
                            <TableHead className="w-24">Dept</TableHead>
                            <TableHead>Item</TableHead>
                            <TableHead className="w-40 text-right">Req / Appr / Disp / Rec</TableHead>
                            <TableHead className="w-24">Priority</TableHead>
                            <TableHead className="w-40">Status</TableHead>
                            <TableHead className="w-40">Created</TableHead>
                            <TableHead>Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {requests.map((r) => (
                            <TableRow key={r.id} className="hover:bg-slate-50" data-testid={`request-row-${r.id}`}>
                                <TableCell className="code-cell">{r.request_number}</TableCell>
                                <TableCell className="text-sm font-mono">{r.department?.code}</TableCell>
                                <TableCell>
                                    <div className="font-semibold text-sm">{r.item?.name_en}</div>
                                    <div className="text-xs text-slate-500 font-mono">{r.item?.internal_code}</div>
                                </TableCell>
                                <TableCell className="num-cell text-xs">
                                    {r.requested_qty} / {r.approved_qty ?? "—"} / {r.dispatched_qty} / {r.received_qty}
                                </TableCell>
                                <TableCell>
                                    <span className={`text-xs font-bold ${
                                        r.priority === "stat" ? "text-red-600" :
                                        r.priority === "urgent" ? "text-amber-600" : "text-slate-600"
                                    }`}>{PRIORITY_LABELS[r.priority]}</span>
                                </TableCell>
                                <TableCell><RequestStatusBadge status={r.status} /></TableCell>
                                <TableCell className="text-xs text-slate-500 font-mono">
                                    {fmtDate(r.created_at)}
                                </TableCell>
                                <TableCell>
                                    <div className="flex gap-1 flex-wrap">
                                        {r.status === "pending_approval" && canApprove && (
                                            <>
                                                <Button size="sm" variant="outline"
                                                        className="text-emerald-700 border-emerald-300"
                                                        data-testid={`approve-req-${r.id}`}
                                                        onClick={() => { setForm({ approved_qty: r.requested_qty }); setActionDialog({ type: "approve", req: r }); }}>
                                                    <Check className="w-3.5 h-3.5 mr-1" /> Approve
                                                </Button>
                                                <Button size="sm" variant="outline"
                                                        className="text-red-700 border-red-300"
                                                        data-testid={`reject-req-${r.id}`}
                                                        onClick={() => { setForm({ reason: "" }); setActionDialog({ type: "reject", req: r }); }}>
                                                    <X className="w-3.5 h-3.5 mr-1" /> Reject
                                                </Button>
                                            </>
                                        )}
                                        {(r.status === "approved" || r.status === "backorder") && canDispatch && (
                                            <Button size="sm" variant="outline"
                                                    className="text-indigo-700 border-indigo-300"
                                                    data-testid={`dispatch-req-${r.id}`}
                                                    onClick={() => { setForm({ dispatched_qty: r.approved_qty || r.requested_qty, backorder: false }); setActionDialog({ type: "dispatch", req: r }); }}>
                                                <Truck className="w-3.5 h-3.5 mr-1" /> Dispatch
                                            </Button>
                                        )}
                                        {(r.status === "dispatched" || r.status === "partially_received") && canReceive && (
                                            <Button size="sm" variant="outline"
                                                    className="text-teal-700 border-teal-300"
                                                    data-testid={`receive-req-${r.id}`}
                                                    onClick={() => { setForm({ received_qty: r.dispatched_qty - r.received_qty }); setActionDialog({ type: "receive", req: r }); }}>
                                                <PackageCheck className="w-3.5 h-3.5 mr-1" /> Receive
                                            </Button>
                                        )}
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                        {requests.length === 0 && (
                            <TableRow><TableCell colSpan={8} className="text-center py-10 text-slate-500">No requests found</TableCell></TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>

            <Dialog open={!!actionDialog} onOpenChange={(o) => !o && setActionDialog(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>
                            {actionDialog?.type === "approve" && "Approve Request"}
                            {actionDialog?.type === "reject" && "Reject Request"}
                            {actionDialog?.type === "dispatch" && "Dispatch Request"}
                            {actionDialog?.type === "receive" && "Record Receipt"}
                        </DialogTitle>
                    </DialogHeader>
                    {actionDialog && (
                        <div className="space-y-3">
                            <div className="bg-slate-50 border border-slate-200 rounded-md p-3 text-sm">
                                <div className="font-bold">{actionDialog.req.item?.name_en}</div>
                                <div className="text-xs text-slate-500 font-mono">{actionDialog.req.request_number}</div>
                                <div className="text-xs text-slate-500">Requested quantity: {actionDialog.req.requested_qty}</div>
                            </div>
                            {actionDialog.type === "approve" && (
                                <div>
                                    <Label className="text-xs font-bold">Approved Quantity</Label>
                                    <Input type="number" value={form.approved_qty || ""} data-testid="approve-qty-input"
                                           onChange={(e) => setForm({ ...form, approved_qty: e.target.value })} />
                                </div>
                            )}
                            {actionDialog.type === "reject" && (
                                <div>
                                    <Label className="text-xs font-bold">Rejection Reason</Label>
                                    <Input value={form.reason || ""} data-testid="reject-reason-input"
                                           onChange={(e) => setForm({ ...form, reason: e.target.value })} />
                                </div>
                            )}
                            {actionDialog.type === "dispatch" && (
                                <>
                                    <div>
                                        <Label className="text-xs font-bold">Dispatched Quantity</Label>
                                        <Input type="number" value={form.dispatched_qty || ""}
                                               data-testid="dispatch-qty-input"
                                               onChange={(e) => setForm({ ...form, dispatched_qty: e.target.value })} />
                                    </div>
                                    <label className="flex items-center gap-2 text-sm font-bold cursor-pointer">
                                        <input type="checkbox" checked={!!form.backorder}
                                               data-testid="dispatch-backorder-toggle"
                                               onChange={(e) => setForm({ ...form, backorder: e.target.checked })} />
                                        Not available — place on backorder
                                    </label>
                                    {form.backorder && (
                                        <div>
                                            <Label className="text-xs font-bold">Expected Supply Date</Label>
                                            <Input type="date" value={form.expected_supply_date || ""}
                                                   onChange={(e) => setForm({ ...form, expected_supply_date: e.target.value })} />
                                        </div>
                                    )}
                                </>
                            )}
                            {actionDialog.type === "receive" && (
                                <>
                                    <div>
                                        <Label className="text-xs font-bold">Quantity Received</Label>
                                        <Input type="number" value={form.received_qty || ""}
                                               data-testid="receive-qty-input"
                                               onChange={(e) => setForm({ ...form, received_qty: e.target.value })} />
                                    </div>
                                    <div>
                                        <Label className="text-xs font-bold">Variance Note (if any)</Label>
                                        <Input value={form.note || ""}
                                               onChange={(e) => setForm({ ...form, note: e.target.value })} />
                                    </div>
                                </>
                            )}
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setActionDialog(null)}>Cancel</Button>
                        <Button onClick={submitAction} className="bg-sky-600 hover:bg-sky-700"
                                data-testid="submit-action-button">Confirm</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

import React, { useEffect, useState } from "react";
import { api, formatApiError, fmtDate } from "@/lib/api";
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
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth, hasRole } from "@/lib/auth";
import { Heart, Pencil, FilePlus2 } from "lucide-react";
import { toast } from "sonner";

export default function Stock() {
    const { user } = useAuth();
    const isDeptStaff = ["department_stock_officer", "department_head"].includes(user.role);
    const canEdit = hasRole(user, "super_admin","department_stock_officer","department_head","supply_officer");
    const [departments, setDepartments] = useState([]);
    const [items, setItems] = useState([]);
    const [stock, setStock] = useState([]);
    const [selectedDept, setSelectedDept] = useState(isDeptStaff ? (user.department_id || "all") : "all");
    const [statusFilter, setStatusFilter] = useState("all");

    const [editOpen, setEditOpen] = useState(false);
    const [editing, setEditing] = useState(null);
    const [newEntryOpen, setNewEntryOpen] = useState(false);

    const [editBalance, setEditBalance] = useState(0);
    const [editNote, setEditNote] = useState("");

    const [newDept, setNewDept] = useState("");
    const [newItem, setNewItem] = useState("");
    const [newBalance, setNewBalance] = useState(0);

    function loadStock() {
        const params = {};
        if (selectedDept && selectedDept !== "all") params.department_id = selectedDept;
        if (statusFilter && statusFilter !== "all") params.status = statusFilter;
        api.get("/stock", { params }).then((r) => setStock(r.data));
    }
    useEffect(() => {
        api.get("/departments").then((r) => setDepartments(r.data));
        api.get("/items").then((r) => setItems(r.data));
    }, []);
    useEffect(loadStock, [selectedDept, statusFilter]);

    function openEdit(row) {
        setEditing(row);
        setEditBalance(row.balance);
        setEditNote("");
        setEditOpen(true);
    }
    async function saveEdit() {
        try {
            await api.post("/stock", {
                department_id: editing.department_id,
                item_id: editing.item_id,
                balance: Number(editBalance),
                notes: editNote || null,
            });
            toast.success("Stock updated");
            setEditOpen(false);
            loadStock();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }
    async function saveNew() {
        try {
            await api.post("/stock", {
                department_id: newDept || (isDeptStaff ? user.department_id : ""),
                item_id: newItem,
                balance: Number(newBalance),
            });
            toast.success("Stock entry created");
            setNewEntryOpen(false);
            setNewDept(""); setNewItem(""); setNewBalance(0);
            loadStock();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }

    return (
        <div className="space-y-5" data-testid="stock-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">Stock Entry &amp; Monitoring</h1>
                {canEdit && (
                    <Dialog open={newEntryOpen} onOpenChange={setNewEntryOpen}>
                        <DialogTrigger asChild>
                            <Button className="bg-sky-600 hover:bg-sky-700" data-testid="new-stock-entry-button">
                                <FilePlus2 className="w-4 h-4 mr-2" /> New Stock Entry
                            </Button>
                        </DialogTrigger>
                        <DialogContent>
                            <DialogHeader><DialogTitle>New Stock Entry</DialogTitle></DialogHeader>
                            <div className="space-y-3">
                                <div>
                                    <Label className="text-xs font-bold">Department</Label>
                                    <Select value={newDept || (isDeptStaff ? user.department_id : "")}
                                            onValueChange={setNewDept}
                                            disabled={isDeptStaff}>
                                        <SelectTrigger data-testid="new-stock-dept-select"><SelectValue placeholder="Select department" /></SelectTrigger>
                                        <SelectContent>
                                            {departments.map((d) =>
                                                <SelectItem key={d.id} value={d.id}>{d.name_en} ({d.code})</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Item</Label>
                                    <Select value={newItem} onValueChange={setNewItem}>
                                        <SelectTrigger data-testid="new-stock-item-select"><SelectValue placeholder="Select item" /></SelectTrigger>
                                        <SelectContent className="max-h-72">
                                            {items.map((it) =>
                                                <SelectItem key={it.id} value={it.id}>{it.name_en} ({it.internal_code})</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Current Balance</Label>
                                    <Input type="number" value={newBalance} data-testid="new-stock-balance-input"
                                           onChange={(e) => setNewBalance(e.target.value)} />
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setNewEntryOpen(false)}>Cancel</Button>
                                <Button onClick={saveNew} className="bg-sky-600 hover:bg-sky-700"
                                        data-testid="save-new-stock-button">Save</Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                )}
            </div>

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3 bg-white border border-slate-200 rounded-lg p-3">
                <Select value={selectedDept} onValueChange={setSelectedDept} disabled={isDeptStaff}>
                    <SelectTrigger className="w-56" data-testid="stock-dept-filter">
                        <SelectValue placeholder="All Departments" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All Departments</SelectItem>
                        {departments.map((d) =>
                            <SelectItem key={d.id} value={d.id}>{d.name_en} ({d.code})</SelectItem>)}
                    </SelectContent>
                </Select>
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                    <SelectTrigger className="w-48" data-testid="stock-status-filter">
                        <SelectValue placeholder="All Statuses" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All Statuses</SelectItem>
                        <SelectItem value="zero_level">Zero Stock</SelectItem>
                        <SelectItem value="critical_level">Critical</SelectItem>
                        <SelectItem value="available">Available</SelectItem>
                        <SelectItem value="back_in_stock">Back in Stock</SelectItem>
                    </SelectContent>
                </Select>
                <div className="text-sm text-slate-500">Records: <b className="tabular-nums">{stock.length}</b></div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="w-28">Department</TableHead>
                            <TableHead>Item</TableHead>
                            <TableHead className="w-28 text-right">Balance</TableHead>
                            <TableHead className="w-32 text-right">Min / Critical</TableHead>
                            <TableHead className="w-36">Status</TableHead>
                            <TableHead className="w-44">Last Updated</TableHead>
                            <TableHead className="w-44">Shortage Since</TableHead>
                            {canEdit && <TableHead className="w-28">Action</TableHead>}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {stock.map((row, idx) => (
                            <TableRow key={row.id} className={`hover:bg-slate-50 ${idx % 2 ? "bg-slate-50/40" : ""}`}
                                      data-testid={`stock-row-${row.id}`}>
                                <TableCell>
                                    <div className="font-semibold text-sm">{row.department?.code}</div>
                                    <div className="text-xs text-slate-500">{row.department?.name_en}</div>
                                </TableCell>
                                <TableCell>
                                    <div className="font-semibold text-sm flex items-center gap-2">
                                        {row.item?.name_en}
                                        {row.item?.is_life_saving && <Heart className="w-3.5 h-3.5 text-red-500" />}
                                    </div>
                                    <div className="text-xs text-slate-500 font-mono">{row.item?.internal_code}</div>
                                </TableCell>
                                <TableCell className="num-cell">
                                    <span className="font-heading text-lg font-black">{row.balance}</span>
                                    <span className="text-xs text-slate-500 ml-1">{row.item?.unit}</span>
                                </TableCell>
                                <TableCell className="num-cell text-slate-600">
                                    {row.item?.min_level} / {row.item?.critical_threshold}
                                </TableCell>
                                <TableCell><StatusBadge status={row.status} /></TableCell>
                                <TableCell className="text-xs text-slate-500 font-mono">
                                    {fmtDate(row.last_updated_at)}
                                </TableCell>
                                <TableCell className="text-xs text-slate-500 font-mono">
                                    {row.shortage_start ? fmtDate(row.shortage_start) : "—"}
                                </TableCell>
                                {canEdit && (
                                    <TableCell>
                                        <Button variant="ghost" size="sm" onClick={() => openEdit(row)}
                                                data-testid={`edit-stock-${row.id}`}>
                                            <Pencil className="w-4 h-4 mr-1" /> Update
                                        </Button>
                                    </TableCell>
                                )}
                            </TableRow>
                        ))}
                        {stock.length === 0 && (
                            <TableRow><TableCell colSpan={8} className="text-center py-10 text-slate-500">
                                No stock records
                            </TableCell></TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>

            {/* Edit dialog */}
            <Dialog open={editOpen} onOpenChange={setEditOpen}>
                <DialogContent>
                    <DialogHeader><DialogTitle>Update Stock</DialogTitle></DialogHeader>
                    {editing && (
                        <div className="space-y-3">
                            <div className="bg-slate-50 rounded-md p-3 border border-slate-200">
                                <div className="text-sm font-bold">{editing.item?.name_en}</div>
                                <div className="text-xs text-slate-500">
                                    {editing.department?.name_en} ({editing.department?.code})
                                </div>
                            </div>
                            <div>
                                <Label className="text-xs font-bold">New Balance</Label>
                                <Input type="number" value={editBalance} data-testid="edit-stock-balance-input"
                                       onChange={(e) => setEditBalance(e.target.value)} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">Reason / Notes</Label>
                                <Input value={editNote} onChange={(e) => setEditNote(e.target.value)} />
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditOpen(false)}>Cancel</Button>
                        <Button onClick={saveEdit} className="bg-sky-600 hover:bg-sky-700"
                                data-testid="save-stock-button">Save</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

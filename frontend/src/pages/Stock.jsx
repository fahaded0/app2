import React, { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
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
import { Plus, Heart, Pencil, FilePlus2 } from "lucide-react";
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
    const [editing, setEditing] = useState(null);     // existing stock entry
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
            toast.success("تم تحديث الرصيد");
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
            toast.success("تم إنشاء سجل الرصيد");
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
                <h1 className="font-heading text-3xl font-black tracking-tight">إدخال ومتابعة الرصيد</h1>
                {canEdit && (
                    <Dialog open={newEntryOpen} onOpenChange={setNewEntryOpen}>
                        <DialogTrigger asChild>
                            <Button className="bg-sky-600 hover:bg-sky-700" data-testid="new-stock-entry-button">
                                <FilePlus2 className="w-4 h-4 me-2" /> إدخال رصيد جديد
                            </Button>
                        </DialogTrigger>
                        <DialogContent dir="rtl">
                            <DialogHeader><DialogTitle>إدخال رصيد جديد</DialogTitle></DialogHeader>
                            <div className="space-y-3">
                                <div>
                                    <Label className="text-xs font-bold">القسم</Label>
                                    <Select value={newDept || (isDeptStaff ? user.department_id : "")}
                                            onValueChange={setNewDept}
                                            disabled={isDeptStaff}>
                                        <SelectTrigger data-testid="new-stock-dept-select"><SelectValue placeholder="اختر القسم" /></SelectTrigger>
                                        <SelectContent>
                                            {departments.map((d) =>
                                                <SelectItem key={d.id} value={d.id}>{d.name_ar} - {d.code}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الصنف</Label>
                                    <Select value={newItem} onValueChange={setNewItem}>
                                        <SelectTrigger data-testid="new-stock-item-select"><SelectValue placeholder="اختر الصنف" /></SelectTrigger>
                                        <SelectContent className="max-h-72">
                                            {items.map((it) =>
                                                <SelectItem key={it.id} value={it.id}>{it.name_ar} ({it.internal_code})</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الرصيد الحالي</Label>
                                    <Input type="number" value={newBalance} data-testid="new-stock-balance-input"
                                           onChange={(e) => setNewBalance(e.target.value)} />
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setNewEntryOpen(false)}>إلغاء</Button>
                                <Button onClick={saveNew} className="bg-sky-600 hover:bg-sky-700"
                                        data-testid="save-new-stock-button">حفظ</Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                )}
            </div>

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3 bg-white border border-slate-200 rounded-lg p-3">
                <Select value={selectedDept} onValueChange={setSelectedDept} disabled={isDeptStaff}>
                    <SelectTrigger className="w-56" data-testid="stock-dept-filter">
                        <SelectValue placeholder="كل الأقسام" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">كل الأقسام</SelectItem>
                        {departments.map((d) =>
                            <SelectItem key={d.id} value={d.id}>{d.name_ar} ({d.code})</SelectItem>)}
                    </SelectContent>
                </Select>
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                    <SelectTrigger className="w-48" data-testid="stock-status-filter">
                        <SelectValue placeholder="كل الحالات" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">كل الحالات</SelectItem>
                        <SelectItem value="zero_level">صفر مخزون</SelectItem>
                        <SelectItem value="critical_level">حرج</SelectItem>
                        <SelectItem value="available">متوفر</SelectItem>
                        <SelectItem value="back_in_stock">عاد للمخزون</SelectItem>
                    </SelectContent>
                </Select>
                <div className="text-sm text-slate-500">السجلات: <b>{stock.length}</b></div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="text-start">القسم</TableHead>
                            <TableHead className="text-start">الصنف</TableHead>
                            <TableHead className="text-start">الرصيد</TableHead>
                            <TableHead className="text-start">Min / Critical</TableHead>
                            <TableHead className="text-start">الحالة</TableHead>
                            <TableHead className="text-start">آخر تحديث</TableHead>
                            <TableHead className="text-start">بدأ النقص</TableHead>
                            {canEdit && <TableHead className="text-start">إجراء</TableHead>}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {stock.map((row, idx) => (
                            <TableRow key={row.id} className={`hover:bg-slate-50 ${idx % 2 ? "bg-slate-50/40" : ""}`}
                                      data-testid={`stock-row-${row.id}`}>
                                <TableCell>
                                    <div className="font-bold text-sm">{row.department?.name_ar}</div>
                                    <div className="text-xs text-slate-500">{row.department?.code}</div>
                                </TableCell>
                                <TableCell>
                                    <div className="font-bold text-sm flex items-center gap-2">
                                        {row.item?.name_ar}
                                        {row.item?.is_life_saving && <Heart className="w-3.5 h-3.5 text-red-500" />}
                                    </div>
                                    <div className="text-xs text-slate-500" dir="ltr">{row.item?.internal_code}</div>
                                </TableCell>
                                <TableCell>
                                    <span className="font-heading text-lg font-black">{row.balance}</span>
                                    <span className="text-xs text-slate-500 ms-1">{row.item?.unit}</span>
                                </TableCell>
                                <TableCell className="text-xs text-slate-600">
                                    {row.item?.min_level} / {row.item?.critical_threshold}
                                </TableCell>
                                <TableCell><StatusBadge status={row.status} /></TableCell>
                                <TableCell className="text-xs text-slate-500" dir="ltr">
                                    {new Date(row.last_updated_at).toLocaleString("ar-SA")}
                                </TableCell>
                                <TableCell className="text-xs text-slate-500" dir="ltr">
                                    {row.shortage_start ? new Date(row.shortage_start).toLocaleString("ar-SA") : "—"}
                                </TableCell>
                                {canEdit && (
                                    <TableCell>
                                        <Button variant="ghost" size="sm" onClick={() => openEdit(row)}
                                                data-testid={`edit-stock-${row.id}`}>
                                            <Pencil className="w-4 h-4" /> تحديث
                                        </Button>
                                    </TableCell>
                                )}
                            </TableRow>
                        ))}
                        {stock.length === 0 && (
                            <TableRow><TableCell colSpan={8} className="text-center py-10 text-slate-500">
                                لا توجد سجلات رصيد
                            </TableCell></TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>

            {/* Edit dialog */}
            <Dialog open={editOpen} onOpenChange={setEditOpen}>
                <DialogContent dir="rtl">
                    <DialogHeader><DialogTitle>تحديث رصيد</DialogTitle></DialogHeader>
                    {editing && (
                        <div className="space-y-3">
                            <div className="bg-slate-50 rounded-md p-3 border border-slate-200">
                                <div className="text-sm font-bold">{editing.item?.name_ar}</div>
                                <div className="text-xs text-slate-500">
                                    {editing.department?.name_ar} - {editing.department?.code}
                                </div>
                            </div>
                            <div>
                                <Label className="text-xs font-bold">الرصيد الجديد</Label>
                                <Input type="number" value={editBalance} data-testid="edit-stock-balance-input"
                                       onChange={(e) => setEditBalance(e.target.value)} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">سبب التغيير / ملاحظة</Label>
                                <Input value={editNote} onChange={(e) => setEditNote(e.target.value)} />
                            </div>
                        </div>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditOpen(false)}>إلغاء</Button>
                        <Button onClick={saveEdit} className="bg-sky-600 hover:bg-sky-700"
                                data-testid="save-stock-button">حفظ</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

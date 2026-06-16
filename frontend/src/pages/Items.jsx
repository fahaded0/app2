import React, { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger
} from "@/components/ui/dialog";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
    Table, TableHeader, TableBody, TableRow, TableHead, TableCell
} from "@/components/ui/table";
import { Plus, Search, Heart, PackageOpen, Pencil, Barcode } from "lucide-react";
import { useAuth, hasRole } from "@/lib/auth";
import { toast } from "sonner";

const CATEGORIES = ["Airway","PPE","Lab","IV","Wound Care","Equipment","Medication","Other"];
const UNITS = ["PCS","BOX","KIT","VIAL","PACK"];

const EMPTY = {
    internal_code: "", barcode: "", udi: "", name_ar: "", name_en: "",
    category: "Other", unit: "PCS",
    min_level: 0, critical_threshold: 0, max_level: 0,
    is_life_saving: false, is_crash_cart: false, requires_expiry: false,
    supplier: "", notes: "",
};

export default function Items() {
    const { user } = useAuth();
    const canManage = hasRole(user, "super_admin","digital_health_manager","supply_officer");
    const [items, setItems] = useState([]);
    const [search, setSearch] = useState("");
    const [categoryFilter, setCategoryFilter] = useState("all");
    const [dialogOpen, setDialogOpen] = useState(false);
    const [editing, setEditing] = useState(null);
    const [form, setForm] = useState(EMPTY);
    const [saving, setSaving] = useState(false);

    function load() {
        const params = {};
        if (search) params.search = search;
        if (categoryFilter && categoryFilter !== "all") params.category = categoryFilter;
        api.get("/items", { params }).then((r) => setItems(r.data));
    }

    useEffect(() => { load(); /* eslint-disable-next-line */ }, [categoryFilter]);
    useEffect(() => { const t = setTimeout(load, 400); return () => clearTimeout(t); /* eslint-disable-next-line */ }, [search]);

    const filtered = useMemo(() => items, [items]);

    function openCreate() {
        setEditing(null);
        setForm(EMPTY);
        setDialogOpen(true);
    }
    function openEdit(it) {
        setEditing(it);
        setForm({ ...EMPTY, ...it });
        setDialogOpen(true);
    }

    async function save() {
        setSaving(true);
        try {
            const payload = {
                ...form,
                min_level: Number(form.min_level) || 0,
                critical_threshold: Number(form.critical_threshold) || 0,
                max_level: Number(form.max_level) || 0,
                barcode: form.barcode || null,
                udi: form.udi || null,
                supplier: form.supplier || null,
                notes: form.notes || null,
            };
            if (editing) {
                const { internal_code: _ic, id: _id, created_at: _c, updated_at: _u, ...rest } = payload;
                await api.patch(`/items/${editing.id}`, rest);
                toast.success("تم تحديث الصنف");
            } else {
                await api.post("/items", payload);
                toast.success("تم إنشاء الصنف");
            }
            setDialogOpen(false);
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="space-y-5" data-testid="items-page">
            <div className="flex items-center justify-between gap-4">
                <h1 className="font-heading text-3xl font-black tracking-tight">سجل الأصناف (Item Master)</h1>
                {canManage && (
                    <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                        <DialogTrigger asChild>
                            <Button onClick={openCreate} data-testid="add-item-button" className="bg-sky-600 hover:bg-sky-700">
                                <Plus className="w-4 h-4 me-2" /> إضافة صنف
                            </Button>
                        </DialogTrigger>
                        <DialogContent className="max-w-2xl" dir="rtl">
                            <DialogHeader>
                                <DialogTitle>{editing ? "تعديل صنف" : "إضافة صنف جديد"}</DialogTitle>
                            </DialogHeader>
                            <div className="grid grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pe-1">
                                <div>
                                    <Label className="text-xs font-bold">رمز داخلي</Label>
                                    <Input value={form.internal_code} disabled={!!editing}
                                           data-testid="item-internal-code-input"
                                           onChange={(e) => setForm({ ...form, internal_code: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Barcode</Label>
                                    <Input value={form.barcode || ""} data-testid="item-barcode-input"
                                           onChange={(e) => setForm({ ...form, barcode: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">UDI</Label>
                                    <Input value={form.udi || ""} onChange={(e) => setForm({ ...form, udi: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الفئة</Label>
                                    <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                                        <SelectTrigger><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الاسم بالعربية</Label>
                                    <Input value={form.name_ar} data-testid="item-name-ar-input"
                                           onChange={(e) => setForm({ ...form, name_ar: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">English Name</Label>
                                    <Input value={form.name_en} dir="ltr"
                                           onChange={(e) => setForm({ ...form, name_en: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الوحدة</Label>
                                    <Select value={form.unit} onValueChange={(v) => setForm({ ...form, unit: v })}>
                                        <SelectTrigger><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            {UNITS.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">المورد</Label>
                                    <Input value={form.supplier || ""}
                                           onChange={(e) => setForm({ ...form, supplier: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الحد الأدنى</Label>
                                    <Input type="number" value={form.min_level} data-testid="item-min-input"
                                           onChange={(e) => setForm({ ...form, min_level: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الحد الحرج</Label>
                                    <Input type="number" value={form.critical_threshold} data-testid="item-critical-input"
                                           onChange={(e) => setForm({ ...form, critical_threshold: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">الحد الأعلى</Label>
                                    <Input type="number" value={form.max_level}
                                           onChange={(e) => setForm({ ...form, max_level: e.target.value })} />
                                </div>
                                <div className="col-span-2 grid grid-cols-3 gap-3 pt-2">
                                    <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                        <span className="text-xs font-bold">منقذ للحياة</span>
                                        <Switch checked={!!form.is_life_saving}
                                                onCheckedChange={(v) => setForm({ ...form, is_life_saving: v })}
                                                data-testid="item-lifesaving-toggle" />
                                    </label>
                                    <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                        <span className="text-xs font-bold">عربة الطوارئ</span>
                                        <Switch checked={!!form.is_crash_cart}
                                                onCheckedChange={(v) => setForm({ ...form, is_crash_cart: v })} />
                                    </label>
                                    <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                        <span className="text-xs font-bold">يحتاج انتهاء</span>
                                        <Switch checked={!!form.requires_expiry}
                                                onCheckedChange={(v) => setForm({ ...form, requires_expiry: v })} />
                                    </label>
                                </div>
                                <div className="col-span-2">
                                    <Label className="text-xs font-bold">ملاحظات</Label>
                                    <Input value={form.notes || ""}
                                           onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setDialogOpen(false)}>إلغاء</Button>
                                <Button onClick={save} disabled={saving} className="bg-sky-600 hover:bg-sky-700"
                                        data-testid="save-item-button">
                                    {saving ? "جاري الحفظ..." : "حفظ"}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                )}
            </div>

            {/* Filter bar */}
            <div className="flex flex-wrap items-center gap-3 bg-white border border-slate-200 rounded-lg p-3">
                <div className="relative flex-1 min-w-[220px]">
                    <Search className="w-4 h-4 absolute top-1/2 -translate-y-1/2 right-3 text-slate-400 pointer-events-none" />
                    <Input value={search} onChange={(e) => setSearch(e.target.value)}
                           placeholder="ابحث بالاسم أو الباركود أو الرمز..."
                           data-testid="items-search-input"
                           className="pe-9" />
                </div>
                <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                    <SelectTrigger className="w-48" data-testid="items-category-filter">
                        <SelectValue placeholder="كل الفئات" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">كل الفئات</SelectItem>
                        {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                </Select>
                <div className="text-sm text-slate-500">العدد: <b>{filtered.length}</b></div>
            </div>

            {/* Table */}
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="text-start">الرمز</TableHead>
                            <TableHead className="text-start">الباركود</TableHead>
                            <TableHead className="text-start">الاسم</TableHead>
                            <TableHead className="text-start">الفئة</TableHead>
                            <TableHead className="text-start">الوحدة</TableHead>
                            <TableHead className="text-start">Min</TableHead>
                            <TableHead className="text-start">Critical</TableHead>
                            <TableHead className="text-start">العلامات</TableHead>
                            {canManage && <TableHead className="text-start">إجراءات</TableHead>}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {filtered.map((it) => (
                            <TableRow key={it.id} data-testid={`item-row-${it.id}`} className="hover:bg-slate-50">
                                <TableCell className="font-mono text-xs" dir="ltr">{it.internal_code}</TableCell>
                                <TableCell className="font-mono text-xs" dir="ltr">
                                    {it.barcode ? (
                                        <span className="inline-flex items-center gap-1">
                                            <Barcode className="w-3.5 h-3.5 text-slate-400" />{it.barcode}
                                        </span>
                                    ) : (
                                        <span className="text-amber-600 text-xs">No code</span>
                                    )}
                                </TableCell>
                                <TableCell>
                                    <div className="font-bold">{it.name_ar}</div>
                                    <div className="text-xs text-slate-500" dir="ltr">{it.name_en}</div>
                                </TableCell>
                                <TableCell><span className="text-xs">{it.category}</span></TableCell>
                                <TableCell><span className="text-xs">{it.unit}</span></TableCell>
                                <TableCell>{it.min_level}</TableCell>
                                <TableCell>{it.critical_threshold}</TableCell>
                                <TableCell>
                                    <div className="flex gap-1 flex-wrap">
                                        {it.is_life_saving && <span className="status-pill status-zero text-[10px]"><Heart className="w-3 h-3" />منقذ</span>}
                                        {it.is_crash_cart && <span className="status-pill status-critical text-[10px]"><PackageOpen className="w-3 h-3" />عربة طوارئ</span>}
                                    </div>
                                </TableCell>
                                {canManage && (
                                    <TableCell>
                                        <Button variant="ghost" size="sm" onClick={() => openEdit(it)}
                                                data-testid={`edit-item-${it.id}`}>
                                            <Pencil className="w-4 h-4" />
                                        </Button>
                                    </TableCell>
                                )}
                            </TableRow>
                        ))}
                        {filtered.length === 0 && (
                            <TableRow>
                                <TableCell colSpan={9} className="text-center py-10 text-slate-500">
                                    لا توجد أصناف
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}

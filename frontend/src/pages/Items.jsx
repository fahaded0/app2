import React, { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger
} from "@/components/ui/dialog";
import {
    Select, SelectTrigger, SelectValue, SelectContent, SelectItem
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
    Table, TableHeader, TableBody, TableRow, TableHead, TableCell
} from "@/components/ui/table";
import { Plus, Search, Heart, PackageOpen, Pencil, Barcode, Sliders } from "lucide-react";
import { useAuth, hasRole } from "@/lib/auth";
import { toast } from "sonner";

const CATEGORIES = ["Airway","PPE","Lab","IV","Wound Care","Equipment","Medication","Other"];
const UNITS = ["PCS","BOX","KIT","VIAL","PACK"];

const EMPTY = {
    internal_code: "", barcode: "", udi: "", gtin: "", name_ar: "", name_en: "",
    category: "Other", unit: "PCS",
    min_level: 0, critical_threshold: 0, max_level: 0,
    reorder_qty: 0, lead_time_days: 0, alternative_item_id: "",
    is_life_saving: false, is_crash_cart: false, requires_expiry: false,
    supplier: "", notes: "",
};

export default function Items() {
    const { user } = useAuth();
    const canManage = hasRole(user, "super_admin","digital_health_manager","supply_officer");
    const canEditThresholds = hasRole(user, "super_admin","digital_health_manager","supply_officer","department_head");
    const [items, setItems] = useState([]);
    const [search, setSearch] = useState("");
    const [categoryFilter, setCategoryFilter] = useState("all");
    const [dialogOpen, setDialogOpen] = useState(false);
    const [editing, setEditing] = useState(null);
    const [form, setForm] = useState(EMPTY);
    const [saving, setSaving] = useState(false);

    // Threshold editor
    const [thresholdOpen, setThresholdOpen] = useState(false);
    const [thresholdItem, setThresholdItem] = useState(null);
    const [departments, setDepartments] = useState([]);
    const [thDeptId, setThDeptId] = useState("");
    const [thresholdForm, setThresholdForm] = useState({
        minimum_level: 0, critical_level: 0, emergency_reserve_level: 0,
        no_issue_threshold: 0, allow_emergency_override: true,
        requires_approval_below_reserve: true, escalation_minutes: 30,
    });
    const [savingThreshold, setSavingThreshold] = useState(false);

    function load() {
        const params = {};
        if (search) params.search = search;
        if (categoryFilter && categoryFilter !== "all") params.category = categoryFilter;
        api.get("/items", { params }).then((r) => setItems(r.data));
    }

    useEffect(() => { load(); /* eslint-disable-next-line */ }, [categoryFilter]);
    useEffect(() => { const t = setTimeout(load, 400); return () => clearTimeout(t); /* eslint-disable-next-line */ }, [search]);
    useEffect(() => {
        if (canEditThresholds) api.get("/departments").then((r) => setDepartments(r.data));
    }, [canEditThresholds]);

    async function openThresholds(it) {
        setThresholdItem(it);
        setThresholdOpen(true);
        // pre-pick first department
        const depts = departments.length ? departments : (await api.get("/departments")).data;
        if (!departments.length) setDepartments(depts);
        const firstId = depts[0]?.id || "";
        setThDeptId(firstId);
        if (firstId) await loadThresholdFor(it.id, firstId);
    }

    async function loadThresholdFor(itemId, deptId) {
        try {
            const r = await api.get(`/items/${itemId}/thresholds/${deptId}`);
            setThresholdForm({
                minimum_level: r.data.minimum_level || 0,
                critical_level: r.data.critical_level || 0,
                emergency_reserve_level: r.data.emergency_reserve_level || 0,
                no_issue_threshold: r.data.no_issue_threshold || 0,
                allow_emergency_override: r.data.allow_emergency_override ?? true,
                requires_approval_below_reserve: r.data.requires_approval_below_reserve ?? true,
                escalation_minutes: r.data.escalation_minutes ?? 30,
            });
        } catch (_) {
            // keep defaults
        }
    }

    async function saveThreshold() {
        if (!thresholdItem || !thDeptId) return;
        setSavingThreshold(true);
        try {
            const payload = {
                minimum_level: Number(thresholdForm.minimum_level) || 0,
                critical_level: Number(thresholdForm.critical_level) || 0,
                emergency_reserve_level: Number(thresholdForm.emergency_reserve_level) || 0,
                no_issue_threshold: Number(thresholdForm.no_issue_threshold) || 0,
                allow_emergency_override: !!thresholdForm.allow_emergency_override,
                requires_approval_below_reserve: !!thresholdForm.requires_approval_below_reserve,
                escalation_minutes: Number(thresholdForm.escalation_minutes) || 30,
            };
            await api.put(`/items/${thresholdItem.id}/thresholds/${thDeptId}`, payload);
            toast.success("Thresholds saved");
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSavingThreshold(false);
        }
    }

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
                name_ar: form.name_ar || form.name_en,
                min_level: Number(form.min_level) || 0,
                critical_threshold: Number(form.critical_threshold) || 0,
                max_level: Number(form.max_level) || 0,
                reorder_qty: Number(form.reorder_qty) || 0,
                lead_time_days: Number(form.lead_time_days) || 0,
                alternative_item_id: form.alternative_item_id || null,
                barcode: form.barcode || null,
                udi: form.udi || null,
                gtin: form.gtin || null,
                supplier: form.supplier || null,
                notes: form.notes || null,
            };
            if (editing) {
                const { internal_code: _ic, id: _id, created_at: _c, updated_at: _u, ...rest } = payload;
                await api.patch(`/items/${editing.id}`, rest);
                toast.success("Item updated");
            } else {
                await api.post("/items", payload);
                toast.success("Item created");
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
                <h1 className="font-heading text-3xl font-black tracking-tight">Item Master</h1>
                {canManage && (
                    <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                        <DialogTrigger asChild>
                            <Button onClick={openCreate} data-testid="add-item-button" className="bg-sky-600 hover:bg-sky-700">
                                <Plus className="w-4 h-4 mr-2" /> Add Item
                            </Button>
                        </DialogTrigger>
                        <DialogContent className="max-w-2xl">
                            <DialogHeader>
                                <DialogTitle>{editing ? "Edit Item" : "Add New Item"}</DialogTitle>
                                <DialogDescription>
                                    Define the item master record. Internal Code and Barcode are the
                                    primary identifiers used during stock entry and Excel import matching.
                                </DialogDescription>
                            </DialogHeader>
                            <div className="grid grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
                                <div>
                                    <Label className="text-xs font-bold">Internal Code</Label>
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
                                    <Label className="text-xs font-bold">GTIN</Label>
                                    <Input value={form.gtin || ""} onChange={(e) => setForm({ ...form, gtin: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Category</Label>
                                    <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                                        <SelectTrigger><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="col-span-2">
                                    <Label className="text-xs font-bold">Item Name</Label>
                                    <Input value={form.name_en} data-testid="item-name-input"
                                           onChange={(e) => setForm({ ...form, name_en: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Unit</Label>
                                    <Select value={form.unit} onValueChange={(v) => setForm({ ...form, unit: v })}>
                                        <SelectTrigger><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            {UNITS.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Supplier</Label>
                                    <Input value={form.supplier || ""}
                                           onChange={(e) => setForm({ ...form, supplier: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Min Level</Label>
                                    <Input type="number" value={form.min_level} data-testid="item-min-input"
                                           onChange={(e) => setForm({ ...form, min_level: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Critical Threshold</Label>
                                    <Input type="number" value={form.critical_threshold} data-testid="item-critical-input"
                                           onChange={(e) => setForm({ ...form, critical_threshold: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Max Level</Label>
                                    <Input type="number" value={form.max_level}
                                           onChange={(e) => setForm({ ...form, max_level: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Reorder Qty</Label>
                                    <Input type="number" value={form.reorder_qty}
                                           onChange={(e) => setForm({ ...form, reorder_qty: e.target.value })} />
                                </div>
                                <div>
                                    <Label className="text-xs font-bold">Lead Time (days)</Label>
                                    <Input type="number" value={form.lead_time_days}
                                           onChange={(e) => setForm({ ...form, lead_time_days: e.target.value })} />
                                </div>
                                <div className="col-span-2 grid grid-cols-3 gap-3 pt-2">
                                    <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                        <span className="text-xs font-bold">Life-Saving</span>
                                        <Switch checked={!!form.is_life_saving}
                                                onCheckedChange={(v) => setForm({ ...form, is_life_saving: v })}
                                                data-testid="item-lifesaving-toggle" />
                                    </label>
                                    <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                        <span className="text-xs font-bold">Crash Cart</span>
                                        <Switch checked={!!form.is_crash_cart}
                                                onCheckedChange={(v) => setForm({ ...form, is_crash_cart: v })} />
                                    </label>
                                    <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                        <span className="text-xs font-bold">Needs Expiry</span>
                                        <Switch checked={!!form.requires_expiry}
                                                onCheckedChange={(v) => setForm({ ...form, requires_expiry: v })} />
                                    </label>
                                </div>
                                <div className="col-span-2">
                                    <Label className="text-xs font-bold">Notes</Label>
                                    <Input value={form.notes || ""}
                                           onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                                <Button onClick={save} disabled={saving} className="bg-sky-600 hover:bg-sky-700"
                                        data-testid="save-item-button">
                                    {saving ? "Saving..." : "Save"}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                )}
            </div>

            {/* Filter bar */}
            <div className="flex flex-wrap items-center gap-3 bg-white border border-slate-200 rounded-lg p-3">
                <div className="relative flex-1 min-w-[220px]">
                    <Search className="w-4 h-4 absolute top-1/2 -translate-y-1/2 left-3 text-slate-400 pointer-events-none" />
                    <Input value={search} onChange={(e) => setSearch(e.target.value)}
                           placeholder="Search by name, barcode or code..."
                           data-testid="items-search-input"
                           className="pl-9" />
                </div>
                <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                    <SelectTrigger className="w-48" data-testid="items-category-filter">
                        <SelectValue placeholder="All Categories" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All Categories</SelectItem>
                        {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                </Select>
                <div className="text-sm text-slate-500">Total: <b className="tabular-nums">{filtered.length}</b></div>
            </div>

            {/* Table */}
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="w-32">Code</TableHead>
                            <TableHead className="w-40">Barcode</TableHead>
                            <TableHead>Name</TableHead>
                            <TableHead className="w-28">Category</TableHead>
                            <TableHead className="w-20">Unit</TableHead>
                            <TableHead className="w-20 text-right">Min</TableHead>
                            <TableHead className="w-24 text-right">Critical</TableHead>
                            <TableHead className="w-44">Flags</TableHead>
                            {canManage && <TableHead className="w-20">Actions</TableHead>}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {filtered.map((it) => (
                            <TableRow key={it.id} data-testid={`item-row-${it.id}`} className="hover:bg-slate-50">
                                <TableCell className="code-cell">{it.internal_code}</TableCell>
                                <TableCell className="code-cell">
                                    {it.barcode ? (
                                        <span className="inline-flex items-center gap-1">
                                            <Barcode className="w-3.5 h-3.5 text-slate-400" />{it.barcode}
                                        </span>
                                    ) : (
                                        <span className="text-amber-600 text-xs">No code</span>
                                    )}
                                </TableCell>
                                <TableCell>
                                    <div className="font-semibold text-sm">{it.name_en}</div>
                                </TableCell>
                                <TableCell><span className="text-xs">{it.category}</span></TableCell>
                                <TableCell><span className="text-xs font-mono">{it.unit}</span></TableCell>
                                <TableCell className="num-cell">{it.min_level}</TableCell>
                                <TableCell className="num-cell">{it.critical_threshold}</TableCell>
                                <TableCell>
                                    <div className="flex gap-1 flex-wrap">
                                        {it.is_life_saving && <span className="status-pill status-zero text-[10px]"><Heart className="w-3 h-3" />Life-Saving</span>}
                                        {it.is_crash_cart && <span className="status-pill status-critical text-[10px]"><PackageOpen className="w-3 h-3" />Crash Cart</span>}
                                    </div>
                                </TableCell>
                                {canManage && (
                                    <TableCell>
                                        <div className="flex gap-1">
                                            <Button variant="ghost" size="sm" onClick={() => openEdit(it)}
                                                    data-testid={`edit-item-${it.id}`}>
                                                <Pencil className="w-4 h-4" />
                                            </Button>
                                            {canEditThresholds && (
                                                <Button variant="ghost" size="sm" onClick={() => openThresholds(it)}
                                                        title="Per-department thresholds"
                                                        data-testid={`thresholds-item-${it.id}`}>
                                                    <Sliders className="w-4 h-4" />
                                                </Button>
                                            )}
                                        </div>
                                    </TableCell>
                                )}
                            </TableRow>
                        ))}
                        {filtered.length === 0 && (
                            <TableRow>
                                <TableCell colSpan={9} className="text-center py-10 text-slate-500">
                                    No items found
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>

            {/* Per-department thresholds dialog */}
            <Dialog open={thresholdOpen} onOpenChange={setThresholdOpen}>
                <DialogContent className="max-w-2xl">
                    <DialogHeader>
                        <DialogTitle>Per-Department Thresholds</DialogTitle>
                        <DialogDescription>
                            Configure issue thresholds for <span className="font-bold">{thresholdItem?.name_en}</span> in each department.
                            Required ordering: <code>no_issue ≤ reserve ≤ critical ≤ minimum</code>.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div>
                            <Label className="text-xs font-bold">Department</Label>
                            <Select value={thDeptId} onValueChange={async (v) => {
                                setThDeptId(v);
                                if (thresholdItem) await loadThresholdFor(thresholdItem.id, v);
                            }}>
                                <SelectTrigger data-testid="th-dept-select"><SelectValue placeholder="Department" /></SelectTrigger>
                                <SelectContent>
                                    {departments.map((d) => (
                                        <SelectItem key={d.id} value={d.id}>{d.code} — {d.name_en}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <div>
                                <Label className="text-xs font-bold">Minimum</Label>
                                <Input type="number" min="0" value={thresholdForm.minimum_level}
                                       data-testid="th-min-input"
                                       onChange={(e) => setThresholdForm({ ...thresholdForm, minimum_level: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">Critical</Label>
                                <Input type="number" min="0" value={thresholdForm.critical_level}
                                       data-testid="th-crit-input"
                                       onChange={(e) => setThresholdForm({ ...thresholdForm, critical_level: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">Emergency Reserve</Label>
                                <Input type="number" min="0" value={thresholdForm.emergency_reserve_level}
                                       data-testid="th-reserve-input"
                                       onChange={(e) => setThresholdForm({ ...thresholdForm, emergency_reserve_level: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">No-Issue Threshold</Label>
                                <Input type="number" min="0" value={thresholdForm.no_issue_threshold}
                                       data-testid="th-noissue-input"
                                       onChange={(e) => setThresholdForm({ ...thresholdForm, no_issue_threshold: e.target.value })} />
                            </div>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                            <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                <span className="text-xs font-bold">Allow Emergency Override</span>
                                <Switch checked={!!thresholdForm.allow_emergency_override}
                                        onCheckedChange={(v) => setThresholdForm({ ...thresholdForm, allow_emergency_override: v })}
                                        data-testid="th-allow-override-toggle" />
                            </label>
                            <label className="flex items-center justify-between bg-slate-50 rounded-md p-2 border border-slate-200">
                                <span className="text-xs font-bold">Approval Below Reserve</span>
                                <Switch checked={!!thresholdForm.requires_approval_below_reserve}
                                        onCheckedChange={(v) => setThresholdForm({ ...thresholdForm, requires_approval_below_reserve: v })} />
                            </label>
                            <div className="flex items-center gap-2 bg-slate-50 rounded-md p-2 border border-slate-200">
                                <span className="text-xs font-bold whitespace-nowrap">Escalation (min)</span>
                                <Input type="number" min="0" value={thresholdForm.escalation_minutes}
                                       data-testid="th-escalation-input"
                                       className="w-20"
                                       onChange={(e) => setThresholdForm({ ...thresholdForm, escalation_minutes: e.target.value })} />
                            </div>
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setThresholdOpen(false)}>Close</Button>
                        <Button onClick={saveThreshold} disabled={savingThreshold} className="bg-sky-600 hover:bg-sky-700"
                                data-testid="save-threshold-button">
                            {savingThreshold ? "Saving..." : "Save Thresholds"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

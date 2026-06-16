import React, { useEffect, useState } from "react";
import { api, formatApiError, ROLE_LABELS } from "@/lib/api";
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
import { Switch } from "@/components/ui/switch";
import { Plus, UserPlus } from "lucide-react";
import { toast } from "sonner";

const ROLES = Object.keys(ROLE_LABELS);

export default function Users() {
    const [users, setUsers] = useState([]);
    const [departments, setDepartments] = useState([]);
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({
        email: "", full_name: "", password: "",
        role: "viewer", department_id: "none",
    });

    function load() {
        api.get("/users").then((r) => setUsers(r.data));
        api.get("/departments").then((r) => setDepartments(r.data));
    }
    useEffect(load, []);

    async function save() {
        try {
            await api.post("/users", {
                ...form,
                department_id: form.department_id === "none" ? null : form.department_id,
            });
            toast.success("تم إنشاء المستخدم");
            setOpen(false);
            setForm({ email: "", full_name: "", password: "", role: "viewer", department_id: "none" });
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }

    async function toggleActive(u) {
        await api.patch(`/users/${u.id}`, { is_active: !u.is_active });
        toast.success(u.is_active ? "تم تعطيل الحساب" : "تم تفعيل الحساب");
        load();
    }

    return (
        <div className="space-y-5" data-testid="users-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">إدارة المستخدمين</h1>
                <Dialog open={open} onOpenChange={setOpen}>
                    <DialogTrigger asChild>
                        <Button className="bg-sky-600 hover:bg-sky-700" data-testid="add-user-button">
                            <UserPlus className="w-4 h-4 me-2" /> إضافة مستخدم
                        </Button>
                    </DialogTrigger>
                    <DialogContent dir="rtl">
                        <DialogHeader><DialogTitle>إضافة مستخدم جديد</DialogTitle></DialogHeader>
                        <div className="space-y-3">
                            <div>
                                <Label className="text-xs font-bold">الاسم الكامل</Label>
                                <Input value={form.full_name} data-testid="user-name-input"
                                       onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">البريد الإلكتروني</Label>
                                <Input type="email" value={form.email} dir="ltr" data-testid="user-email-input"
                                       onChange={(e) => setForm({ ...form, email: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">كلمة المرور</Label>
                                <Input type="password" value={form.password} data-testid="user-password-input"
                                       onChange={(e) => setForm({ ...form, password: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">الدور</Label>
                                <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                                    <SelectTrigger data-testid="user-role-select"><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        {ROLES.map((r) => <SelectItem key={r} value={r}>{ROLE_LABELS[r]}</SelectItem>)}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div>
                                <Label className="text-xs font-bold">القسم (اختياري)</Label>
                                <Select value={form.department_id}
                                        onValueChange={(v) => setForm({ ...form, department_id: v })}>
                                    <SelectTrigger><SelectValue placeholder="بدون قسم محدد" /></SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="none">بدون قسم محدد</SelectItem>
                                        {departments.map((d) =>
                                            <SelectItem key={d.id} value={d.id}>{d.name_ar} ({d.code})</SelectItem>)}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => setOpen(false)}>إلغاء</Button>
                            <Button onClick={save} className="bg-sky-600 hover:bg-sky-700"
                                    data-testid="save-user-button">إنشاء</Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="text-start">الاسم</TableHead>
                            <TableHead className="text-start">البريد</TableHead>
                            <TableHead className="text-start">الدور</TableHead>
                            <TableHead className="text-start">القسم</TableHead>
                            <TableHead className="text-start">الحالة</TableHead>
                            <TableHead className="text-start">إجراء</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {users.map((u) => {
                            const dept = departments.find((d) => d.id === u.department_id);
                            return (
                                <TableRow key={u.id} className="hover:bg-slate-50" data-testid={`user-row-${u.id}`}>
                                    <TableCell className="font-bold">{u.full_name}</TableCell>
                                    <TableCell dir="ltr" className="text-sm">{u.email}</TableCell>
                                    <TableCell className="text-sm">{ROLE_LABELS[u.role]}</TableCell>
                                    <TableCell className="text-sm">{dept ? `${dept.name_ar} (${dept.code})` : "—"}</TableCell>
                                    <TableCell>
                                        {u.is_active ? (
                                            <span className="status-pill status-available text-[10px]">مفعل</span>
                                        ) : (
                                            <span className="status-pill status-zero text-[10px]">معطل</span>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <Switch checked={u.is_active} onCheckedChange={() => toggleActive(u)}
                                                data-testid={`toggle-active-${u.id}`} />
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}

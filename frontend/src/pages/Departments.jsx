import React, { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
    Table, TableHeader, TableBody, TableRow, TableHead, TableCell
} from "@/components/ui/table";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger
} from "@/components/ui/dialog";
import { Plus, Building2 } from "lucide-react";
import { toast } from "sonner";

export default function Departments() {
    const [list, setList] = useState([]);
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({ code: "", name_ar: "", name_en: "", is_critical: false });

    function load() {
        api.get("/departments").then((r) => setList(r.data));
    }
    useEffect(load, []);

    async function save() {
        try {
            await api.post("/departments", form);
            toast.success("تم إنشاء القسم");
            setOpen(false);
            setForm({ code: "", name_ar: "", name_en: "", is_critical: false });
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }

    return (
        <div className="space-y-5" data-testid="departments-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">الأقسام</h1>
                <Dialog open={open} onOpenChange={setOpen}>
                    <DialogTrigger asChild>
                        <Button className="bg-sky-600 hover:bg-sky-700" data-testid="add-dept-button">
                            <Plus className="w-4 h-4 me-2" /> إضافة قسم
                        </Button>
                    </DialogTrigger>
                    <DialogContent dir="rtl">
                        <DialogHeader><DialogTitle>إضافة قسم جديد</DialogTitle></DialogHeader>
                        <div className="space-y-3">
                            <div>
                                <Label className="text-xs font-bold">الرمز (Code)</Label>
                                <Input value={form.code} dir="ltr" data-testid="dept-code-input"
                                       onChange={(e) => setForm({ ...form, code: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">الاسم بالعربية</Label>
                                <Input value={form.name_ar} data-testid="dept-name-ar-input"
                                       onChange={(e) => setForm({ ...form, name_ar: e.target.value })} />
                            </div>
                            <div>
                                <Label className="text-xs font-bold">English Name</Label>
                                <Input value={form.name_en} dir="ltr"
                                       onChange={(e) => setForm({ ...form, name_en: e.target.value })} />
                            </div>
                            <label className="flex items-center justify-between bg-slate-50 rounded-md p-3 border border-slate-200">
                                <span className="text-sm font-bold">قسم حرج (Critical Department)</span>
                                <Switch checked={form.is_critical}
                                        onCheckedChange={(v) => setForm({ ...form, is_critical: v })} />
                            </label>
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => setOpen(false)}>إلغاء</Button>
                            <Button onClick={save} className="bg-sky-600 hover:bg-sky-700"
                                    data-testid="save-dept-button">إنشاء</Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
                <Table className="table-dense">
                    <TableHeader className="bg-slate-50">
                        <TableRow>
                            <TableHead className="text-start">الرمز</TableHead>
                            <TableHead className="text-start">الاسم</TableHead>
                            <TableHead className="text-start">English</TableHead>
                            <TableHead className="text-start">حرج</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {list.map((d) => (
                            <TableRow key={d.id} data-testid={`dept-row-${d.id}`} className="hover:bg-slate-50">
                                <TableCell><span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">{d.code}</span></TableCell>
                                <TableCell className="font-bold">{d.name_ar}</TableCell>
                                <TableCell className="text-sm text-slate-600" dir="ltr">{d.name_en}</TableCell>
                                <TableCell>
                                    {d.is_critical ? (
                                        <span className="status-pill status-critical text-[10px]">حرج</span>
                                    ) : (
                                        <span className="text-xs text-slate-400">—</span>
                                    )}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}

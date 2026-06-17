import React, { useEffect, useState } from "react";
import { api, formatApiError, ROLE_LABELS } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
    ShieldCheck, AlertCircle, Heart, Clock, RotateCcw, Save, Mail, Send, Trash2,
} from "lucide-react";
import { toast } from "sonner";

const FIELD_META = [
    { key: "zero_level_normal_minutes",       label: "Zero Stock — normal item",           help: "Escalate to Supply + Dept Head after (minutes). Default 360 = 6h.",  icon: AlertCircle },
    { key: "zero_level_lifesaving_minutes",   label: "Zero Stock — life-saving item",      help: "Escalate immediately to management (minutes). Default 0 = instant.", icon: Heart },
    { key: "critical_level_escalation_minutes", label: "Critical Level — escalation time", help: "Escalate to management if not handled within (minutes). Default 1440 = 24h.", icon: AlertCircle },
    { key: "backorder_escalation_minutes",    label: "Backorder — escalation time",        help: "Escalate Backorder requests to procurement/management (minutes). Default 2880 = 48h.", icon: Clock },
    { key: "no_update_minutes",               label: "Stale data — no update threshold",   help: "Open a data-quality alert if stock not updated (minutes). Default 1440 = 24h.", icon: Clock },
    { key: "scheduler_interval_minutes",      label: "Scheduler interval",                 help: "How often the SLA engine runs (minutes). Default 15.", icon: RotateCcw },
];

const DEFAULTS = {
    zero_level_normal_minutes: 360,
    zero_level_lifesaving_minutes: 0,
    critical_level_escalation_minutes: 1440,
    backorder_escalation_minutes: 2880,
    no_update_minutes: 1440,
    scheduler_interval_minutes: 15,
};

// Roles that receive escalation emails (Stock Issue workflow)
const ESCALATION_ROLES = [
    "supply_officer",
    "department_head",
    "hospital_manager",
    "digital_health_manager",
    "procurement",
];

export default function Settings() {
    return (
        <div className="space-y-5" data-testid="settings-page">
            <h1 className="font-heading text-3xl font-black tracking-tight">Settings</h1>
            <Tabs defaultValue="sla">
                <TabsList>
                    <TabsTrigger value="sla" data-testid="tab-sla">
                        <ShieldCheck className="w-4 h-4 mr-2" /> SLA &amp; Escalation
                    </TabsTrigger>
                    <TabsTrigger value="recipients" data-testid="tab-recipients">
                        <Mail className="w-4 h-4 mr-2" /> Escalation Recipients
                    </TabsTrigger>
                </TabsList>
                <TabsContent value="sla" className="pt-4">
                    <SlaSection />
                </TabsContent>
                <TabsContent value="recipients" className="pt-4">
                    <RecipientsSection />
                </TabsContent>
            </Tabs>
        </div>
    );
}

function SlaSection() {
    const [data, setData] = useState(null);
    const [saving, setSaving] = useState(false);

    function load() {
        api.get("/settings/sla").then((r) => setData(r.data));
    }
    useEffect(load, []);

    async function save() {
        setSaving(true);
        try {
            const payload = {};
            for (const k of Object.keys(DEFAULTS)) payload[k] = Number(data[k]);
            const r = await api.put("/settings/sla", payload);
            setData(r.data);
            toast.success("SLA settings updated");
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSaving(false);
        }
    }
    function resetDefaults() { setData({ ...data, ...DEFAULTS }); }

    if (!data) return <div className="text-slate-500">Loading settings...</div>;

    return (
        <div className="space-y-4">
            <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={resetDefaults} data-testid="reset-defaults-button">
                    <RotateCcw className="w-4 h-4 mr-2" /> Reset Defaults
                </Button>
                <Button onClick={save} disabled={saving} className="bg-sky-600 hover:bg-sky-700"
                        data-testid="save-settings-button">
                    <Save className="w-4 h-4 mr-2" /> {saving ? "Saving..." : "Save Changes"}
                </Button>
            </div>
            <Card className="border-slate-200">
                <CardHeader className="pb-2">
                    <CardTitle className="font-heading text-lg flex items-center gap-2">
                        <ShieldCheck className="w-5 h-5 text-sky-600" />
                        Escalation Thresholds
                    </CardTitle>
                    <p className="text-xs text-slate-500 leading-relaxed mt-1">
                        These thresholds drive automatic escalation by the background SLA engine.
                        Smaller values raise alerts faster; <code>0</code> means escalate immediately at creation.
                    </p>
                </CardHeader>
                <CardContent>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {FIELD_META.map(({ key, label, help, icon: Icon }) => (
                            <div key={key} className="bg-slate-50 border border-slate-200 rounded-lg p-4"
                                 data-testid={`setting-${key}`}>
                                <div className="flex items-start gap-3 mb-2">
                                    <div className="w-9 h-9 rounded-md bg-white border border-slate-200 flex items-center justify-center text-sky-600 shrink-0">
                                        <Icon className="w-4 h-4" />
                                    </div>
                                    <div className="min-w-0">
                                        <Label className="text-sm font-bold text-slate-800">{label}</Label>
                                        <p className="text-xs text-slate-500 mt-0.5 leading-snug">{help}</p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-2">
                                    <Input type="number" min="0"
                                        className="w-32 tabular-nums text-right"
                                        value={data[key]}
                                        data-testid={`input-${key}`}
                                        onChange={(e) => setData({ ...data, [key]: e.target.value })} />
                                    <span className="text-xs text-slate-500 uppercase tracking-wider">minutes</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}

function RecipientsSection() {
    const [recipients, setRecipients] = useState([]);
    const [draft, setDraft] = useState({});
    const [saving, setSaving] = useState(null);

    function load() {
        api.get("/settings/escalation-recipients").then((r) => {
            setRecipients(r.data || []);
            const d = {};
            for (const x of r.data || []) d[x.role] = x.email || "";
            setDraft(d);
        });
    }
    useEffect(load, []);

    async function save(role) {
        const email = (draft[role] || "").trim();
        setSaving(role);
        try {
            await api.put("/settings/escalation-recipients", { role, email: email || null });
            toast.success(email ? `Saved recipient for ${ROLE_LABELS[role] || role}` : "Recipient removed");
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSaving(null);
        }
    }

    async function clear(role) {
        setSaving(role);
        try {
            await api.put("/settings/escalation-recipients", { role, email: null });
            toast.success("Recipient removed");
            load();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSaving(null);
        }
    }

    const map = Object.fromEntries(recipients.map((x) => [x.role, x.email]));

    return (
        <Card className="border-slate-200">
            <CardHeader className="pb-2">
                <CardTitle className="font-heading text-lg flex items-center gap-2">
                    <Mail className="w-5 h-5 text-sky-600" /> Escalation Recipients
                </CardTitle>
                <p className="text-xs text-slate-500 leading-relaxed mt-1">
                    The Stock Issue workflow sends escalation emails to every active user with the relevant role.
                    Optionally pin a fixed email per role here (e.g. shared mailbox <code>supply@hospital.sa</code>).
                </p>
            </CardHeader>
            <CardContent>
                <div className="space-y-3">
                    {ESCALATION_ROLES.map((role) => (
                        <div key={role} className="grid grid-cols-1 md:grid-cols-12 gap-3 bg-slate-50 border border-slate-200 rounded-md p-3"
                             data-testid={`recipient-row-${role}`}>
                            <div className="md:col-span-4">
                                <Label className="text-sm font-bold text-slate-800">{ROLE_LABELS[role] || role}</Label>
                                <p className="text-[11px] text-slate-500">{role}</p>
                            </div>
                            <div className="md:col-span-6">
                                <Input
                                    type="email"
                                    placeholder="e.g. supply@hospital.sa"
                                    value={draft[role] || ""}
                                    onChange={(e) => setDraft({ ...draft, [role]: e.target.value })}
                                    data-testid={`recipient-input-${role}`}
                                />
                            </div>
                            <div className="md:col-span-2 flex gap-2 justify-end">
                                <Button
                                    size="sm" variant="outline"
                                    onClick={() => clear(role)}
                                    disabled={saving === role || !map[role]}
                                    data-testid={`recipient-clear-${role}`}
                                >
                                    <Trash2 className="w-3.5 h-3.5" />
                                </Button>
                                <Button
                                    size="sm" className="bg-sky-600 hover:bg-sky-700"
                                    onClick={() => save(role)}
                                    disabled={saving === role}
                                    data-testid={`recipient-save-${role}`}
                                >
                                    <Send className="w-3.5 h-3.5 mr-1" /> Save
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
                <div className="text-[11px] text-slate-500 leading-relaxed mt-4">
                    Emails are sent via <span className="font-bold">Resend</span> from the address configured in
                    <code className="ml-1">SENDER_EMAIL</code>. Even without an entry above, the system always
                    notifies users assigned to that role (active accounts with a valid email).
                </div>
            </CardContent>
        </Card>
    );
}

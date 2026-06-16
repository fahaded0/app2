import React, { useState } from "react";
import { api, API, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Upload, FileSpreadsheet, Download, CheckCircle2, AlertTriangle, FileWarning } from "lucide-react";
import { toast } from "sonner";

export default function ImportItems() {
    const [file, setFile] = useState(null);
    const [preview, setPreview] = useState(null);
    const [previewing, setPreviewing] = useState(false);
    const [committing, setCommitting] = useState(false);
    const [includeManualReview, setIncludeManualReview] = useState(false);
    const [result, setResult] = useState(null);

    async function uploadPreview() {
        if (!file) return;
        setPreviewing(true);
        setResult(null);
        try {
            const data = await file.arrayBuffer();
            const r = await api.post("/items/import/preview", data, {
                headers: { "Content-Type": "application/octet-stream" },
                transformRequest: [(d) => d],
            });
            setPreview(r.data);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setPreviewing(false);
        }
    }

    async function commit() {
        if (!file) return;
        setCommitting(true);
        try {
            const data = await file.arrayBuffer();
            const r = await api.post(
                `/items/import/commit?include_manual_review=${includeManualReview}`,
                data,
                {
                    headers: { "Content-Type": "application/octet-stream" },
                    transformRequest: [(d) => d],
                }
            );
            setResult(r.data);
            toast.success(`Imported: ${r.data.created_items} created, ${r.data.updated_items} updated`);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setCommitting(false);
        }
    }

    function downloadTemplate() {
        const token = localStorage.getItem("access_token");
        fetch(`${API}/items/import/template.xlsx`, {
            headers: { Authorization: `Bearer ${token}` },
        }).then((r) => r.blob()).then((blob) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url; a.download = "items_template.xlsx"; a.click();
            URL.revokeObjectURL(url);
        });
    }

    return (
        <div className="space-y-5" data-testid="import-page">
            <div className="flex items-center justify-between">
                <h1 className="font-heading text-3xl font-black tracking-tight">Excel Import</h1>
                <Button variant="outline" onClick={downloadTemplate} data-testid="download-template-button">
                    <Download className="w-4 h-4 mr-2" /> Download Template
                </Button>
            </div>

            <Card className="border-slate-200">
                <CardHeader className="pb-2">
                    <CardTitle className="font-heading text-lg flex items-center gap-2">
                        <FileSpreadsheet className="w-5 h-5 text-sky-600" /> Bulk Item Import
                    </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="text-xs text-slate-600 leading-relaxed">
                        <p>Expected columns (header row required):</p>
                        <code className="block mt-2 p-2 bg-slate-100 rounded text-xs">
                            internal_code, barcode, name, category, unit, min_level, critical_threshold, max_level, department_code, balance
                        </code>
                        <p className="mt-2">
                            Matching priority: <b>Barcode → Internal Code → Name → Manual Review</b>.
                            Rows without any of these or with an unknown <code>department_code</code> are reported as errors.
                        </p>
                    </div>

                    <div className="flex items-center gap-3">
                        <input
                            type="file"
                            accept=".xlsx,.xls"
                            data-testid="excel-file-input"
                            onChange={(e) => {
                                setFile(e.target.files?.[0] || null);
                                setPreview(null);
                                setResult(null);
                            }}
                            className="block text-sm text-slate-700 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-bold file:bg-sky-600 file:text-white hover:file:bg-sky-700"
                        />
                        <Button onClick={uploadPreview} disabled={!file || previewing} className="bg-sky-600 hover:bg-sky-700"
                                data-testid="upload-preview-button">
                            <Upload className="w-4 h-4 mr-2" /> {previewing ? "Analysing..." : "Preview"}
                        </Button>
                    </div>
                </CardContent>
            </Card>

            {preview && (
                <Card className="border-slate-200" data-testid="preview-result">
                    <CardHeader>
                        <CardTitle className="font-heading text-lg">Preview</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                            <div className="bg-slate-50 border border-slate-200 rounded-md p-3">
                                <div className="text-xs font-bold uppercase tracking-wider text-slate-500">Total rows</div>
                                <div className="text-2xl font-black tabular-nums" data-testid="preview-total">{preview.total_rows}</div>
                            </div>
                            <div className="bg-emerald-50 border border-emerald-200 rounded-md p-3">
                                <div className="text-xs font-bold uppercase tracking-wider text-emerald-700">To create</div>
                                <div className="text-2xl font-black tabular-nums text-emerald-700" data-testid="preview-create">{preview.to_create.length}</div>
                            </div>
                            <div className="bg-sky-50 border border-sky-200 rounded-md p-3">
                                <div className="text-xs font-bold uppercase tracking-wider text-sky-700">To update</div>
                                <div className="text-2xl font-black tabular-nums text-sky-700" data-testid="preview-update">{preview.to_update.length}</div>
                            </div>
                            <div className="bg-amber-50 border border-amber-200 rounded-md p-3">
                                <div className="text-xs font-bold uppercase tracking-wider text-amber-700">Manual review / Errors</div>
                                <div className="text-2xl font-black tabular-nums text-amber-700" data-testid="preview-review">
                                    {preview.manual_review.length + preview.errors.length}
                                </div>
                            </div>
                        </div>

                        {preview.errors.length > 0 && (
                            <div className="border border-red-200 bg-red-50 rounded-md p-3">
                                <div className="flex items-center gap-2 font-bold text-red-700 mb-2">
                                    <AlertTriangle className="w-4 h-4" /> Errors ({preview.errors.length})
                                </div>
                                <ul className="text-xs space-y-1 font-mono">
                                    {preview.errors.slice(0, 50).map((e, i) => (
                                        <li key={i} className="text-red-700">Row {e.row}: {e.reason}</li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {preview.manual_review.length > 0 && (
                            <div className="border border-amber-200 bg-amber-50 rounded-md p-3">
                                <div className="flex items-center gap-2 font-bold text-amber-800 mb-2">
                                    <FileWarning className="w-4 h-4" /> Manual review ({preview.manual_review.length})
                                </div>
                                <ul className="text-xs space-y-1 font-mono">
                                    {preview.manual_review.slice(0, 25).map((e, i) => (
                                        <li key={i}>Row {e.row}: name=&quot;{e.name}&quot; (no code/barcode match)</li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        <div className="flex items-center justify-between pt-2 border-t border-slate-200">
                            <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={includeManualReview}
                                    data-testid="include-manual-review-toggle"
                                    onChange={(e) => setIncludeManualReview(e.target.checked)}
                                />
                                Also import manual-review rows (creates new items with generated codes)
                            </label>
                            <Button onClick={commit} disabled={committing} className="bg-emerald-600 hover:bg-emerald-700"
                                    data-testid="commit-import-button">
                                <CheckCircle2 className="w-4 h-4 mr-2" /> {committing ? "Importing..." : "Commit Import"}
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            )}

            {result && (
                <Card className="border-emerald-200 bg-emerald-50/50" data-testid="import-result">
                    <CardContent className="p-4">
                        <div className="flex items-center gap-2 font-bold text-emerald-800 mb-2">
                            <CheckCircle2 className="w-5 h-5" /> Import completed
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                            <div><span className="text-slate-500">Created:</span> <b className="tabular-nums">{result.created_items}</b></div>
                            <div><span className="text-slate-500">Updated:</span> <b className="tabular-nums">{result.updated_items}</b></div>
                            <div><span className="text-slate-500">Stock touched:</span> <b className="tabular-nums">{result.stock_entries_touched}</b></div>
                            <div><span className="text-slate-500">Skipped:</span> <b className="tabular-nums">{result.skipped}</b></div>
                        </div>
                    </CardContent>
                </Card>
            )}
        </div>
    );
}

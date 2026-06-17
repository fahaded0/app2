import React from "react";
import { Card, CardContent } from "@/components/ui/card";
import RiskBadge from "@/components/RiskBadge";
import { ArrowRight, Heart, AlertTriangle } from "lucide-react";

/**
 * Read-only preview of what will happen if the issue is executed.
 * `preview` is the response of POST /stock/issue/preview.
 */
export default function IssuePreviewCard({ preview }) {
    if (!preview) return null;
    const {
        current_balance, requested_quantity, projected_balance,
        minimum_level, critical_level, no_issue_threshold,
        is_life_saving, allow_emergency_override,
        insufficient_stock, decision,
    } = preview;

    const rule = decision?.rule;
    const message = decision?.message;
    const block = decision?.block;

    const blockBg = block && !is_life_saving ? "bg-red-50/50 border-red-200"
        : block && is_life_saving ? "bg-rose-50/40 border-rose-200"
        : rule === "below_critical" ? "bg-orange-50/40 border-orange-200"
        : rule === "below_minimum" ? "bg-amber-50/30 border-amber-200"
        : "bg-emerald-50/30 border-emerald-200";

    return (
        <Card className={`border-2 ${blockBg}`} data-testid="issue-preview-card">
            <CardContent className="p-5 space-y-4">
                {/* Top — rule badge + life-saving */}
                <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                        <RiskBadge rule={rule} insufficient={insufficient_stock} />
                        {is_life_saving && (
                            <span className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-2 py-0.5 text-[11px] font-bold text-rose-700 uppercase tracking-wider"
                                  data-testid="life-saving-badge">
                                <Heart className="w-3 h-3" /> Life-Saving
                            </span>
                        )}
                    </div>
                </div>

                {/* Balance transition */}
                <div className="grid grid-cols-3 gap-3 bg-white rounded-lg border border-slate-200 p-4">
                    <div className="text-center">
                        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">Current</div>
                        <div className="text-3xl font-black text-slate-900 tabular-nums" data-testid="preview-current-balance">
                            {current_balance}
                        </div>
                    </div>
                    <div className="flex flex-col items-center justify-center text-slate-400">
                        <ArrowRight className="w-6 h-6" />
                        <div className="text-[11px] tabular-nums font-bold text-slate-600 mt-1">
                            −{requested_quantity}
                        </div>
                    </div>
                    <div className="text-center">
                        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">Projected</div>
                        <div className={`text-3xl font-black tabular-nums ${
                            insufficient_stock || (block && rule === "blocked_no_issue")
                                ? "text-red-600"
                                : rule === "below_critical" || rule === "emergency_override"
                                  ? "text-orange-600"
                                  : rule === "below_minimum"
                                    ? "text-amber-600"
                                    : "text-emerald-700"
                        }`} data-testid="preview-projected-balance">
                            {projected_balance}
                        </div>
                    </div>
                </div>

                {/* Thresholds reference line */}
                <div className="grid grid-cols-3 gap-2 text-center text-[11px]" data-testid="preview-thresholds">
                    <div className="rounded-md bg-white border border-slate-200 py-2">
                        <div className="text-slate-500 uppercase tracking-wider">Minimum</div>
                        <div className="font-black text-slate-800 text-sm tabular-nums">{minimum_level}</div>
                    </div>
                    <div className="rounded-md bg-white border border-slate-200 py-2">
                        <div className="text-slate-500 uppercase tracking-wider">Critical</div>
                        <div className="font-black text-slate-800 text-sm tabular-nums">{critical_level}</div>
                    </div>
                    <div className="rounded-md bg-white border border-slate-200 py-2">
                        <div className="text-slate-500 uppercase tracking-wider">No-Issue</div>
                        <div className="font-black text-slate-800 text-sm tabular-nums">{no_issue_threshold}</div>
                    </div>
                </div>

                {/* Decision message */}
                <div className="flex items-start gap-2 text-sm text-slate-800 bg-white border border-slate-200 rounded-md p-3"
                     data-testid="preview-message">
                    <AlertTriangle className={`w-4 h-4 mt-0.5 shrink-0 ${
                        block ? "text-red-500" : rule === "below_critical" ? "text-orange-500"
                              : rule === "below_minimum" ? "text-amber-500"
                              : rule === "emergency_override" ? "text-rose-500"
                              : "text-emerald-600"
                    }`} />
                    <div>
                        <div className="leading-relaxed">{insufficient_stock
                            ? "Quantity exceeds the current balance. Reduce the request, or restock first."
                            : message}
                        </div>
                        {block && is_life_saving && allow_emergency_override && (
                            <div className="text-xs text-rose-700 mt-2 leading-relaxed font-medium">
                                This is a life-saving item. You may proceed with an <span className="font-bold">Emergency Override</span> by providing a written justification below.
                            </div>
                        )}
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}

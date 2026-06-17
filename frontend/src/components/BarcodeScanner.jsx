import React, { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Camera, X, RefreshCcw, AlertCircle } from "lucide-react";

/**
 * BarcodeScanner — minimal camera-based scanner for 1D/2D codes.
 * Props:
 *   open      — boolean
 *   onClose   — () => void
 *   onScanned — (code) => void   // fires once per opening
 */
export default function BarcodeScanner({ open, onClose, onScanned }) {
    const elRef = useRef(null);
    const scannerRef = useRef(null);
    const [error, setError] = useState(null);
    const [running, setRunning] = useState(false);

    useEffect(() => {
        if (!open) return;
        let cancelled = false;

        async function start() {
            setError(null);
            try {
                // small delay so the <div id="..."> is mounted by the dialog
                await new Promise((r) => setTimeout(r, 80));
                if (!elRef.current) return;
                const scanner = new Html5Qrcode(elRef.current.id, /* verbose */ false);
                scannerRef.current = scanner;
                const config = {
                    fps: 12,
                    qrbox: { width: 260, height: 160 },
                    aspectRatio: 1.6,
                };
                await scanner.start(
                    { facingMode: "environment" },
                    config,
                    (decodedText) => {
                        if (cancelled) return;
                        // Fire once, then stop
                        onScanned(decodedText);
                        stop();
                    },
                    () => { /* swallow per-frame parse errors */ }
                );
                setRunning(true);
            } catch (e) {
                console.error(e);
                setError(
                    "Cannot start the camera. Grant camera permission for this site and try again, " +
                    "or use the manual input below."
                );
            }
        }

        async function stop() {
            const s = scannerRef.current;
            scannerRef.current = null;
            try { if (s) { await s.stop(); await s.clear(); } } catch (_) {}
            setRunning(false);
        }

        start();
        return () => {
            cancelled = true;
            stop();
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open]);

    function manualSubmit(e) {
        e.preventDefault();
        const v = (e.target.elements.code.value || "").trim();
        if (!v) return;
        onScanned(v);
    }

    return (
        <Dialog open={open} onOpenChange={(v) => !v && onClose && onClose()}>
            <DialogContent className="max-w-md" data-testid="barcode-scanner-dialog">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Camera className="w-5 h-5 text-sky-600" />
                        Scan Barcode / QR
                    </DialogTitle>
                    <DialogDescription>
                        Point the camera at the item label. We accept EAN, UPC, Code128, QR and DataMatrix codes.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    <div
                        id="barcode-reader-region"
                        ref={elRef}
                        className="rounded-md overflow-hidden bg-slate-900 min-h-[220px] flex items-center justify-center"
                        data-testid="barcode-reader-region"
                    >
                        {!running && !error && (
                            <div className="text-slate-300 text-xs flex items-center gap-2">
                                <RefreshCcw className="w-4 h-4 animate-spin" /> starting camera...
                            </div>
                        )}
                    </div>

                    {error && (
                        <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-md p-3"
                             data-testid="barcode-error">
                            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                            <span>{error}</span>
                        </div>
                    )}

                    <form className="flex items-center gap-2 pt-1" onSubmit={manualSubmit}>
                        <input
                            name="code"
                            placeholder="...or type / paste a code"
                            className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-sky-500"
                            data-testid="manual-code-input"
                        />
                        <Button type="submit" size="sm" className="bg-sky-600 hover:bg-sky-700" data-testid="manual-code-submit">
                            Use
                        </Button>
                        <Button type="button" size="sm" variant="ghost" onClick={onClose} data-testid="close-scanner-button">
                            <X className="w-4 h-4" />
                        </Button>
                    </form>
                </div>
            </DialogContent>
        </Dialog>
    );
}

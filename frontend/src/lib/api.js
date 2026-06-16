import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

api.interceptors.request.use((config) => {
    const token = localStorage.getItem("access_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
});

export function formatApiError(err) {
    const detail = err?.response?.data?.detail;
    if (!detail) return err?.message || "An unknown error occurred";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail))
        return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" - ");
    if (detail && typeof detail.msg === "string") return detail.msg;
    return String(detail);
}

export const ROLE_LABELS = {
    super_admin: "System Administrator",
    digital_health_manager: "Digital Health Manager",
    hospital_manager: "Hospital Manager",
    department_head: "Department Head",
    department_stock_officer: "Department Stock Officer",
    supply_officer: "Medical Supply Officer",
    procurement: "Procurement",
    quality: "Quality & Patient Safety",
    auditor: "Internal Auditor",
    viewer: "Viewer",
};

export const STATUS_LABELS = {
    zero_level: "Zero Stock",
    critical_level: "Critical",
    available: "Available",
    back_in_stock: "Back in Stock",
    backorder: "Backorder",
};

export const REQ_STATUS_LABELS = {
    pending_approval: "Pending Approval",
    approved: "Approved",
    rejected: "Rejected",
    dispatched: "Dispatched",
    partially_received: "Partially Received",
    received: "Received",
    closed: "Closed",
    backorder: "Backorder",
};

export const PRIORITY_LABELS = {
    routine: "Routine",
    urgent: "Urgent",
    stat: "STAT",
};

export function fmtDate(iso) {
    if (!iso) return "—";
    try {
        return new Date(iso).toLocaleString("en-GB", {
            year: "numeric", month: "short", day: "2-digit",
            hour: "2-digit", minute: "2-digit", hour12: false,
        });
    } catch (_) {
        return iso;
    }
}

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
    if (!detail) return err?.message || "حدث خطأ غير معروف";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail))
        return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" - ");
    if (detail && typeof detail.msg === "string") return detail.msg;
    return String(detail);
}

export const ROLE_LABELS = {
    super_admin: "مدير النظام",
    digital_health_manager: "مدير الصحة الرقمية",
    hospital_manager: "مدير المستشفى",
    department_head: "رئيس القسم",
    department_stock_officer: "مسؤول مخزون القسم",
    supply_officer: "التموين الطبي",
    procurement: "المشتريات",
    quality: "الجودة وسلامة المرضى",
    auditor: "المراجع الداخلي",
    viewer: "قراءة فقط",
};

export const STATUS_LABELS = {
    zero_level: "صفر مخزون",
    critical_level: "حرج",
    available: "متوفر",
    back_in_stock: "عاد للمخزون",
    backorder: "Backorder",
};

export const REQ_STATUS_LABELS = {
    pending_approval: "بانتظار الاعتماد",
    approved: "معتمد",
    rejected: "مرفوض",
    dispatched: "تم الصرف",
    partially_received: "استلام جزئي",
    received: "مستلم",
    closed: "مغلق",
    backorder: "Backorder",
};

export const PRIORITY_LABELS = {
    routine: "اعتيادي",
    urgent: "عاجل",
    stat: "فوري",
};

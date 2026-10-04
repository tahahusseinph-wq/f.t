"""ترجمة بسيطة للواجهة: النصوص العربية هي الأصل، والإنكليزية عند اختيارها."""
from __future__ import annotations

from PySide6.QtCore import Qt

_lang = "ar"

EN: dict[str, str] = {
    "لوحة التحكم": "Dashboard", "المنتجات": "Products", "الأقسام والخانات": "Categories & Fields",
    "المخزون": "Inventory", "المشتريات": "Purchases", "نقطة البيع": "Point of Sale", "الفواتير": "Invoices",
    "الزبائن": "Customers", "المالية": "Finance", "التقارير": "Reports", "المستخدمون": "Users",
    "الإشعارات": "Notifications", "المساعد الذكي": "AI Assistant", "الإعدادات": "Settings",
    "الرئيسية": "Main", "البضاعة": "Goods", "المبيعات": "Sales", "الإدارة": "Management",
    "تسجيل الخروج": "Log out", "قفل الشاشة": "Lock screen", "بحث شامل... (Ctrl+K)": "Search... (Ctrl+K)",
    "إضافة": "Add", "تعديل": "Edit", "حذف": "Delete", "حفظ": "Save", "إلغاء": "Cancel", "تحديث": "Refresh",
    "تصدير Excel": "Export Excel", "طباعة": "Print", "بحث": "Search", "إغلاق": "Close",
    "تسجيل الدخول": "Sign in", "اسم المستخدم": "Username", "كلمة السر": "Password",
    "منتج جديد": "New product", "السيرفر يعمل": "Server running", "السيرفر متوقف": "Server stopped",
}


def set_language(lang: str) -> None:
    global _lang
    _lang = "en" if lang == "en" else "ar"


def language() -> str:
    return _lang


def tr(text: str) -> str:
    if _lang == "en":
        return EN.get(text, text)
    return text


def direction() -> Qt.LayoutDirection:
    return Qt.LayoutDirection.LeftToRight if _lang == "en" else Qt.LayoutDirection.RightToLeft

"""الأدوار والصلاحيات."""
from __future__ import annotations

from ftapp.models import User

PERMISSIONS: dict[str, str] = {
    "dashboard.view": "عرض لوحة التحكم",
    "products.view": "عرض المنتجات",
    "products.edit": "إضافة وتعديل المنتجات",
    "products.delete": "حذف المنتجات",
    "products.view_cost": "رؤية سعر التكلفة والأرباح",
    "categories.manage": "إدارة الأقسام والخانات",
    "inventory.view": "عرض المخزون",
    "inventory.adjust": "تعديل المخزون والجرد والنقل",
    "purchases.manage": "المشتريات والموردين",
    "sales.create": "البيع وإصدار الفواتير",
    "sales.discount": "منح خصومات",
    "sales.return": "المرتجعات",
    "sales.cancel": "إلغاء الفواتير",
    "sales.view_all": "رؤية فواتير كل البائعين",
    "sales.oversell": "البيع بأكثر من الكمية المتوفرة",
    "customers.manage": "إدارة الزبائن والديون",
    "expenses.manage": "المصاريف",
    "shifts.manage": "إدارة الورديات والصندوق",
    "reports.view": "التقارير",
    "users.manage": "إدارة المستخدمين",
    "settings.manage": "الإعدادات والنسخ الاحتياطي",
    "ai.use": "استخدام الذكاء الاصطناعي",
}

ROLES: dict[str, str] = {
    "admin": "أدمن",
    "manager": "مدير",
    "seller": "بائع",
    "viewer": "مستخدم (بحث فقط)",
}

# صلاحيات لا تُمنح تلقائياً لأي دور (حتى الأدمن) ويجب تفعيلها يدوياً للمستخدم
OPT_IN: set[str] = {"sales.oversell"}

ROLE_DEFAULTS: dict[str, set[str]] = {
    "admin": set(PERMISSIONS) - OPT_IN,
    "manager": set(PERMISSIONS) - {"users.manage", "settings.manage"} - OPT_IN,
    "seller": {"products.view", "inventory.view", "sales.create", "sales.discount", "customers.manage",
               "shifts.manage"},
    "viewer": {"products.view"},
}


def effective_permissions(user: User) -> set[str]:
    perms = set(ROLE_DEFAULTS.get(user.role, set()))
    for perm, granted in (user.permissions or {}).items():
        if user.role == "admin" and perm not in OPT_IN:
            continue  # الأدمن يملك كل الصلاحيات الأساسية دائماً
        if granted:
            perms.add(perm)
        else:
            perms.discard(perm)
    return perms


def has(user: User | None, perm: str) -> bool:
    if user is None:
        return False
    return perm in effective_permissions(user)


def is_privileged(user: User | None) -> bool:
    """المستخدم الذي يرى كل الحقول (حتى المخفية عن المستخدمين العاديين)."""
    return user is not None and user.role in ("admin", "manager")

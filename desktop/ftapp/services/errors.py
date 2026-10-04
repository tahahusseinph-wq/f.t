class ServiceError(Exception):
    """خطأ منطقي برسالة عربية تُعرض للمستخدم مباشرة."""


class NotFound(ServiceError):
    pass


class PermissionDenied(ServiceError):
    pass


class ValidationError(ServiceError):
    pass

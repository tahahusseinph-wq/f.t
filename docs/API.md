<div dir="rtl">

# توثيق الـ API (سيرفر الموبايل)

السيرفر يعمل داخل تطبيق الأدمن على المنفذ `8765` افتراضياً، ويقبل الاتصال من الشبكة المحلية فقط.
التوثيق التفاعلي متاح على `http://<IP>:8765/api/docs`.

- **المصادقة:** `POST /api/v1/auth/login` يعيد `token`، ويُرسل بعدها في الترويسة `Authorization: Bearer <token>` (صالح 7 أيام، ويمكن إلغاؤه من صفحة الأجهزة).
- **الصلاحيات:** كل مسار يتحقق من صلاحية المستخدم. حقول المنتج المخفية عن المستخدمين **لا تُرسل أبداً** من السيرفر.
- **الأخطاء:** `{"detail": "رسالة بالعربية"}` مع رمز 400/401/403/404/422/429.
- **منع التكرار:** عمليات البيع وتعديل الكمية والجرد تقبل `client_op_id`؛ تكرار نفس المعرف يعيد نفس النتيجة دون تنفيذ مرة ثانية (أساس وضع بدون اتصال عبر `POST /sync/ops`).
- **الاكتشاف:** السيرفر يعلن عن نفسه عبر mDNS بالنوع `_fttrading._tcp`.

| الطريقة | المسار | الوظيفة |
|---|---|---|
| GET | `/api/v1/ping` | فحص السيرفر |
| POST | `/api/v1/auth/login` | تسجيل الدخول |
| POST | `/api/v1/auth/logout` | تسجيل الخروج |
| GET | `/api/v1/auth/me` | المستخدم الحالي |
| GET | `/api/v1/products/lookup` | منتج بالكود/الباركود |
| GET | `/api/v1/products` | بحث المنتجات |
| POST | `/api/v1/products` | إضافة منتج |
| GET | `/api/v1/products/generate-code` | توليد كود |
| GET | `/api/v1/products/{product_id}` | تفاصيل منتج |
| PUT | `/api/v1/products/{product_id}` | تعديل منتج |
| PATCH | `/api/v1/products/{product_id}/stock` | تعديل الكمية |
| GET | `/api/v1/images/{name}` | صورة منتج |
| GET | `/api/v1/meta` | بيانات مرجعية |
| GET | `/api/v1/sync/products` | مزامنة تفاضلية للمنتجات |
| GET | `/api/v1/dashboard` | لوحة التحكم |
| GET | `/api/v1/notifications` | الإشعارات |
| POST | `/api/v1/notifications/{notification_id}/read` | تحديد إشعار كمقروء |
| POST | `/api/v1/notifications/read-all` | تحديد الكل كمقروء |
| POST | `/api/v1/sales/preview` | حساب السلة |
| POST | `/api/v1/sales` | بيع / عرض سعر |
| GET | `/api/v1/invoices` | الفواتير |
| GET | `/api/v1/invoices/{invoice_id}` | تفاصيل فاتورة |
| GET | `/api/v1/invoices/{invoice_id}/pdf` | فاتورة PDF |
| POST | `/api/v1/invoices/{invoice_id}/return` | مرتجع |
| POST | `/api/v1/invoices/{invoice_id}/convert` | تحويل عرض سعر لفاتورة |
| GET | `/api/v1/customers` | الزبائن |
| POST | `/api/v1/customers` | إضافة زبون |
| POST | `/api/v1/customers/{customer_id}/payments` | دفعة زبون |
| GET | `/api/v1/counts` | جلسات الجرد المفتوحة |
| POST | `/api/v1/counts` | بدء جرد |
| GET | `/api/v1/counts/{count_id}` | تفاصيل جرد |
| POST | `/api/v1/counts/{count_id}/lines` | عدّ منتج |
| GET | `/api/v1/stock/low` | المنتجات المنخفضة |
| GET | `/api/v1/users` | المستخدمون |
| POST | `/api/v1/users` | إضافة مستخدم |
| GET | `/api/v1/roles` | الأدوار |
| PATCH | `/api/v1/users/{user_id}` | تعديل مستخدم |
| POST | `/api/v1/sync/ops` | إرسال العمليات المؤجلة |

</div>

<div dir="rtl">

# البناء والتطوير

## هيكلية المشروع
```
assets/                 الشعار، الأيقونات، خط Cairo
desktop/
  ftapp/core/           الإعدادات، قاعدة البيانات، الأمان، الأحداث
  ftapp/models/         جداول SQLAlchemy
  ftapp/services/       منطق العمل (يُستخدم من الواجهة والـ API معاً)
  ftapp/api/            سيرفر FastAPI للموبايل
  ftapp/ui/             واجهة PySide6 (صفحات، نوافذ، عناصر)
  migrations/           ترحيلات Alembic
  templates/            قالب الفاتورة
  tests/                اختبارات pytest (الخدمات، الـ API، الواجهة)
mobile/                 تطبيق Flutter
.github/workflows/      بناء APK ونسخة ويندوز تلقائياً
```

## تطبيق الأدمن
```bash
cd desktop
pip install -r requirements-dev.txt
python run_ftapp.py                       # تشغيل
QT_QPA_PLATFORM=offscreen pytest -q tests # الاختبارات
pyinstaller --noconfirm ft_trading.spec   # ملف تنفيذي في dist/FaroukToumma
```
- متغير `FT_DATA_DIR` يغيّر مجلد البيانات (مفيد للتجربة).
- تعديل الجداول: عدّل `ftapp/models` ثم `alembic revision --autogenerate -m "وصف"`؛ الترحيلات تُطبّق تلقائياً عند التشغيل.

## تطبيق الموبايل
```bash
cd mobile
flutter pub get
flutter analyze && flutter test
flutter build apk --release
```
### توقيع نسخة الإصدار
1. `keytool -genkey -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload`
2. أنشئ `mobile/android/key.properties`:
```
storePassword=...
keyPassword=...
keyAlias=upload
storeFile=/path/to/upload-keystore.jks
```
بدون هذا الملف تُوقّع النسخة بمفتاح التطوير.

## الإصدارات
ادفع وسماً مثل `v1.0.0` فيبني GitHub Actions ملف APK ونسخة ويندوز وينشرهما في Releases.
ولتنبيه التطبيق بالتحديثات ضع في الإعدادات ← التحديثات الرابط:
`https://api.github.com/repos/<owner>/<repo>/releases/latest`

</div>

import 'dart:io';

import 'package:dio/dio.dart';
import 'package:path_provider/path_provider.dart';

import 'storage.dart';

/// خطأ برسالة عربية جاهزة للعرض.
class ApiException implements Exception {
  ApiException(this.message, {this.status, this.offline = false});

  final String message;
  final int? status;
  final bool offline;

  bool get unauthorized => status == 401;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient(this.server, {this.token}) {
    _dio = Dio(BaseOptions(
      baseUrl: server.baseUrl,
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 25),
      headers: {'Accept': 'application/json'},
    ));
    _dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) {
      if (token != null) options.headers['Authorization'] = 'Bearer $token';
      handler.next(options);
    }));
  }

  final ServerInfo server;
  String? token;
  late final Dio _dio;

  Map<String, String> get authHeaders => token == null ? {} : {'Authorization': 'Bearer $token'};

  String imageUrl(String name) => '${server.baseUrl}/images/$name';

  ApiException _wrap(Object e) {
    if (e is DioException) {
      final res = e.response;
      if (res == null) {
        return ApiException('تعذر الاتصال بالسيرفر. تأكد أن الكمبيوتر يعمل وأنك على نفس شبكة الواي فاي', offline: true);
      }
      final data = res.data;
      final detail = data is Map ? data['detail'] : null;
      return ApiException(detail is String ? detail : 'خطأ من السيرفر (${res.statusCode})', status: res.statusCode);
    }
    return ApiException('حدث خطأ غير متوقع: $e');
  }

  Future<T> _run<T>(Future<Response<dynamic>> Function() call) async {
    try {
      final res = await call();
      return res.data as T;
    } catch (e) {
      throw _wrap(e);
    }
  }

  Future<T> get<T>(String path, {Map<String, dynamic>? query}) => _run<T>(() => _dio.get(path, queryParameters: query));
  Future<T> post<T>(String path, [Object? body]) => _run<T>(() => _dio.post(path, data: body));
  Future<T> put<T>(String path, [Object? body]) => _run<T>(() => _dio.put(path, data: body));
  Future<T> patch<T>(String path, [Object? body]) => _run<T>(() => _dio.patch(path, data: body));
  Future<T> delete<T>(String path) => _run<T>(() => _dio.delete(path));

  /// يجرب كل عناوين السيرفر ويعيد أول عنوان يستجيب.
  static Future<(ServerInfo, Map<String, dynamic>)> probe(ServerInfo s) async {
    ApiException? last;
    for (final host in s.hosts) {
      final candidate = s.withPrimary(host);
      try {
        final dio = Dio(BaseOptions(baseUrl: candidate.baseUrl, connectTimeout: const Duration(seconds: 3), receiveTimeout: const Duration(seconds: 5)));
        final res = await dio.get('/ping');
        final data = res.data as Map<String, dynamic>;
        if (data['app'] != 'ft-trading') throw ApiException('هذا العنوان ليس سيرفر مجموعة الطعمة التجارية');
        return (ServerInfo(hosts: candidate.hosts, port: s.port, id: '${data['server_id']}', name: '${data['company'] ?? ''}'), data);
      } on ApiException catch (e) {
        last = e;
      } catch (_) {
        last = ApiException('لا يوجد سيرفر على $host:${s.port}', offline: true);
      }
    }
    throw last ?? ApiException('تعذر الوصول للسيرفر', offline: true);
  }

  Future<File> downloadPdf(int invoiceId, String number, {String paper = 'A4'}) async {
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/$number-$paper.pdf');
    try {
      await _dio.download('/invoices/$invoiceId/pdf', file.path, queryParameters: {'paper': paper});
    } catch (e) {
      throw _wrap(e);
    }
    return file;
  }
}

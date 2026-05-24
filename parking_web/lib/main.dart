import 'package:flutter/material.dart';
import 'screens/add_camera.dart';
import 'screens/admin_login.dart';
import 'screens/admin_register.dart';
import 'screens/camera_list.dart';
import 'screens/login.dart';
import 'screens/register.dart';
import 'screens/parking_history.dart';
import 'config/session.dart';
import 'config/theme_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppThemeController.instance.load();
  runApp(const ParkingAIApp());
}

class ParkingAIApp extends StatelessWidget {
  const ParkingAIApp({super.key});

  Route<dynamic> _buildRoute(RouteSettings settings) {
    switch (settings.name) {
      case '/login':
        return MaterialPageRoute(builder: (_) => const LoginScreen(), settings: settings);
      case '/register':
        return MaterialPageRoute(builder: (_) => const RegisterScreen(), settings: settings);
      case '/admin/login':
        return MaterialPageRoute(builder: (_) => const AdminLoginScreen(), settings: settings);
      case '/admin/register':
        return MaterialPageRoute(builder: (_) => const AdminRegisterScreen(), settings: settings);
      case '/add':
        return MaterialPageRoute(
          builder: (_) => RequireRole(requiredRole: 'admin', child: AddCameraScreen()),
          settings: settings,
        );
      case '/list':
        return MaterialPageRoute(
          builder: (_) => const RequireAuth(child: CameraListScreen()),
          settings: settings,
        );
      case '/history':
        return MaterialPageRoute(
          builder: (_) => const RequireAuth(child: ParkingHistoryScreen(isAdmin: false)),
          settings: settings,
        );
      case '/admin/history':
        return MaterialPageRoute(
          builder: (_) => RequireRole(requiredRole: 'admin', child: const ParkingHistoryScreen(isAdmin: true)),
          settings: settings,
        );
      default:
        return MaterialPageRoute(builder: (_) => const LoginScreen(), settings: settings);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: AppThemeController.instance,
      builder: (context, _) {
        return MaterialApp(
          title: 'Parking AI System',
          themeMode: AppThemeController.instance.themeMode,
          theme: ThemeData(
            primarySwatch: Colors.indigo,
            useMaterial3: true,
            colorScheme: ColorScheme.fromSeed(
              seedColor: Colors.indigo,
              brightness: Brightness.light,
            ),
            scaffoldBackgroundColor: Colors.grey[50],
            appBarTheme: AppBarTheme(
              backgroundColor: Colors.indigo,
              foregroundColor: Colors.white,
              elevation: 4,
            ),
            elevatedButtonTheme: ElevatedButtonThemeData(
              style: ElevatedButton.styleFrom(
                padding: EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ),
            inputDecorationTheme: InputDecorationTheme(
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
              ),
              filled: true,
              fillColor: Colors.white,
            ),
          ),
          darkTheme: ThemeData(
            useMaterial3: true,
            colorScheme: ColorScheme.fromSeed(
              seedColor: Colors.indigo,
              brightness: Brightness.dark,
            ),
            scaffoldBackgroundColor: const Color(0xFF121212),
            appBarTheme: const AppBarTheme(
              backgroundColor: Color(0xFF1E1E1E),
              foregroundColor: Colors.white,
              elevation: 2,
            ),
            cardTheme: const CardThemeData(
              color: Color(0xFF1E1E1E),
            ),
            inputDecorationTheme: InputDecorationTheme(
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
              ),
              filled: true,
              fillColor: const Color(0xFF2A2A2A),
            ),
          ),
          initialRoute: '/login',
          onGenerateRoute: _buildRoute,
          // หน้า LiveView เราจะใช้ Navigator.push แบบส่งค่าแทน
        );
      },
    );
  }
}

class RequireAuth extends StatelessWidget {
  final Widget child;
  const RequireAuth({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: SessionStore.isLoggedIn(),
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        final isLoggedIn = snapshot.data ?? false;
        if (!isLoggedIn) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!context.mounted) return;
            Navigator.pushNamedAndRemoveUntil(context, '/login', (route) => false);
          });
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        return child;
      },
    );
  }
}

class RequireRole extends StatelessWidget {
  final Widget child;
  final String requiredRole;

  const RequireRole({
    super.key,
    required this.child,
    required this.requiredRole,
  });

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<dynamic>>(
      future: Future.wait([SessionStore.isLoggedIn(), SessionStore.getRole()]),
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        final isLoggedIn = (snapshot.data?[0] as bool?) ?? false;
        final userRole = (snapshot.data?[1] as String?) ?? 'customer';

        if (!isLoggedIn) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!context.mounted) return;
            Navigator.pushNamedAndRemoveUntil(context, '/login', (route) => false);
          });
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        if (userRole != requiredRole) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!context.mounted) return;
            Navigator.pushNamedAndRemoveUntil(context, '/list', (route) => false);
          });
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        return child;
      },
    );
  }
}

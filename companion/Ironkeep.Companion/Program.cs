using System;
using System.IO;
using System.Threading;
using System.Windows;
using Ironkeep;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace Ironkeep.Companion
{
    public static class Program
    {
        static int _reported;

        [STAThread]
        public static int Main(string[] args)
        {
            string mode = args != null && args.Length > 0 ? args[0] : "window";
            try
            {
                File.WriteAllText(Path.Combine(Path.GetTempPath(), "ironkeep-wpf-start.txt"), "mode=" + mode + Environment.NewLine);
            }
            catch (Exception)
            {
            }
            StartupLog.Write("starting " + mode);
            AppDomain.CurrentDomain.UnhandledException += delegate(object sender, UnhandledExceptionEventArgs e)
            {
                Report(e.ExceptionObject as Exception ?? new Exception("The companion stopped."), false);
            };
            if (args != null && args.Length > 0 && args[0] == "--send-check") return SendCheck(args);
            if (args != null && args.Length > 0 && args[0] == "--capture") return Capture(args);
            try
            {
                PrepareDesktop();
                var app = new App();
                app.DispatcherUnhandledException += delegate(object sender, DispatcherUnhandledExceptionEventArgs e)
                {
                    Report(e.Exception, true);
                    e.Handled = true;
                    app.Shutdown(1);
                };
                app.InitializeComponent();
                app.Startup += Start;
                return app.Run();
            }
            catch (Exception ex)
            {
                Report(ex, true);
                return 1;
            }
        }

        static void PrepareDesktop()
        {
            try { System.Windows.Forms.Application.SetHighDpiMode(System.Windows.Forms.HighDpiMode.PerMonitorV2); }
            catch (InvalidOperationException) { }
            try { System.Windows.Forms.Application.EnableVisualStyles(); }
            catch (InvalidOperationException) { }
        }

        static void Start(object sender, StartupEventArgs e)
        {
            var app = (App)sender;
            app.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            try
            {
                var instance = SingleInstance.Acquire("IronkeepCompanion");
                if (!instance.IsOwner)
                {
                    StartupLog.Write("already-running");
                    instance.Signal();
                    instance.Dispose();
                    app.Shutdown();
                    return;
                }
                StartupLog.Write("session");
                var session = CompanionSession.ForCurrentUser();
                session.Start();
                StartupLog.Write("window");
                var window = new MainWindow(session);
                NotifyIconHost host = null;
                try
                {
                    var tray = TrayIcon.Create(window, session, delegate
                    {
                        window.AllowExit = true;
                        if (host != null) host.Dispose();
                        window.Close();
                        session.Dispose();
                        instance.Dispose();
                        app.Shutdown();
                    });
                    host = new NotifyIconHost(tray);
                    StartupLog.Write("tray");
                }
                catch (Exception ex)
                {
                    StartupLog.WriteException("tray", ex);
                }
                window.Show();
                var timer = new DispatcherTimer();
                timer.Interval = TimeSpan.FromMilliseconds(500);
                timer.Tick += delegate
                {
                    if (instance.Consume()) window.BringForward();
                    if (window.IsVisible) window.Refresh();
                };
                timer.Start();
                StartupLog.Write("ready");
            }
            catch (Exception ex)
            {
                Report(ex, true);
                app.Shutdown(1);
            }
        }

        static void Report(Exception ex, bool show)
        {
            if (Interlocked.Exchange(ref _reported, 1) != 0)
            {
                StartupLog.WriteException("fatal", ex);
                return;
            }
            StartupLog.WriteException("fatal", ex);
            if (!show || ex == null) return;
            string text = StartupLog.Redact(ex.GetType().Name + ": " + ex.Message);
            if (text.Length > 500) text = text.Substring(0, 500);
            text += Environment.NewLine + Environment.NewLine + StartupLog.FilePath();
            try
            {
                MessageBox.Show(text, "Ironkeep Companion", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            catch (Exception)
            {
                try { System.Windows.Forms.MessageBox.Show(text, "Ironkeep Companion"); }
                catch (Exception) { }
            }
        }

        static int SendCheck(string[] args)
        {
            if (args.Length < 5)
            {
                Console.Error.WriteLine("Usage: IronkeepCompanion --send-check <url> <slug> <token> <lua>");
                return 2;
            }
            string root = Path.Combine(Path.GetTempPath(), "ironkeep-send-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            string saved = Path.Combine(root, "wow", "WTF", "Account", "Send", "SavedVariables");
            Directory.CreateDirectory(saved);
            File.Copy(args[4], Path.Combine(saved, "Ironkeep.lua"), true);
            var config = new CompanionConfig();
            config.Address = args[1];
            config.Slug = args[2];
            config.Token = args[3];
            config.WowFolder = Path.Combine(root, "wow");
            var uploader = new LegacyUploader(delegate { return config; });
            var session = new CompanionSession(
                Path.Combine(root, "queue.sqlite"),
                Path.Combine(root, "settings.txt"),
                new PrefixProtector(),
                new MemoryStartup(),
                "",
                uploader);
            try
            {
                session.UseMemory(config);
                session.SyncNow();
                Console.WriteLine(uploader.LastResponse ?? "");
                return SiteClient.Accepted(uploader.LastResponse) ? 0 : 1;
            }
            finally
            {
                session.Dispose();
            }
        }

        static int Capture(string[] args)
        {
            if (args.Length < 2) return 2;
            string directory = args[1];
            Directory.CreateDirectory(directory);
            string root = Path.Combine(Path.GetTempPath(), "ironkeep-preview-" + Guid.NewGuid().ToString("N"));
            string saved = Path.Combine(root, "wow", "WTF", "Account", "Preview", "SavedVariables");
            Directory.CreateDirectory(saved);
            string sample = Path.Combine(AppContext.BaseDirectory, "sample-Ironkeep.lua");
            if (!File.Exists(sample)) sample = Path.Combine(Directory.GetCurrentDirectory(), "sample-Ironkeep.lua");
            if (!File.Exists(sample))
            {
                Console.Error.WriteLine("sample-Ironkeep.lua was not next to the application.");
                return 3;
            }
            File.Copy(sample, Path.Combine(saved, "Ironkeep.lua"), true);
            var memory = new CompanionConfig();
            memory.Address = "https://ironkeep.gg";
            memory.Slug = "preview";
            memory.WowFolder = Path.Combine(root, "wow");
            var session = new CompanionSession(
                Path.Combine(root, "queue.sqlite"),
                Path.Combine(root, "settings.txt"),
                new PrefixProtector(),
                new MemoryStartup(),
                "",
                new LegacyUploader(delegate { return memory; }));
            int code = 0;
            string scaleLog = Path.Combine(directory, "scales.txt");
            _scaleLog = scaleLog;
            var app = new App();
            app.InitializeComponent();
            app.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            app.Startup += delegate
            {
                app.Dispatcher.BeginInvoke(new Action(delegate
                {
                    try
                    {
                        session.UseMemory(memory);
                        session.Discover();
                        var dashboard = new MainWindow(session);
                        Save(dashboard, Path.Combine(directory, "dashboard.png"), 1);
                        Save(dashboard, Path.Combine(directory, "pending.png"), 1);
                        Save(dashboard, Path.Combine(directory, "dashboard-125.png"), 1.25);
                        Save(dashboard, Path.Combine(directory, "dashboard-150.png"), 1.5);
                        memory.AuthMode = CompanionConfig.ModeDiscord;
                        memory.Slug = "preview";
                        memory.GuildName = "Preview Guild";
                        memory.GuildDiscordId = "4242";
                        memory.RefreshToken = "ikr.preview-session";
                        memory.AccessToken = "ika.preview-session";
                        memory.AccessExpiresAt = DateTime.UtcNow.AddMinutes(5).ToString("o");
                        memory.SessionStatus = "";
                        session.UseMemory(memory);
                        dashboard.Refresh();
                        Save(dashboard, Path.Combine(directory, "connected.png"), 1);
                        Save(dashboard, Path.Combine(directory, "connected-125.png"), 1.25);
                        Save(dashboard, Path.Combine(directory, "connected-150.png"), 1.5);
                        var settings = new SettingsWindow(session);
                        Save(settings, Path.Combine(directory, "settings.png"), 1);
                        Save(settings, Path.Combine(directory, "settings-125.png"), 1.25);
                        Save(settings, Path.Combine(directory, "settings-150.png"), 1.5);
                        dashboard.AllowExit = true;
                        if (settings.IsVisible) settings.Close();
                        if (dashboard.IsVisible) dashboard.Close();
                    }
                    catch (Exception ex)
                    {
                        code = 1;
                        File.WriteAllText(Path.Combine(directory, "capture-error.txt"), ex.ToString());
                    }
                    finally
                    {
                        session.Dispose();
                        app.Shutdown(code);
                    }
                }));
            };
            int run = app.Run();
            return code != 0 ? code : run;
        }

        static string _scaleLog;

        static void Save(Window window, string path, double scale)
        {
            if (scale < 1) scale = 1;
            try
            {
                if (!window.IsVisible) window.Show();
                VisualTreeHelper.SetRootDpi(window, new DpiScale(scale, scale));
                window.UpdateLayout();
            }
            catch (Exception)
            {
            }
            Visual visual = window;
            double dipWidth = window.ActualWidth;
            double dipHeight = window.ActualHeight;
            if (dipWidth < 50 || dipHeight < 50)
            {
                var root = window.Content as FrameworkElement;
                if (root == null) throw new InvalidOperationException("The window has no content.");
                double layoutWidth = window.Width > 50 ? window.Width : 460;
                double layoutHeight = window.Height > 50 ? window.Height : 640;
                root.Measure(new Size(layoutWidth, layoutHeight));
                root.Arrange(new Rect(0, 0, layoutWidth, layoutHeight));
                root.UpdateLayout();
                dipWidth = root.RenderSize.Width;
                dipHeight = root.RenderSize.Height;
                if (dipWidth < 50) dipWidth = layoutWidth;
                if (dipHeight < 50) dipHeight = layoutHeight;
                visual = root;
            }
            if (_scaleLog != null)
            {
                File.AppendAllText(_scaleLog, path + " scale " + scale.ToString("0.00") + " dip " + dipWidth.ToString("0") + "x" + dipHeight.ToString("0") + Environment.NewLine);
            }
            if (dipWidth > 0 && dipWidth < 400) throw new InvalidOperationException("The window became too narrow at scale " + scale.ToString("0.00") + ".");
            int width = Math.Max(1, (int)Math.Ceiling(dipWidth * scale));
            int height = Math.Max(1, (int)Math.Ceiling(dipHeight * scale));
            var bitmap = new RenderTargetBitmap(width, height, 96 * scale, 96 * scale, PixelFormats.Pbgra32);
            bitmap.Render(visual);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var stream = File.Create(path)) encoder.Save(stream);
        }
    }

    sealed class NotifyIconHost : IDisposable
    {
        readonly System.Windows.Forms.NotifyIcon _icon;

        public NotifyIconHost(System.Windows.Forms.NotifyIcon icon)
        {
            _icon = icon;
        }

        public void Dispose()
        {
            _icon.Visible = false;
            _icon.Dispose();
        }
    }
}

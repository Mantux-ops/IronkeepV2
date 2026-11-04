using System;
using System.Collections.Generic;
using System.IO;
using Ironkeep;

namespace Ironkeep.Companion
{
    /// <summary>
    /// Production composition root. The window and the tray share this session.
    /// Closing the window does not dispose it.
    /// </summary>
    public sealed class CompanionSession : IDisposable
    {
        public const string Version = "2.0.0";
        public const string StartupName = "IronkeepCompanion";

        readonly CompanionConfigStore _store;
        readonly IStartupRegistration _startup;
        readonly string _launchCommand;
        readonly QueueStore _queue;
        readonly SyncCoordinator _coordinator;
        readonly LegacyUploader _legacy;
        bool _disposed;

        public CompanionSession(string queuePath, string settingsPath, IProtector protector, IStartupRegistration startup, string launchCommand, IReportUploader uploader)
        {
            if (startup == null) throw new ArgumentNullException("startup");
            _store = new CompanionConfigStore(settingsPath, protector);
            _startup = startup;
            _launchCommand = launchCommand ?? "";
            Config = _store.Load();
            _queue = QueueStore.Open(queuePath);
            if (uploader == null)
            {
                _legacy = new LegacyUploader(delegate { return Config; });
                uploader = _legacy;
            }
            _coordinator = new SyncCoordinator(_queue, uploader, new SyncSettings());
            ApplyToCoordinator();
        }

        public CompanionConfig Config { get; private set; }
        public SyncCoordinator Coordinator { get { return _coordinator; } }
        public LegacyUploader Legacy { get { return _legacy; } }

        public static CompanionSession ForCurrentUser()
        {
            string directory = SyncPaths.AppDirectory();
            return new CompanionSession(
                SyncPaths.QueueDatabase(),
                Path.Combine(directory, "companion-wpf.txt"),
                new DpapiProtector(),
                new RegistryStartup(),
                Environment.ProcessPath ?? "",
                null);
        }

        public void UseMemory(CompanionConfig config)
        {
            Config = config ?? new CompanionConfig();
            ApplyToCoordinator();
        }

        public SyncSnapshot Discover()
        {
            ApplyToCoordinator();
            _coordinator.Reconcile();
            return _coordinator.Snapshot();
        }

        public void Save(CompanionConfig config)
        {
            _store.Save(config);
            Config = _store.Load();
            ApplyToCoordinator();
            if (_launchCommand.Length > 0)
                _startup.Apply(Config.StartWithWindows, StartupName, _launchCommand);
        }

        public void MarkTrayExplained()
        {
            Config.TrayExplained = true;
            Save(Config);
        }

        public void Start()
        {
            ApplyToCoordinator();
            _coordinator.Start();
        }

        public SyncSnapshot Snapshot()
        {
            return _coordinator.Snapshot();
        }

        public int SavedFileCount()
        {
            string folder = Config.WowFolder ?? "";
            if (folder.Trim().Length == 0 || !Directory.Exists(folder)) return 0;
            return Saved.AllSaved(folder).Count;
        }

        public SyncSnapshot SyncNow()
        {
            ApplyToCoordinator();
            _coordinator.Reconcile();
            _coordinator.Pump(DateTime.UtcNow);
            return _coordinator.Snapshot();
        }

        public void RetryFailed()
        {
            foreach (QueueItem item in _coordinator.History(100))
            {
                if (item.State == SyncState.FailedPermanent) _coordinator.Retry(item.Id, DateTime.UtcNow);
            }
            _coordinator.Pump(DateTime.UtcNow);
        }

        public List<QueueItem> History()
        {
            return _coordinator.History(40);
        }

        public static string Website(CompanionConfig config)
        {
            string address = config == null || config.Address == null || config.Address.Trim().Length == 0
                ? "https://ironkeep.gg"
                : config.Address.Trim().TrimEnd('/');
            string slug = config == null ? "" : (config.Slug ?? "").Trim();
            if (slug.Length == 0) return address;
            return address + "/" + slug + "/raids";
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _coordinator.Dispose();
            _queue.Dispose();
        }

        void ApplyToCoordinator()
        {
            _coordinator.GuildId = Config.Slug ?? "";
            _coordinator.Folder = Config.WowFolder ?? "";
        }
    }
}

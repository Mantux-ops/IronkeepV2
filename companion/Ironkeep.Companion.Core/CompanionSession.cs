using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using Ironkeep;

namespace Ironkeep.Companion
{
    /// <summary>
    /// Production composition root. The window and the tray share this session.
    /// Closing the window does not dispose it.
    /// </summary>
    public sealed class CompanionSession : IDisposable
    {
        public const string Version = "2.0.1";
        public const string StartupName = "IronkeepCompanion";

        readonly CompanionConfigStore _store;
        readonly IStartupRegistration _startup;
        readonly string _launchCommand;
        readonly QueueStore _queue;
        readonly SyncCoordinator _coordinator;
        readonly LegacyUploader _legacy;
        readonly DiscordLogin _login;
        readonly object _configGate = new object();
        readonly List<CompanionGuild> _guilds = new List<CompanionGuild>();
        CancellationTokenSource _loginCancel;
        int _loginBusy;
        bool _disposed;

        public CompanionSession(string queuePath, string settingsPath, IProtector protector, IStartupRegistration startup, string launchCommand, IReportUploader uploader)
            : this(queuePath, settingsPath, protector, startup, launchCommand, uploader, null)
        {
        }

        public CompanionSession(string queuePath, string settingsPath, IProtector protector, IStartupRegistration startup, string launchCommand, IReportUploader uploader, IBrowser browser)
        {
            if (startup == null) throw new ArgumentNullException("startup");
            _store = new CompanionConfigStore(settingsPath, protector);
            _startup = startup;
            _launchCommand = launchCommand ?? "";
            Config = _store.Load();
            _queue = QueueStore.Open(queuePath);
            _legacy = new LegacyUploader(CurrentConfig);
            _login = new DiscordLogin(CurrentConfig, Persist, RememberGuilds, browser ?? new SystemBrowser());
            if (uploader == null)
            {
                uploader = new SessionUploader(CurrentConfig, new DiscordUploader(CurrentConfig, _login), _legacy);
            }
            _coordinator = new SyncCoordinator(_queue, uploader, new SyncSettings());
            ApplyToCoordinator();
        }

        public CompanionConfig Config { get; private set; }
        public SyncCoordinator Coordinator { get { return _coordinator; } }
        public LegacyUploader Legacy { get { return _legacy; } }
        public DiscordLogin Login { get { return _login; } }
        public bool LoginBusy { get { return _loginBusy == 1; } }
        public CompanionAuthState LoginState { get; private set; }
        public string Notice { get; private set; }

        public List<CompanionGuild> GuildChoices()
        {
            lock (_configGate)
            {
                if (_guilds.Count > 0) return new List<CompanionGuild>(_guilds);
                var saved = new List<CompanionGuild>();
                if ((Config.Slug ?? "").Length > 0 || (Config.GuildName ?? "").Length > 0)
                {
                    saved.Add(new CompanionGuild { Id = Config.GuildDiscordId ?? "", Slug = Config.Slug ?? "", Name = Config.GuildName ?? "" });
                }
                return saved;
            }
        }

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
            lock (_configGate)
            {
                Config = config ?? new CompanionConfig();
                ApplyToCoordinator();
            }
        }

        public LoginResult ConnectDiscord(CancellationToken cancel)
        {
            if (Interlocked.CompareExchange(ref _loginBusy, 1, 0) != 0)
                return new LoginResult { Kind = "busy", Detail = "A connection is already in progress." };
            CancellationTokenSource linked = CancellationTokenSource.CreateLinkedTokenSource(cancel);
            _loginCancel = linked;
            Notice = "";
            LoginState = CompanionAuthState.Connecting;
            try
            {
                LoginResult result = _login.Run(linked.Token, delegate(CompanionAuthState state) { LoginState = state; });
                Notice = result.Succeeded || result.Kind == "cancelled" || result.Kind == "success" || result.Kind == "choose" || result.Kind == "denied"
                    ? ""
                    : result.Detail;
                if (result.Kind == "denied") Notice = "";
                return result;
            }
            finally
            {
                LoginState = CompanionAuthState.NotConnected;
                Interlocked.Exchange(ref _loginBusy, 0);
                linked.Dispose();
                if (object.ReferenceEquals(_loginCancel, linked)) _loginCancel = null;
            }
        }

        public void CancelConnect()
        {
            CancellationTokenSource linked = _loginCancel;
            if (linked != null)
            {
                try { linked.Cancel(); }
                catch (ObjectDisposedException) { }
            }
        }

        public LoginResult RetryAuthentication()
        {
            Notice = "";
            CompanionConfig config = CurrentConfig();
            if (config.AuthMode == CompanionConfig.ModeDiscord && (config.RefreshToken ?? "").Length > 0)
                return _login.RefreshGuilds();
            return ConnectDiscord(CancellationToken.None);
        }

        public void DisconnectDiscord()
        {
            CancelConnect();
            _login.RevokeBestEffort();
            lock (_configGate)
            {
                CompanionConfig config = Config ?? new CompanionConfig();
                config.AuthMode = CompanionConfig.ModeSignedOut;
                config.ClearDiscordSecrets();
                _guilds.Clear();
                Notice = "";
                Persist(config);
            }
        }

        public bool SelectGuild(string slug)
        {
            CompanionGuild match = null;
            lock (_configGate)
            {
                for (int i = 0; i < _guilds.Count; i++)
                {
                    if (string.Equals(_guilds[i].Slug, slug ?? "", StringComparison.OrdinalIgnoreCase))
                    {
                        match = _guilds[i];
                        break;
                    }
                }
            }
            if (match == null) return false;
            lock (_configGate)
            {
                CompanionConfig config = Config ?? new CompanionConfig();
                config.AuthMode = CompanionConfig.ModeDiscord;
                config.Slug = match.Slug;
                config.GuildDiscordId = match.Id ?? "";
                config.GuildName = match.Name ?? "";
                config.SessionStatus = "";
                config.SessionDetail = "";
                Persist(config);
            }
            return true;
        }

        public SyncSnapshot Discover()
        {
            ApplyToCoordinator();
            _coordinator.Reconcile();
            return _coordinator.Snapshot();
        }

        public void Save(CompanionConfig config)
        {
            lock (_configGate)
            {
                Persist(config);
                if (_launchCommand.Length > 0)
                    _startup.Apply(Config.StartWithWindows, StartupName, _launchCommand);
            }
        }

        public void MarkTrayExplained()
        {
            Config.TrayExplained = true;
            Save(Config);
        }

        public void Start()
        {
            ApplyToCoordinator();
            _coordinator.Reconcile();
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

        CompanionConfig CurrentConfig()
        {
            return Config ?? new CompanionConfig();
        }

        void RememberGuilds(List<CompanionGuild> guilds)
        {
            lock (_configGate)
            {
                _guilds.Clear();
                if (guilds == null) return;
                for (int i = 0; i < guilds.Count; i++) _guilds.Add(guilds[i]);
            }
        }

        void Persist(CompanionConfig config)
        {
            lock (_configGate)
            {
                _store.Save(config ?? new CompanionConfig());
                Config = _store.Load();
                ApplyToCoordinator();
            }
        }

        void ApplyToCoordinator()
        {
            CompanionConfig config = Config ?? new CompanionConfig();
            string slug = (config.Slug ?? "").Trim();
            bool discordBlocked = config.AuthMode == CompanionConfig.ModeDiscord && ((config.SessionStatus ?? "").Length > 0 || (config.RefreshToken ?? "").Length == 0 || config.SessionUnreadable);
            bool blocked = discordBlocked || config.AuthMode == CompanionConfig.ModeSignedOut;
            _coordinator.GuildId = blocked || slug.Length == 0 ? "" : slug;
            _coordinator.Folder = config.WowFolder ?? "";
        }
    }
}

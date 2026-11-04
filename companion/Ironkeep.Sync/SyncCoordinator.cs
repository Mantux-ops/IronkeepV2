using System;
using System.Collections.Generic;
using System.IO;

namespace Ironkeep
{
    public interface IReportUploader
    {
        UploadResult Upload(string guildId, string body);
    }

    public sealed class UploadResult
    {
        public int Status;
        public string Body = "";
        public bool TransportFailed;
    }

    public sealed class SyncSettings
    {
        public TimeSpan RescanInterval = TimeSpan.FromMinutes(2);
        public TimeSpan SettleInterval = TimeSpan.FromMilliseconds(400);
        public bool Watch = true;
    }

    public sealed class SyncSnapshot
    {
        public bool CorruptionDetected;
        public bool UnsentReportsRecovered;
        public string PreservedCorruptPath = "";
        public int WatcherFaults;
        public bool WatcherRunning;
        public bool WaitingForGuild;
        public int Pending;
        public int RetryScheduled;
        public int Confirmed;
        public int FailedPermanent;
        public string Folder = "";
        public string GuildId = "";
    }

    /// <summary>
    /// Owns discovery, the watcher, the rescan, the queue, and uploads.
    /// A queued body is sent as stored. The source file is not read again for that item.
    /// This replaces the sync work inside the WinForms window. The window itself stays
    /// on .NET Framework until a later phase.
    /// </summary>
    public sealed class SyncCoordinator : IDisposable
    {
        readonly QueueStore _queue;
        readonly IReportUploader _uploader;
        readonly SyncSettings _settings;
        readonly object _gate = new object();
        readonly Dictionary<string, SettleWatch> _armed = new Dictionary<string, SettleWatch>(StringComparer.OrdinalIgnoreCase);
        FileSystemWatcher _watcher;
        System.Threading.Timer _settleTimer;
        System.Threading.Timer _rescanTimer;
        int _watcherFaults;
        bool _started;

        public SyncCoordinator(QueueStore queue, IReportUploader uploader, SyncSettings settings)
        {
            if (queue == null) throw new ArgumentNullException("queue");
            if (uploader == null) throw new ArgumentNullException("uploader");
            _queue = queue;
            _uploader = uploader;
            _settings = settings ?? new SyncSettings();
        }

        public string GuildId { get; set; }
        public string Folder { get; set; }

        public void Start()
        {
            lock (_gate)
            {
                if (_started) return;
                _started = true;
                if (_settings.Watch) StartWatcher();
                if (_settings.SettleInterval > TimeSpan.Zero)
                {
                    _settleTimer = new System.Threading.Timer(delegate { TickSettle(); }, null, _settings.SettleInterval, _settings.SettleInterval);
                }
                if (_settings.RescanInterval > TimeSpan.Zero)
                {
                    _rescanTimer = new System.Threading.Timer(delegate { Reconcile(); Pump(DateTime.UtcNow); }, null, _settings.RescanInterval, _settings.RescanInterval);
                }
            }
        }

        public void Stop()
        {
            lock (_gate)
            {
                _started = false;
                if (_settleTimer != null) _settleTimer.Dispose();
                if (_rescanTimer != null) _rescanTimer.Dispose();
                _settleTimer = null;
                _rescanTimer = null;
                StopWatcher();
            }
        }

        public void Dispose()
        {
            Stop();
        }

        public void Reconcile()
        {
            string folder = Folder;
            string guild = GuildId;
            if (folder == null || folder.Trim().Length == 0 || !Directory.Exists(folder)) return;
            if (guild == null || guild.Trim().Length == 0) return;
            foreach (string file in Saved.AllSaved(folder)) SnapshotFile(guild, file);
        }

        public void Arm(string path)
        {
            if (path == null || path.Length == 0) return;
            lock (_gate)
            {
                if (_armed.ContainsKey(path)) return;
                _armed[path] = new SettleWatch();
            }
        }

        public void TickSettle()
        {
            List<string> ready = new List<string>();
            lock (_gate)
            {
                var done = new List<string>();
                foreach (var pair in _armed)
                {
                    if (!File.Exists(pair.Key))
                    {
                        done.Add(pair.Key);
                        continue;
                    }
                    long length = new FileInfo(pair.Key).Length;
                    if (!pair.Value.Due(length)) continue;
                    done.Add(pair.Key);
                    ready.Add(pair.Key);
                }
                foreach (string path in done) _armed.Remove(path);
            }
            string guild = GuildId;
            if (guild == null || guild.Trim().Length == 0) return;
            foreach (string path in ready) SnapshotFile(guild, path);
        }

        public int Pump(DateTime utcNow)
        {
            int sent = 0;
            foreach (QueueItem item in _queue.Due(utcNow))
            {
                if (item.Body == null)
                {
                    _queue.MarkFailed(item.Id, "missing snapshot", utcNow);
                    continue;
                }
                string body = item.Body;
                string guild = item.GuildId;
                int attempt = item.Attempts + 1;
                _queue.MarkSending(item.Id, utcNow);
                UploadResult result;
                try
                {
                    result = _uploader.Upload(guild, body);
                }
                catch (Exception)
                {
                    _queue.MarkRetry(item.Id, utcNow.AddSeconds(DelaySeconds(attempt)), "transport", utcNow);
                    continue;
                }
                if (result == null || result.TransportFailed || SiteClient.Retryable(result.Status))
                {
                    string error = result == null ? "transport" : "HTTP " + result.Status.ToString();
                    _queue.MarkRetry(item.Id, utcNow.AddSeconds(DelaySeconds(attempt)), error, utcNow);
                    continue;
                }
                if (result.Status >= 200 && result.Status < 300 && SiteClient.Accepted(result.Body))
                {
                    _queue.MarkConfirmed(item.Id, utcNow);
                    sent++;
                    continue;
                }
                _queue.MarkFailed(item.Id, "HTTP " + result.Status.ToString(), utcNow);
            }
            return sent;
        }

        public void Retry(string id, DateTime utcNow)
        {
            _queue.RetryFailed(id, utcNow);
        }

        public void SimulateWatcherError()
        {
            OnWatcherError(null, null);
        }

        public SyncSnapshot Snapshot()
        {
            var snap = new SyncSnapshot();
            snap.CorruptionDetected = _queue.CorruptionDetected;
            snap.UnsentReportsRecovered = _queue.UnsentReportsRecovered;
            snap.PreservedCorruptPath = _queue.PreservedCorruptPath ?? "";
            snap.WatcherFaults = _watcherFaults;
            snap.WatcherRunning = _watcher != null && _watcher.EnableRaisingEvents;
            snap.Folder = Folder ?? "";
            snap.GuildId = GuildId ?? "";
            snap.WaitingForGuild = snap.GuildId.Length == 0;
            Dictionary<string, int> counts = _queue.Counts();
            int count;
            if (counts.TryGetValue(SyncState.Pending, out count)) snap.Pending = count;
            if (counts.TryGetValue(SyncState.RetryScheduled, out count)) snap.RetryScheduled = count;
            if (counts.TryGetValue(SyncState.Confirmed, out count)) snap.Confirmed = count;
            if (counts.TryGetValue(SyncState.FailedPermanent, out count)) snap.FailedPermanent = count;
            return snap;
        }

        public static int DelaySeconds(int attempt)
        {
            if (attempt <= 1) return 15;
            if (attempt == 2) return 60;
            if (attempt == 3) return 300;
            return 900;
        }

        void SnapshotFile(string guild, string file)
        {
            Dictionary<object, object> db;
            try
            {
                db = Saved.LoadPath(file);
            }
            catch (SavedException)
            {
                return;
            }
            string text = Saved.TextFor(db);
            if (text == null || text.Trim().Length == 0) return;
            if (text.IndexOf("format: ironkeep-group 1") < 0) return;
            _queue.Enqueue(guild, file, text);
        }

        void StartWatcher()
        {
            StopWatcher();
            string folder = Folder;
            if (folder == null || !Directory.Exists(folder)) return;
            _watcher = new FileSystemWatcher(folder);
            _watcher.Filter = "Ironkeep.lua";
            _watcher.IncludeSubdirectories = true;
            _watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size;
            _watcher.Changed += delegate(object sender, FileSystemEventArgs e) { Arm(e.FullPath); };
            _watcher.Created += delegate(object sender, FileSystemEventArgs e) { Arm(e.FullPath); };
            _watcher.Renamed += delegate(object sender, RenamedEventArgs e) { Arm(e.FullPath); };
            _watcher.Error += OnWatcherError;
            _watcher.EnableRaisingEvents = true;
        }

        void StopWatcher()
        {
            if (_watcher == null) return;
            _watcher.EnableRaisingEvents = false;
            _watcher.Dispose();
            _watcher = null;
        }

        void OnWatcherError(object sender, ErrorEventArgs e)
        {
            _watcherFaults++;
            try
            {
                StartWatcher();
            }
            catch (Exception)
            {
                StopWatcher();
            }
        }
    }
}

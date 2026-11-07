using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;

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

    /// <summary>
    /// Accepted: HTTP 2xx whose body is one JSON object with boolean ok true. The stored report body may be removed.
    /// Retry: no response, a transport failure, status 0, 408, 429, or 500-599, or any 2xx that is not that JSON object.
    /// Reauthenticate: 401 and 403. The report body stays. Pump does not send it again until Retry is called.
    /// Permanent: every other completed response, including a JSON object with boolean ok false. The report body stays.
    /// </summary>
    public enum DeliveryKind
    {
        Accepted,
        Retry,
        Reauthenticate,
        Permanent
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
        public int Sending;
        public int RetryScheduled;
        public int Confirmed;
        public int FailedPermanent;
        public string LastError = "";
        public string LastConfirmedAt = "";
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
        readonly object _pumpGate = new object();
        readonly Dictionary<string, SettleWatch> _armed = new Dictionary<string, SettleWatch>(StringComparer.OrdinalIgnoreCase);
        FileSystemWatcher _watcher;
        Timer _settleTimer;
        Timer _rescanTimer;
        int _watcherFaults;
        volatile bool _started;

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
                if (_settings.SettleInterval > TimeSpan.Zero)
                {
                    _settleTimer = new Timer(delegate { GuardTimer(TickSettle); }, null, _settings.SettleInterval, _settings.SettleInterval);
                }
                if (_settings.RescanInterval > TimeSpan.Zero)
                {
                    _rescanTimer = new Timer(delegate { GuardTimer(delegate { Reconcile(); Pump(DateTime.UtcNow); }); }, null, _settings.RescanInterval, _settings.RescanInterval);
                }
            }
            if (_settings.Watch) StartWatcher();
        }

        public void Stop()
        {
            Timer settle;
            Timer rescan;
            lock (_gate)
            {
                _started = false;
                settle = _settleTimer;
                rescan = _rescanTimer;
                _settleTimer = null;
                _rescanTimer = null;
            }
            if (settle != null) settle.Dispose();
            if (rescan != null) rescan.Dispose();
            StopWatcher();
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
            if (!Monitor.TryEnter(_pumpGate)) return 0;
            try
            {
                return PumpHeld(utcNow);
            }
            finally
            {
                Monitor.Exit(_pumpGate);
            }
        }

        /// <summary>
        /// Accepted: HTTP 2xx and a JSON object with boolean ok true.
        /// Retry: transport failure, status 0, 408, 429, 500-599, or a 2xx that is not valid acceptance JSON.
        /// Reauthenticate: 401 and 403. Permanent keeps the body until Retry is called.
        /// Permanent: other completed responses, including {"ok":false}. The body stays.
        /// </summary>
        public static DeliveryKind Classify(UploadResult result)
        {
            if (result == null || result.TransportFailed) return DeliveryKind.Retry;
            if (result.Status >= 200 && result.Status < 300)
            {
                AckKind ack = SiteClient.ReadAck(result.Body);
                if (ack == AckKind.Accepted) return DeliveryKind.Accepted;
                if (ack == AckKind.Unparseable) return DeliveryKind.Retry;
                return DeliveryKind.Permanent;
            }
            if (result.Status == 401 || result.Status == 403) return DeliveryKind.Reauthenticate;
            if (SiteClient.Retryable(result.Status)) return DeliveryKind.Retry;
            return DeliveryKind.Permanent;
        }

        internal static void GuardTimer(Action work)
        {
            try
            {
                if (work != null) work();
            }
            catch (Exception)
            {
            }
        }

        int PumpHeld(DateTime utcNow)
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
                if (!_queue.MarkSending(item.Id, utcNow)) continue;
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
                DeliveryKind kind = Classify(result);
                if (kind == DeliveryKind.Accepted)
                {
                    _queue.MarkConfirmed(item.Id, utcNow);
                    sent++;
                    continue;
                }
                if (kind == DeliveryKind.Retry)
                {
                    string error = "transport";
                    if (result != null && !result.TransportFailed)
                        error = result.Status >= 200 && result.Status < 300 ? "malformed acknowledgment" : "HTTP " + result.Status.ToString();
                    _queue.MarkRetry(item.Id, utcNow.AddSeconds(DelaySeconds(attempt)), error, utcNow);
                    continue;
                }
                string failure = kind == DeliveryKind.Reauthenticate
                    ? "reauthentication HTTP " + result.Status.ToString()
                    : (result.Status >= 200 && result.Status < 300 ? "rejected HTTP " + result.Status.ToString() : "HTTP " + result.Status.ToString());
                _queue.MarkFailed(item.Id, failure, utcNow);
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
            if (counts.TryGetValue(SyncState.Sending, out count)) snap.Sending = count;
            if (counts.TryGetValue(SyncState.RetryScheduled, out count)) snap.RetryScheduled = count;
            if (counts.TryGetValue(SyncState.Confirmed, out count)) snap.Confirmed = count;
            if (counts.TryGetValue(SyncState.FailedPermanent, out count)) snap.FailedPermanent = count;
            snap.LastError = _queue.LatestError() ?? "";
            snap.LastConfirmedAt = _queue.LatestConfirmedAt() ?? "";
            return snap;
        }

        public List<QueueItem> History(int limit)
        {
            return _queue.History(limit);
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
            if (!_started) return;
            string folder = Folder;
            if (folder == null || !Directory.Exists(folder)) return;
            var watcher = new FileSystemWatcher(folder);
            watcher.Filter = "Ironkeep.lua";
            watcher.IncludeSubdirectories = true;
            watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size;
            watcher.Changed += delegate(object sender, FileSystemEventArgs e) { Arm(e.FullPath); };
            watcher.Created += delegate(object sender, FileSystemEventArgs e) { Arm(e.FullPath); };
            watcher.Renamed += delegate(object sender, RenamedEventArgs e) { Arm(e.FullPath); };
            watcher.Error += OnWatcherError;
            lock (_gate)
            {
                if (!_started)
                {
                    watcher.Dispose();
                    return;
                }
                _watcher = watcher;
            }
            watcher.EnableRaisingEvents = true;
        }

        void StopWatcher()
        {
            FileSystemWatcher watcher;
            lock (_gate)
            {
                watcher = _watcher;
                _watcher = null;
            }
            if (watcher == null) return;
            try
            {
                watcher.EnableRaisingEvents = false;
                watcher.Dispose();
            }
            catch (Exception)
            {
            }
        }

        void OnWatcherError(object sender, ErrorEventArgs e)
        {
            Interlocked.Increment(ref _watcherFaults);
            if (!_started) return;
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

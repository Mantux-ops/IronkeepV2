using System;
using System.Collections.Generic;
using System.IO;
using System.Security.AccessControl;
using System.Text;
using System.Threading;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Ironkeep.Tests
{
    public sealed class SyncFoundationTests : IDisposable
    {
        readonly string _root;
        readonly string _queuePath;
        readonly RecordingUploader _uploader;
        readonly QueueStore _queue;
        readonly SyncCoordinator _sync;

        public SyncFoundationTests()
        {
            _root = Path.Combine(Path.GetTempPath(), "ironkeep-sync-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
            _queuePath = Path.Combine(_root, "companion-queue.sqlite");
            _uploader = new RecordingUploader();
            _queue = QueueStore.Open(_queuePath);
            _sync = new SyncCoordinator(_queue, _uploader, new SyncSettings());
            _sync.GuildId = "guild-a";
        }

        public void Dispose()
        {
            _sync.Dispose();
            _queue.Dispose();
            try
            {
                Directory.Delete(_root, true);
            }
            catch (IOException)
            {
            }
        }

        [Fact]
        public void AChangedFileDoesNotReplaceAQueuedSnapshot()
        {
            string file = WriteAccount("One", Sample("Hall of Thanes"));
            _sync.Folder = WowRoot();
            _sync.Reconcile();
            QueueItem first = _queue.Due(DateTime.UtcNow)[0];
            File.WriteAllText(file, Sample("Molten Core"));
            _uploader.Handler = delegate { return Ok(false); };
            _sync.Pump(DateTime.UtcNow);
            Assert.Equal(first.Body, _uploader.Sent[0].Body);
            Assert.Contains("Hall of Thanes", _uploader.Sent[0].Body);
            Assert.DoesNotContain("Molten Core", _uploader.Sent[0].Body);

            _sync.Reconcile();
            Assert.Equal(2, _queue.Due(DateTime.UtcNow).Count + ConfirmedCount());
            _sync.Pump(DateTime.UtcNow);
            Assert.Contains("Molten Core", _uploader.Sent[1].Body);
        }

        [Fact]
        public void ARestartDuringUploadKeepsTheSnapshotPending()
        {
            string file = WriteAccount("One", Sample("Hall of Thanes"));
            _sync.Folder = WowRoot();
            _sync.Reconcile();
            QueueItem item = _queue.Due(DateTime.UtcNow)[0];
            _queue.MarkSending(item.Id, DateTime.UtcNow);
            _queue.Dispose();

            QueueStore reopened = QueueStore.Open(_queuePath);
            try
            {
                QueueItem again = reopened.Get(item.Id);
                Assert.Equal(SyncState.Pending, again.State);
                Assert.Equal(item.Body, again.Body);
                Assert.Equal(item.GuildId, again.GuildId);
            }
            finally
            {
                reopened.Dispose();
            }
        }

        [Fact]
        public void ALostResponseAfterAcceptanceIsConfirmedOnRetry()
        {
            string file = WriteAccount("One", Sample("Hall of Thanes"));
            _sync.Folder = WowRoot();
            _sync.Reconcile();
            QueueItem item = _queue.Due(DateTime.UtcNow)[0];
            int calls = 0;
            _uploader.Handler = delegate
            {
                calls++;
                if (calls == 1) throw new IOException("reset");
                return Ok(true);
            };
            DateTime now = DateTime.UtcNow;
            _sync.Pump(now);
            Assert.Equal(SyncState.RetryScheduled, _queue.Get(item.Id).State);
            Assert.Equal(item.Body, _queue.Get(item.Id).Body);

            _sync.Pump(now.AddMinutes(20));
            QueueItem done = _queue.Get(item.Id);
            Assert.Equal(SyncState.Confirmed, done.State);
            Assert.Null(done.Body);
            Assert.Equal(item.BodyHash, done.BodyHash);
            Assert.Equal(item.Body, _uploader.Sent[0].Body);
            Assert.Equal(item.Body, _uploader.Sent[1].Body);
        }

        [Fact]
        public void EachAccountIsQueuedOnItsOwn()
        {
            WriteAccount("One", Sample("Hall of Thanes"));
            WriteAccount("Two", Sample("Molten Core"));
            _sync.Folder = WowRoot();
            _sync.Reconcile();
            List<QueueItem> due = _queue.Due(DateTime.UtcNow);
            Assert.Equal(2, due.Count);
            Assert.NotEqual(due[0].SourcePath, due[1].SourcePath);
            Assert.NotEqual(due[0].BodyHash, due[1].BodyHash);
        }

        [Fact]
        public void TheSameTextCanBeSentToTwoGuilds()
        {
            WriteAccount("One", Sample("Hall of Thanes"));
            _sync.Folder = WowRoot();
            _sync.GuildId = "guild-a";
            _sync.Reconcile();
            _sync.GuildId = "guild-b";
            _sync.Reconcile();
            List<QueueItem> due = _queue.Due(DateTime.UtcNow);
            Assert.Equal(2, due.Count);
            Assert.Equal(due[0].Body, due[1].Body);
            Assert.NotEqual(due[0].GuildId, due[1].GuildId);
            _uploader.Handler = delegate { return Ok(false); };
            _sync.Pump(DateTime.UtcNow);
            Assert.Equal(2, _uploader.Sent.Count);
            Assert.Contains(_uploader.Sent, pair => pair.GuildId == "guild-a");
            Assert.Contains(_uploader.Sent, pair => pair.GuildId == "guild-b");
        }

        [Fact]
        public void ASecondEnqueueOfTheSameReportDoesNotCreateAnotherRow()
        {
            WriteAccount("One", Sample("Hall of Thanes"));
            _sync.Folder = WowRoot();
            _sync.Reconcile();
            _sync.Reconcile();
            Assert.Single(_queue.Due(DateTime.UtcNow));
        }

        [Fact]
        public void TwoThreadsEnqueueOneSnapshot()
        {
            string body = Saved.TextFor(Saved.Load(Sample("Hall of Thanes")));
            var ids = new List<string>();
            var gate = new object();
            var start = new ManualResetEvent(false);
            var threads = new Thread[8];
            for (int i = 0; i < threads.Length; i++)
            {
                threads[i] = new Thread(new ThreadStart(delegate
                {
                    start.WaitOne();
                    QueueItem item = _queue.Enqueue("guild-a", "a.lua", body);
                    lock (gate) ids.Add(item.Id);
                }));
                threads[i].Start();
            }
            start.Set();
            for (int i = 0; i < threads.Length; i++) threads[i].Join();
            Assert.Single(new HashSet<string>(ids));
            Assert.Single(_queue.Due(DateTime.UtcNow));
        }

        [Fact]
        public void ACorruptQueueIsKeptAndIsNotTreatedAsRecovered()
        {
            _sync.Stop();
            _queue.Dispose();
            SqliteConnection.ClearAllPools();
            if (File.Exists(_queuePath + "-wal")) File.Delete(_queuePath + "-wal");
            if (File.Exists(_queuePath + "-shm")) File.Delete(_queuePath + "-shm");
            File.WriteAllText(_queuePath, "this is not a sqlite database");
            QueueStore reopened = QueueStore.Open(_queuePath);
            try
            {
                Assert.True(reopened.CorruptionDetected);
                Assert.False(reopened.UnsentReportsRecovered);
                Assert.True(File.Exists(reopened.PreservedCorruptPath));
                Assert.Equal("this is not a sqlite database", File.ReadAllText(reopened.PreservedCorruptPath));
                QueueItem item = reopened.Enqueue("guild-a", "a.lua", "Ironkeep group\nformat: ironkeep-group 1\n");
                Assert.Equal(SyncState.Pending, item.State);
                string kept = reopened.PreservedCorruptPath;
                reopened.Dispose();
                reopened = null;
                QueueStore third = QueueStore.Open(_queuePath);
                try
                {
                    Assert.True(third.CorruptionDetected);
                    Assert.False(third.UnsentReportsRecovered);
                    Assert.Equal(kept, third.PreservedCorruptPath);
                    Assert.NotNull(third.Get(item.Id));
                }
                finally
                {
                    third.Dispose();
                }
            }
            finally
            {
                if (reopened != null) reopened.Dispose();
            }
        }

        [Fact]
        public void AMissedWatcherEventIsFoundByTheRescan()
        {
            _sync.Folder = WowRoot();
            _sync.Reconcile();
            Assert.Empty(_queue.Due(DateTime.UtcNow));
            WriteAccount("One", Sample("Hall of Thanes"));
            _sync.Reconcile();
            Assert.Single(_queue.Due(DateTime.UtcNow));
        }

        [Fact]
        public void TheRescanTimerFindsAFileWithoutAWatcherEvent()
        {
            var settings = new SyncSettings();
            settings.Watch = false;
            settings.RescanInterval = TimeSpan.FromMilliseconds(50);
            _sync.Dispose();
            var queue = QueueStore.Open(Path.Combine(_root, "timer-queue.sqlite"));
            var sync = new SyncCoordinator(queue, _uploader, settings);
            try
            {
                sync.GuildId = "guild-a";
                sync.Folder = WowRoot();
                sync.Start();
                WriteAccount("One", Sample("Hall of Thanes"));
                var until = DateTime.UtcNow.AddSeconds(3);
                while (DateTime.UtcNow < until && sync.Snapshot().Pending == 0 && sync.Snapshot().Confirmed == 0)
                    Thread.Sleep(20);
                SyncSnapshot snap = sync.Snapshot();
                Assert.Equal(1, snap.Pending + snap.Confirmed);
            }
            finally
            {
                sync.Dispose();
                queue.Dispose();
            }
        }

        [Fact]
        public void AWatcherErrorRestartsTheWatcher()
        {
            Directory.CreateDirectory(WowRoot());
            _sync.Folder = WowRoot();
            _sync.Start();
            Assert.True(_sync.Snapshot().WatcherRunning);
            _sync.SimulateWatcherError();
            Assert.Equal(1, _sync.Snapshot().WatcherFaults);
            Assert.True(_sync.Snapshot().WatcherRunning);
        }

        [Fact]
        public void APermanentFailureKeepsTheSnapshot()
        {
            WriteAccount("One", Sample("Hall of Thanes"));
            _sync.Folder = WowRoot();
            _sync.Reconcile();
            QueueItem item = _queue.Due(DateTime.UtcNow)[0];
            _uploader.Handler = delegate { return new UploadResult { Status = 400, Body = "{\"ok\":false}" }; };
            DateTime now = DateTime.UtcNow;
            _sync.Pump(now);
            QueueItem failed = _queue.Get(item.Id);
            Assert.Equal(SyncState.FailedPermanent, failed.State);
            Assert.Equal(item.Body, failed.Body);
            int calls = _uploader.Sent.Count;
            _sync.Pump(now.AddHours(1));
            Assert.Equal(calls, _uploader.Sent.Count);
        }

        [Fact]
        public void TheQueueFileIsReadableOnlyByThisUser()
        {
            Assert.True(File.Exists(_queuePath + "-wal"));
            Assert.True(File.Exists(_queuePath + "-shm"));
            string directory = Path.GetDirectoryName(_queuePath);
            if (OperatingSystem.IsWindows())
            {
                Assert.True(new FileInfo(_queuePath).GetAccessControl().AreAccessRulesProtected);
                Assert.True(new FileInfo(_queuePath + "-wal").GetAccessControl().AreAccessRulesProtected);
                Assert.True(new FileInfo(_queuePath + "-shm").GetAccessControl().AreAccessRulesProtected);
                Assert.True(new DirectoryInfo(directory).GetAccessControl().AreAccessRulesProtected);
                return;
            }
            AssertPrivateFile(_queuePath);
            AssertPrivateFile(_queuePath + "-wal");
            AssertPrivateFile(_queuePath + "-shm");
            Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute, File.GetUnixFileMode(directory));
        }

        [Fact]
        public void AZeroByteMainFileDoesNotDiscardTheWal()
        {
            byte[] main;
            byte[] wal = CommittedWal(out main);
            Assert.Contains("secret-report-body", Encoding.Latin1.GetString(wal));
            string path = Path.Combine(_root, "zero-main.sqlite");
            File.WriteAllBytes(path, new byte[0]);
            File.WriteAllBytes(path + "-wal", wal);
            QueueStore store = QueueStore.Open(path);
            try
            {
                Assert.True(store.CorruptionDetected);
                Assert.False(store.UnsentReportsRecovered);
                Assert.Equal(wal, File.ReadAllBytes(store.PreservedCorruptPath + "-wal"));
                Assert.Equal(0, new FileInfo(store.PreservedCorruptPath).Length);
                Assert.NotEqual(wal, ReadShared(path + "-wal"));
                Assert.Contains("preserved", File.ReadAllText(path + ".corruption"));
                if (!OperatingSystem.IsWindows())
                {
                    AssertPrivateFile(store.PreservedCorruptPath + "-wal");
                    AssertPrivateFile(path + ".corruption");
                }
            }
            finally
            {
                store.Dispose();
            }
        }

        [Fact]
        public void AValidHeaderStillReplaysTheWal()
        {
            byte[] main;
            byte[] wal = CommittedWal(out main);
            string path = Path.Combine(_root, "replay.sqlite");
            File.WriteAllBytes(path, main);
            File.WriteAllBytes(path + "-wal", wal);
            QueueStore store = QueueStore.Open(path);
            try
            {
                Assert.False(store.CorruptionDetected);
                Assert.Equal("", store.PreservedCorruptPath);
            }
            finally
            {
                store.Dispose();
            }
            SqliteConnection.ClearAllPools();
            using (var check = new SqliteConnection("Data Source=" + path + ";Pooling=False"))
            {
                check.Open();
                using (var cmd = check.CreateCommand())
                {
                    cmd.CommandText = "SELECT body FROM report";
                    Assert.Equal("secret-report-body", cmd.ExecuteScalar());
                }
            }
        }

        [Fact]
        public void AMissingMainFileKeepsTheWal()
        {
            byte[] main;
            byte[] wal = CommittedWal(out main);
            string path = Path.Combine(_root, "missing-main.sqlite");
            File.WriteAllBytes(path + "-wal", wal);
            QueueStore store = QueueStore.Open(path);
            try
            {
                Assert.True(store.CorruptionDetected);
                Assert.False(store.UnsentReportsRecovered);
                Assert.Equal(wal, File.ReadAllBytes(store.PreservedCorruptPath + "-wal"));
                Assert.NotEqual(wal, ReadShared(path + "-wal"));
            }
            finally
            {
                store.Dispose();
            }
        }

        [Fact]
        public void InterruptedPreservationIsResumed()
        {
            byte[] main;
            byte[] wal = CommittedWal(out main);
            string path = Path.Combine(_root, "interrupted.sqlite");
            string dest = Path.Combine(_root, "held-recovery.sqlite");
            File.WriteAllBytes(path, new byte[0]);
            File.WriteAllBytes(path + "-wal", wal);
            QueueStore.WritePendingRecoveryMarker(path, dest);
            Assert.Contains("\npending\n", File.ReadAllText(path + ".corruption"));
            QueueStore store = QueueStore.Open(path);
            try
            {
                Assert.True(store.CorruptionDetected);
                Assert.False(store.UnsentReportsRecovered);
                Assert.Equal(dest, store.PreservedCorruptPath);
                Assert.Equal(wal, File.ReadAllBytes(dest + "-wal"));
                Assert.Contains("\npreserved\n", File.ReadAllText(path + ".corruption"));
            }
            finally
            {
                store.Dispose();
            }
            QueueStore again = QueueStore.Open(path);
            try
            {
                Assert.True(again.CorruptionDetected);
                Assert.False(again.UnsentReportsRecovered);
                Assert.Equal(wal, File.ReadAllBytes(dest + "-wal"));
            }
            finally
            {
                again.Dispose();
            }
        }

        [Fact]
        public void PreservationAlreadyInProgressIsReported()
        {
            byte[] main;
            byte[] wal = CommittedWal(out main);
            string path = Path.Combine(_root, "partial.sqlite");
            string dest = Path.Combine(_root, "partial-recovery.sqlite");
            File.WriteAllBytes(dest, new byte[0]);
            File.WriteAllBytes(dest + "-wal", wal);
            QueueStore.WritePendingRecoveryMarker(path, dest);
            QueueStore store = QueueStore.Open(path);
            try
            {
                Assert.True(store.CorruptionDetected);
                Assert.False(store.UnsentReportsRecovered);
                Assert.Equal(dest, store.PreservedCorruptPath);
                Assert.Equal(wal, File.ReadAllBytes(dest + "-wal"));
                Assert.Contains("\npreserved\n", File.ReadAllText(path + ".corruption"));
            }
            finally
            {
                store.Dispose();
            }
        }

        [Fact]
        public void AnOpenQueueIsNotRenamed()
        {
            InvalidOperationException ex = Assert.Throws<InvalidOperationException>(delegate { QueueStore.Open(_queuePath); });
            Assert.Contains("not moved", ex.Message);
            Assert.True(File.Exists(_queuePath));
            QueueItem item = _queue.Enqueue("guild-a", "live.lua", "Ironkeep group\nformat: ironkeep-group 1\nstill-here");
            Assert.Equal(SyncState.Pending, item.State);
        }

        [Fact]
        public void AcknowledgmentsAreClassifiedBeforeTheBodyIsRemoved()
        {
            Deliver(200, "{\"ok\":true}", SyncState.Confirmed, false, null);
            Deliver(200, "{\"ok\":true,\"duplicate\":true}", SyncState.Confirmed, false, null);
            Deliver(200, "{\"ok\": true, \"duplicate\": false, \"place\": \"Hall of Thanes\", \"people\": 3}", SyncState.Confirmed, false, null);
            Deliver(200, "{\"ok\":false}", SyncState.FailedPermanent, true, "rejected");
            Deliver(200, "{", SyncState.RetryScheduled, true, "malformed");
            Deliver(200, "{\"ok\":true", SyncState.RetryScheduled, true, "malformed");
            Deliver(200, "\"{\\\"ok\\\":true}\"", SyncState.RetryScheduled, true, "malformed");
            Deliver(200, "see \"ok\":true", SyncState.RetryScheduled, true, "malformed");
            Deliver(200, "", SyncState.RetryScheduled, true, "malformed");
            Deliver(202, "{\"ok\":", SyncState.RetryScheduled, true, "malformed");
            Deliver(408, "", SyncState.RetryScheduled, true, "HTTP 408");
            Deliver(429, "", SyncState.RetryScheduled, true, "HTTP 429");
            Deliver(500, "", SyncState.RetryScheduled, true, "HTTP 500");
            Deliver(401, "{\"ok\":false}", SyncState.FailedPermanent, true, "reauthentication HTTP 401");
            Deliver(403, "{\"ok\":false}", SyncState.FailedPermanent, true, "reauthentication HTTP 403");
        }

        [Fact]
        public void OverlappingPumpsClaimEachItemOnce()
        {
            _queue.Enqueue("guild-a", "a.lua", "Ironkeep group\nformat: ironkeep-group 1\none");
            _queue.Enqueue("guild-a", "b.lua", "Ironkeep group\nformat: ironkeep-group 1\ntwo");
            int active = 0;
            int max = 0;
            _uploader.Handler = delegate
            {
                int now = Interlocked.Increment(ref active);
                int seen;
                do
                {
                    seen = max;
                }
                while (now > seen && Interlocked.CompareExchange(ref max, now, seen) != seen);
                Thread.Sleep(200);
                Interlocked.Decrement(ref active);
                return Ok(false);
            };
            Exception failed = null;
            var threads = new Thread[2];
            for (int i = 0; i < threads.Length; i++)
            {
                threads[i] = new Thread(new ThreadStart(delegate
                {
                    try
                    {
                        _sync.Pump(DateTime.UtcNow);
                    }
                    catch (Exception ex)
                    {
                        failed = ex;
                    }
                }));
            }
            threads[0].Start();
            threads[1].Start();
            threads[0].Join();
            threads[1].Join();
            Assert.Null(failed);
            Assert.Equal(1, max);
            Assert.Equal(2, _uploader.Sent.Count);
            Assert.Equal(2, ConfirmedCount());
        }

        [Fact]
        public void ASecondClaimDoesNotThrow()
        {
            QueueItem item = _queue.Enqueue("guild-a", "a.lua", "Ironkeep group\nformat: ironkeep-group 1\nclaim");
            Assert.True(_queue.MarkSending(item.Id, DateTime.UtcNow));
            Assert.False(_queue.MarkSending(item.Id, DateTime.UtcNow));
            Assert.Equal(SyncState.Sending, _queue.Get(item.Id).State);
        }

        [Fact]
        public void ATimerFaultDoesNotEscape()
        {
            SyncCoordinator.GuardTimer(delegate { throw new InvalidOperationException("timer"); });
        }

        void Deliver(int status, string httpBody, string state, bool keepBody, string errorPart)
        {
            string report = "Ironkeep group\nformat: ironkeep-group 1\n" + Guid.NewGuid().ToString("N");
            QueueItem item = _queue.Enqueue("guild-a", "case.lua", report);
            _uploader.Handler = delegate { return new UploadResult { Status = status, Body = httpBody }; };
            DateTime now = DateTime.UtcNow;
            int before = _uploader.Sent.Count;
            _sync.Pump(now);
            Assert.Equal(before + 1, _uploader.Sent.Count);
            _sync.Pump(now);
            Assert.Equal(before + 1, _uploader.Sent.Count);
            QueueItem got = _queue.Get(item.Id);
            Assert.Equal(state, got.State);
            if (keepBody) Assert.Equal(report, got.Body);
            else Assert.Null(got.Body);
            if (errorPart != null) Assert.Contains(errorPart, got.LastError);
        }

        static void AssertPrivateFile(string path)
        {
            if (OperatingSystem.IsWindows()) return;
            UnixFileMode mode = File.GetUnixFileMode(path);
            Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, mode);
        }

        static byte[] ReadShared(string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                var bytes = new byte[stream.Length];
                int read = 0;
                while (read < bytes.Length)
                {
                    int n = stream.Read(bytes, read, bytes.Length - read);
                    if (n <= 0) break;
                    read += n;
                }
                if (read == bytes.Length) return bytes;
                var exact = new byte[read];
                Buffer.BlockCopy(bytes, 0, exact, 0, read);
                return exact;
            }
        }

        byte[] CommittedWal(out byte[] main)
        {
            string dir = Path.Combine(_root, "wal-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            string src = Path.Combine(dir, "src.sqlite");
            var connection = new SqliteConnection("Data Source=" + src + ";Pooling=False");
            connection.Open();
            try
            {
                using (var cmd = connection.CreateCommand())
                {
                    cmd.CommandText = "PRAGMA journal_mode=WAL;";
                    cmd.ExecuteNonQuery();
                    cmd.CommandText = "PRAGMA wal_autocheckpoint=0;";
                    cmd.ExecuteNonQuery();
                    cmd.CommandText = "CREATE TABLE report(body TEXT);";
                    cmd.ExecuteNonQuery();
                    cmd.CommandText = "INSERT INTO report(body) VALUES ('secret-report-body');";
                    cmd.ExecuteNonQuery();
                }
                main = ReadShared(src);
                return ReadShared(src + "-wal");
            }
            finally
            {
                connection.Dispose();
            }
        }

        static UploadResult Ok(bool duplicate)
        {
            return new UploadResult
            {
                Status = 200,
                Body = duplicate ? "{\"ok\":true,\"duplicate\":true}" : "{\"ok\":true,\"duplicate\":false}"
            };
        }

        int ConfirmedCount()
        {
            int count;
            return _queue.Counts().TryGetValue(SyncState.Confirmed, out count) ? count : 0;
        }

        string WowRoot()
        {
            return Path.Combine(_root, "wow");
        }

        string WriteAccount(string account, string lua)
        {
            string file = Path.Combine(WowRoot(), "WTF", "Account", account, "SavedVariables", "Ironkeep.lua");
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            File.WriteAllText(file, lua);
            return file;
        }

        static string Sample(string place)
        {
            string path = Path.Combine(AppContext.BaseDirectory, "sample-Ironkeep.lua");
            return File.ReadAllText(path).Replace("Hall of Thanes", place);
        }

        sealed class RecordingUploader : IReportUploader
        {
            public readonly List<SentReport> Sent = new List<SentReport>();
            public Func<string, string, UploadResult> Handler = delegate { return Ok(false); };

            public UploadResult Upload(string guildId, string body)
            {
                Sent.Add(new SentReport { GuildId = guildId, Body = body });
                return Handler(guildId, body);
            }
        }

        sealed class SentReport
        {
            public string GuildId;
            public string Body;
        }
    }
}

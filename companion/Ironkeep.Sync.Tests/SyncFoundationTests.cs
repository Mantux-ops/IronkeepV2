using System;
using System.Collections.Generic;
using System.IO;
using System.Security.AccessControl;
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
                QueueStore third = QueueStore.Open(_queuePath);
                try
                {
                    Assert.True(third.CorruptionDetected);
                    Assert.False(third.UnsentReportsRecovered);
                    Assert.NotNull(third.Get(item.Id));
                }
                finally
                {
                    third.Dispose();
                }
            }
            finally
            {
                reopened.Dispose();
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
            if (OperatingSystem.IsWindows())
            {
                var security = new FileInfo(_queuePath).GetAccessControl();
                Assert.True(security.AreAccessRulesProtected);
                return;
            }
            var mode = File.GetUnixFileMode(_queuePath);
            Assert.Equal(UnixFileMode.None, mode & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.OtherRead | UnixFileMode.OtherWrite));
            Assert.True((mode & UnixFileMode.UserRead) != 0);
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

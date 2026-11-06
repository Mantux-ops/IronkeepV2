using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using Ironkeep;
using Ironkeep.Companion;
using Xunit;

namespace Ironkeep.Companion.Core.Tests
{
    public sealed class CompanionCoreTests : IDisposable
    {
        const string Token = "guild-secret-key";
        readonly string _root;

        public CompanionCoreTests()
        {
            _root = Path.Combine(Path.GetTempPath(), "ironkeep-wpf-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
        }

        public void Dispose()
        {
            try { Directory.Delete(_root, true); }
            catch (Exception) { }
        }

        [Fact]
        public void DisplayedVersionIsTheReleaseVersion()
        {
            Assert.Equal("2.0.1", CompanionSession.Version);
            Assert.Equal("2.0.1", new DashboardViewModel().Version);
        }

        [Fact]
        public void ConfigRoundTripKeepsTheKeyProtected()
        {
            var store = new CompanionConfigStore(Path.Combine(_root, "settings.txt"), new PrefixProtector());
            var config = new CompanionConfig();
            config.Address = "https://ironkeep.gg";
            config.Slug = "dutchchaos";
            config.Token = Token;
            config.WowFolder = Path.Combine(_root, "wow");
            config.StartWithWindows = true;
            config.TrayExplained = true;
            store.Save(config);
            string stored = File.ReadAllText(Path.Combine(_root, "settings.txt"));
            Assert.DoesNotContain(Token, stored);
            Assert.StartsWith("test:", File.ReadAllLines(Path.Combine(_root, "settings.txt"))[2]);
            CompanionConfig loaded = store.Load();
            Assert.Equal(Token, loaded.Token);
            Assert.False(loaded.TokenUnreadable);
            Assert.Equal("dutchchaos", loaded.Slug);
            Assert.True(loaded.StartWithWindows);
            Assert.True(loaded.TrayExplained);
            AssertFileIsPrivate(Path.Combine(_root, "settings.txt"));
        }

        [Fact]
        public void PlaintextKeyIsRefused()
        {
            string path = Path.Combine(_root, "plain.txt");
            File.WriteAllLines(path, new string[] { "https://ironkeep.gg", "dutchchaos", Token, "", "0", "0" });
            CompanionConfig loaded = new CompanionConfigStore(path, new PrefixProtector()).Load();
            Assert.True(loaded.TokenUnreadable);
            Assert.Equal("", loaded.Token);
            Assert.Equal("dutchchaos", loaded.Slug);
        }

        [Fact]
        public void ProtectFailureDoesNotWriteTheKey()
        {
            string path = Path.Combine(_root, "broken.txt");
            var config = new CompanionConfig();
            config.Token = Token;
            config.Slug = "dutchchaos";
            Assert.Throws<InvalidOperationException>(delegate { new CompanionConfigStore(path, new BrokenProtector()).Save(config); });
            Assert.False(File.Exists(path));
            Assert.False(File.Exists(path + ".tmp"));
            Assert.Throws<InvalidOperationException>(delegate { new CompanionConfigStore(path, new NakedProtector()).Save(config); });
            Assert.False(File.Exists(path));
        }

        [Fact]
        public void DpapiRoundTripOnWindows()
        {
            if (!OperatingSystem.IsWindows()) return;
            string path = Path.Combine(_root, "dpapi.txt");
            var config = new CompanionConfig();
            config.Address = "http://127.0.0.1:8765";
            config.Slug = "dutchchaos";
            config.Token = Token;
            new CompanionConfigStore(path, new DpapiProtector()).Save(config);
            string stored = File.ReadAllText(path);
            Assert.DoesNotContain(Token, stored);
            Assert.Contains("dpapi:", stored);
            CompanionConfig loaded = new CompanionConfigStore(path, new DpapiProtector()).Load();
            Assert.Equal(Token, loaded.Token);
            Assert.False(loaded.TokenUnreadable);
        }

        [Fact]
        public void StartupRegistrationFollowsTheSavedChoice()
        {
            var startup = new MemoryStartup();
            string folder = InstallLua();
            using (CompanionSession session = Open("startup", folder, "dutchchaos", Token, new ScriptedUploader(), startup))
            {
                Assert.False(startup.Enabled);
                CompanionConfig config = session.Config;
                config.StartWithWindows = true;
                session.Save(config);
                Assert.True(startup.Enabled);
                Assert.Equal(CompanionSession.StartupName, startup.Name);
                Assert.Equal("IronkeepCompanion.exe", startup.Command);
                config = session.Config;
                config.StartWithWindows = false;
                session.Save(config);
                Assert.False(startup.Enabled);
            }
        }

        [Fact]
        public void RealCoordinatorUploadsAndPresentsTheQueue()
        {
            var uploader = new ScriptedUploader();
            uploader.Add(200, "{\"ok\":true,\"duplicate\":false}");
            string folder = InstallLua();
            using (CompanionSession session = Open("sync", folder, "dutchchaos", Token, uploader, new MemoryStartup()))
            {
                Assert.IsType<SyncCoordinator>(session.Coordinator);
                session.Start();
                SyncSnapshot before = session.Snapshot();
                Assert.True(before.WatcherRunning);
                Assert.Equal("dutchchaos", before.GuildId);
                SyncSnapshot done = session.SyncNow();
                Assert.Equal(1, done.Confirmed);
                Assert.Equal(0, done.Pending);
                Assert.Equal("dutchchaos", uploader.Guilds[0]);
                Assert.Contains("format: ironkeep-group 1", uploader.Bodies[0]);
                Assert.Null(session.History()[0].Body);
                Assert.False(string.IsNullOrEmpty(done.LastConfirmedAt));
                var model = new DashboardViewModel();
                model.Apply(done, session.Config, session.SavedFileCount());
                Assert.Equal("Up to date", model.SyncState);
                Assert.Equal("Legacy channel", model.Connection);
                Assert.Equal("Ok", model.Level);
                Assert.Equal("0", model.Pending);
                Assert.Equal("Forever SavedVariables layout found.", model.FolderStatus);
                Assert.Equal("1 Ironkeep.lua file found.", model.SavedStatus);
                Assert.DoesNotContain(Token, model.Auth + model.LastError + model.Connection + model.Guild);
                var settings = new SettingsViewModel();
                settings.Load(session.Config, session.History());
                Assert.Contains("not shown", settings.KeyNote);
                Assert.DoesNotContain(Token, settings.KeyNote);
                Assert.Equal("Confirmed", settings.History[0].State);
                Assert.Equal("Ironkeep.lua", settings.History[0].Source);
                Assert.DoesNotContain("Ada Smith", settings.History[0].Detail + settings.History[0].Source);
                Assert.DoesNotContain(Token, uploader.Bodies[0]);
                Assert.DoesNotContain(Token, File.ReadAllText(Path.Combine(_root, "sync.txt")));
            }
        }

        [Fact]
        public void PendingReportSurvivesRestartAndManualSyncClearsTheBody()
        {
            string folder = InstallLua();
            var ignored = new ScriptedUploader();
            using (CompanionSession first = Open("restart", folder, "dutchchaos", Token, ignored, new MemoryStartup()))
            {
                SyncSnapshot discovered = first.Discover();
                Assert.Equal(1, discovered.Pending);
                Assert.Empty(ignored.Bodies);
                Assert.Contains("Ada Smith", first.History()[0].Body);
            }
            var accept = new ScriptedUploader();
            accept.Add(200, "{\"ok\":true}");
            using (CompanionSession second = Open("restart", folder, "dutchchaos", Token, accept, new MemoryStartup()))
            {
                Assert.Equal(1, second.Snapshot().Pending);
                Assert.Contains("Ada Smith", second.History()[0].Body);
                var model = new DashboardViewModel();
                model.Apply(second.Snapshot(), second.Config, second.SavedFileCount());
                Assert.Equal("Upload queued", model.SyncState);
                Assert.Equal("1", model.Pending);
                SyncSnapshot done = second.SyncNow();
                Assert.Equal(1, done.Confirmed);
                Assert.Equal(0, done.Pending);
                Assert.Null(second.History()[0].Body);
                Assert.Single(accept.Bodies);
            }
        }

        [Fact]
        public void RejectedAndRetryStatesAreShownFromTheQueue()
        {
            var uploader = new ScriptedUploader();
            uploader.Add(400, "{\"ok\":false}");
            uploader.Add(200, "{\"ok\":true}");
            string folder = InstallLua();
            using (CompanionSession session = Open("retry", folder, "dutchchaos", Token, uploader, new MemoryStartup()))
            {
                SyncSnapshot failed = session.SyncNow();
                Assert.Equal(1, failed.FailedPermanent);
                Assert.Contains("HTTP 400", failed.LastError);
                var model = new DashboardViewModel();
                model.Apply(failed, session.Config, session.SavedFileCount());
                Assert.Equal("A report was rejected", model.SyncState);
                Assert.Equal("Bad", model.Level);
                Assert.Equal("1", model.Failed);
                var settings = new SettingsViewModel();
                settings.Load(session.Config, session.History());
                Assert.Equal("Failed", settings.History[0].State);
                Assert.Contains("HTTP 400", settings.History[0].Detail);
                session.RetryFailed();
                SyncSnapshot done = session.Snapshot();
                Assert.Equal(1, done.Confirmed);
                Assert.Equal(0, done.FailedPermanent);
                Assert.Null(session.History()[0].Body);
            }
        }

        [Fact]
        public void TransportFailureStaysScheduled()
        {
            var uploader = new ScriptedUploader();
            uploader.Add(0, "", true);
            string folder = InstallLua();
            using (CompanionSession session = Open("transport", folder, "dutchchaos", Token, uploader, new MemoryStartup()))
            {
                SyncSnapshot snap = session.SyncNow();
                Assert.Equal(1, snap.RetryScheduled);
                Assert.Contains("Ada Smith", session.History()[0].Body);
                var model = new DashboardViewModel();
                model.Apply(snap, session.Config, 0);
                Assert.Equal("Waiting to retry", model.SyncState);
                Assert.Equal("1", model.Retry);
            }
        }

        [Fact]
        public void ShutdownReleasesTheQueue()
        {
            string folder = InstallLua();
            string queue = Path.Combine(_root, "lock.sqlite");
            CompanionSession session = OpenAt(queue, "lock.txt", folder, "dutchchaos", "", new ScriptedUploader(), new MemoryStartup());
            session.Discover();
            session.Dispose();
            QueueStore again = QueueStore.Open(queue);
            again.Dispose();
        }

        [Fact]
        public void SecondLaunchSignalsTheFirstAndQuitReleasesIt()
        {
            string name = "instance-" + Guid.NewGuid().ToString("N");
            using (SingleInstance first = SingleInstance.Acquire(name))
            {
                Assert.True(first.IsOwner);
                using (SingleInstance second = SingleInstance.Acquire(name))
                {
                    Assert.False(second.IsOwner);
                    Assert.False(first.Consume());
                    second.Signal();
                    Assert.True(first.Consume());
                    Assert.False(first.Consume());
                }
            }
            using (SingleInstance third = SingleInstance.Acquire(name))
                Assert.True(third.IsOwner);
        }

        [Fact]
        public void TrayCommandsAreDistinct()
        {
            int open = 0, sync = 0, website = 0, quit = 0;
            var actions = new TrayActions(
                delegate { open++; },
                delegate { sync++; },
                delegate { website++; },
                delegate { quit++; });
            actions.Open();
            actions.Sync();
            actions.Website();
            actions.Quit();
            Assert.Equal(1, open);
            Assert.Equal(1, sync);
            Assert.Equal(1, website);
            Assert.Equal(1, quit);
        }

        [Fact]
        public void WebsiteStaysOnTheConfiguredGuild()
        {
            var config = new CompanionConfig();
            config.Address = "https://ironkeep.gg/";
            config.Slug = "dutchchaos";
            Assert.Equal("https://ironkeep.gg/dutchchaos/raids", CompanionSession.Website(config));
            config.Slug = "";
            Assert.Equal("https://ironkeep.gg", CompanionSession.Website(config));
        }

        [Fact]
        public void EmptyGuildDoesNotInventAConnection()
        {
            var model = new DashboardViewModel();
            model.Apply(new SyncSnapshot(), new CompanionConfig(), 0);
            Assert.Equal("Not signed in", model.Connection);
            Assert.Equal("Not signed in", model.Headline);
            Assert.Equal("No legacy key", model.Auth);
            Assert.Equal("Waiting for a guild", model.SyncState);
            Assert.NotEqual("Ok", model.Level);
            Assert.Equal("No folder selected. This is not a detected install.", model.FolderStatus);
            Assert.Equal("No Ironkeep.lua found.", model.SavedStatus);
            var stored = new SyncSnapshot();
            stored.LastConfirmedAt = "2026-01-01T00:00:00.0000000Z";
            var signedOut = new CompanionConfig();
            signedOut.Slug = "dutchchaos";
            model.Apply(stored, signedOut, 0);
            Assert.Equal("Up to date", model.SyncState);
            Assert.Equal("Not signed in", model.Headline);
            Assert.NotEqual("Ok", model.Level);
            signedOut.Token = "guild-secret-key";
            model.Apply(stored, signedOut, 0);
            Assert.Equal("Up to date", model.Headline);
            Assert.Equal("Ok", model.Level);
        }

        [Fact]
        public void LegacyUploaderPostsToAttendanceAndAcceptsADuplicate()
        {
            int port = StartPort();
            var listener = new HttpListener();
            listener.Prefixes.Add("http://127.0.0.1:" + port.ToString() + "/");
            listener.Start();
            int posts = 0;
            string lastAuth = "";
            var gate = new object();
            var thread = new Thread(delegate ()
            {
                while (listener.IsListening)
                {
                    HttpListenerContext context;
                    try { context = listener.GetContext(); }
                    catch (Exception) { break; }
                    string auth = context.Request.Headers["Authorization"] ?? "";
                    using (var reader = new StreamReader(context.Request.InputStream, Encoding.UTF8))
                        reader.ReadToEnd();
                    int seen;
                    lock (gate)
                    {
                        posts++;
                        lastAuth = auth;
                        seen = posts;
                    }
                    string json = seen == 1
                        ? "{\"ok\":true,\"duplicate\":false}"
                        : "{\"ok\":true,\"duplicate\":true}";
                    byte[] bytes = Encoding.UTF8.GetBytes(json);
                    context.Response.StatusCode = 200;
                    context.Response.ContentType = "application/json";
                    context.Response.ContentLength64 = bytes.Length;
                    context.Response.OutputStream.Write(bytes, 0, bytes.Length);
                    context.Response.OutputStream.Close();
                }
            });
            thread.IsBackground = true;
            thread.Start();
            try
            {
                string folder = InstallLua();
                RunLegacy(port, folder, Path.Combine(_root, "http-a.sqlite"));
                RunLegacy(port, folder, Path.Combine(_root, "http-b.sqlite"));
                lock (gate)
                {
                    Assert.Equal(2, posts);
                    Assert.Equal("Bearer " + Token, lastAuth);
                }
            }
            finally
            {
                listener.Close();
                thread.Join(2000);
            }
        }

        [Fact]
        public void PlaintextKeyIsNotSent()
        {
            int port = StartPort();
            var listener = new HttpListener();
            listener.Prefixes.Add("http://127.0.0.1:" + port.ToString() + "/");
            listener.Start();
            int posts = 0;
            var thread = new Thread(delegate ()
            {
                while (listener.IsListening)
                {
                    try { listener.GetContext().Response.Abort(); }
                    catch (Exception) { break; }
                    posts++;
                }
            });
            thread.IsBackground = true;
            thread.Start();
            try
            {
                string path = Path.Combine(_root, "refused.txt");
                File.WriteAllLines(path, new string[] { "http://127.0.0.1:" + port.ToString(), "dutchchaos", Token, InstallLua(), "0", "0" });
                CompanionConfig sessionConfig = null;
                var uploader = new LegacyUploader(delegate { return sessionConfig; });
                using (var session = new CompanionSession(Path.Combine(_root, "refused.sqlite"), path, new PrefixProtector(), new MemoryStartup(), "", uploader))
                {
                    sessionConfig = session.Config;
                    Assert.True(session.Config.TokenUnreadable);
                    Assert.Equal("", session.Config.Token);
                    SyncSnapshot snap = session.SyncNow();
                    Assert.Equal(1, snap.FailedPermanent);
                    Assert.Contains("reauthentication", snap.LastError);
                    Assert.DoesNotContain(Token, snap.LastError ?? "");
                }
                Assert.Equal(0, posts);
            }
            finally
            {
                listener.Close();
                thread.Join(2000);
            }
        }

        void RunLegacy(int port, string folder, string queue)
        {
            CompanionConfig current = new CompanionConfig();
            current.Address = "http://127.0.0.1:" + port.ToString();
            current.Slug = "dutchchaos";
            current.Token = Token;
            current.WowFolder = folder;
            var uploader = new LegacyUploader(delegate { return current; });
            using (var session = new CompanionSession(queue, queue + ".settings", new PrefixProtector(), new MemoryStartup(), "", uploader))
            {
                session.UseMemory(current);
                SyncSnapshot done = session.SyncNow();
                Assert.Equal(1, done.Confirmed);
                Assert.True(SiteClient.Accepted(uploader.LastResponse));
                Assert.False(File.Exists(queue + ".settings"));
                if (queue.EndsWith("http-b.sqlite")) Assert.True(SiteClient.Duplicate(uploader.LastResponse));
            }
        }

        CompanionSession Open(string name, string folder, string slug, string token, IReportUploader uploader, MemoryStartup startup)
        {
            return OpenAt(Path.Combine(_root, name + ".sqlite"), Path.Combine(_root, name + ".txt"), folder, slug, token, uploader, startup);
        }

        CompanionSession OpenAt(string queue, string settings, string folder, string slug, string token, IReportUploader uploader, MemoryStartup startup)
        {
            var session = new CompanionSession(queue, settings, new PrefixProtector(), startup, "IronkeepCompanion.exe", uploader);
            var config = new CompanionConfig();
            config.Address = "https://ironkeep.gg";
            config.Slug = slug;
            config.Token = token;
            config.WowFolder = folder;
            session.Save(config);
            return session;
        }

        [Fact]
        public void FolderStatusFollowsTheSupportedSavedVariablesLayout()
        {
            string sample = Path.Combine(AppContext.BaseDirectory, "sample-Ironkeep.lua");
            string parent = Path.Combine(_root, "World of Warcraft");
            string forever = Path.Combine(parent, "_forever_");
            string saved = Path.Combine(forever, "WTF", "Account", "125458546#1", "SavedVariables");
            Directory.CreateDirectory(saved);
            File.Copy(sample, Path.Combine(saved, "Ironkeep.lua"), true);
            string bare = Path.Combine(_root, "empty-install");
            Directory.CreateDirectory(bare);
            var model = new DashboardViewModel();

            var found = new CompanionConfig();
            found.WowFolder = forever;
            int foundFiles = Saved.AllSaved(forever).Count;
            model.Apply(new SyncSnapshot(), found, foundFiles);
            Assert.Equal(1, foundFiles);
            Assert.Equal("Forever SavedVariables layout found.", model.FolderStatus);
            Assert.Equal("1 Ironkeep.lua file found.", model.SavedStatus);

            var parentConfig = new CompanionConfig();
            parentConfig.WowFolder = parent;
            int parentFiles = Saved.AllSaved(parent).Count;
            model.Apply(new SyncSnapshot(), parentConfig, parentFiles);
            Assert.Equal(0, parentFiles);
            Assert.Equal("Folder found, but no Ironkeep.lua was found in a supported SavedVariables layout.", model.FolderStatus);
            Assert.Equal("No Ironkeep.lua found.", model.SavedStatus);

            var bareConfig = new CompanionConfig();
            bareConfig.WowFolder = bare;
            int bareFiles = Saved.AllSaved(bare).Count;
            model.Apply(new SyncSnapshot(), bareConfig, bareFiles);
            Assert.Equal(0, bareFiles);
            Assert.Equal("Folder found, but no Ironkeep.lua was found in a supported SavedVariables layout.", model.FolderStatus);
            Assert.Equal("No Ironkeep.lua found.", model.SavedStatus);

            var missing = new CompanionConfig();
            missing.WowFolder = Path.Combine(_root, "missing-forever");
            model.Apply(new SyncSnapshot(), missing, 0);
            Assert.Equal("That folder was not found.", model.FolderStatus);
            Assert.Equal("No Ironkeep.lua found.", model.SavedStatus);
            Assert.False(Directory.Exists(missing.WowFolder));

            model.Apply(new SyncSnapshot(), new CompanionConfig(), 0);
            Assert.Equal("No folder selected. This is not a detected install.", model.FolderStatus);
            Assert.Equal("No Ironkeep.lua found.", model.SavedStatus);
        }

        string InstallLua()
        {
            string folder = Path.Combine(_root, "wow");
            string saved = Path.Combine(folder, "WTF", "Account", "One", "SavedVariables");
            Directory.CreateDirectory(saved);
            string sample = Path.Combine(AppContext.BaseDirectory, "sample-Ironkeep.lua");
            File.Copy(sample, Path.Combine(saved, "Ironkeep.lua"), true);
            return folder;
        }

        static int StartPort()
        {
            return 20000 + (Math.Abs(Guid.NewGuid().GetHashCode()) % 20000);
        }

        static void AssertFileIsPrivate(string path)
        {
            if (OperatingSystem.IsWindows())
            {
                FileSecurity security = new FileInfo(path).GetAccessControl();
                AuthorizationRuleCollection rules = security.GetAccessRules(true, true, typeof(SecurityIdentifier));
                Assert.NotEmpty(rules);
                SecurityIdentifier user = WindowsIdentity.GetCurrent().User;
                foreach (AuthorizationRule rule in rules)
                    Assert.Equal(user, (SecurityIdentifier)rule.IdentityReference);
                return;
            }
            UnixFileMode mode = File.GetUnixFileMode(path);
            Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, mode);
        }

        sealed class ScriptedUploader : IReportUploader
        {
            readonly Queue<UploadResult> _results = new Queue<UploadResult>();
            public List<string> Bodies = new List<string>();
            public List<string> Guilds = new List<string>();

            public void Add(int status, string body, bool transport)
            {
                _results.Enqueue(new UploadResult { Status = status, Body = body ?? "", TransportFailed = transport });
            }

            public void Add(int status, string body)
            {
                Add(status, body, false);
            }

            public UploadResult Upload(string guildId, string body)
            {
                Guilds.Add(guildId ?? "");
                Bodies.Add(body ?? "");
                if (_results.Count == 0) return new UploadResult { Status = 0, Body = "", TransportFailed = true };
                return _results.Dequeue();
            }
        }

        sealed class BrokenProtector : IProtector
        {
            public bool IsProtected(string stored) { return false; }
            public string Protect(string plain) { throw new CryptographicException("unavailable"); }
            public string Unprotect(string stored) { throw new CryptographicException("unavailable"); }
        }

        sealed class NakedProtector : IProtector
        {
            public bool IsProtected(string stored) { return stored != null && stored.StartsWith("safe:", StringComparison.Ordinal); }
            public string Protect(string plain) { return plain ?? ""; }
            public string Unprotect(string stored) { return stored ?? ""; }
        }
    }
}

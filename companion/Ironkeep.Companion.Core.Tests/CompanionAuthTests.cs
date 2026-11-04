using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using Ironkeep;
using Ironkeep.Companion;
using Xunit;

namespace Ironkeep.Companion.Core.Tests
{
    public sealed class CompanionAuthTests : IDisposable
    {
        const string Access = "ika.access-token-should-not-be-stored-raw";
        const string Refresh = "ikr.refresh-token-should-not-be-stored-raw";
        const string NextAccess = "ika.next-access-token-should-not-be-stored-raw";
        const string NextRefresh = "ikr.next-refresh-token-should-not-be-stored-raw";
        const string Legacy = "guild-secret-key";
        readonly string _root;

        public CompanionAuthTests()
        {
            _root = Path.Combine(Path.GetTempPath(), "ironkeep-auth-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_root);
        }

        public void Dispose()
        {
            try { Directory.Delete(_root, true); }
            catch (Exception) { }
        }

        [Fact]
        public void PkceUsesThePublishedS256Vector()
        {
            Assert.Equal("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", CompanionProtocol.ChallengeS256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"));
            string secret = CompanionProtocol.RandomSecret(64);
            Assert.Equal(64, secret.Length);
            Assert.Equal(43, CompanionProtocol.ChallengeS256(secret).Length);
            Assert.False(CompanionProtocol.FixedEqual("state-one-value", "state-two-value"));
            Assert.True(CompanionProtocol.FixedEqual("same-state-value", "same-state-value"));
        }

        [Fact]
        public void BrowserLoginExchangesTheCodeAndStoresOnlyHashesOfNothingRaw()
        {
            using (var api = new FakeSite())
            {
                api.On("/api/companion/token", delegate (FakeRequest request)
                {
                    Dictionary<string, string> fields = ReadForm(request.Body);
                    string challenge = ChallengeFrom(api.OpenedUrl);
                    Assert.Equal(challenge, CompanionProtocol.ChallengeS256(fields["code_verifier"]));
                    Assert.Equal("authorization_code", fields["grant_type"]);
                    Assert.Contains("/callback", fields["redirect_uri"]);
                    return Json(200, TokenJson(Access, Refresh));
                });
                api.On("/api/companion/guilds", delegate { return Json(200, "{\"ok\":true,\"guilds\":[{\"id\":\"4242\",\"slug\":\"dutchchaos\",\"name\":\"Dutch Chaos\"}]}"); });
                Holder holder = Hold(api);
                holder.Use(new ScriptBrowser(delegate (string url)
                {
                    api.OpenedUrl = url;
                    Assert.Contains("client_id=ironkeep-companion", url);
                    Assert.Contains("code_challenge_method=S256", url);
                    Assert.Contains("response_type=code", url);
                    Assert.DoesNotContain("discord.com", url);
                    Dictionary<string, string> query = Query(url);
                    string page = Get(query["redirect_uri"] + "?code=ikn.one-time&state=" + Uri.EscapeDataString(query["state"]));
                    Assert.DoesNotContain("ikn.one-time", page);
                    Assert.Contains("close this window", page);
                }));
                LoginResult result = holder.Login.Run(CancellationToken.None, delegate { });
                Assert.Equal("success", result.Kind);
                Assert.Equal("dutchchaos", holder.Current.Slug);
                Assert.Equal("Dutch Chaos", holder.Current.GuildName);
                Assert.Equal(Access, holder.Current.AccessToken);
                Assert.Equal(Refresh, holder.Current.RefreshToken);
                string stored = File.ReadAllText(holder.Path);
                Assert.DoesNotContain(Access, stored);
                Assert.DoesNotContain(Refresh, stored);
                Assert.DoesNotContain("ikn.one-time", stored);
                Assert.Equal(CompanionConfig.ModeDiscord, holder.Config.AuthMode);
            }
        }

        [Fact]
        public void InvalidStateDoesNotExchange()
        {
            using (var api = new FakeSite())
            {
                int posts = 0;
                api.On("/api/companion/token", delegate { posts++; return Json(401, "{\"ok\":false}"); });
                Holder holder = Hold(api);
                var browser = new ScriptBrowser(delegate (string url)
                {
                    Dictionary<string, string> query = Query(url);
                    Get(query["redirect_uri"] + "?code=ikn.one-time&state=different-state-value");
                });
                holder.Use(browser);
                LoginResult result = holder.Login.Run(CancellationToken.None, delegate { });
                Assert.Equal("invalid-state", result.Kind);
                Assert.Equal(0, posts);
                Assert.Equal("", holder.Current.AccessToken);
            }
        }

        [Fact]
        public void PkceMismatchIsRejectedAndStoresNothing()
        {
            using (var api = new FakeSite())
            {
                api.On("/api/companion/token", delegate (FakeRequest request)
                {
                    Dictionary<string, string> fields = ReadForm(request.Body);
                    string challenge = ChallengeFrom(api.OpenedUrl);
                    if (CompanionProtocol.ChallengeS256(fields["code_verifier"]) != challenge)
                        return Json(401, "{\"ok\":false}");
                    return Json(200, TokenJson(Access, Refresh));
                });
                Holder holder = Hold(api);
                holder.Use(new ScriptBrowser(delegate (string url)
                {
                    api.OpenedUrl = url;
                    Dictionary<string, string> query = Query(url);
                    Get(query["redirect_uri"] + "?code=ikn.one-time&state=" + Uri.EscapeDataString(query["state"]));
                }));
                holder.Login.ChallengeOverride = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";
                holder.Login.VerifierOverride = new string('a', 64);
                LoginResult result = holder.Login.Run(CancellationToken.None, delegate { });
                Assert.Equal("failed", result.Kind);
                Assert.Equal("", holder.Current.AccessToken);
                Assert.DoesNotContain(Access, File.ReadAllText(holder.Path));
            }
        }

        [Fact]
        public void LoopbackTimesOutAndShutsDown()
        {
            using (var api = new FakeSite())
            {
                Holder holder = Hold(api);
                holder.Use(new ScriptBrowser(delegate { }));
                holder.Login.Timeout = TimeSpan.FromMilliseconds(200);
                DateTime started = DateTime.UtcNow;
                LoginResult result = holder.Login.Run(CancellationToken.None, delegate { });
                Assert.Equal("failed", result.Kind);
                Assert.Contains("time", result.Detail);
                Assert.True((DateTime.UtcNow - started).TotalSeconds < 3);
                Assert.Equal("", holder.Current.AccessToken);
            }
        }

        [Fact]
        public void CancelClosesTheListener()
        {
            using (var api = new FakeSite())
            {
                Holder holder = Hold(api);
                holder.Use(new ScriptBrowser(delegate { }));
                var cancel = new CancellationTokenSource();
                LoginResult result = null;
                var thread = new Thread(new ThreadStart(delegate { result = holder.Login.Run(cancel.Token, delegate { }); }));
                thread.Start();
                Thread.Sleep(100);
                cancel.Cancel();
                thread.Join();
                Assert.Equal("cancelled", result.Kind);
                Assert.Equal("", holder.Current.AccessToken);
            }
        }

        [Fact]
        public void RejectedAuthorizationDoesNotExchange()
        {
            using (var api = new FakeSite())
            {
                int posts = 0;
                api.On("/api/companion/token", delegate { posts++; return Json(401, "{\"ok\":false}"); });
                Holder holder = Hold(api);
                holder.Use(new ScriptBrowser(delegate (string url)
                {
                    Dictionary<string, string> query = Query(url);
                    Get(query["redirect_uri"] + "?error=access_denied&state=" + Uri.EscapeDataString(query["state"]));
                }));
                LoginResult result = holder.Login.Run(CancellationToken.None, delegate { });
                Assert.Equal("rejected", result.Kind);
                Assert.Equal(0, posts);
            }
        }

        [Fact]
        public void RefreshRotatesOnceUnderConcurrency()
        {
            using (var api = new FakeSite())
            {
                int refreshes = 0;
                api.On("/api/companion/token", delegate (FakeRequest request)
                {
                    Dictionary<string, string> fields = ReadForm(request.Body);
                    Assert.Equal("refresh_token", fields["grant_type"]);
                    Assert.Equal(Refresh, fields["refresh_token"]);
                    Interlocked.Increment(ref refreshes);
                    Thread.Sleep(200);
                    return Json(200, TokenJson(NextAccess, NextRefresh));
                });
                Holder holder = Hold(api);
                holder.Config.AuthMode = CompanionConfig.ModeDiscord;
                holder.Config.AccessToken = Access;
                holder.Config.RefreshToken = Refresh;
                holder.Config.AccessExpiresAt = "2000-01-01T00:00:00.0000000Z";
                holder.Config.Slug = "dutchchaos";
                holder.Save();
                var gate = new Barrier(2);
                string[] seen = new string[2];
                var threads = new Thread[2];
                for (int i = 0; i < 2; i++)
                {
                    int index = i;
                    threads[i] = new Thread(new ThreadStart(delegate
                    {
                        gate.SignalAndWait();
                        seen[index] = holder.Login.EnsureAccess(false);
                    }));
                    threads[i].Start();
                }
                threads[0].Join();
                threads[1].Join();
                Assert.Equal(1, refreshes);
                Assert.Equal(NextAccess, seen[0]);
                Assert.Equal(NextAccess, seen[1]);
                CompanionConfig loaded = holder.Reload();
                Assert.Equal(NextRefresh, loaded.RefreshToken);
                string stored = File.ReadAllText(holder.Path);
                Assert.DoesNotContain(NextAccess, stored);
                Assert.DoesNotContain(NextRefresh, stored);
                Assert.DoesNotContain(Refresh, stored);
            }
        }

        [Fact]
        public void RevokedSessionDoesNotUseTheLegacyKey()
        {
            using (var api = new FakeSite())
            {
                var paths = new List<string>();
                var auths = new List<string>();
                api.On("/api/companion/token", delegate (FakeRequest request)
                {
                    lock (paths)
                    {
                        paths.Add(request.Path);
                        auths.Add(request.Authorization);
                    }
                    return Json(401, "{\"ok\":false}");
                });
                api.On("/api/dutchchaos/attendance", delegate (FakeRequest request)
                {
                    lock (paths)
                    {
                        paths.Add(request.Path);
                        auths.Add(request.Authorization);
                    }
                    return Json(200, "{\"ok\":true}");
                });
                Holder holder = Hold(api);
                holder.Config.AuthMode = CompanionConfig.ModeDiscord;
                holder.Config.Token = Legacy;
                holder.Config.AccessToken = Access;
                holder.Config.RefreshToken = Refresh;
                holder.Config.AccessExpiresAt = "2000-01-01T00:00:00.0000000Z";
                holder.Config.Slug = "dutchchaos";
                holder.Save();
                var uploader = new DiscordUploader(delegate { return holder.Reload(); }, holder.Login);
                UploadResult result = uploader.Upload("dutchchaos", "format: ironkeep-group 1");
                Assert.Equal(401, result.Status);
                Assert.Equal(CompanionConfig.StatusExpired, holder.Reload().SessionStatus);
                Assert.Equal(Legacy, holder.Reload().Token);
                Assert.DoesNotContain("/api/dutchchaos/attendance", paths);
                Assert.DoesNotContain("Bearer " + Legacy, auths);
                var model = new DashboardViewModel();
                model.Apply(new SyncSnapshot(), holder.Reload(), 0);
                Assert.Equal("Session expired", model.Headline);
                Assert.DoesNotContain(Access, model.Headline + model.Detail + model.Auth + model.CardDetail);
                Assert.DoesNotContain(Refresh, model.Headline + model.Detail + model.Auth + model.CardDetail);
                Assert.DoesNotContain(Legacy, model.Headline + model.Detail + model.Auth + model.CardDetail);
            }
        }

        [Fact]
        public void GuildSelectionUsesOnlyReturnedGuilds()
        {
            using (var api = new FakeSite())
            {
                api.On("/api/companion/guilds", delegate
                {
                    return Json(200, "{\"ok\":true,\"guilds\":[{\"id\":\"1\",\"slug\":\"alpha\",\"name\":\"Alpha\"},{\"id\":\"2\",\"slug\":\"beta\",\"name\":\"Beta\"}]}");
                });
                Holder holder = Hold(api);
                holder.Config.AuthMode = CompanionConfig.ModeDiscord;
                holder.Config.AccessToken = Access;
                holder.Config.RefreshToken = Refresh;
                holder.Config.AccessExpiresAt = DateTime.UtcNow.AddMinutes(5).ToString("o");
                holder.Save();
                LoginResult result = holder.Login.RefreshGuilds();
                Assert.Equal("choose", result.Kind);
                Assert.Equal("", holder.Reload().Slug);
                var session = holder.Session;
                Assert.False(session.SelectGuild("other"));
                Assert.True(session.SelectGuild("beta"));
                Assert.Equal("beta", session.Config.Slug);
                Assert.Equal("Beta", session.Config.GuildName);
                Assert.NotEqual("alpha", session.Config.Slug);
            }
        }

        [Fact]
        public void PermissionRemovalDoesNotMoveTheQueue()
        {
            using (var api = new FakeSite())
            {
                var paths = new List<string>();
                api.On("/api/companion/guilds", delegate { return Json(200, "{\"ok\":true,\"guilds\":[]}"); });
                api.On("/api/companion/guilds/dutchchaos/attendance", delegate (FakeRequest request)
                {
                    paths.Add(request.Path);
                    return Json(403, "{\"ok\":false}");
                });
                api.On("/api/companion/guilds/other/attendance", delegate (FakeRequest request)
                {
                    paths.Add(request.Path);
                    return Json(200, "{\"ok\":true}");
                });
                Holder holder = Hold(api);
                holder.Config.AuthMode = CompanionConfig.ModeDiscord;
                holder.Config.AccessToken = Access;
                holder.Config.RefreshToken = Refresh;
                holder.Config.AccessExpiresAt = DateTime.UtcNow.AddMinutes(5).ToString("o");
                holder.Config.Slug = "dutchchaos";
                holder.Config.GuildName = "Dutch Chaos";
                holder.Save();
                string queuePath = Path.Combine(_root, "remove.sqlite");
                using (var queue = QueueStore.Open(queuePath))
                {
                    queue.Enqueue("dutchchaos", "one.lua", "format: ironkeep-group 1\nDutch");
                    var coordinator = new SyncCoordinator(queue, new DiscordUploader(delegate { return holder.Reload(); }, holder.Login), new SyncSettings());
                    coordinator.GuildId = "dutchchaos";
                    LoginResult removed = holder.Login.RefreshGuilds();
                    Assert.Equal("denied", removed.Kind);
                    Assert.Equal("dutchchaos", holder.Reload().Slug);
                    coordinator.Pump(DateTime.UtcNow);
                    Assert.Empty(paths);
                    Assert.Equal("dutchchaos", queue.History(5)[0].GuildId);
                    Assert.Equal(SyncState.FailedPermanent, queue.History(5)[0].State);
                }
                var model = new DashboardViewModel();
                model.Apply(new SyncSnapshot(), holder.Reload(), 0);
                Assert.Equal("Permission denied", model.Headline);
            }
        }

        [Fact]
        public void CrossGuildQueueIsNotUploadedToTheSelectedGuild()
        {
            using (var api = new FakeSite())
            {
                var posted = new List<string>();
                api.On("/api/companion/guilds/alpha/attendance", delegate (FakeRequest request)
                {
                    posted.Add("alpha:" + request.Body);
                    return Json(200, "{\"ok\":true}");
                });
                api.On("/api/companion/guilds/beta/attendance", delegate (FakeRequest request)
                {
                    posted.Add("beta:" + request.Body);
                    return Json(200, "{\"ok\":true}");
                });
                Holder holder = Hold(api);
                holder.Config.AuthMode = CompanionConfig.ModeDiscord;
                holder.Config.AccessToken = Access;
                holder.Config.RefreshToken = Refresh;
                holder.Config.AccessExpiresAt = DateTime.UtcNow.AddMinutes(5).ToString("o");
                holder.Config.Slug = "alpha";
                holder.Save();
                string queuePath = Path.Combine(_root, "cross.sqlite");
                using (var queue = QueueStore.Open(queuePath))
                {
                    queue.Enqueue("alpha", "a.lua", "format: ironkeep-group 1\nAlpha");
                    queue.Enqueue("beta", "b.lua", "format: ironkeep-group 1\nBeta");
                    var coordinator = new SyncCoordinator(queue, new SessionUploader(delegate { return holder.Reload(); }, new DiscordUploader(delegate { return holder.Reload(); }, holder.Login), new LegacyUploader(delegate { return holder.Reload(); })), new SyncSettings());
                    coordinator.GuildId = "alpha";
                    coordinator.Pump(DateTime.UtcNow);
                    Assert.Single(posted);
                    Assert.StartsWith("alpha:", posted[0]);
                    Assert.DoesNotContain("Beta", posted[0]);
                    List<QueueItem> history = queue.History(10);
                    Assert.Contains(history, item => item.GuildId == "beta" && item.State == SyncState.FailedPermanent);
                    Assert.Contains(history, item => item.GuildId == "alpha" && item.State == SyncState.Confirmed);
                }
                byte[] database = File.ReadAllBytes(queuePath);
                Assert.False(Contains(database, Encoding.UTF8.GetBytes(Access)));
                Assert.False(Contains(database, Encoding.UTF8.GetBytes(Refresh)));
            }
        }

        [Fact]
        public void LegacyModeStaysAvailableAndIsNotADiscordFallback()
        {
            using (var api = new FakeSite())
            {
                var paths = new List<string>();
                api.On("/api/dutchchaos/attendance", delegate (FakeRequest request)
                {
                    paths.Add(request.Path + " " + request.Authorization);
                    return Json(200, "{\"ok\":true,\"duplicate\":false}");
                });
                api.On("/api/companion/guilds/dutchchaos/attendance", delegate (FakeRequest request)
                {
                    paths.Add("companion " + request.Authorization);
                    return Json(401, "{\"ok\":false}");
                });
                Holder holder = Hold(api);
                holder.Config.Token = Legacy;
                holder.Config.Slug = "dutchchaos";
                holder.Save();
                var legacy = new LegacyUploader(delegate { return holder.Reload(); });
                var uploader = new SessionUploader(delegate { return holder.Reload(); }, new DiscordUploader(delegate { return holder.Reload(); }, holder.Login), legacy);
                UploadResult sent = uploader.Upload("dutchchaos", "format: ironkeep-group 1");
                Assert.Equal(200, sent.Status);
                Assert.Contains("/api/dutchchaos/attendance Bearer " + Legacy, paths);

                paths.Clear();
                holder.Config.AuthMode = CompanionConfig.ModeDiscord;
                holder.Config.Token = Legacy;
                holder.Config.AccessToken = "";
                holder.Config.RefreshToken = "";
                holder.Config.SessionStatus = CompanionConfig.StatusExpired;
                holder.Save();
                UploadResult blocked = uploader.Upload("dutchchaos", "format: ironkeep-group 1");
                Assert.Equal(401, blocked.Status);
                Assert.Empty(paths);
                var model = new DashboardViewModel();
                CompanionConfig signedOut = holder.Reload();
                signedOut.AuthMode = CompanionConfig.ModeSignedOut;
                model.Apply(new SyncSnapshot { LastConfirmedAt = "2026-01-01T00:00:00.0000000Z" }, signedOut, 0);
                Assert.Equal("Not signed in", model.Headline);
                Assert.NotEqual("Legacy channel", model.Connection);
            }
        }

        [Fact]
        public void PlaintextDiscordTokensAreNotSent()
        {
            string path = Path.Combine(_root, "plain.txt");
            File.WriteAllLines(path, new string[]
            {
                "https://ironkeep.gg", "dutchchaos", "", "", "0", "0", "discord", Access, Refresh, "", "1", "Dutch", "", ""
            });
            var store = new CompanionConfigStore(path, new PrefixProtector());
            CompanionConfig loaded = store.Load();
            Assert.True(loaded.SessionUnreadable);
            Assert.Equal("", loaded.AccessToken);
            Assert.Equal("", loaded.RefreshToken);
            Assert.DoesNotContain(Access, loaded.SessionDetail ?? "");
        }

        Holder Hold(FakeSite api)
        {
            var holder = new Holder();
            holder.Path = Path.Combine(_root, Guid.NewGuid().ToString("N") + ".txt");
            holder.Config = new CompanionConfig();
            holder.Config.Address = api.Origin;
            holder.Use(new ScriptBrowser(delegate { }));
            holder.Save();
            return holder;
        }

        static string TokenJson(string access, string refresh)
        {
            return "{\"ok\":true,\"token_type\":\"Bearer\",\"access_token\":\"" + access + "\",\"refresh_token\":\"" + refresh + "\",\"expires_in\":600,\"refresh_expires_in\":2592000,\"guild_id\":\"4242\",\"guild_slug\":\"dutchchaos\"}";
        }

        static Dictionary<string, string> Query(string url)
        {
            var uri = new Uri(url);
            return Split(uri.Query.TrimStart('?'));
        }

        static Dictionary<string, string> ReadForm(string body)
        {
            CompanionJson root;
            Assert.True(CompanionProtocol.TryParse(body, out root));
            var map = new Dictionary<string, string>();
            foreach (var pair in root.Map)
                if (pair.Value != null && pair.Value.IsText) map[pair.Key] = pair.Value.Text;
            return map;
        }

        static Dictionary<string, string> Split(string query)
        {
            var map = new Dictionary<string, string>(StringComparer.Ordinal);
            if (query == null || query.Length == 0) return map;
            string[] parts = query.Split('&');
            for (int i = 0; i < parts.Length; i++)
            {
                int eq = parts[i].IndexOf('=');
                string key = Uri.UnescapeDataString(eq < 0 ? parts[i] : parts[i].Substring(0, eq));
                string value = eq < 0 ? "" : Uri.UnescapeDataString(parts[i].Substring(eq + 1));
                map[key] = value;
            }
            return map;
        }

        static string ChallengeFrom(string url)
        {
            Dictionary<string, string> query = Query(url);
            return query["code_challenge"];
        }

        static string Get(string url)
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Timeout = 5000;
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                return reader.ReadToEnd();
        }

        static FakeReply Json(int status, string body)
        {
            return new FakeReply { Status = status, Body = body };
        }

        static bool Contains(byte[] haystack, byte[] needle)
        {
            if (needle.Length == 0 || haystack.Length < needle.Length) return false;
            for (int i = 0; i <= haystack.Length - needle.Length; i++)
            {
                bool match = true;
                for (int j = 0; j < needle.Length; j++)
                {
                    if (haystack[i + j] != needle[j])
                    {
                        match = false;
                        break;
                    }
                }
                if (match) return true;
            }
            return false;
        }

        sealed class Holder
        {
            public string Path;
            public CompanionConfig Config;
            public DiscordLogin Login;
            public CompanionSession Session;
            string _queue;

            public CompanionConfig Current { get { return Session.Config; } }

            public void Use(ScriptBrowser browser)
            {
                CompanionConfig current = Config;
                if (Session != null) Session.Dispose();
                if (_queue == null) _queue = Path + ".sqlite";
                Session = new CompanionSession(_queue, Path, new PrefixProtector(), new MemoryStartup(), "", null, browser);
                Session.UseMemory(current);
                Config = Session.Config;
                Login = Session.Login;
            }

            public void Save()
            {
                Session.Save(Config);
                Config = Session.Config;
                Login = Session.Login;
            }

            public CompanionConfig Reload()
            {
                Config = Session.Config;
                return Config;
            }
        }

        sealed class ScriptBrowser : IBrowser
        {
            readonly Action<string> _open;
            public ScriptBrowser(Action<string> open) { _open = open; }
            public void Open(string url) { if (_open != null) _open(url); }
        }

        sealed class FakeRequest
        {
            public string Path = "";
            public string Body = "";
            public string Authorization = "";
        }

        sealed class FakeReply
        {
            public int Status;
            public string Body = "";
        }

        sealed class FakeSite : IDisposable
        {
            readonly HttpListener _listener = new HttpListener();
            readonly Thread _thread;
            readonly Dictionary<string, Func<FakeRequest, FakeReply>> _routes = new Dictionary<string, Func<FakeRequest, FakeReply>>(StringComparer.Ordinal);
            public string OpenedUrl = "";
            public string Origin;

            public FakeSite()
            {
                int port = 20000 + (Math.Abs(Guid.NewGuid().GetHashCode()) % 20000);
                Origin = "http://127.0.0.1:" + port.ToString();
                _listener.Prefixes.Add(Origin + "/");
                _listener.Start();
                _thread = new Thread(Loop);
                _thread.IsBackground = true;
                _thread.Start();
            }

            public void On(string path, Func<FakeRequest, FakeReply> handler)
            {
                _routes[path] = handler;
            }

            public void Dispose()
            {
                _listener.Close();
                _thread.Join(2000);
            }

            void Loop()
            {
                while (_listener.IsListening)
                {
                    HttpListenerContext context;
                    try { context = _listener.GetContext(); }
                    catch (Exception) { return; }
                    string body;
                    using (var reader = new StreamReader(context.Request.InputStream, Encoding.UTF8))
                        body = reader.ReadToEnd();
                    var request = new FakeRequest();
                    request.Path = context.Request.Url.AbsolutePath;
                    request.Body = body;
                    request.Authorization = context.Request.Headers["Authorization"] ?? "";
                    FakeReply reply = null;
                    Func<FakeRequest, FakeReply> handler;
                    if (_routes.TryGetValue(request.Path, out handler)) reply = handler(request);
                    if (reply == null) reply = new FakeReply { Status = 404, Body = "{\"detail\":\"Not Found\"}" };
                    byte[] bytes = Encoding.UTF8.GetBytes(reply.Body ?? "");
                    context.Response.StatusCode = reply.Status;
                    context.Response.ContentType = "application/json";
                    context.Response.ContentLength64 = bytes.Length;
                    context.Response.OutputStream.Write(bytes, 0, bytes.Length);
                    context.Response.Close();
                }
            }
        }
    }
}
